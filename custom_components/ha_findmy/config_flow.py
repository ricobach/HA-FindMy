"""Config flow for HA-FindMy."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from findmy import (
    AsyncAppleAccount,
    AsyncSmsSecondFactor,
    AsyncTrustedDeviceSecondFactor,
    InvalidCredentialsError,
    LocalAnisetteProvider,
    LoginState,
)
from findmy.icloud import AsyncFindMyClient
from findmy.keychain.recovery import RecoveryError
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import CONF_ACCESSORIES, CONF_ACCOUNT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HAFindMyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an Apple account and import its Find My accessories."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._account: AsyncAppleAccount | None = None
        self._two_factor_methods: list[Any] = []
        self._two_factor_method: Any | None = None
        self._client: AsyncFindMyClient | None = None
        self._recovery_records: list[Any] = []
        self._accessories: list[Any] = []

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Collect Apple ID credentials and sign in."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            try:
                # LocalAnisetteProvider may download ADI support libraries on first use. Its
                # constructor must therefore not run on Home Assistant's event loop.
                provider = await self.hass.async_add_executor_job(LocalAnisetteProvider)
                self._account = AsyncAppleAccount(
                    provider,
                    device_name="HA-FindMy",
                    timeout=30,
                )
                self._email = email
                state = await self._account.login(email, password)
            except InvalidCredentialsError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Apple sign-in failed")
                errors["base"] = "cannot_connect"
            else:
                if state == LoginState.REQUIRE_2FA:
                    return await self.async_step_two_factor_method()
                if state == LoginState.LOGGED_IN:
                    return await self._open_keychain()
                errors["base"] = "unexpected_state"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_two_factor_method(self, user_input=None) -> FlowResult:
        """Choose where Apple should send the verification code."""
        assert self._account is not None

        if not self._two_factor_methods:
            try:
                self._two_factor_methods = list(await self._account.get_2fa_methods())
            except Exception:
                _LOGGER.exception("Unable to enumerate Apple 2FA methods")
                return self.async_abort(reason="cannot_get_2fa")

        choices: dict[str, str] = {}
        for index, method in enumerate(self._two_factor_methods):
            if isinstance(method, AsyncTrustedDeviceSecondFactor):
                label = "Trusted Apple device"
            elif isinstance(method, AsyncSmsSecondFactor):
                label = f"SMS to {method.phone_number}"
            else:
                label = type(method).__name__
            choices[str(index)] = label

        if user_input is not None:
            index = int(user_input["method"])
            self._two_factor_method = self._two_factor_methods[index]
            try:
                await self._two_factor_method.request()
            except Exception:
                _LOGGER.exception("Unable to request Apple verification code")
                return self.async_show_form(
                    step_id="two_factor_method",
                    data_schema=vol.Schema({vol.Required("method"): vol.In(choices)}),
                    errors={"base": "cannot_request_code"},
                )
            return await self.async_step_two_factor_code()

        return self.async_show_form(
            step_id="two_factor_method",
            data_schema=vol.Schema({vol.Required("method"): vol.In(choices)}),
        )

    async def async_step_two_factor_code(self, user_input=None) -> FlowResult:
        """Submit Apple's verification code."""
        assert self._two_factor_method is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                state = await self._two_factor_method.submit(user_input["code"].strip())
            except InvalidCredentialsError:
                errors["base"] = "invalid_code"
            except Exception:
                _LOGGER.exception("Apple rejected or failed the verification step")
                errors["base"] = "cannot_connect"
            else:
                if state == LoginState.LOGGED_IN:
                    return await self._open_keychain()
                errors["base"] = "unexpected_state"

        return self.async_show_form(
            step_id="two_factor_code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )

    async def _open_keychain(self) -> FlowResult:
        """Open the read-only Find My/iCloud client and list recovery devices."""
        assert self._account is not None
        try:
            self._client = await AsyncFindMyClient.open(self._account)
            options = await self._client.recovery_options()
            self._recovery_records = list(options.recoverable)
        except Exception:
            _LOGGER.exception("Unable to open iCloud Keychain recovery")
            return self.async_abort(reason="cannot_open_keychain")

        if not self._recovery_records:
            return self.async_abort(reason="no_recovery_devices")

        return await self.async_step_recovery_device()

    async def async_step_recovery_device(self, user_input=None) -> FlowResult:
        """Choose the trusted device whose screen-lock passcode will unlock the keychain."""
        choices = {
            str(index): record.describe()
            for index, record in enumerate(self._recovery_records)
        }

        if user_input is not None:
            self._selected_recovery_record = self._recovery_records[
                int(user_input["recovery_device"])
            ]
            return await self.async_step_device_passcode()

        return self.async_show_form(
            step_id="recovery_device",
            data_schema=vol.Schema(
                {vol.Required("recovery_device"): vol.In(choices)}
            ),
        )

    async def async_step_device_passcode(self, user_input=None) -> FlowResult:
        """Unlock keychain keys with a device screen-lock passcode.

        The passcode is intentionally never placed in config-entry data.
        """
        assert self._client is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            passcode = user_input["passcode"]
            try:
                await self._client.unlock(self._selected_recovery_record, passcode)
                self._accessories = list(await self._client.accessories())
            except RecoveryError:
                errors["base"] = "invalid_passcode"
            except Exception:
                _LOGGER.exception("Unable to recover Find My accessory keys")
                errors["base"] = "cannot_recover"
            finally:
                # Keep the secret scoped to this call only.
                passcode = None

            if not errors:
                if not self._accessories:
                    return self.async_abort(reason="no_accessories")
                await self._client.close()
                self._client = None
                return await self.async_step_accessories()

        return self.async_show_form(
            step_id="device_passcode",
            data_schema=vol.Schema({vol.Required("passcode"): str}),
            errors=errors,
        )

    async def async_step_accessories(self, user_input=None) -> FlowResult:
        """Select which discovered accessories to add."""
        choices: dict[str, str] = {}
        by_id: dict[str, Any] = {}

        for index, accessory in enumerate(self._accessories):
            key = str(index)
            name = accessory.name or "Unnamed Find My accessory"
            serial = getattr(accessory, "serial_number", None)
            choices[key] = f"{name} ({serial})" if serial else name
            by_id[key] = accessory

        if user_input is not None:
            selected = user_input["accessories"]
            if not selected:
                return self.async_show_form(
                    step_id="accessories",
                    data_schema=vol.Schema(
                        {vol.Required("accessories"): cv.multi_select(choices)}
                    ),
                    errors={"base": "select_one"},
                )

            account_data = dict(self._account.to_json()) if self._account else {}
            account_section = account_data.get("account")
            if isinstance(account_section, dict):
                account_section["password"] = None

            accessory_data = [by_id[key].to_json() for key in selected]
            title = self._email or "Apple Find My"

            if self._account is not None:
                await self._account.close()
                self._account = None

            return self.async_create_entry(
                title=title,
                data={
                    CONF_ACCOUNT: account_data,
                    CONF_ACCESSORIES: accessory_data,
                },
            )

        return self.async_show_form(
            step_id="accessories",
            data_schema=vol.Schema(
                {vol.Required("accessories"): cv.multi_select(choices)}
            ),
        )
