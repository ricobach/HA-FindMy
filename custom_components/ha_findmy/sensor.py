"""Sensors for remote position, battery and local Bluetooth diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cached_property

from findmy import FindMyAccessory
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.components.zone import async_active_zone
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bermuda_bridge import bermuda_coordinators, bermuda_location_snapshot
from ._entity import (
    battery_percent,
    build_device_info,
    latest_report,
    latest_status,
)
from .const import DOMAIN, signal_local_observation
from .coordinator import HAFindMyCoordinator, accessory_id
from .presence import HAFindMySignalStrengthSensor
from .runtime import HAFindMyRuntime


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    runtime: HAFindMyRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for accessory in runtime.accessories:
        entities.extend(
            [
                HAFindMyLatitudeSensor(runtime, accessory),
                HAFindMyLongitudeSensor(runtime, accessory),
                HAFindMyLastReportSensor(runtime, accessory),
                HAFindMyGPSAccuracySensor(runtime, accessory),
                HAFindMyCurrentLocationSensor(runtime, accessory),
                HAFindMyReportAgeSensor(runtime, accessory),
                HAFindMyLocalBLEDiagnosticSensor(runtime, accessory),
                HAFindMyBatteryPercentSensor(runtime, accessory),
                HAFindMySignalStrengthSensor(runtime, accessory),
            ]
        )
    async_add_entities(entities)


class _BaseSensor(CoordinatorEntity[HAFindMyCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    suffix = ""

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        super().__init__(runtime.coordinator, context=accessory_id(accessory))
        self.runtime = runtime
        self.accessory = accessory
        self._attr_unique_id = f"{accessory_id(accessory)}_{self.suffix}"

    @cached_property
    def device_info(self):
        return build_device_info(self.accessory)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_local_observation(accessory_id(self.accessory)),
                self._handle_local_observation,
            )
        )

    @callback
    def _handle_local_observation(self, *_args) -> None:
        self.async_write_ha_state()


class HAFindMyLatitudeSensor(_BaseSensor):
    _attr_name = "Latitude"
    _attr_native_unit_of_measurement = "°"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 6
    suffix = "latitude"

    @property
    def native_value(self):
        report = latest_report(self.coordinator, self.accessory)
        return report.latitude if report else None


class HAFindMyLongitudeSensor(_BaseSensor):
    _attr_name = "Longitude"
    _attr_native_unit_of_measurement = "°"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 6
    suffix = "longitude"

    @property
    def native_value(self):
        report = latest_report(self.coordinator, self.accessory)
        return report.longitude if report else None


class HAFindMyCurrentLocationSensor(_BaseSensor):
    """Best human-readable answer to where this accessory is."""

    _attr_name = "Current location"
    _attr_icon = "mdi:map-marker"
    suffix = "current_location"

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        super().__init__(runtime, accessory)
        self._bermuda_listener_ids: set[int] = set()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attach_bermuda_listeners()

    @callback
    def _attach_bermuda_listeners(self) -> None:
        """Listen for Bermuda area changes, including coordinators loaded later."""
        for coordinator in bermuda_coordinators(self.hass):
            coordinator_id = id(coordinator)
            if coordinator_id in self._bermuda_listener_ids:
                continue
            add_listener = getattr(coordinator, "async_add_listener", None)
            if callable(add_listener):
                self.async_on_remove(add_listener(self._handle_bermuda_update))
                self._bermuda_listener_ids.add(coordinator_id)

    @callback
    def _handle_local_observation(self, *_args) -> None:
        self._attach_bermuda_listeners()
        self.async_write_ha_state()

    @callback
    def _handle_bermuda_update(self) -> None:
        self.async_write_ha_state()

    def _gps_zone_name(self) -> str | None:
        report = latest_report(self.coordinator, self.accessory)
        if report is None:
            return None
        radius = float(report.horizontal_accuracy or 0)
        zone_state = async_active_zone(
            self.hass,
            float(report.latitude),
            float(report.longitude),
            radius,
        )
        return zone_state.name if zone_state is not None else None

    @property
    def native_value(self) -> str:
        bermuda = bermuda_location_snapshot(self.hass, self.accessory)
        if bermuda["area"]:
            return str(bermuda["area"])
        if bermuda["nearest_scanner"]:
            return str(bermuda["nearest_scanner"])

        zone_name = self._gps_zone_name()
        if zone_name:
            return zone_name

        if latest_report(self.coordinator, self.accessory) is not None:
            return "Away"
        return "Unknown"

    @property
    def extra_state_attributes(self):
        bermuda = bermuda_location_snapshot(self.hass, self.accessory)
        report = latest_report(self.coordinator, self.accessory)
        zone_name = self._gps_zone_name()

        if bermuda["area"]:
            source = "bermuda_area"
        elif bermuda["nearest_scanner"]:
            source = "bermuda_nearest_scanner"
        elif zone_name:
            source = "gps_zone"
        elif report is not None:
            source = "gps_away"
        else:
            source = "unknown"

        return {
            "source": source,
            "bermuda_area": bermuda["area"],
            "nearest_proxy": bermuda["nearest_scanner"],
            "bermuda_distance": bermuda["distance"],
            "bermuda_rssi": bermuda["rssi"],
            "gps_zone": zone_name,
            "gps_report_at": report.timestamp if report else None,
            "gps_accuracy": float(report.horizontal_accuracy)
            if report is not None and report.horizontal_accuracy is not None
            else None,
        }


class HAFindMyReportAgeSensor(_BaseSensor):
    """Age of the newest location report Apple returned."""

    _attr_name = "Find My report age"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-alert-outline"
    suffix = "report_age"

    @property
    def native_value(self) -> int | None:
        report = latest_report(self.coordinator, self.accessory)
        if report is None:
            return None
        timestamp = report.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        age = datetime.now(tz=UTC) - timestamp.astimezone(UTC)
        return max(0, round(age.total_seconds() / 60))

    @property
    def extra_state_attributes(self):
        report = latest_report(self.coordinator, self.accessory)
        return {
            "last_successful_poll": self.coordinator.last_poll_at,
            "report_timestamp": report.timestamp if report else None,
            "report_confidence": getattr(report, "confidence", None) if report else None,
            "report_payload_bytes": len(report.payload) if report else None,
        }


class HAFindMyLocalBLEDiagnosticSensor(_BaseSensor):
    """Diagnostic view of rolling keys and locally matched BLE advertisements."""

    _attr_name = "Local BLE diagnostic"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bluetooth-connect"
    suffix = "local_ble_diagnostic"

    @property
    def native_value(self) -> str:
        ident = accessory_id(self.accessory)
        observation_row = self.runtime.local_observations.get(ident)
        if observation_row is not None:
            return "seen"
        if self.runtime.local_key_candidates.get(ident, 0) > 0:
            return "keys ready"
        return "no keys"

    @property
    def extra_state_attributes(self):
        ident = accessory_id(self.accessory)
        observation_row = self.runtime.local_observations.get(ident)
        observation = observation_row[0] if observation_row else None
        source = observation_row[1] if observation_row else None
        return {
            "key_candidates": self.runtime.local_key_candidates.get(ident, 0),
            "last_ble_seen": observation.detected_at if observation else None,
            "ble_source": source,
            "ble_mac": observation.mac_address if observation else None,
            "ble_state": observation.state if observation else None,
            "ble_rssi": observation.rssi if observation else None,
            "model": getattr(self.accessory, "model", None),
            "serial_number": getattr(self.accessory, "serial_number", None),
            "group_identifier": getattr(self.accessory, "group_identifier", None),
        }


class HAFindMyGPSAccuracySensor(_BaseSensor):
    """Horizontal accuracy radius reported by the Find My network."""

    _attr_name = "GPS accuracy"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    suffix = "gps_accuracy"

    @property
    def native_value(self) -> float | None:
        report = latest_report(self.coordinator, self.accessory)
        if report is None or report.horizontal_accuracy is None:
            return None
        return float(report.horizontal_accuracy)


class HAFindMyLastReportSensor(_BaseSensor):
    _attr_name = "Last Find My report"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    suffix = "last_report"

    @property
    def native_value(self) -> datetime | None:
        report = latest_report(self.coordinator, self.accessory)
        return report.timestamp if report else None


class HAFindMyBatteryPercentSensor(_BaseSensor):
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    suffix = "battery"

    @property
    def native_value(self):
        return battery_percent(latest_status(self.runtime, self.accessory))

    @property
    def extra_state_attributes(self):
        return {
            "accuracy": "approximate",
            "note": "AirTags expose four battery bands, not an exact percentage.",
        }

