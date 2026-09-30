"""Location polling coordinator for HA-FindMy."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from findmy import (
    AsyncAppleAccount,
    FindMyAccessory,
    InvalidStateError,
    LocationReport,
    UnauthorizedError,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_ACCOUNT, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def accessory_id(accessory: FindMyAccessory) -> str:
    """Return the stable identifier used by Home Assistant."""
    identifier = accessory.identifier
    if identifier:
        return identifier
    # FindMyAccessory should normally have an identifier. Keeping a deterministic fallback
    # prevents one malformed record from taking down the entire integration.
    return f"unnamed-{abs(hash(str(accessory.to_json())))}"


def _scrub_password(account_data: dict[str, Any]) -> dict[str, Any]:
    """Remove the Apple ID password from serialized FindMy.py state."""
    account = account_data.get("account")
    if isinstance(account, dict):
        account["password"] = None
    return account_data


class HAFindMyCoordinator(DataUpdateCoordinator[dict[str, LocationReport | None]]):
    """Poll Apple for the selected accessories."""

    def __init__(
        self,
        hass,
        entry: ConfigEntry,
        account: AsyncAppleAccount,
        accessories: list[FindMyAccessory],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="HA-FindMy locations",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.entry = entry
        self.account = account
        self.accessories = accessories
        self.last_poll_at: datetime | None = None

    async def _async_update_data(self) -> dict[str, LocationReport | None]:
        try:
            reports = await self.account.fetch_location(self.accessories)
        except (UnauthorizedError, InvalidStateError) as err:
            raise ConfigEntryAuthFailed("Apple account authentication is no longer valid") from err
        except Exception as err:
            raise UpdateFailed(f"Unable to fetch Find My locations: {err}") from err

        self.last_poll_at = datetime.now(tz=UTC)

        result: dict[str, LocationReport | None] = {}
        for accessory, report in reports.items():
            if isinstance(accessory, FindMyAccessory):
                result[accessory_id(accessory)] = report

        # FindMy.py can refresh session state while talking to Apple. Persist the newest session,
        # but never persist the password.
        account_data = _scrub_password(dict(self.account.to_json()))
        if account_data != self.entry.data.get(CONF_ACCOUNT):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_ACCOUNT: account_data},
            )

        return result
