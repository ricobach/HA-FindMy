"""HA-FindMy integration setup."""

from __future__ import annotations

import logging

from findmy import AsyncAppleAccount, FindMyAccessory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESSORIES, CONF_ACCOUNT, DOMAIN, PLATFORMS
from .bermuda_bridge import async_register_accessories_with_bermuda
from .coordinator import HAFindMyCoordinator
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA-FindMy from a config entry."""
    account = await _restore_account(hass, dict(entry.data[CONF_ACCOUNT]))
    accessories = await _restore_accessories(
        hass, [dict(item) for item in entry.data[CONF_ACCESSORIES]]
    )

    coordinator = HAFindMyCoordinator(hass, entry, account, accessories)
    await coordinator.async_config_entry_first_refresh()

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
