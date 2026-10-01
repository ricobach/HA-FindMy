"""HA-FindMy integration setup."""

from __future__ import annotations

import logging

from findmy import AsyncAppleAccount, FindMyAccessory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_ACCESSORIES, CONF_ACCOUNT, DOMAIN, PLATFORMS
from .bermuda_bridge import async_register_accessories_with_bermuda
from .coordinator import HAFindMyCoordinator, accessory_id
from .runtime import HAFindMyRuntime

_LOGGER = logging.getLogger(__name__)


async def _restore_account(hass: HomeAssistant, data: dict) -> AsyncAppleAccount:
    """Restore FindMy.py account state outside Home Assistant's event loop."""
    return await hass.async_add_executor_job(AsyncAppleAccount.from_json, data)


async def _restore_accessories(hass: HomeAssistant, rows: list[dict]) -> list[FindMyAccessory]:
    """Restore selected accessories outside the event loop."""
    return await hass.async_add_executor_job(
        lambda: [FindMyAccessory.from_json(row) for row in rows]
    )


def _remove_retired_battery_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    accessories: list[FindMyAccessory],
) -> None:
    """Remove battery entities retired in v0.3.1 from the entity registry."""
    registry = er.async_get(hass)
    for accessory in accessories:
        identifier = accessory_id(accessory)
        for platform, suffix in (
            ("sensor", "battery_level"),
            ("binary_sensor", "battery_low"),
        ):
            entity_id = registry.async_get_entity_id(
                platform,
                DOMAIN,
                f"{identifier}_{suffix}",
            )
            if entity_id is not None:
                registry.async_remove(entity_id)


def _accessory_rows(entry: ConfigEntry) -> list[dict]:
    """Return selected accessories, preferring post-setup options."""
    rows = entry.options.get(CONF_ACCESSORIES, entry.data.get(CONF_ACCESSORIES, []))
    return [dict(item) for item in rows]


def _remove_unselected_registry_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    active_accessories: list[FindMyAccessory],
) -> None:
    """Remove stale entities/devices for accessories no longer selected."""
    active_ids = {accessory_id(accessory) for accessory in active_accessories}

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    stale_device_ids: set[str] = set()
    stale_accessory_ids: set[str] = set()

    for device in list(dr.async_entries_for_config_entry(
        device_registry,
        entry.entry_id,
    )):
        accessory_ids = {
            identifier
            for domain, identifier in device.identifiers
            if domain == DOMAIN
        }
        if not accessory_ids:
            continue
        if accessory_ids.isdisjoint(active_ids):
            stale_device_ids.add(device.id)
            stale_accessory_ids.update(accessory_ids)

    for entity in list(er.async_entries_for_config_entry(
        entity_registry,
        entry.entry_id,
    )):
        if entity.device_id in stale_device_ids or any(
            entity.unique_id == identifier
            or entity.unique_id.startswith(f"{identifier}_")
            for identifier in stale_accessory_ids
        ):
            entity_registry.async_remove(entity.entity_id)

    for device_id in stale_device_ids:
        device_registry.async_remove_device(device_id)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when the selected accessory options changed."""
    runtime: HAFindMyRuntime | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return

    configured_rows = _accessory_rows(entry)
    configured_ids = {
        row.get("identifier")
        for row in configured_rows
        if isinstance(row, dict) and row.get("identifier")
    }
    runtime_ids = {accessory_id(accessory) for accessory in runtime.accessories}

    # Coordinator session-state persistence updates entry.data too. Do not reload
    # for those updates; only a real accessory selection change needs a reload.
    if configured_ids == runtime_ids:
        return

    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA-FindMy from a config entry."""
    account = await _restore_account(hass, dict(entry.data[CONF_ACCOUNT]))
    accessories = await _restore_accessories(hass, _accessory_rows(entry))

    _remove_retired_battery_entities(hass, entry, accessories)
    _remove_unselected_registry_entries(hass, entry, accessories)

    coordinator = HAFindMyCoordinator(hass, entry, account, accessories)
    # Do not block config-entry setup on Apple's Find My report endpoint. It can
    # legitimately take long enough for Home Assistant's bootstrap watchdog to
    # cancel the whole integration. Entities can start with no cloud report and
    # populate as soon as the background refresh completes.
    coordinator.async_set_updated_data({})

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = HAFindMyRuntime(
        account=account,
        accessories=accessories,
        coordinator=coordinator,
    )

    # Optional integration: when Bermuda is installed and loaded, expose each
    # accessory as a stable Bermuda metadevice. Rotating BLE source addresses
    # are attached later as HA-FindMy resolves them.
    await async_register_accessories_with_bermuda(hass, accessories)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    entry.async_create_background_task(
        hass,
        coordinator.async_request_refresh(),
        f"{DOMAIN} initial Find My refresh",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA-FindMy."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    runtime: HAFindMyRuntime | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.account.close()

    return True
