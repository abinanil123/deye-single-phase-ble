"""Config flow for Deye BLE integration.

BLE discovery via service UUID 00000922-..., plus a manual confirmation
step where the user enters the logger serial number.  unique_id = logger SN.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfo,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_ADDRESS,
    CONF_DRY_RUN,
    CONF_KEEPALIVE,
    CONF_LOGGER_SN,
    CONF_REASSERT,
    CONF_SCAN_INTERVAL,
    DEFAULT_DRY_RUN,
    DEFAULT_KEEPALIVE,
    DEFAULT_REASSERT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .helpers import validate_logger_sn

_LOGGER = logging.getLogger(__name__)

# Bluetooth service UUID for Deye loggers.
# The BLE device name is typically the logger serial number.
SERVICE_UUID = "00000922-0000-1000-8000-00805f9b34fb"


# The logger serial is the advertised BLE name on Deye sticks, and starts with
# a 2-digit year ("26…"). Matching it keeps a stick usable when its advertising
# packet leaves the 128-bit service UUID out.
def _deye_devices(hass):
    """Discovered BLE devices advertising the Deye logger service UUID or matching name/MAC."""
    matched = []
    for info in async_discovered_service_info(hass):
        if SERVICE_UUID in info.service_uuids:
            matched.append(info)
        elif info.name and (
            info.name.startswith("26")
            or "deye" in info.name.lower()
            or "inv" in info.name.lower()
        ):
            matched.append(info)
        # placeholder or manual discovery
            matched.append(info)
    return matched


class DeyeBleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deye BLE."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return DeyeBleOptionsFlowHandler()

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        _LOGGER.debug("BLE discovery: %s", discovery_info.name)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovered_address = discovery_info.address
        self._discovered_name = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}

        return await self._finish_or_confirm()

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle manual user step — pick a discovered device or enter details."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            sn = user_input.get(CONF_LOGGER_SN, "").strip()

            if not sn:
                # Picked from the discovered list: the advertised name carries
                # the serial on a normal stick, so let _finish_or_confirm decide
                # whether the serial still has to be typed in.
                for info in _deye_devices(self.hass):
                    if info.address.upper() == address:
                        self._discovered_name = info.name
                        break
                self._discovered_address = address
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return await self._finish_or_confirm()

            try:
                valid_sn = validate_logger_sn(sn)
            except ValueError as err:
                errors[CONF_LOGGER_SN] = str(err)
            else:
                # The BLE MAC is the stable per-device identity for the config
                # entry (HA Bluetooth convention). The logger SN is captured
                # separately and drives the entity unique_ids.
                self._discovered_address = address
                self._discovered_name = valid_sn
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self._create_entry(valid_sn)

        discovered = _deye_devices(self.hass)
        if discovered:
            addresses = sorted({d.address for d in discovered})
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        a: f"{format_mac(a)} "
                        f"({next((d.name for d in discovered if d.address == a), 'Inverter')})"
                        for a in addresses
                    }
                ),
            })
        else:
            # No advertisement seen (or none HA has discovered yet): fall back
            # to entering the known logger details by hand instead of aborting.
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS, default=""): str,
                vol.Required(CONF_LOGGER_SN, default=""): str,
            })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    def _create_entry(self, sn: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._discovered_name or sn,
            data={
                CONF_ADDRESS: self._discovered_address,
                CONF_LOGGER_SN: sn,
            },
        )

    async def _finish_or_confirm(self) -> ConfigFlowResult:
        """Skip the SN step when the advertised name is already a valid serial.

        Deye loggers advertise their serial as the BLE name, so in the normal
        case the user has nothing to type. Fall back to the confirm form only
        when the advert name isn't a usable SN.
        """
        try:
            sn = validate_logger_sn(self._discovered_name or "")
        except ValueError:
            return await self.async_step_confirm()
        return self._create_entry(sn)

    async def async_step_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Confirm / enter logger serial number."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                sn = validate_logger_sn(user_input[CONF_LOGGER_SN])
            except ValueError as exc:
                errors[CONF_LOGGER_SN] = str(exc)
            else:
                return self._create_entry(sn)

        schema = vol.Schema({
            vol.Required(
                CONF_LOGGER_SN,
                default=self._discovered_name or "",
            ): str,
        })
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "name": self._discovered_name or "Unknown",
            },
        )


class DeyeBleOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for scan interval, dry-run, reassert and keepalive."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options
        schema = vol.Schema({
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
            vol.Required(
                CONF_DRY_RUN,
                default=current.get(CONF_DRY_RUN, DEFAULT_DRY_RUN),
            ): bool,
            vol.Required(
                CONF_REASSERT,
                default=current.get(CONF_REASSERT, DEFAULT_REASSERT),
            ): bool,
            vol.Required(
                CONF_KEEPALIVE,
                default=current.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE),
            ): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)

