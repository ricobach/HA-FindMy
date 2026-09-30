"""Local Bluetooth presence and signal strength entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cached_property

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from findmy import FindMyAccessory

from ._entity import build_device_info
from .const import (
    DEFAULT_AWAY_TIMEOUT_MINUTES,
    signal_local_observation,
    signal_local_rssi,
)
from .coordinator import accessory_id
from .local_bluetooth import LocalObservation
from .runtime import HAFindMyRuntime

_REFRESH_INTERVAL = timedelta(seconds=30)
_ATTRIBUTE_UPDATE_DELAY = timedelta(minutes=5)
_RSSI_UPDATE_THRESHOLD = 3


class HAFindMyPresenceBinarySensor(BinarySensorEntity):
    """On while the accessory is being heard by HA Bluetooth."""

    _attr_has_entity_name = True
    _attr_name = "Bluetooth presence"
    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_should_poll = False
    _unrecorded_attributes = frozenset(
        {"last_seen", "rssi", "source", "mac_address", "local_state"}
    )

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        self.runtime = runtime
        self.accessory = accessory
        self.identifier = accessory_id(accessory)
        self._attr_unique_id = f"{self.identifier}_bluetooth_presence"
        self._is_on = False
        self._last_seen: datetime | None = None
        self._rssi: int | None = None
        self._source: str | None = None
        self._mac_address: str | None = None
        self._local_state: str | None = None

    @cached_property
    def device_info(self):
        return build_device_info(self.accessory)

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self):
        return {
            "last_seen": self._last_seen,
            "rssi": self._rssi,
            "source": self._source,
            "mac_address": self._mac_address,
            "local_state": self._local_state,
            "away_timeout": DEFAULT_AWAY_TIMEOUT_MINUTES,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        stored = self.runtime.local_observations.get(self.identifier)
        if stored is not None:
            self._handle_observation(*stored)

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_local_observation(self.identifier),
                self._handle_observation,
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_refresh, _REFRESH_INTERVAL)
        )

    @callback
    def _handle_observation(
        self,
        observation: LocalObservation,
        source: str | None,
    ) -> None:
        if self._last_seen is not None and observation.detected_at < self._last_seen:
            return
        self._last_seen = observation.detected_at
        self._rssi = observation.rssi
        self._source = source
        self._mac_address = observation.mac_address
        self._local_state = observation.state
        self._update_state(force=True)

    @callback
    def _async_refresh(self, _now: datetime | None = None) -> None:
        if self._mac_address is not None:
            info = bluetooth.async_last_service_info(
                self.hass,
                self._mac_address,
                connectable=False,
            )
            if info is not None:
                age = max(0.0, bluetooth.MONOTONIC_TIME() - info.time)
                heard_at = datetime.now(tz=UTC) - timedelta(seconds=age)
                if self._last_seen is None or heard_at > self._last_seen:
                    self._last_seen = heard_at
                    self._rssi = info.rssi
                    self._source = info.source
        self._update_state(force=False)

    @callback
    def _update_state(self, *, force: bool) -> None:
        now = datetime.now(tz=UTC)
        was_on = self._is_on
        self._is_on = (
            self._last_seen is not None
            and now - self._last_seen <= timedelta(minutes=DEFAULT_AWAY_TIMEOUT_MINUTES)
        )

        rssi = self._rssi if self._is_on else None
        if self.runtime.local_rssi.get(self.identifier) != rssi:
            self.runtime.local_rssi[self.identifier] = rssi
            async_dispatcher_send(self.hass, signal_local_rssi(self.identifier))

        if force or was_on != self._is_on:
            self.async_write_ha_state()
        else:
            # Keep last_seen useful without hammering the recorder.
            self.async_write_ha_state()


class HAFindMySignalStrengthSensor(SensorEntity):
    """RSSI from whichever HA adapter/proxy most recently heard the accessory."""

    _attr_has_entity_name = True
    _attr_name = "Signal strength"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        self.runtime = runtime
        self.accessory = accessory
        self.identifier = accessory_id(accessory)
        self._attr_unique_id = f"{self.identifier}_signal_strength"
        self._rssi: int | None = None
        self._last_write: datetime | None = None

    @cached_property
    def device_info(self):
        return build_device_info(self.accessory)

    @property
    def native_value(self) -> int | None:
        return self._rssi

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._rssi = self.runtime.local_rssi.get(self.identifier)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_local_rssi(self.identifier),
                self._handle_rssi,
            )
        )

    @callback
    def _handle_rssi(self) -> None:
        rssi = self.runtime.local_rssi.get(self.identifier)
        previous = self._rssi
        now = datetime.now(tz=UTC)
        due = self._last_write is None or now - self._last_write >= _ATTRIBUTE_UPDATE_DELAY
        changed = (
            rssi is None
            or previous is None
            or abs(rssi - previous) >= _RSSI_UPDATE_THRESHOLD
        )
        if rssi == previous or not (changed or due):
            return
        self._rssi = rssi
        self._last_write = now
        self.async_write_ha_state()
