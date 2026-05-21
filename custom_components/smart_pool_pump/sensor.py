"""Sensors for Smart Pool."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_BACKWASH_INTERVAL_SUMMER_DAYS,
    CONF_BACKWASH_INTERVAL_WINTER_DAYS,
    DATA_COORDINATOR,
    DEFAULT_BACKWASH_INTERVAL_SUMMER_DAYS,
    DEFAULT_BACKWASH_INTERVAL_WINTER_DAYS,
    DOMAIN,
    MODE_SUMMER,
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
            OutdoorTempSensor(coordinator, entry.entry_id),
            PoolTempSensor(coordinator, entry.entry_id),
            WinterStateSensor(coordinator, entry.entry_id),
            TargetRuntimeSensor(coordinator, entry.entry_id),
            ActualRuntimeSensor(coordinator, entry.entry_id),
            PlannedSlotsSensor(coordinator, entry.entry_id),
            ControllerUpdateSensor(coordinator, entry.entry_id),
            ActionLogSensor(coordinator, entry.entry_id),
            ActualVolumeSensor(coordinator, entry.entry_id),
            TargetVolumeSensor(coordinator, entry.entry_id),
            SummerPumpStateSensor(coordinator, entry.entry_id),
            DailySummarySensor(coordinator, entry.entry_id),
            BackwashReminderSensor(coordinator, entry.entry_id),
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
        # Target runtime is not a concept in summer mode — the pump stops on volume.
        if self.coordinator.season_mode == MODE_SUMMER:
            return None
        return int(self.coordinator.target_runtime_minutes)


class ActualRuntimeSensor(SmartPoolSensorBase):
    _attr_name = "Actual Runtime"
    _attr_unique_id = "smart_pool_actual_runtime"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

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


class ActualVolumeSensor(SmartPoolSensorBase):
    _attr_name = "Actual Volume"
    _attr_unique_id = "smart_pool_actual_volume"
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return round(self.coordinator.actual_volume_m3, 2)


class TargetVolumeSensor(SmartPoolSensorBase):
    _attr_name = "Target Volume"
    _attr_unique_id = "smart_pool_target_volume"
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-check"

    @property
    def native_value(self):
        return round(self.coordinator.target_volume_m3, 2)


class SummerPumpStateSensor(SmartPoolSensorBase):
    _attr_name = "Summer Pump State"
    _attr_unique_id = "smart_pool_summer_pump_state"
    _attr_icon = "mdi:pump"

    @property
    def native_value(self):
        return self.coordinator.summer_pump_state

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "flow_rate_m3h": self.coordinator.current_flow_rate_m3h,
            "volume_target_achieved": self.coordinator.volume_target_achieved,
            "max_runtime_exceeded": self.coordinator.max_runtime_exceeded,
            "backwash_active": self.coordinator.backwash_active,
            "device_mode": data.get("device_pump_mode", "unknown"),
            "device_switch": data.get("device_pump_switch", "unknown"),
        }


class DailySummarySensor(SmartPoolSensorBase):
    """Aggregated daily summary: total pump hours and hours per mode."""

    _attr_name = "Daily Summary"
    _attr_unique_id = "smart_pool_daily_summary"
    _attr_icon = "mdi:calendar-today"
    _attr_native_unit_of_measurement = "h"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Total pump running hours today."""
        return round(self.coordinator.actual_runtime_minutes / 60.0, 2)

    @property
    def extra_state_attributes(self) -> dict:
        smr = self.coordinator.summer_mode_runtimes
        wsr = self.coordinator.winter_state_runtimes
        return {
            "heat_hours": round(smr.get("heat", 0.0) / 60.0, 2),
            "filtration_hours": round(smr.get("filtration", 0.0) / 60.0, 2),
            "winter_normal_hours": round(wsr.get("normal", 0.0) / 60.0, 2),
            "winter_freeze_hours": round(wsr.get("freeze", 0.0) / 60.0, 2),
            "winter_extreme_hours": round(wsr.get("extreme", 0.0) / 60.0, 2),
            "volume_m3": round(self.coordinator.actual_volume_m3, 2),
            "target_volume_m3": round(self.coordinator.target_volume_m3, 2),
            "volume_target_achieved": self.coordinator.volume_target_achieved,
            "max_runtime_exceeded": self.coordinator.max_runtime_exceeded,
            "backwash_active": self.coordinator.backwash_active,
            "season_mode": self.coordinator.season_mode,
            "summer_pump_state": self.coordinator.summer_pump_state,
            "winter_state": self.coordinator.winter_state,
        }


class BackwashReminderSensor(SmartPoolSensorBase):
    """Sensor that shows whether a backwash is due, and when the last one was done."""

    _attr_name = "Backwash Reminder"
    _attr_unique_id = "smart_pool_backwash_reminder"
    _attr_icon = "mdi:filter-check"

    @property
    def native_value(self) -> str:
        return "due" if self.coordinator.backwash_due else "ok"

    @property
    def extra_state_attributes(self):
        from datetime import date as _date
        from homeassistant.util import dt as dt_util

        is_summer = self.coordinator.season_mode == MODE_SUMMER
        interval_days = int(
            self.coordinator.config.get(
                CONF_BACKWASH_INTERVAL_SUMMER_DAYS if is_summer else CONF_BACKWASH_INTERVAL_WINTER_DAYS,
                DEFAULT_BACKWASH_INTERVAL_SUMMER_DAYS if is_summer else DEFAULT_BACKWASH_INTERVAL_WINTER_DAYS,
            )
        )
        last = self.coordinator.last_backwash_date
        days_since: int | None = None
        days_remaining: int | None = None
        if last:
            try:
                days_since = (dt_util.now().date() - _date.fromisoformat(last)).days
                days_remaining = interval_days - days_since
            except (ValueError, TypeError):
                pass
        return {
            "last_backwash_date": last,
            "backwash_active": self.coordinator.backwash_active,
            "days_since_backwash": days_since,
            "days_remaining": days_remaining,
            "interval_days": interval_days,
        }
