"""Sensors for remote position, battery and local Bluetooth diagnostics."""

from __future__ import annotations

from datetime import datetime
from functools import cached_property

from findmy import FindMyAccessory
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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

