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

_ACCESSORY_FETCH_TIMEOUT = 45
_MAX_CONCURRENT_FETCHES = 3


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
        """Fetch accessories independently so one slow Apple request cannot block all data."""
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

        async def _fetch_one(
            accessory: FindMyAccessory,
        ) -> tuple[str, LocationReport | None, Exception | None]:
            identifier = accessory_id(accessory)
            try:
                async with semaphore:
                    async with asyncio.timeout(_ACCESSORY_FETCH_TIMEOUT):
                        report = await self.account.fetch_location(accessory)
                return identifier, report, None
            except (UnauthorizedError, InvalidStateError):
                raise
            except Exception as err:
                return identifier, None, err

        try:
            rows = await asyncio.gather(
                *(_fetch_one(accessory) for accessory in self.accessories)
            )
        except (UnauthorizedError, InvalidStateError) as err:
            raise ConfigEntryAuthFailed(
                "Apple account authentication is no longer valid"
            ) from err

        # Keep the last good value for an accessory whose current request failed.
        previous = self.data or {}
        result: dict[str, LocationReport | None] = dict(previous)
        failures = 0

        for identifier, report, error in rows:
            if error is None:
                result[identifier] = report
                continue

            failures += 1
            if isinstance(error, TimeoutError):
                _LOGGER.warning(
                    "Apple Find My request for %s timed out after %s seconds; "
                    "keeping the previous report",
                    identifier,
                    _ACCESSORY_FETCH_TIMEOUT,
                )
            else:
                _LOGGER.warning(
                    "Apple Find My request for %s failed: %s; keeping the previous report",
                    identifier,
                    error,
                )

        self.last_poll_at = datetime.now(tz=UTC)

        # If every accessory failed and there is no previous cloud data at all,
        # report the coordinator update as failed. Otherwise publish the partial
        # refresh so healthy accessories still update.
        if self.accessories and failures == len(self.accessories) and not previous:
            raise UpdateFailed(
                "All Apple Find My accessory requests failed; will retry on the next refresh"
            )

        # FindMy.py can refresh session state while talking to Apple. Persist the newest session,
        # but never persist the password.
        account_data = _scrub_password(dict(self.account.to_json()))
        if account_data != self.entry.data.get(CONF_ACCOUNT):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_ACCOUNT: account_data},
            )

        return result
