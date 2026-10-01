"""Location polling coordinator for HA-FindMy."""

from __future__ import annotations

import asyncio
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

_ACCESSORY_FETCH_TIMEOUT = 180


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
        """Fetch accessories sequentially to avoid throttling Apple's report service."""
        previous = self.data or {}
        result: dict[str, LocationReport | None] = dict(previous)
        failures = 0
        successes = 0

        for accessory in self.accessories:
            identifier = accessory_id(accessory)
            try:
                # FindMy.py may need multiple report requests while walking a stale
                # rolling-key window. Keep this generous; startup no longer waits
                # for the coordinator, so a slow Apple response cannot block HA.
                async with asyncio.timeout(_ACCESSORY_FETCH_TIMEOUT):
                    report = await self.account.fetch_location(accessory)
            except (UnauthorizedError, InvalidStateError) as err:
                raise ConfigEntryAuthFailed(
                    "Apple account authentication is no longer valid"
                ) from err
            except TimeoutError:
                failures += 1
                _LOGGER.warning(
                    "Apple Find My request for %s timed out after %s seconds; "
                    "keeping the previous report",
                    identifier,
                    _ACCESSORY_FETCH_TIMEOUT,
                )
                continue
            except Exception as err:
                failures += 1
                _LOGGER.warning(
                    "Apple Find My request for %s failed: %s; keeping the previous report",
                    identifier,
                    err,
                )
                continue

            result[identifier] = report
            successes += 1

        self.last_poll_at = datetime.now(tz=UTC)

        if self.accessories and successes == 0 and not previous:
            raise UpdateFailed(
                "All Apple Find My accessory requests failed; will retry on the next refresh"
            )

        account_data = _scrub_password(dict(self.account.to_json()))
        if account_data != self.entry.data.get(CONF_ACCOUNT):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_ACCOUNT: account_data},
            )

        return result
