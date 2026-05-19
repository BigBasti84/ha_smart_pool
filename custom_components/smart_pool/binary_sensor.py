"""Binary sensors for Smart Pool."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TEST_MODE, DATA_COORDINATOR, DOMAIN
from .coordinator import SmartPoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartPoolCoordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    async_add_entities([TestModeBinarySensor(coordinator, entry.entry_id, entry.data.get(CONF_TEST_MODE, True))])


class TestModeBinarySensor(CoordinatorEntity[SmartPoolCoordinator], BinarySensorEntity):
    """Shows whether integration runs in TEST MODE."""

    _attr_name = "Test Mode"
    _attr_unique_id = "smart_pool_test_mode"
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str, value: bool) -> None:
        super().__init__(coordinator)
        self._value = bool(value)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }

    @property
    def is_on(self):
        return self._value
