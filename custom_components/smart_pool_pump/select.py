"""Select entities for Smart Pool."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DATA_SCHEDULER, DEFAULT_SEASON_MODE, DOMAIN, MODE_WINTER, SEASON_OPTIONS
from .coordinator import SmartPoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartPoolCoordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    async_add_entities([SeasonModeSelect(coordinator, entry.entry_id)])


class SeasonModeSelect(CoordinatorEntity[SmartPoolCoordinator], SelectEntity):
    """Manual season selector for winter/summer logic."""

    _attr_name = "Season Mode"
    _attr_unique_id = "smart_pool_season_mode"
    _attr_options = SEASON_OPTIONS
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self.coordinator.season_mode = DEFAULT_SEASON_MODE
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    @property
    def current_option(self):
        return self.coordinator.season_mode

    async def async_select_option(self, option: str) -> None:
        self.coordinator.season_mode = option
        if self.hass and option == MODE_WINTER:
            scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
            if scheduler:
                await scheduler.async_run_now(force_schedule=True)
        self.async_write_ha_state()
