"""Scheduler logic for Smart Pool."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later, async_track_time_interval

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
    CONF_SLOT1_SPEED_LEVEL,
    CONF_SLOT1_SPEED_SELECT,
    CONF_SLOT1_START,
    CONF_SLOT2_END,
    CONF_SLOT2_SPEED_LEVEL,
    CONF_SLOT2_SPEED_SELECT,
    CONF_SLOT2_START,
    CONF_SLOT3_END,
    CONF_SLOT3_SPEED_LEVEL,
    CONF_SLOT3_SPEED_SELECT,
    CONF_SLOT3_START,
    CONF_TEST_MODE,
    CONF_UPDATE_INTERVAL_MIN,
    CONF_WINTER_MIN_RUNTIME_MIN,
    DEFAULT_FREEZE_HYSTERESIS_C,
    MODE_WINTER,
    SPEED_LEVEL_HIGH,
    SPEED_LEVEL_LOW,
    SPEED_LEVEL_MEDIUM,
    WINTER_STATE_EXTREME,
    WINTER_STATE_FREEZE,
    WINTER_STATE_NORMAL,
)
from .coordinator import SmartPoolCoordinator

_LOGGER = logging.getLogger(__name__)

_INTERVAL_APPLY_VERIFY_DELAY_S = 2
_INTERVAL_APPLY_RETRY_DELAY_S = 120
_INTERVAL_APPLY_MAX_FAILURES = 3


class SmartPoolScheduler:
    """Applies winter logic with minimal hardware writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartPoolCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = entry.data
        self._previous_winter_state: str | None = None  # tracks last confirmed state for hysteresis
        self._interval_apply_failures: int = 0
        self._interval_failure_notified: bool = False
        self._interval_retry_cancel: Any = None
        self._cancel_tick = async_track_time_interval(
            hass,
            self._async_tick,
            timedelta(minutes=int(self.config.get(CONF_UPDATE_INTERVAL_MIN, 5))),
        )

    async def async_shutdown(self) -> None:
        if self._cancel_tick:
            self._cancel_tick()
            self._cancel_tick = None
        if self._interval_retry_cancel:
            self._interval_retry_cancel()
            self._interval_retry_cancel = None

    async def async_run_now(self, force_schedule: bool = False) -> None:
        """Run scheduler immediately (used on startup and season changes)."""
        await self._evaluate(datetime.now(), force_schedule=force_schedule)

    async def _async_tick(self, now: datetime) -> None:
        await self._evaluate(now, force_schedule=False)

    async def _evaluate(self, now: datetime, force_schedule: bool) -> None:
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}

        # Keep configured target visible in UI, even during freeze override.
        self.coordinator.target_runtime_minutes = int(self.config[CONF_WINTER_MIN_RUNTIME_MIN])

        if self.coordinator.season_mode != MODE_WINTER:
            self.coordinator.winter_state = "summer"
            return

        await self._ensure_daily_plan(now, force_schedule=force_schedule)

        outdoor_temp_raw = data.get("outdoor_temp")
        if outdoor_temp_raw is None:
            self.coordinator.winter_state = "unknown"
            return

        outdoor_temp = float(outdoor_temp_raw)
        freeze = float(self.config[CONF_FREEZE_TEMP_C])
        extreme = float(self.config[CONF_EXTREME_FREEZE_TEMP_C])
        hysteresis = DEFAULT_FREEZE_HYSTERESIS_C

        # --- Hysteresis logic ---
        # Enter a colder state immediately when the threshold is crossed downward.
        # Only leave that state (move back to a warmer one) once the temperature
        # has risen at least `hysteresis` °C above the threshold, preventing
        # rapid mode-flipping when temperature hovers near a boundary.
        prev = self._previous_winter_state

        if outdoor_temp <= extreme:
            new_state = WINTER_STATE_EXTREME
        elif outdoor_temp <= freeze:
            # Already in extreme? Stay there until temp rises hysteresis above extreme threshold.
            if prev == WINTER_STATE_EXTREME and outdoor_temp <= extreme + hysteresis:
                new_state = WINTER_STATE_EXTREME
            else:
                new_state = WINTER_STATE_FREEZE
        else:
            # Already in freeze? Stay there until temp rises hysteresis above freeze threshold.
            if prev == WINTER_STATE_FREEZE and outdoor_temp <= freeze + hysteresis:
                new_state = WINTER_STATE_FREEZE
            # Already in extreme? Must pass through freeze on the way back up.
            elif prev == WINTER_STATE_EXTREME and outdoor_temp <= freeze + hysteresis:
                new_state = WINTER_STATE_FREEZE
            else:
                new_state = WINTER_STATE_NORMAL

        self._previous_winter_state = new_state
        self.coordinator.winter_state = new_state

        if new_state == WINTER_STATE_EXTREME:
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_MEDIUM_VALUE])
        elif new_state == WINTER_STATE_FREEZE:
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_LOW_VALUE])
        else:
            # Normal winter — Auto mode and slots are already enforced in _ensure_daily_plan.
            pass

    async def _apply_continuous(self, speed: str) -> None:
        await self._set_select(self.config[CONF_PUMP_MODE_SELECT], self.config[CONF_PUMP_MODE_AUTO_VALUE], "pump_mode")
        await self._set_select(self.config[CONF_PUMP_SPEED_SELECT], speed, "pump_speed")
        await self._set_switch(self.config[CONF_PUMP_SWITCH], True, "pump_switch")

    async def _ensure_daily_plan(self, now: datetime, force_schedule: bool) -> None:
        target = int(self.config[CONF_WINTER_MIN_RUNTIME_MIN])

        day = now.date().isoformat()
        plan = self._build_three_slots(target)

        # Skip if already planned today AND the slot entities still hold the correct values.
        # If the controller lost power and reset its slots, slots_match will be False and we re-apply.
        if not force_schedule and self.coordinator.last_schedule_day == day and self._slots_match(plan):
            return

        previous_plan = " | ".join(f"{a}-{b}" for a, b in self.coordinator.last_plan) or "none"
        current_plan = " | ".join(f"{a}-{b}" for a, b in plan)

        # Always expose the intended plan immediately in sensors/dashboard,
        # even if hardware verification fails and retries are still pending.
        self.coordinator.last_plan = plan

        interval_ok = await self._apply_interval_settings_with_verify(plan)
        if not interval_ok:
            self.coordinator.add_action_log("plan_pending", "daily_slots", previous_plan, current_plan, False)
            await self._handle_interval_apply_failure(plan)
            return

        self._clear_interval_retry_state()
        self.coordinator.last_schedule_day = day

        # Ensure hardware runs schedule-based control after plan updates.
        await self._set_select(self.config[CONF_PUMP_MODE_SELECT], self.config[CONF_PUMP_MODE_AUTO_VALUE], "pump_mode")

        self.coordinator.add_action_log("plan", "daily_slots", previous_plan, current_plan, not self._is_test_mode)

    def _slots_match(self, plan: list[tuple[str, str]]) -> bool:
        """Return True if the slot entities currently hold the expected plan values."""
        keys = [
            CONF_SLOT1_START, CONF_SLOT1_END,
            CONF_SLOT2_START, CONF_SLOT2_END,
            CONF_SLOT3_START, CONF_SLOT3_END,
        ]
        values = [plan[0][0], plan[0][1], plan[1][0], plan[1][1], plan[2][0], plan[2][1]]
        for key, expected in zip(keys, values):
            entity_id = self.config.get(key)
            if not entity_id:
                return False
            actual = self._get_state(entity_id)
            # Normalize to HH:MM:SS for comparison (some entities return HH:MM)
            if actual and len(actual) == 5:
                actual = actual + ":00"
            if actual != expected:
                return False
        return True

    def _build_three_slots(self, target_minutes: int) -> list[tuple[str, str]]:
        total = max(0, min(1440, target_minutes))
        each = max(1, total // 3)

        starts = [
            datetime.strptime("22:00", "%H:%M"),
            datetime.strptime("02:00", "%H:%M"),
            datetime.strptime("05:00", "%H:%M"),
        ]

        plan: list[tuple[str, str]] = []
        for st in starts:
            en = st + timedelta(minutes=each)
            if en.day != st.day:
                en = datetime.strptime("23:59", "%H:%M")
            plan.append((st.strftime("%H:%M:%S"), en.strftime("%H:%M:%S")))
        return plan

    def _build_interval_targets(self, plan: list[tuple[str, str]]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []

        time_targets = [
            (CONF_SLOT1_START, plan[0][0], CONF_SLOT1_START),
            (CONF_SLOT1_END, plan[0][1], CONF_SLOT1_END),
            (CONF_SLOT2_START, plan[1][0], CONF_SLOT2_START),
            (CONF_SLOT2_END, plan[1][1], CONF_SLOT2_END),
            (CONF_SLOT3_START, plan[2][0], CONF_SLOT3_START),
            (CONF_SLOT3_END, plan[2][1], CONF_SLOT3_END),
        ]
        for config_key, value, field in time_targets:
            targets.append(
                {
                    "kind": "time",
                    "entity_id": self.config[config_key],
                    "field": field,
                    "value": value,
                }
            )

        slot_speed_targets = [
            (CONF_SLOT1_SPEED_SELECT, CONF_SLOT1_SPEED_LEVEL, "slot1_speed"),
            (CONF_SLOT2_SPEED_SELECT, CONF_SLOT2_SPEED_LEVEL, "slot2_speed"),
            (CONF_SLOT3_SPEED_SELECT, CONF_SLOT3_SPEED_LEVEL, "slot3_speed"),
        ]
        for entity_key, level_key, field in slot_speed_targets:
            entity_id = self.config.get(entity_key)
            if not entity_id:
                continue
            targets.append(
                {
                    "kind": "select",
                    "entity_id": entity_id,
                    "field": field,
                    "value": self._speed_level_to_option(self.config.get(level_key, SPEED_LEVEL_LOW)),
                }
            )

        # Also align the main pump speed select with slot-1 desired speed.
        targets.append(
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_SPEED_SELECT],
                "field": "pump_speed",
                "value": self._speed_level_to_option(self.config.get(CONF_SLOT1_SPEED_LEVEL, SPEED_LEVEL_LOW)),
            }
        )
        return targets

    async def _apply_interval_settings_with_verify(self, plan: list[tuple[str, str]]) -> bool:
        targets = self._build_interval_targets(plan)
        changed_targets: list[dict[str, str]] = []
        for target in targets:
            before = self._normalized_state(target["entity_id"], target["kind"])
            target["before"] = before
            if before != target["value"]:
                changed_targets.append(target)

        if not changed_targets:
            return True

        if self._is_test_mode:
            for target in changed_targets:
                self.coordinator.add_action_log(
                    "would_set",
                    target["field"],
                    target["before"],
                    target["value"],
                    False,
                )
            return True

        # Send all interval writes in one batch to minimize controller lockout impact.
        results = await asyncio.gather(
            *(self._apply_target(target) for target in changed_targets),
            return_exceptions=True,
        )
        for target, result in zip(changed_targets, results):
            if isinstance(result, Exception):
                _LOGGER.error(
                    "Smart Pool: failed to apply interval target %s (%s -> %s): %s",
                    target["entity_id"],
                    target["before"],
                    target["value"],
                    result,
                )

        await asyncio.sleep(_INTERVAL_APPLY_VERIFY_DELAY_S)

        mismatches: list[dict[str, str]] = []
        for target in changed_targets:
            after = self._normalized_state(target["entity_id"], target["kind"])
            if after != target["value"]:
                mismatches.append(target)
                self.coordinator.add_action_log("verify_failed", target["field"], after, target["value"], False)
            else:
                self.coordinator.add_action_log("set", target["field"], target["before"], target["value"], True)

        return not mismatches

    async def _apply_target(self, target: dict[str, str]) -> None:
        entity_id = target["entity_id"]
        value = target["value"]
        if target["kind"] == "select":
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": value},
                blocking=True,
            )
            return

        domain = entity_id.split(".")[0]
        if domain == "time":
            await self.hass.services.async_call(
                "time",
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
            )
            return
        if domain == "input_datetime":
            await self.hass.services.async_call(
                "input_datetime",
                "set_datetime",
                {"entity_id": entity_id, "time": value},
                blocking=True,
            )
            return

        raise ValueError(f"Unsupported slot entity domain '{domain}' for {entity_id}")

    async def _handle_interval_apply_failure(self, plan: list[tuple[str, str]]) -> None:
        self._interval_apply_failures += 1
        current_plan = " | ".join(f"{a}-{b}" for a, b in plan)
        _LOGGER.warning(
            "Smart Pool: interval apply verification failed (attempt %s/%s)",
            self._interval_apply_failures,
            _INTERVAL_APPLY_MAX_FAILURES,
        )

        if self._interval_apply_failures >= _INTERVAL_APPLY_MAX_FAILURES:
            if not self._interval_failure_notified:
                self._interval_failure_notified = True
                await self.coordinator.async_send_notification(
                    "Smart Pool Alert",
                    "Smart Pool: failed to apply/verify interval settings after 3 attempts. "
                    f"Wanted plan: {current_plan}",
                )
            return

        self._schedule_interval_retry()

    def _schedule_interval_retry(self) -> None:
        if self._interval_retry_cancel:
            self._interval_retry_cancel()

        def _retry_callback(_now: datetime) -> None:
            self._interval_retry_cancel = None
            self.hass.async_create_task(self.async_run_now(force_schedule=True))

        self._interval_retry_cancel = async_call_later(self.hass, _INTERVAL_APPLY_RETRY_DELAY_S, _retry_callback)

    def _clear_interval_retry_state(self) -> None:
        self._interval_apply_failures = 0
        self._interval_failure_notified = False
        if self._interval_retry_cancel:
            self._interval_retry_cancel()
            self._interval_retry_cancel = None

    def _normalized_state(self, entity_id: str, kind: str) -> str:
        state = self._get_state(entity_id)
        if kind == "time" and state and len(state) == 5:
            return state + ":00"
        return state

    def _speed_level_to_option(self, level: str) -> str:
        if level == SPEED_LEVEL_HIGH:
            return self.config[CONF_PUMP_SPEED_HIGH_VALUE]
        if level == SPEED_LEVEL_MEDIUM:
            return self.config[CONF_PUMP_SPEED_MEDIUM_VALUE]
        return self.config[CONF_PUMP_SPEED_LOW_VALUE]

    async def _set_time_entity(self, entity_id: str, value: str, field: str) -> None:
        before = self._get_state(entity_id)
        # Normalize both sides to HH:MM:SS before comparing
        norm_before = (before + ":00") if before and len(before) == 5 else before
        if norm_before == value:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, value, False)
            return

        domain = entity_id.split(".")[0]
        try:
            if domain == "time":
                # HA time.set_value uses 'value' as the parameter name
                await self.hass.services.async_call(
                    "time",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
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
                _LOGGER.warning("Smart Pool: unsupported slot entity domain '%s' for %s", domain, entity_id)
                return
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Smart Pool: failed to set time entity %s to %s: %s", entity_id, value, err)
            return

        self.coordinator.add_action_log("set", field, before, value, True)

    async def _set_select(self, entity_id: str, option: str, field: str) -> None:
        before = self._get_state(entity_id)
        if before == option:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, option, False)
            return

        try:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": option},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Smart Pool: failed to set select %s to '%s': %s", entity_id, option, err)
            return

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
