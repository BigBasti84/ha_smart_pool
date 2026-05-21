"""Button entities for Smart Pool."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DATA_SCHEDULER, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Pool button entities."""
    coordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    scheduler = hass.data[DOMAIN][DATA_SCHEDULER]
    async_add_entities([ForceCheckButton(coordinator, scheduler, entry.entry_id)])


class ForceCheckButton(ButtonEntity):
    """Button that triggers an immediate pump schedule evaluation."""

    _attr_has_entity_name = True
    _attr_name = "Force Check"
    _attr_unique_id = "smart_pool_force_check"
    _attr_icon = "mdi:refresh-circle"

    def __init__(self, coordinator, scheduler, entry_id: str) -> None:
        self._scheduler = scheduler
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    async def async_press(self) -> None:
        """Trigger an immediate evaluation."""
        await self._scheduler.async_run_now(allow_writes=True)
