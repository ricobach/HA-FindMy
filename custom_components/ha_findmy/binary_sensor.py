"""Binary sensors for HA-FindMy."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .presence import HAFindMyPresenceBinarySensor
from .runtime import HAFindMyRuntime


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    """Set up local Bluetooth presence for each selected accessory."""
    runtime: HAFindMyRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        HAFindMyPresenceBinarySensor(runtime, accessory)
        for accessory in runtime.accessories
    ]
    async_add_entities(entities)
