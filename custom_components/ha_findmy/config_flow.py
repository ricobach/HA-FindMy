"""Config flow for HA-FindMy."""

from __future__ import annotations

import logging
from copy import deepcopy
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
from findmy.keychain.session import KeychainSessionError
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HAFindMyOptionsFlow":
        """Return the options flow for accessory management."""
        return HAFindMyOptionsFlow()

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
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

    async def async_step_two_factor_method(self, user_input=None) -> config_entries.ConfigFlowResult:
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

    async def async_step_two_factor_code(self, user_input=None) -> config_entries.ConfigFlowResult:
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

    async def _open_keychain(self) -> config_entries.ConfigFlowResult:
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

    async def async_step_recovery_device(self, user_input=None) -> config_entries.ConfigFlowResult:
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

    async def async_step_device_passcode(self, user_input=None) -> config_entries.ConfigFlowResult:
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

    async def async_step_accessories(self, user_input=None) -> config_entries.ConfigFlowResult:
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


class HAFindMyOptionsFlow(config_entries.OptionsFlow):
    """Add or remove Find My accessories on an existing config entry."""

    def __init__(self) -> None:
        self._account: AsyncAppleAccount | None = None
        self._client: AsyncFindMyClient | None = None
        self._two_factor_methods: list[Any] = []
        self._two_factor_method: Any | None = None
        self._recovery_records: list[Any] = []
        self._selected_recovery_record: Any | None = None
        self._accessories: list[Any] = []
        self._email: str | None = None
        self._current_accessory_rows: list[dict[str, Any]] = []

    async def _async_close(self) -> None:
        """Close temporary Apple/iCloud objects used by the options flow."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                _LOGGER.debug("Error closing temporary iCloud client", exc_info=True)
            self._client = None
        if self._account is not None:
            try:
                await self._account.close()
            except Exception:
                _LOGGER.debug("Error closing temporary Apple account", exc_info=True)
            self._account = None

    async def _open_keychain(self) -> config_entries.ConfigFlowResult:
        """Open iCloud Keychain after a fresh Apple authentication."""
        assert self._account is not None
        try:
            self._client = await AsyncFindMyClient.open(self._account)
            options = await self._client.recovery_options()
            self._recovery_records = list(options.recoverable)
        except Exception:
            _LOGGER.exception("Unable to open iCloud Keychain after reauthentication")
            await self._async_close()
            return self.async_abort(reason="cannot_open_keychain")

        if not self._recovery_records:
            await self._async_close()
            return self.async_abort(reason="no_recovery_devices")

        return await self.async_step_recovery_device()

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Start accessory management with an explicit fresh Apple authentication."""
        self._current_accessory_rows = [
            dict(item) for item in self.config_entry.data.get(CONF_ACCESSORIES, [])
        ]

        account_data = self.config_entry.data.get(CONF_ACCOUNT, {})
        account_section = account_data.get("account") if isinstance(account_data, dict) else None
        if not isinstance(account_section, dict):
            return self.async_abort(reason="cannot_open_keychain")

        self._email = account_section.get("username")
        if not self._email:
            return self.async_abort(reason="cannot_open_keychain")

        return await self.async_step_reauth()

    async def async_step_reauth(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Reauthenticate the saved Apple ID without persisting its password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                state_data = deepcopy(self.config_entry.data[CONF_ACCOUNT])
                account_section = state_data.get("account")
                if not isinstance(account_section, dict):
                    raise ValueError("Saved account state has no account section")

                # Reuse the saved Anisette/device identity, but start a fresh login.
                account_section["password"] = password
                state_data["login"] = {
                    "state": LoginState.LOGGED_OUT.value,
                    "data": {},
                }

                self._account = await self.hass.async_add_executor_job(
                    AsyncAppleAccount.from_json,
                    state_data,
                )
                assert self._email is not None
                state = await self._account.login(self._email, password)
            except InvalidCredentialsError:
                errors["base"] = "invalid_auth"
                await self._async_close()
            except Exception:
                _LOGGER.exception("Apple reauthentication failed")
                errors["base"] = "cannot_connect"
                await self._async_close()
            else:
                if state == LoginState.REQUIRE_2FA:
                    return await self.async_step_two_factor_method()
                if state == LoginState.LOGGED_IN:
                    return await self._open_keychain()
                errors["base"] = "unexpected_state"
                await self._async_close()
            finally:
                password = None

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self._email or ""},
        )

    async def async_step_two_factor_method(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Choose where Apple should send the reauthentication code."""
        assert self._account is not None

        if not self._two_factor_methods:
            try:
                self._two_factor_methods = list(await self._account.get_2fa_methods())
            except Exception:
                _LOGGER.exception("Unable to enumerate Apple 2FA methods")
                await self._async_close()
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

    async def async_step_two_factor_code(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Submit Apple's reauthentication verification code."""
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

    async def async_step_recovery_device(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Choose a trusted device for the keychain recovery operation."""
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

    async def async_step_device_passcode(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Unlock the keychain and rediscover Find My accessories."""
        assert self._client is not None
        assert self._selected_recovery_record is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            passcode = user_input["passcode"]

            try:
                await self._client.unlock(self._selected_recovery_record, passcode)
            except RecoveryError as err:
                _LOGGER.warning(
                    "Find My escrow recovery failed for %s: %s",
                    self._selected_recovery_record.describe(),
                    err,
                )
                errors["base"] = "recovery_failed"
            except KeychainSessionError as err:
                _LOGGER.warning(
                    "Find My keychain recovery failed for %s: %s",
                    self._selected_recovery_record.describe(),
                    err,
                )
                errors["base"] = "keychain_recovery_failed"
            except Exception:
                _LOGGER.exception("Unexpected error while unlocking Find My keychain")
                errors["base"] = "cannot_recover"
            finally:
                passcode = None

            if not errors:
                try:
                    discovered = list(await self._client.accessories())
                except KeychainSessionError as err:
                    _LOGGER.warning(
                        "Find My accessory decryption/discovery failed after recovery: %s",
                        err,
                    )
                    errors["base"] = "accessory_discovery_failed"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error while reading Find My accessories after recovery"
                    )
                    errors["base"] = "accessory_discovery_failed"

            if not errors:
                by_identifier: dict[str, Any] = {}
                for accessory in discovered:
                    identifier = getattr(accessory, "identifier", None)
                    if identifier:
                        by_identifier[identifier] = accessory

                # Existing accessory rows are only a safety net for a transiently
                # incomplete iCloud discovery. A stale/old row must never turn a
                # successful keychain recovery into a generic recovery failure.
                for row in self._current_accessory_rows:
                    try:
                        accessory = await self.hass.async_add_executor_job(
                            FindMyAccessory.from_json,
                            row,
                        )
                    except Exception:
                        _LOGGER.warning(
                            "Skipping an unreadable previously stored Find My accessory",
                            exc_info=True,
                        )
                        continue

                    identifier = getattr(accessory, "identifier", None)
                    if identifier and identifier not in by_identifier:
                        discovered.append(accessory)
                        by_identifier[identifier] = accessory

                self._accessories = discovered

            if not errors:
                if not self._accessories:
                    await self._async_close()
                    return self.async_abort(reason="no_accessories")
                if self._client is not None:
                    await self._client.close()
                    self._client = None
                return await self.async_step_accessories()

        return self.async_show_form(
            step_id="device_passcode",
            data_schema=vol.Schema({vol.Required("passcode"): str}),
            errors=errors,
        )

    async def async_step_accessories(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Select the accessories that should remain configured."""
        choices: dict[str, str] = {}
        by_key: dict[str, Any] = {}
        current_ids = {
            row.get("identifier")
            for row in self._current_accessory_rows
            if row.get("identifier")
        }
        default_selected: list[str] = []

        for index, accessory in enumerate(self._accessories):
            key = str(index)
            name = accessory.name or "Unnamed Find My accessory"
            serial = getattr(accessory, "serial_number", None)
            model = getattr(accessory, "model", None)
            details = serial or model
            choices[key] = f"{name} ({details})" if details else name
            by_key[key] = accessory
            if getattr(accessory, "identifier", None) in current_ids:
                default_selected.append(key)

        if user_input is not None:
            selected_keys = list(user_input.get("accessories", []))
            selected_accessories = [by_key[key] for key in selected_keys]
            accessory_data = [accessory.to_json() for accessory in selected_accessories]

            new_ids = {
                getattr(accessory, "identifier", None)
                for accessory in selected_accessories
                if getattr(accessory, "identifier", None)
            }
            removed_ids = current_ids - new_ids

            account_data = (
                dict(self._account.to_json())
                if self._account is not None
                else dict(self.config_entry.data[CONF_ACCOUNT])
            )
            account_section = account_data.get("account")
            if isinstance(account_section, dict):
                account_section["password"] = None

            await self._async_close()

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_ACCOUNT: account_data,
                    CONF_ACCESSORIES: accessory_data,
                },
            )

            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            self._remove_accessory_registry_entries(removed_ids)

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="accessories",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "accessories",
                        default=default_selected,
                    ): cv.multi_select(choices)
                }
            ),
        )

    @callback
    def _remove_accessory_registry_entries(self, removed_ids: set[str]) -> None:
        """Remove Home Assistant registry entries for explicitly deselected accessories."""
        if not removed_ids:
            return

        entity_registry = er.async_get(self.hass)
        for entity in list(er.async_entries_for_config_entry(
            entity_registry,
            self.config_entry.entry_id,
        )):
            unique_id = entity.unique_id
            if any(
                unique_id == identifier
                or unique_id.startswith(f"{identifier}_")
                for identifier in removed_ids
            ):
                entity_registry.async_remove(entity.entity_id)

        device_registry = dr.async_get(self.hass)
        for identifier in removed_ids:
            device = device_registry.async_get_device_by_identifier(
                (DOMAIN, identifier),
                self.config_entry.entry_id,
            )
            if device is not None:
                device_registry.async_remove_device(device.id)
