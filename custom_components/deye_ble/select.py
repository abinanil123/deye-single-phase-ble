"""Select entities for Deye BLE integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LOGGER_SN, DEVICE_NAME, DOMAIN
from .registers import REG_WORK_MODE, WORK_MODE_LABELS, encode_work_mode

MODE_KEEPALIVE_CLOUD = "Keepalive - with Deye Cloud"
MODE_KEEPALIVE_LOCAL = "Keepalive - no Deye Cloud"
MODE_NO_KEEPALIVE = "No Keepalive"
MODE_DISABLED = "Disabled (Firmware / Cloud Only)"

CONNECTION_MODES = [
    MODE_KEEPALIVE_CLOUD,
    MODE_KEEPALIVE_LOCAL,
    MODE_NO_KEEPALIVE,
    MODE_DISABLED,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [DeyeConnectionModeSelect(coordinator, entry)]
    async_add_entities(entities)


def _device_info(sn: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, sn)},
        name=DEVICE_NAME,
        manufacturer="Deye",
        model=sn,
    )


class DeyeConnectionModeSelect(CoordinatorEntity, SelectEntity):
    """Dropdown entity to control BLE polling mode, keepalive, and cloud coexistence."""

    _attr_has_entity_name = True
    _attr_name = "Connection Mode"
    _attr_icon = "mdi:transit-connection-variant"
    _attr_options = CONNECTION_MODES

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        sn = entry.data[CONF_LOGGER_SN]
        self._attr_unique_id = f"{sn}_connection_mode"
        self._attr_device_info = _device_info(sn)

    @property
    def current_option(self) -> str:
        if not self.coordinator.ble_enabled:
            return MODE_DISABLED
        if not self.coordinator.keepalive:
            return MODE_NO_KEEPALIVE
        if self.coordinator.fully_local:
            return MODE_KEEPALIVE_LOCAL
        return MODE_KEEPALIVE_CLOUD

    async def async_select_option(self, option: str) -> None:
        if option == MODE_DISABLED:
            await self.coordinator.async_set_ble_enabled(False)
        elif option == MODE_NO_KEEPALIVE:
            await self.coordinator.async_set_ble_enabled(True)
            self.coordinator.set_fully_local(False)
            await self.coordinator.async_set_keepalive(False)
        elif option == MODE_KEEPALIVE_LOCAL:
            await self.coordinator.async_set_ble_enabled(True)
            self.coordinator.set_fully_local(True)
            await self.coordinator.async_set_keepalive(True)
        elif option == MODE_KEEPALIVE_CLOUD:
            await self.coordinator.async_set_ble_enabled(True)
            self.coordinator.set_fully_local(False)
            await self.coordinator.async_set_keepalive(True)

        self.async_write_ha_state()


class DeyeWorkModeSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Work Mode"
    _attr_icon = "mdi:solar-power-variant"
    _attr_options = list(WORK_MODE_LABELS.values())

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        sn = entry.data[CONF_LOGGER_SN]
        self._attr_unique_id = f"{sn}_work_mode"
        self._attr_device_info = _device_info(sn)

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get("work_mode")

    async def async_select_option(self, option: str) -> None:
        reg_val = encode_work_mode(option)
        await self.coordinator.async_write(REG_WORK_MODE, reg_val)
        self.coordinator.async_set_updated_data(
            {**(self.coordinator.data or {}), "work_mode": option},
        )
        self.coordinator.mark_config_dirty()
