"""Optional bridge from HA-FindMy to Bermuda BLE Trilateration.

Bermuda already has the right data model for rotating-address devices: a stable
"metadevice" owns one or more short-lived source MAC addresses. Private BLE Device
feeds that model with IRK resolutions. HA-FindMy can feed the same model with Find My
rolling-key resolutions.

This module deliberately has no import-time dependency on Bermuda. The integration
keeps working when Bermuda is absent, disabled, or not yet loaded.
"""

from __future__ import annotations

import logging
from typing import Any

from findmy import FindMyAccessory
from homeassistant.core import HomeAssistant

from .coordinator import accessory_id

_LOGGER = logging.getLogger(__name__)

_BERMUDA_DOMAIN = "bermuda"
_STABLE_PREFIX = "findmy:"


def _stable_id(accessory: FindMyAccessory) -> str:
    """Return a stable, non-MAC identifier for Bermuda."""
    return f"{_STABLE_PREFIX}{accessory_id(accessory)}"


def bermuda_coordinators(hass: HomeAssistant) -> list[Any]:
    """Return currently loaded Bermuda coordinators without importing Bermuda."""
    coordinators: list[Any] = []
    for entry in hass.config_entries.async_entries(_BERMUDA_DOMAIN, include_disabled=False):
        runtime_data = getattr(entry, "runtime_data", None)
        coordinator = getattr(runtime_data, "coordinator", None)
        if coordinator is not None:
            coordinators.append(coordinator)
    return coordinators



def bermuda_location_snapshot(
    hass: HomeAssistant,
    accessory: FindMyAccessory,
) -> dict[str, object | None]:
    """Return Bermuda's current local-location data for one accessory."""
    empty: dict[str, object | None] = {
        "area": None,
        "nearest_scanner": None,
        "distance": None,
        "rssi": None,
    }
    stable_id = _stable_id(accessory).lower()
    best = empty

    for coordinator in bermuda_coordinators(hass):
        try:
            metadevices = getattr(coordinator, "metadevices", None)
            if not isinstance(metadevices, dict):
                continue

            metadevice = metadevices.get(stable_id)
            if metadevice is None:
                devices = getattr(coordinator, "devices", None)
                if isinstance(devices, dict):
                    metadevice = devices.get(stable_id)
            if metadevice is None:
                continue

            area = getattr(metadevice, "area_name", None)
            distance = getattr(metadevice, "area_distance", None)
            rssi = getattr(metadevice, "area_rssi", None)

            nearest_scanner = None
            area_advert = getattr(metadevice, "area_advert", None)
            scanner_address = getattr(area_advert, "scanner_address", None)
            devices = getattr(coordinator, "devices", None)
            if scanner_address is not None and isinstance(devices, dict):
                scanner = devices.get(scanner_address)
                if scanner is not None:
                    nearest_scanner = getattr(scanner, "name", None)

            snapshot = {
                "area": area,
                "nearest_scanner": nearest_scanner,
                "distance": round(float(distance), 1) if distance is not None else None,
                "rssi": round(float(rssi), 1) if rssi is not None else None,
            }

            if area:
                return snapshot
            if nearest_scanner:
                best = snapshot
        except Exception:
            _LOGGER.debug("Could not read Bermuda location snapshot", exc_info=True)

    return best

def _ensure_metadevice(
    coordinator: Any,
    accessory: FindMyAccessory,
) -> tuple[Any | None, bool]:
    """Create/update Bermuda's stable metadevice for an accessory.

    Bermuda does not currently expose a public external-resolver API, so this is a
    compatibility shim over its current metadevice interface. Every private attribute
    access is guarded; an incompatible Bermuda version simply disables the bridge.
    """
    getter = getattr(coordinator, "_get_or_create_device", None)
    metadevices = getattr(coordinator, "metadevices", None)
    if not callable(getter) or not isinstance(metadevices, dict):
        return None, False

    stable_id = _stable_id(accessory)
    metadevice = getter(stable_id)
    changed = False

    if stable_id.lower() not in metadevices:
        metadevices[metadevice.address] = metadevice
        changed = True

    if not getattr(metadevice, "create_sensor", False):
        metadevice.create_sensor = True
        changed = True

    name = accessory.name or "Find My accessory"
    if getattr(metadevice, "name_by_user", None) != name:
        metadevice.name_by_user = name
        changed = True

    make_name = getattr(metadevice, "make_name", None)
    if callable(make_name):
        make_name()

    return metadevice, changed


async def _refresh_if_changed(coordinator: Any, changed: bool) -> None:
    """Ask Bermuda to process newly registered mappings promptly."""
    if not changed:
        return
    request_refresh = getattr(coordinator, "async_request_refresh", None)
    if callable(request_refresh):
        try:
            await request_refresh()
        except Exception:  # Bermuda must never make HA-FindMy fail.
            _LOGGER.debug("Bermuda refresh after Find My registration failed", exc_info=True)


async def async_register_accessories_with_bermuda(
    hass: HomeAssistant,
    accessories: list[FindMyAccessory],
) -> None:
    """Register stable Find My devices with every loaded Bermuda instance."""
    coordinators = bermuda_coordinators(hass)
    if not coordinators:
        return

    for coordinator in coordinators:
        changed = False
        try:
            for accessory in accessories:
                _metadevice, item_changed = _ensure_metadevice(coordinator, accessory)
                changed = changed or item_changed
            await _refresh_if_changed(coordinator, changed)
        except Exception:
            _LOGGER.warning(
                "Bermuda is installed but its internal API is not compatible with "
                "the HA-FindMy bridge",
                exc_info=True,
            )


async def async_register_bermuda_source(
    hass: HomeAssistant,
    accessory: FindMyAccessory,
    bluetooth_address: str,
) -> None:
    """Attach a resolved rotating AirTag address to its Bermuda metadevice."""
    coordinators = bermuda_coordinators(hass)
    if not coordinators:
        return

    for coordinator in coordinators:
        try:
            metadevice, changed = _ensure_metadevice(coordinator, accessory)
            if metadevice is None:
                continue

            getter = getattr(coordinator, "_get_or_create_device", None)
            if not callable(getter):
                continue

            # Ensure Bermuda has a source device object for the actual Bluetooth
            # address. Its own gathering loop owns all per-scanner adverts, RSSI,
            # distance history and timestamps on this source.
            source_device = getter(bluetooth_address)
            source_address = source_device.address

            sources = getattr(metadevice, "metadevice_sources", None)
            if not isinstance(sources, list):
                continue

            if source_address in sources:
                # Keep the freshest rotating address at index zero, which also
                # matches Bermuda's pruning assumptions.
                if sources[0] != source_address:
                    sources.remove(source_address)
                    sources.insert(0, source_address)
                    changed = True
            else:
                sources.insert(0, source_address)
                changed = True
                _LOGGER.debug(
                    "Registered Find My accessory %s with Bermuda source %s",
                    accessory.name or accessory_id(accessory),
                    source_address,
                )

            await _refresh_if_changed(coordinator, changed)
        except Exception:
            _LOGGER.warning(
                "Could not register Find My Bluetooth source with Bermuda",
                exc_info=True,
            )
