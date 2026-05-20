"""Select entities for Smart Pool."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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


class SeasonModeSelect(CoordinatorEntity[SmartPoolCoordinator], SelectEntity, RestoreEntity):
    """Manual season selector for winter/summer logic."""

    _attr_name = "Season Mode"
    _attr_unique_id = "smart_pool_season_mode"
    _attr_options = SEASON_OPTIONS
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        if not self.coordinator.season_mode:
            self.coordinator.season_mode = DEFAULT_SEASON_MODE
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in SEASON_OPTIONS:
            self.coordinator.season_mode = last_state.state
        elif self.coordinator.season_mode not in SEASON_OPTIONS:
            self.coordinator.season_mode = DEFAULT_SEASON_MODE

        self.async_write_ha_state()

        self._async_schedule_refresh()

    def _async_schedule_refresh(self) -> None:
        if not self.hass:
            return
        scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
        if scheduler:
            self.hass.async_create_task(scheduler.async_run_now(force_schedule=True))

    @property
    def current_option(self):
        if self.coordinator.season_mode not in SEASON_OPTIONS:
            return DEFAULT_SEASON_MODE
        return self.coordinator.season_mode

    async def async_select_option(self, option: str) -> None:
        if option not in SEASON_OPTIONS:
            return
        self.coordinator.season_mode = option
        if self.hass and option in (MODE_WINTER, MODE_SUMMER):
            scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
            if scheduler:
                self.hass.async_create_task(scheduler.async_run_now(force_schedule=True))
        self.async_write_ha_state()


class SummerHeatingSelect(CoordinatorEntity[SmartPoolCoordinator], SelectEntity, RestoreEntity):
    """Toggle for enabling/disabling summer heat-mode behavior."""

    _attr_name = "Summer Heating"
    _attr_unique_id = "smart_pool_summer_heating"
    _attr_options = SUMMER_HEATING_OPTIONS
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        if not self.coordinator.summer_heating_mode:
            self.coordinator.summer_heating_mode = SUMMER_HEATING_ON
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in SUMMER_HEATING_OPTIONS:
            self.coordinator.summer_heating_mode = last_state.state
        elif self.coordinator.summer_heating_mode not in SUMMER_HEATING_OPTIONS:
            self.coordinator.summer_heating_mode = SUMMER_HEATING_ON

        self.async_write_ha_state()

        if self.coordinator.season_mode == MODE_SUMMER:
            self._async_schedule_refresh()

    def _async_schedule_refresh(self) -> None:
        if not self.hass:
            return
        scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
        if scheduler:
            self.hass.async_create_task(scheduler.async_run_now(force_schedule=True))

    @property
    def current_option(self):
        if self.coordinator.summer_heating_mode not in SUMMER_HEATING_OPTIONS:
            return SUMMER_HEATING_ON
        return self.coordinator.summer_heating_mode

    async def async_select_option(self, option: str) -> None:
        if option not in SUMMER_HEATING_OPTIONS:
            return
        self.coordinator.summer_heating_mode = option
        if self.hass and self.coordinator.season_mode == MODE_SUMMER:
            scheduler = self.hass.data.get(DOMAIN, {}).get(DATA_SCHEDULER)
            if scheduler:
                self.hass.async_create_task(scheduler.async_run_now(force_schedule=True))
        self.async_write_ha_state()
