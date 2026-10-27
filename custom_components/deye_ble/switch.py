"""Switch entities for Deye BLE integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LOGGER_SN, DEVICE_NAME, DOMAIN
from .registers import (
    GEN_PEAK_SHAVE_MASK,
    GRID_PEAK_SHAVE_MASK,
    REG_PEAK_SHAVING_FLAGS,
    set_flag,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    # All coexistence and local modes are now cleanly unified in select.connection_mode.
    # No redundant switches are added.
    async_add_entities([])


def _device_info(sn: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, sn)},
        name=DEVICE_NAME,
        manufacturer="Deye",
        model=sn,
    )


class _PeakShaveSwitch(CoordinatorEntity, SwitchEntity):
    """One enable bit of the packed 0x00B2 peak-shaving flag register."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _mask: int
    _data_key: str

    def __init__(self, coordinator, entry: ConfigEntry, sn: str):
        super().__init__(coordinator)
        self._attr_unique_id = f"{sn}_{self._data_key}"
        self._attr_device_info = _device_info(sn)

    @property
    def is_on(self) -> bool | None:
        val = (self.coordinator.data or {}).get(self._data_key)
        return bool(val) if val is not None else None

    async def _async_set(self, on: bool) -> None:
        raw = (self.coordinator.data or {}).get("peak_shaving_flags_raw")
        if raw is None:
            raise HomeAssistantError(
                "peak-shaving flag register (0x00B2) not read yet; cannot toggle safely"
            )
        new_raw = set_flag(int(raw), self._mask, on)
        await self.coordinator.async_write(REG_PEAK_SHAVING_FLAGS, new_raw)
        self.coordinator.async_set_updated_data({
            **(self.coordinator.data or {}),
            "peak_shaving_flags_raw": new_raw,
            "grid_peak_shaving": bool(new_raw & GRID_PEAK_SHAVE_MASK),
            "gen_peak_shaving": bool(new_raw & GEN_PEAK_SHAVE_MASK),
        })
        self.coordinator.mark_config_dirty()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)


class DeyeGridPeakShaving(_PeakShaveSwitch):
    _mask = GRID_PEAK_SHAVE_MASK
    _data_key = "grid_peak_shaving"
    _attr_name = "Grid Peak Shaving"
    _attr_icon = "mdi:transmission-tower"


class DeyeGenPeakShaving(_PeakShaveSwitch):
    _mask = GEN_PEAK_SHAVE_MASK
    _data_key = "gen_peak_shaving"
    _attr_name = "Gen Peak Shaving"
    _attr_icon = "mdi:engine"
