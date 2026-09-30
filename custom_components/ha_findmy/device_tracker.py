"""Device tracker entities for HA-FindMy."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import cached_property

from findmy import FindMyAccessory, LocationReport
from homeassistant.components import bluetooth
from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._entity import battery_percent, build_device_info
from .bermuda_bridge import async_register_bermuda_source
from .const import DOMAIN, signal_local_observation
from .coordinator import HAFindMyCoordinator, accessory_id
from .local_bluetooth import (
    APPLE_COMPANY_ID,
    DULT_SERVICE_UUID,
    CandidateKeyLookup,
    LocalObservation,
    build_candidate_key_lookup_from_json,
    match_dult_advertisement,
    match_local_advertisement,
)
from .runtime import HAFindMyRuntime

_LOCAL_KEY_REFRESH_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    """Set up one tracker for each selected accessory."""
    runtime: HAFindMyRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HAFindMyTracker(runtime, accessory)
        for accessory in runtime.accessories
    )


class HAFindMyTracker(CoordinatorEntity[HAFindMyCoordinator], TrackerEntity):
    """A Find My accessory with cloud GPS and local Bluetooth observations."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _unrecorded_attributes = frozenset(
        {
            "local_detected_at",
            "local_rssi",
            "local_source",
            "local_state",
            "local_mac_address",
            "local_key_candidates",
        }
    )

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        super().__init__(runtime.coordinator, context=accessory_id(accessory))
        self.runtime = runtime
        self.accessory = accessory
        self._attr_unique_id = accessory_id(accessory)

        self._local_candidates: CandidateKeyLookup = {}
        self._local_candidate_count = 0
        self._local_observation: LocalObservation | None = None
        self._local_source: str | None = None
        self._local_refresh_lock = asyncio.Lock()
        self._local_refresh_tasks: set[asyncio.Task[None]] = set()
        self._local_active = False

    @property
    def report(self) -> LocationReport | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._attr_unique_id)

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.report.latitude if self.report else None

    @property
    def longitude(self) -> float | None:
        return self.report.longitude if self.report else None

    @property
    def location_accuracy(self) -> float:
        return float(self.report.horizontal_accuracy) if self.report else 0.0

    @property
    def battery_level(self) -> int | None:
        from ._entity import latest_status
        return battery_percent(latest_status(self.runtime, self.accessory))

    @cached_property
    def device_info(self):
        return build_device_info(self.accessory)

    @property
    def extra_state_attributes(self):
        report = self.report
        obs = self._local_observation
        return {
            "detected_at": report.timestamp if report else None,
            "status": report.status if report else None,
            "serial_number": getattr(self.accessory, "serial_number", None),
            "model": getattr(self.accessory, "model", None),
            "local_detected_at": obs.detected_at if obs else None,
            "local_rssi": obs.rssi if obs else None,
            "local_source": self._local_source,
            "local_state": obs.state if obs else None,
            "local_mac_address": obs.mac_address if obs else None,
            "local_key_candidates": self._local_candidate_count,
        }

    async def async_added_to_hass(self) -> None:
        """Start matching advertisements from HA adapters and ESPHome proxies."""
        await super().async_added_to_hass()
        self._local_active = True

        for connectable in (False, True):
            self.async_on_remove(
                bluetooth.async_register_callback(
                    self.hass,
                    self._async_track_service_info,
                    bluetooth.BluetoothCallbackMatcher(
                        connectable=connectable,
                        manufacturer_id=APPLE_COMPANY_ID,
                    ),
                    bluetooth.BluetoothScanningMode.PASSIVE,
                )
            )

        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._async_track_service_info,
                bluetooth.BluetoothCallbackMatcher(
                    connectable=False,
                    service_data_uuid=DULT_SERVICE_UUID,
                ),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )

        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._async_refresh_local_candidates,
                _LOCAL_KEY_REFRESH_INTERVAL,
            )
        )
        self.async_on_remove(self._cancel_local_refresh_tasks)
        self._schedule_local_candidate_refresh("initial")

    async def async_will_remove_from_hass(self) -> None:
        self._local_active = False
        await super().async_will_remove_from_hass()

    @callback
    def _cancel_local_refresh_tasks(self) -> None:
        for task in self._local_refresh_tasks:
            task.cancel()
        self._local_refresh_tasks.clear()

    @callback
    def _schedule_local_candidate_refresh(self, reason: str) -> None:
        task = self.hass.async_create_task(
            self._async_refresh_local_candidates(),
            f"ha_findmy local key cache ({reason}): {self._attr_unique_id}",
        )
        self._local_refresh_tasks.add(task)
        task.add_done_callback(self._local_refresh_tasks.discard)

    async def _async_refresh_local_candidates(self, _now: datetime | None = None) -> None:
        async with self._local_refresh_lock:
            observed_at = datetime.now(tz=UTC)
            candidates = await self.hass.async_add_executor_job(
                build_candidate_key_lookup_from_json,
                self.accessory.to_json(),
                observed_at,
            )

            if not self._local_active:
                return

            self._local_candidates = candidates
            self._local_candidate_count = sum(len(keys) for keys in candidates.values())

            # HA replays history when callbacks are registered before the key cache is ready.
            # Match the existing history once so startup does not have to wait for key rotation.
            history = sorted(
                (
                    info
                    for info in bluetooth.async_discovered_service_info(
                        self.hass,
                        connectable=False,
                    )
                    if APPLE_COMPANY_ID in info.manufacturer_data
                    or DULT_SERVICE_UUID in info.service_data
                ),
                key=lambda info: info.time,
            )
            for info in history:
                self._async_track_service_info(info, bluetooth.BluetoothChange.ADVERTISEMENT)

            self.async_write_ha_state()

    def _match_service_info(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
    ) -> LocalObservation | None:
        apple_data = service_info.manufacturer_data.get(APPLE_COMPANY_ID)
        dult_data = service_info.service_data.get(DULT_SERVICE_UUID)
        if apple_data is None and dult_data is None:
            return None

        age = max(0.0, bluetooth.MONOTONIC_TIME() - service_info.time)
        detected_at = datetime.now(tz=UTC) - timedelta(seconds=age)

        observation = None
        if apple_data is not None:
            observation = match_local_advertisement(
                service_info.address,
                apple_data,
                detected_at,
                service_info.rssi,
                self._local_candidates,
            )
        if observation is None and dult_data is not None:
            observation = match_dult_advertisement(
                service_info.address,
                dult_data,
                detected_at,
                service_info.rssi,
                self._local_candidates,
            )
        return observation

    @callback
    def _async_track_service_info(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        if not self._local_candidates:
            return

        observation = self._match_service_info(service_info)
        if observation is None:
            return

        if (
            self._local_observation is not None
            and observation.detected_at < self._local_observation.detected_at
        ):
            return

        self._local_observation = observation
        self._local_source = service_info.source
        self.runtime.local_observations[self._attr_unique_id] = (
            observation,
            service_info.source,
        )

        # DULT carries no battery band; only store status when the Offline Finding
        # advertisement actually supplied battery information.
        if observation.battery_level is not None:
            self.runtime.local_status[self._attr_unique_id] = (
                observation.status,
                observation.detected_at,
            )

        async_dispatcher_send(
            self.hass,
            signal_local_observation(self._attr_unique_id),
            observation,
            service_info.source,
        )

        # Tell Bermuda that this rotating BLE address belongs to this stable
        # Find My accessory. Bermuda keeps the per-proxy advertisements/RSSI and
        # does its own distance and area calculations.
        self.hass.async_create_task(
            async_register_bermuda_source(
                self.hass,
                self.accessory,
                observation.mac_address,
            ),
            f"ha_findmy bermuda bridge: {self._attr_unique_id}",
        )

        # A primary-key observation can repair alignment for this runtime session.
        if observation.can_align:
            current_index = self.accessory._alignment_index
            if current_index != observation.key_index:
                self.accessory.update_alignment(
                    observation.detected_at,
                    observation.key_index,
                )
                self._schedule_local_candidate_refresh("realignment")

        self.async_write_ha_state()
