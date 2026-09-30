"""Shared entity helpers for HA-FindMy."""

from __future__ import annotations

from findmy import FindMyAccessory, LocationReport
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import HAFindMyCoordinator, accessory_id
from .runtime import HAFindMyRuntime


def build_device_info(accessory: FindMyAccessory) -> DeviceInfo:
    """Build a common HA device for all entities belonging to an accessory."""
    return DeviceInfo(
        identifiers={(DOMAIN, accessory_id(accessory))},
        name=accessory.name or "Find My accessory",
        manufacturer="Apple Find My",
        model=getattr(accessory, "model", None),
        serial_number=getattr(accessory, "serial_number", None),
    )


def latest_report(
    coordinator: HAFindMyCoordinator,
    accessory: FindMyAccessory,
) -> LocationReport | None:
    """Return the latest remote Find My report."""
    if not coordinator.data:
        return None
    return coordinator.data.get(accessory_id(accessory))


def latest_status(
    runtime: HAFindMyRuntime,
    accessory: FindMyAccessory,
) -> int | None:
    """Return the newest status byte from cloud or local Bluetooth."""
    report = latest_report(runtime.coordinator, accessory)
    local = runtime.local_status.get(accessory_id(accessory))
    if local is None:
        return report.status if report else None
    if report is None or report.timestamp <= local[1]:
        return local[0]
    return report.status


# AirTags report four battery bands, not a real percentage. These are intentionally
# approximate midpoints so HA can render a battery gauge without pretending precision.
BATTERY_PERCENTS = {
    0b00: 90,
    0b01: 65,
    0b10: 40,
    0b11: 15,
}


def battery_bits(status: int | None) -> int | None:
    if status is None:
        return None
    return (status >> 6) & 0b11


def battery_percent(status: int | None) -> int | None:
    bits = battery_bits(status)
    return BATTERY_PERCENTS.get(bits) if bits is not None else None
