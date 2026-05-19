"""Scheduler logic for Smart Pool."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_EXTREME_FREEZE_TEMP_C,
    CONF_FREEZE_TEMP_C,
    CONF_PUMP_MODE_AUTO_VALUE,
    CONF_PUMP_MODE_SELECT,
    CONF_PUMP_SPEED_LOW_VALUE,
    CONF_PUMP_SPEED_MEDIUM_VALUE,
    CONF_PUMP_SPEED_SELECT,
    CONF_PUMP_SWITCH,
    CONF_SLOT1_END,
    CONF_SLOT1_START,
    CONF_SLOT2_END,
    CONF_SLOT2_START,
    CONF_SLOT3_END,
    CONF_SLOT3_START,
    CONF_TEST_MODE,
    CONF_UPDATE_INTERVAL_MIN,
    CONF_WINTER_MIN_RUNTIME_MIN,
    MODE_WINTER,
    WINTER_STATE_EXTREME,
    WINTER_STATE_FREEZE,
    WINTER_STATE_NORMAL,
)
from .coordinator import SmartPoolCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartPoolScheduler:
    """Applies winter logic with minimal hardware writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartPoolCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = entry.data
        self._cancel_tick = async_track_time_interval(
            hass,
            self._async_tick,
            timedelta(minutes=int(self.config.get(CONF_UPDATE_INTERVAL_MIN, 5))),
        )

    async def async_shutdown(self) -> None:
        if self._cancel_tick:
            self._cancel_tick()
            self._cancel_tick = None

    async def _async_tick(self, now: datetime) -> None:
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}

        if self.coordinator.season_mode != MODE_WINTER:
            return

        outdoor_temp = float(data.get("outdoor_temp", 0.0))
        freeze = float(self.config[CONF_FREEZE_TEMP_C])
        extreme = float(self.config[CONF_EXTREME_FREEZE_TEMP_C])

        if outdoor_temp <= extreme:
            self.coordinator.winter_state = WINTER_STATE_EXTREME
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_MEDIUM_VALUE])
            return

        if outdoor_temp <= freeze:
            self.coordinator.winter_state = WINTER_STATE_FREEZE
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_LOW_VALUE])
            return

        self.coordinator.winter_state = WINTER_STATE_NORMAL
        await self._apply_min_runtime_slots(now)

    async def _apply_continuous(self, speed: str) -> None:
        await self._set_select(self.config[CONF_PUMP_MODE_SELECT], self.config[CONF_PUMP_MODE_AUTO_VALUE], "pump_mode")
        await self._set_select(self.config[CONF_PUMP_SPEED_SELECT], speed, "pump_speed")
        await self._set_switch(self.config[CONF_PUMP_SWITCH], True, "pump_switch")

    async def _apply_min_runtime_slots(self, now: datetime) -> None:
        target = int(self.config[CONF_WINTER_MIN_RUNTIME_MIN])
        self.coordinator.target_runtime_minutes = target

        # Change schedule only once per day to protect pool hardware.
        day = now.date().isoformat()
        if self.coordinator.last_schedule_day == day:
            return

        plan = self._build_three_slots(target)
        await self._write_slot_plan(plan)
        self.coordinator.last_schedule_day = day
        self.coordinator.last_plan = plan

        await self._set_select(self.config[CONF_PUMP_MODE_SELECT], self.config[CONF_PUMP_MODE_AUTO_VALUE], "pump_mode")
        await self._set_switch(self.config[CONF_PUMP_SWITCH], False, "pump_switch")

    def _build_three_slots(self, target_minutes: int) -> list[tuple[str, str]]:
        total = max(0, min(1440, target_minutes))
        each = max(1, total // 3)

        starts = [
            datetime.strptime("08:00", "%H:%M"),
            datetime.strptime("13:00", "%H:%M"),
            datetime.strptime("18:00", "%H:%M"),
        ]

        plan: list[tuple[str, str]] = []
        for st in starts:
            en = st + timedelta(minutes=each)
            if en.day != st.day:
                en = datetime.strptime("23:59", "%H:%M")
            plan.append((st.strftime("%H:%M:%S"), en.strftime("%H:%M:%S")))
        return plan

    async def _write_slot_plan(self, plan: list[tuple[str, str]]) -> None:
        keys = [
            CONF_SLOT1_START,
            CONF_SLOT1_END,
            CONF_SLOT2_START,
            CONF_SLOT2_END,
            CONF_SLOT3_START,
            CONF_SLOT3_END,
        ]
        values = [plan[0][0], plan[0][1], plan[1][0], plan[1][1], plan[2][0], plan[2][1]]

        for key, value in zip(keys, values):
            entity_id = self.config[key]
            await self._set_time_entity(entity_id, value, key)

    async def _set_time_entity(self, entity_id: str, value: str, field: str) -> None:
        before = self._get_state(entity_id)
        if before == value:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, value, False)
            return

        domain = entity_id.split(".")[0]
        if domain == "time":
            await self.hass.services.async_call(
                "time",
                "set_value",
                {"entity_id": entity_id, "time": value},
                blocking=True,
            )
        elif domain == "input_datetime":
            await self.hass.services.async_call(
                "input_datetime",
                "set_datetime",
                {"entity_id": entity_id, "time": value},
                blocking=True,
            )
        else:
            _LOGGER.warning("Unsupported slot entity domain for %s", entity_id)
            return

        self.coordinator.add_action_log("set", field, before, value, True)

    async def _set_select(self, entity_id: str, option: str, field: str) -> None:
        before = self._get_state(entity_id)
        if before == option:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, option, False)
            return

        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": option},
            blocking=True,
        )
        self.coordinator.add_action_log("set", field, before, option, True)

    async def _set_switch(self, entity_id: str, on: bool, field: str) -> None:
        before = self._get_state(entity_id)
        target = "on" if on else "off"
        if before == target:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, target, False)
            return

        service = "turn_on" if on else "turn_off"
        await self.hass.services.async_call(
            "homeassistant",
            service,
            {"entity_id": entity_id},
            blocking=True,
        )
        self.coordinator.add_action_log("set", field, before, target, True)

    def _get_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.state if state else "unknown"

    @property
    def _is_test_mode(self) -> bool:
        return bool(self.config.get(CONF_TEST_MODE, True))
