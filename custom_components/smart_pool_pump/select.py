"""Select entities for Smart Pool."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_COORDINATOR,
    DATA_SCHEDULER,
    DEFAULT_SEASON_MODE,
    DOMAIN,
    MODE_SUMMER,
    MODE_WINTER,
    SEASON_OPTIONS,
    SUMMER_HEATING_ON,
    SUMMER_HEATING_OPTIONS,
)
from .coordinator import SmartPoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartPoolCoordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    async_add_entities(
        [
            SeasonModeSelect(coordinator, entry.entry_id),
            SummerHeatingSelect(coordinator, entry.entry_id),
        ]
    )


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
        if self.hass and option in (MODE_WINTER, MODE_SUMMER):
            scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
            if scheduler:
                await scheduler.async_run_now(force_schedule=True)
        self.async_write_ha_state()


class SummerHeatingSelect(CoordinatorEntity[SmartPoolCoordinator], SelectEntity):
    """Toggle for enabling/disabling summer heat-mode behavior."""

    _attr_name = "Summer Heating"
    _attr_unique_id = "smart_pool_summer_heating"
    _attr_options = SUMMER_HEATING_OPTIONS
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self.coordinator.summer_heating_mode = SUMMER_HEATING_ON
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    @property
    def current_option(self):
        return self.coordinator.summer_heating_mode

    async def async_select_option(self, option: str) -> None:
        self.coordinator.summer_heating_mode = option
        if self.hass and self.coordinator.season_mode == MODE_SUMMER:
            scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
            if scheduler:
                await scheduler.async_run_now(force_schedule=True)
        self.async_write_ha_state()
