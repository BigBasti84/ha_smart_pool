"""Sensors for Smart Pool."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SmartPoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartPoolCoordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    async_add_entities(
        [
            OutdoorTempSensor(coordinator, entry.entry_id),
            PoolTempSensor(coordinator, entry.entry_id),
            WinterStateSensor(coordinator, entry.entry_id),
            TargetRuntimeSensor(coordinator, entry.entry_id),
            ActualRuntimeSensor(coordinator, entry.entry_id),
            PlannedSlotsSensor(coordinator, entry.entry_id),
            ControllerUpdateSensor(coordinator, entry.entry_id),
            ActionLogSensor(coordinator, entry.entry_id),
        ]
    )


class SmartPoolSensorBase(CoordinatorEntity[SmartPoolCoordinator], SensorEntity):
    """Base sensor class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartPoolCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Smart Pool",
            "manufacturer": "Smart Pool",
            "model": "Pool Pump Controller",
        }


class OutdoorTempSensor(SmartPoolSensorBase):
    _attr_name = "Outdoor Temperature"
    _attr_unique_id = "smart_pool_outdoor_temp"
    _attr_native_unit_of_measurement = "degC"

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("outdoor_temp")
        if value is None:
            return None
        return round(float(value), 1)


class PoolTempSensor(SmartPoolSensorBase):
    _attr_name = "Pool Temperature"
    _attr_unique_id = "smart_pool_pool_temp"
    _attr_native_unit_of_measurement = "degC"

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("pool_temp")
        if value is None:
            return None
        return round(float(value), 1)


class WinterStateSensor(SmartPoolSensorBase):
    _attr_name = "Winter State"
    _attr_unique_id = "smart_pool_winter_state"

    @property
    def native_value(self):
        return self.coordinator.winter_state


class TargetRuntimeSensor(SmartPoolSensorBase):
    _attr_name = "Target Runtime"
    _attr_unique_id = "smart_pool_target_runtime"
    _attr_native_unit_of_measurement = "min"

    @property
    def native_value(self):
        return int(self.coordinator.target_runtime_minutes)


class ActualRuntimeSensor(SmartPoolSensorBase):
    _attr_name = "Actual Runtime"
    _attr_unique_id = "smart_pool_actual_runtime"
    _attr_native_unit_of_measurement = "min"

    @property
    def native_value(self):
        return round(self.coordinator.actual_runtime_minutes, 1)


class PlannedSlotsSensor(SmartPoolSensorBase):
    _attr_name = "Planned Slots"
    _attr_unique_id = "smart_pool_planned_slots"

    @property
    def native_value(self):
        plan = self.coordinator.last_plan
        if not plan:
            return "none"
        return " | ".join(f"{a}-{b}" for a, b in plan)


class ControllerUpdateSensor(SmartPoolSensorBase):
    _attr_name = "Controller Update"
    _attr_unique_id = "smart_pool_controller_update"
    _attr_icon = "mdi:update"

    @property
    def native_value(self) -> str:
        if self.coordinator.controller_update_running:
            return "running"
        result = self.coordinator.controller_update_last_result
        if result in ("success", "failed"):
            return result
        return "never"

    @property
    def extra_state_attributes(self):
        return {
            "last_at": self.coordinator.controller_update_last_at,
            "last_result": self.coordinator.controller_update_last_result,
            "context": self.coordinator.controller_update_last_context,
        }


class ActionLogSensor(SmartPoolSensorBase):
    _attr_name = "Action Log"
    _attr_unique_id = "smart_pool_action_log"
    _attr_icon = "mdi:history"

    @property
    def native_value(self):
        entries = self.coordinator.action_log_as_dicts()
        return entries[0]["at"] if entries else "empty"

    @property
    def extra_state_attributes(self):
        return {"entries": self.coordinator.action_log_as_dicts()}
