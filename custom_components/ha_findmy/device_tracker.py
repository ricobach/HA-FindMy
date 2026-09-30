"""Device tracker entities for HA-FindMy."""

from __future__ import annotations

from functools import cached_property

from findmy import FindMyAccessory, LocationReport
from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HAFindMyCoordinator, accessory_id
from .runtime import HAFindMyRuntime


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    """Set up one tracker for each selected accessory."""
    runtime: HAFindMyRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HAFindMyTracker(runtime.coordinator, accessory)
        for accessory in runtime.accessories
    )


class HAFindMyTracker(CoordinatorEntity[HAFindMyCoordinator], TrackerEntity):
    """A Find My accessory."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HAFindMyCoordinator,
        accessory: FindMyAccessory,
    ) -> None:
        super().__init__(coordinator)
        self.accessory = accessory
        self._attr_unique_id = accessory_id(accessory)

    @property
    def report(self) -> LocationReport | None:
        """Return the latest report for this accessory."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._attr_unique_id)

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        report = self.report
        return report.latitude if report else None

    @property
    def longitude(self) -> float | None:
        report = self.report
        return report.longitude if report else None

    @property
    def location_accuracy(self) -> float:
        report = self.report
        return float(report.horizontal_accuracy) if report else 0.0

    @property
    def battery_level(self) -> int | None:
        """Expose no guessed percentage yet.

        Find My reports contain a status byte rather than a true percentage. A later sensor
        implementation can decode it explicitly without implying precision here.
        """
        return None

    @cached_property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self.accessory.name or "Find My accessory",
            manufacturer="Apple Find My",
        )

    @property
    def extra_state_attributes(self):
        report = self.report
        return {
            "detected_at": report.timestamp if report else None,
            "status": report.status if report else None,
            "serial_number": getattr(self.accessory, "serial_number", None),
            "model": getattr(self.accessory, "model", None),
        }
