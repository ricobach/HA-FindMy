"""Binary sensors for HA-FindMy."""

from __future__ import annotations

from findmy import FindMyAccessory
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ._entity import battery_bits, build_device_info, latest_status
from .const import DOMAIN, signal_local_observation
from .coordinator import accessory_id
from .presence import HAFindMyPresenceBinarySensor
from .runtime import HAFindMyRuntime


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    runtime: HAFindMyRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for accessory in runtime.accessories:
        entities.extend(
            [
                HAFindMyBatteryLowBinarySensor(runtime, accessory),
                HAFindMyPresenceBinarySensor(runtime, accessory),
            ]
        )
    async_add_entities(entities)


class HAFindMyBatteryLowBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Battery low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_should_poll = False

    def __init__(self, runtime: HAFindMyRuntime, accessory: FindMyAccessory) -> None:
        self.runtime = runtime
        self.accessory = accessory
        self._attr_unique_id = f"{accessory_id(accessory)}_battery_low"

    @property
    def device_info(self):
        return build_device_info(self.accessory)

    @property
    def is_on(self) -> bool | None:
        bits = battery_bits(latest_status(self.runtime, self.accessory))
        if bits is None:
            return None
        return bits >= 0b10

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.coordinator.async_add_listener(self._handle_update)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_local_observation(accessory_id(self.accessory)),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, *_args) -> None:
        self.async_write_ha_state()
