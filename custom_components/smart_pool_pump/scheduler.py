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
    CONF_PUMP_MODE_HEAT_VALUE,
    CONF_PUMP_MODE_MANUAL_VALUE,
    CONF_PUMP_MODE_SELECT,
    CONF_PUMP_SPEED_HIGH_VALUE,
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
    CONF_SOLAR_EXCESS_SENSOR,
    CONF_SUMMER_BATHER_LOAD_FACTOR,
    CONF_SUMMER_COVER_REDUCTION_PCT,
    CONF_SUMMER_HEAT_HYSTERESIS_C,
    CONF_SUMMER_HEAT_TARGET_TEMP_C,
    CONF_SUMMER_MAX_RUNTIME_MIN,
    CONF_SUMMER_MIN_RUNTIME_MIN,
    CONF_SUMMER_POOL_VOLUME_M3,
    CONF_SUMMER_PUMP_FLOW_M3H,
    CONF_TEST_MODE,
    CONF_UPDATE_INTERVAL_MIN,
    CONF_WINTER_MIN_RUNTIME_MIN,
    DEFAULT_SUMMER_BATHER_LOAD_FACTOR,
    DEFAULT_SUMMER_COVER_REDUCTION_PCT,
    DEFAULT_SUMMER_HEAT_HYSTERESIS_C,
    DEFAULT_SUMMER_HEAT_TARGET_TEMP_C,
    DEFAULT_SUMMER_MAX_RUNTIME_MIN,
    DEFAULT_SUMMER_MIN_RUNTIME_MIN,
    DEFAULT_SUMMER_POOL_VOLUME_M3,
    DEFAULT_SUMMER_PUMP_FLOW_M3H,
    DEFAULT_FREEZE_HYSTERESIS_C,
    MODE_SUMMER,
    MODE_WINTER,
    SPEED_LEVEL_HIGH,
    SPEED_LEVEL_LOW,
    SPEED_LEVEL_MEDIUM,
    SUMMER_HEATING_ON,
    WINTER_STATE_EXTREME,
    WINTER_STATE_FREEZE,
    WINTER_STATE_NORMAL,
    WINTER_STATE_WAITING_FOR_DATA,
)
from .coordinator import SmartPoolCoordinator

_LOGGER = logging.getLogger(__name__)

_POOL_CONNECTIVITY_ENTITY_ID = "binary_sensor.pool_connected"
_POOL_CONNECTED_STATES = {"connected", "on", "true", "1"}
_INTERVAL_STEP_VERIFY_DELAY_S = 30
_INTERVAL_STEP_CONNECTIVITY_RETRY_WAIT_S = 60
_INTERVAL_STARTUP_STEP_VERIFY_DELAY_S = 5
_INTERVAL_STARTUP_STEP_CONNECTIVITY_RETRY_WAIT_S = 10
_INTERVAL_CONNECTIVITY_CHECK_ATTEMPTS = 3
_INTERVAL_APPLY_RETRY_DELAY_S = 30 * 60  # 30 minutes
_INTERVAL_APPLY_STARTUP_RETRY_DELAY_S = 30
_FLOW_FACTOR_HIGH = 1.0
_FLOW_FACTOR_MEDIUM = 0.5
_FLOW_FACTOR_LOW = 0.2
_SUMMER_RUNTIME_TOLERANCE_MIN = 30
_SUMMER_CHECK_BASE_TIME = "09:00"
_SUMMER_CHECK_DELAY_MIN = 5
_SUMMER_CHECK_OFFSETS_H = (0, 4, 8)


class SmartPoolScheduler:
    """Applies winter logic with minimal hardware writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartPoolCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = entry.data
        self._previous_winter_state: str | None = None  # tracks last confirmed state for hysteresis
        self._summer_heat_demand_active: bool = False
        self._summer_check_day: str | None = None
        self._summer_checks_done: set[int] = set()
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

    async def async_run_now(
        self,
        force_schedule: bool = False,
        startup: bool = False,
        allow_writes: bool = True,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
        """Run scheduler immediately (used on startup and season changes).
        
        Args:
            force_schedule: Force rebuilding the schedule even if one exists for today.
            startup: True during initial integration startup (uses faster timeouts).
            allow_writes: If False, only plan without writing to hardware.
            fail_fast_on_no_connectivity: If True, skip writes if pool not connected (used for post-startup to avoid delays).
        """
        await self._evaluate(
            datetime.now(),
            force_schedule=force_schedule,
            startup=startup,
            allow_writes=allow_writes,
            fail_fast_on_no_connectivity=fail_fast_on_no_connectivity,
        )

    async def _async_tick(self, now: datetime) -> None:
        await self._evaluate(now, force_schedule=False, startup=False, allow_writes=True, fail_fast_on_no_connectivity=False)

    async def _evaluate(
        self,
        now: datetime,
        force_schedule: bool,
        startup: bool,
        allow_writes: bool,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}

        # Keep configured/derived target visible in UI.
        self.coordinator.target_runtime_minutes = self._calculate_target_runtime_minutes(data)

        if self.coordinator.season_mode == MODE_SUMMER:
            self.coordinator.winter_state = "summer"
            self.coordinator.notify_listeners()

            if allow_writes and self.coordinator.summer_heating_mode != SUMMER_HEATING_ON:
                current_mode = self._get_state(self.config[CONF_PUMP_MODE_SELECT])
                if current_mode == self.config[CONF_PUMP_MODE_HEAT_VALUE]:
                    await self._set_select(
                        self.config[CONF_PUMP_MODE_SELECT],
                        self.config[CONF_PUMP_MODE_AUTO_VALUE],
                        "pump_mode",
                    )

            day = now.date().isoformat()
            if self._summer_check_day != day:
                self._summer_check_day = day
                self._summer_checks_done = set()

            should_plan_now = force_schedule or self.coordinator.last_schedule_day != day
            if self.coordinator.summer_heating_mode != SUMMER_HEATING_ON:
                # Heating OFF: at most 3 adjustment checks/day once pool temp is valid.
                check_idx = self._summer_due_check_index(now, data)
                if check_idx is not None:
                    self._summer_checks_done.add(check_idx)
                    should_plan_now = True

            if should_plan_now:
                await self._ensure_daily_plan(
                    now,
                    force_schedule=force_schedule,
                    startup=startup,
                    allow_writes=allow_writes,
                    fail_fast_on_no_connectivity=fail_fast_on_no_connectivity,
                )

            if not allow_writes:
                return

            if self._should_run_summer_heating(data):
                await self._apply_summer_heat_mode(startup=startup, fail_fast=fail_fast_on_no_connectivity)
            return

        # CRITICAL: Check data availability FIRST, before any scheduling logic
        outdoor_temp_available = data.get("outdoor_temp_available", False)
        if not outdoor_temp_available:
            self.coordinator.winter_state = WINTER_STATE_WAITING_FOR_DATA
            self.coordinator.notify_listeners()
            _LOGGER.debug("Smart Pool: outdoor temperature not yet available, waiting for data")
            return

        outdoor_temp_raw = data.get("outdoor_temp")
        if outdoor_temp_raw is None:
            self.coordinator.winter_state = "unknown"
            self.coordinator.notify_listeners()
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
        self.coordinator.notify_listeners()

        if new_state in (WINTER_STATE_EXTREME, WINTER_STATE_FREEZE):
            # Freeze protection runs continuously in manual mode and must not be
            # interrupted by delayed slot-plan retries from normal winter mode.
            self._clear_interval_retry_state()

            if not allow_writes:
                return

            if new_state == WINTER_STATE_EXTREME:
                await self._apply_continuous(
                    speed=self.config[CONF_PUMP_SPEED_MEDIUM_VALUE],
                    startup=startup,
                    fail_fast=fail_fast_on_no_connectivity,
                )
            else:
                await self._apply_continuous(
                    speed=self.config[CONF_PUMP_SPEED_LOW_VALUE],
                    startup=startup,
                    fail_fast=fail_fast_on_no_connectivity,
                )
            return

        await self._ensure_daily_plan(
            now,
            force_schedule=force_schedule,
            startup=startup,
            allow_writes=allow_writes,
            fail_fast_on_no_connectivity=fail_fast_on_no_connectivity,
        )

        if not allow_writes:
            return

    def _calculate_target_runtime_minutes(self, data: dict[str, Any]) -> int:
        if self.coordinator.season_mode == MODE_WINTER:
            return int(self.config[CONF_WINTER_MIN_RUNTIME_MIN])
        return self._calculate_summer_runtime_minutes(data)

    def _calculate_summer_runtime_minutes(self, data: dict[str, Any]) -> int:
        pool_temp = data.get("pool_temp")
        outdoor_temp = data.get("outdoor_temp")

        volume_m3 = float(self.config.get(CONF_SUMMER_POOL_VOLUME_M3, DEFAULT_SUMMER_POOL_VOLUME_M3))
        flow_m3h = self._effective_pump_flow_m3h()
        cover_reduction_pct = float(
            self.config.get(CONF_SUMMER_COVER_REDUCTION_PCT, DEFAULT_SUMMER_COVER_REDUCTION_PCT)
        )
        bather_load_factor = float(
            self.config.get(CONF_SUMMER_BATHER_LOAD_FACTOR, DEFAULT_SUMMER_BATHER_LOAD_FACTOR)
        )
        min_runtime = int(self.config.get(CONF_SUMMER_MIN_RUNTIME_MIN, DEFAULT_SUMMER_MIN_RUNTIME_MIN))
        max_runtime = int(self.config.get(CONF_SUMMER_MAX_RUNTIME_MIN, DEFAULT_SUMMER_MAX_RUNTIME_MIN))

        # Ensure sane min/max bounds even if user configured them inversely.
        if min_runtime > max_runtime:
            min_runtime, max_runtime = max_runtime, min_runtime

        # One full turnover time in hours from pool volume and pump flow.
        turnover_hours = volume_m3 / flow_m3h

        # Temperature factors: warmer water and warmer outdoor conditions need
        # more filtration/chlorine circulation time.
        pool_temp_factor = 0.7
        if pool_temp is not None:
            pool_temp_factor = 0.7 + 0.03 * (float(pool_temp) - 20.0)
        pool_temp_factor = max(0.5, min(1.8, pool_temp_factor))

        outdoor_temp_factor = 1.0
        if outdoor_temp is not None:
            outdoor_temp_factor = 0.9 + 0.02 * (float(outdoor_temp) - 20.0)
        outdoor_temp_factor = max(0.7, min(1.4, outdoor_temp_factor))

        cover_factor = 1.0 - max(0.0, min(60.0, cover_reduction_pct)) / 100.0
        bather_factor = max(0.6, min(2.5, bather_load_factor))

        suggested_hours = turnover_hours * pool_temp_factor * outdoor_temp_factor * cover_factor * bather_factor
        suggested_minutes = int(round(suggested_hours * 60.0))

        return max(min_runtime, min(max_runtime, suggested_minutes))

    def _effective_pump_flow_m3h(self) -> float:
        """Return effective flow based on current mode/speed.

        `CONF_SUMMER_PUMP_FLOW_M3H` is treated as nominal HIGH-speed flow.
        Derived factors:
        - high: 100%
        - medium: 50%
        - slow: 20%
        Heat mode is assumed to force slow speed regardless of speed select state.
        """
        high_flow_m3h = max(0.1, float(self.config.get(CONF_SUMMER_PUMP_FLOW_M3H, DEFAULT_SUMMER_PUMP_FLOW_M3H)))

        # With summer heating disabled, runtime sizing should not be penalized by
        # a stale Heat/Slow state. Use medium-flow baseline for calculations.
        if self.coordinator.season_mode == MODE_SUMMER and self.coordinator.summer_heating_mode != SUMMER_HEATING_ON:
            return high_flow_m3h * _FLOW_FACTOR_MEDIUM

        pump_mode_state = self._get_state(self.config[CONF_PUMP_MODE_SELECT])
        if pump_mode_state == self.config[CONF_PUMP_MODE_HEAT_VALUE]:
            return high_flow_m3h * _FLOW_FACTOR_LOW

        pump_speed_state = self._get_state(self.config[CONF_PUMP_SPEED_SELECT])
        if pump_speed_state == self.config[CONF_PUMP_SPEED_LOW_VALUE]:
            return high_flow_m3h * _FLOW_FACTOR_LOW
        if pump_speed_state == self.config[CONF_PUMP_SPEED_HIGH_VALUE]:
            return high_flow_m3h * _FLOW_FACTOR_HIGH

        # Default to medium when speed is unknown/unavailable or explicitly medium.
        return high_flow_m3h * _FLOW_FACTOR_MEDIUM

    def _should_run_summer_heating(self, data: dict[str, Any]) -> bool:
        if self.coordinator.summer_heating_mode != SUMMER_HEATING_ON:
            self._summer_heat_demand_active = False
            return False

        pool_temp = data.get("pool_temp")
        if pool_temp is None:
            return False

        target = float(self.config.get(CONF_SUMMER_HEAT_TARGET_TEMP_C, DEFAULT_SUMMER_HEAT_TARGET_TEMP_C))
        hysteresis = float(self.config.get(CONF_SUMMER_HEAT_HYSTERESIS_C, DEFAULT_SUMMER_HEAT_HYSTERESIS_C))
        current_temp = float(pool_temp)

        # Enter demand below target-hysteresis, leave above target+hysteresis.
        if self._summer_heat_demand_active:
            self._summer_heat_demand_active = current_temp <= (target + hysteresis)
        else:
            self._summer_heat_demand_active = current_temp <= (target - hysteresis)

        if not self._summer_heat_demand_active:
            return False

        solar_entity = self.config.get(CONF_SOLAR_EXCESS_SENSOR)
        if not solar_entity:
            return False

        solar_state = self._get_state(solar_entity).strip().lower()
        return solar_state in {"on", "true", "1", "available", "excess", "surplus"}

    async def _apply_summer_heat_mode(self, startup: bool, fail_fast: bool = False) -> None:
        target = {
            "kind": "select",
            "entity_id": self.config[CONF_PUMP_MODE_SELECT],
            "field": "pump_mode",
            "before": self._get_state(self.config[CONF_PUMP_MODE_SELECT]),
            "value": self.config[CONF_PUMP_MODE_HEAT_VALUE],
        }

        if target["before"] == target["value"]:
            return

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", target["field"], target["before"], target["value"], False)
            return

        await self._apply_pump_mode_with_connectivity_check(target, startup=startup, fail_fast=fail_fast)

    async def _apply_continuous(self, speed: str, startup: bool, fail_fast: bool = False) -> None:
        targets = [
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_MODE_SELECT],
                "field": "pump_mode",
                "before": self._get_state(self.config[CONF_PUMP_MODE_SELECT]),
                "value": self.config[CONF_PUMP_MODE_MANUAL_VALUE],
            },
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_SPEED_SELECT],
                "field": "pump_speed",
                "before": self._get_state(self.config[CONF_PUMP_SPEED_SELECT]),
                "value": speed,
            },
            {
                "kind": "switch",
                "entity_id": self.config[CONF_PUMP_SWITCH],
                "field": "pump_switch",
                "before": self._get_state(self.config[CONF_PUMP_SWITCH]),
                "value": "on",
            },
        ]

        changed_targets = [
            target for target in targets if self._normalized_state(target["entity_id"], target["kind"]) != target["value"]
        ]

        if not changed_targets:
            return

        if self._is_test_mode:
            for target in changed_targets:
                self.coordinator.add_action_log(
                    "would_set",
                    target["field"],
                    target["before"],
                    target["value"],
                    False,
                )
            return

        first_target = changed_targets[0]
        remaining_targets = changed_targets[1:]

        if first_target["field"] == "pump_mode":
            if not await self._apply_pump_mode_with_connectivity_check(first_target, startup=startup, fail_fast=fail_fast):
                return
        else:
            if not await self._apply_target_with_verify(first_target, startup=startup, fail_fast=fail_fast):
                return

        for target in remaining_targets:
            if not await self._apply_target_with_verify(target, startup=startup, fail_fast=fail_fast):
                return

    async def _ensure_daily_plan(
        self,
        now: datetime,
        force_schedule: bool,
        startup: bool,
        allow_writes: bool,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
        target = self._calculate_target_runtime_minutes(self.coordinator.data or {})

        day = now.date().isoformat()
        if self.coordinator.season_mode == MODE_SUMMER:
            plan = self._build_summer_slots(target)
        else:
            plan = self._build_three_slots(target)

        if self.coordinator.season_mode == MODE_SUMMER and self.coordinator.summer_heating_mode != SUMMER_HEATING_ON:
            current_runtime = self._plan_total_minutes(self.coordinator.last_plan)
            if (
                not force_schedule
                and self.coordinator.last_schedule_day == day
                and current_runtime > 0
                and abs(target - current_runtime) <= _SUMMER_RUNTIME_TOLERANCE_MIN
            ):
                _LOGGER.debug(
                    "Smart Pool: summer heating OFF target delta (%s min) within tolerance, keeping current plan",
                    abs(target - current_runtime),
                )
                return

        # Skip if already planned today AND the slot entities still hold the correct values.
        # If the controller lost power and reset its slots, slots_match will be False and we re-apply.
        if not force_schedule and self.coordinator.last_schedule_day == day and self._slots_match(plan):
            return

        previous_plan = " | ".join(f"{a}-{b}" for a, b in self.coordinator.last_plan) or "none"
        current_plan = " | ".join(f"{a}-{b}" for a, b in plan)

        # Always expose the intended plan immediately in sensors/dashboard,
        # even if hardware verification fails and retries are still pending.
        self.coordinator.last_plan = plan

        if not allow_writes:
            self.coordinator.add_action_log("plan_ready", "daily_slots", previous_plan, current_plan, False)
            return

        interval_ok = await self._apply_interval_settings_with_verify(
            plan, startup=startup, fail_fast_on_no_connectivity=fail_fast_on_no_connectivity
        )
        if not interval_ok:
            self.coordinator.add_action_log("plan_pending", "daily_slots", previous_plan, current_plan, False)
            await self._handle_interval_apply_failure(plan, startup=startup)
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

    def _build_summer_slots(self, target_minutes: int) -> list[tuple[str, str]]:
        total = max(60, min(1440, target_minutes))

        # Summer focus: keep short night circulation, always include 09:00-09:30,
        # and concentrate the main runtime so it reaches up to 19:30.
        morning_mandatory = 30
        preferred_night = max(30, min(90, int(round(total * 0.15))))

        if total < morning_mandatory + preferred_night + 30:
            night_minutes = max(0, total - morning_mandatory - 30)
        else:
            night_minutes = preferred_night

        daytime_main = max(30, total - night_minutes - morning_mandatory)

        # 09:30..19:30 window is 600 minutes. If the requested daytime main
        # exceeds this, spill the remainder to the night run.
        if daytime_main > 600:
            spill_to_night = daytime_main - 600
            night_minutes += spill_to_night
            daytime_main = 600

        starts_and_minutes = [
            ("02:00", night_minutes),
            ("09:00", morning_mandatory),
            # End at 19:30 so runtime is focused towards late daytime.
            ((datetime.strptime("19:30", "%H:%M") - timedelta(minutes=daytime_main)).strftime("%H:%M"), daytime_main),
        ]

        plan: list[tuple[str, str]] = []
        for start_text, minutes in starts_and_minutes:
            st = datetime.strptime(start_text, "%H:%M")
            en = st + timedelta(minutes=max(0, minutes))
            if en.day != st.day:
                en = datetime.strptime("23:59", "%H:%M")
            plan.append((st.strftime("%H:%M:%S"), en.strftime("%H:%M:%S")))

        return plan

    def _plan_total_minutes(self, plan: list[tuple[str, str]]) -> int:
        total = 0
        for start_s, end_s in plan:
            st = datetime.strptime(start_s, "%H:%M:%S")
            en = datetime.strptime(end_s, "%H:%M:%S")
            minutes = int((en - st).total_seconds() // 60)
            if minutes < 0:
                minutes += 24 * 60
            total += minutes
        return total

    def _summer_due_check_index(self, now: datetime, data: dict[str, Any]) -> int | None:
        if data.get("pool_temp") is None:
            return None

        base = datetime.combine(now.date(), datetime.strptime(_SUMMER_CHECK_BASE_TIME, "%H:%M").time())
        base += timedelta(minutes=_SUMMER_CHECK_DELAY_MIN)

        for idx, offset_h in enumerate(_SUMMER_CHECK_OFFSETS_H):
            if idx in self._summer_checks_done:
                continue
            check_time = base + timedelta(hours=offset_h)
            if now >= check_time:
                return idx
        return None

    def _build_interval_targets(self, plan: list[tuple[str, str]]) -> list[dict[str, str]]:
        ordered_targets: list[dict[str, str]] = []

        def _slot_speed_value(slot_number: int) -> str:
            # Summer policy: slot1 (night) runs slow; daytime focus slots run medium.
            if self.coordinator.season_mode == MODE_SUMMER:
                if slot_number == 1:
                    return self.config[CONF_PUMP_SPEED_LOW_VALUE]
                return self.config[CONF_PUMP_SPEED_MEDIUM_VALUE]

            # Winter/default behavior uses configured desired slot speeds.
            if slot_number == 1:
                return self._speed_level_to_option(self.config.get(CONF_SLOT1_SPEED_LEVEL, SPEED_LEVEL_LOW))
            if slot_number == 2:
                return self._speed_level_to_option(self.config.get(CONF_SLOT2_SPEED_LEVEL, SPEED_LEVEL_LOW))
            return self._speed_level_to_option(self.config.get(CONF_SLOT3_SPEED_LEVEL, SPEED_LEVEL_LOW))

        # FIRST: Pump mode (prerequisite for all other changes)
        ordered_targets.append(
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_MODE_SELECT],
                "field": "pump_mode",
                "value": self.config[CONF_PUMP_MODE_AUTO_VALUE],
                "is_pump_mode": True,
            }
        )

        # Requested order per slot: to (end), from (start), speed.
        slot_targets = [
            (CONF_SLOT1_END, plan[0][1], CONF_SLOT1_END, CONF_SLOT1_SPEED_SELECT, CONF_SLOT1_SPEED_LEVEL, "slot1_speed"),
            (CONF_SLOT1_START, plan[0][0], CONF_SLOT1_START, None, None, None),
            (CONF_SLOT2_END, plan[1][1], CONF_SLOT2_END, CONF_SLOT2_SPEED_SELECT, CONF_SLOT2_SPEED_LEVEL, "slot2_speed"),
            (CONF_SLOT2_START, plan[1][0], CONF_SLOT2_START, None, None, None),
            (CONF_SLOT3_END, plan[2][1], CONF_SLOT3_END, CONF_SLOT3_SPEED_SELECT, CONF_SLOT3_SPEED_LEVEL, "slot3_speed"),
            (CONF_SLOT3_START, plan[2][0], CONF_SLOT3_START, None, None, None),
        ]

        # Build times in the requested order.
        time_targets = []
        for config_key, value, field, _, _, _ in slot_targets:
            time_targets.append(
                {
                    "kind": "time",
                    "entity_id": self.config[config_key],
                    "field": field,
                    "value": value,
                }
            )

        # Then insert each slot speed directly after the slot's start value.
        for idx, target in enumerate(time_targets):
            ordered_targets.append(target)
            # 0/1 belong to slot1, 2/3 to slot2, 4/5 to slot3
            if idx in (1, 3, 5):
                if idx == 1:
                    entity_key, level_key, field = CONF_SLOT1_SPEED_SELECT, CONF_SLOT1_SPEED_LEVEL, "slot1_speed"
                elif idx == 3:
                    entity_key, level_key, field = CONF_SLOT2_SPEED_SELECT, CONF_SLOT2_SPEED_LEVEL, "slot2_speed"
                else:
                    entity_key, level_key, field = CONF_SLOT3_SPEED_SELECT, CONF_SLOT3_SPEED_LEVEL, "slot3_speed"
                entity_id = self.config.get(entity_key)
                if entity_id:
                    slot_number = 1 if idx == 1 else (2 if idx == 3 else 3)
                    ordered_targets.append(
                        {
                            "kind": "select",
                            "entity_id": entity_id,
                            "field": field,
                            "value": _slot_speed_value(slot_number),
                        }
                    )

        # Align the main pump speed select with season behavior.
        ordered_targets.append(
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_SPEED_SELECT],
                "field": "pump_speed",
                "value": self.config[CONF_PUMP_SPEED_MEDIUM_VALUE]
                if self.coordinator.season_mode == MODE_SUMMER
                else self._speed_level_to_option(self.config.get(CONF_SLOT1_SPEED_LEVEL, SPEED_LEVEL_LOW)),
            }
        )
        return ordered_targets

    async def _apply_interval_settings_with_verify(
        self, plan: list[tuple[str, str]], startup: bool, fail_fast_on_no_connectivity: bool = False
    ) -> bool:
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

        # Apply each target one by one, sequentially
        for target in changed_targets:
            is_pump_mode = target.get("is_pump_mode", False)
            if is_pump_mode:
                ok = await self._apply_pump_mode_with_connectivity_check(
                    target, startup=startup, fail_fast=fail_fast_on_no_connectivity
                )
            else:
                ok = await self._apply_target_with_verify(
                    target, startup=startup, fail_fast=fail_fast_on_no_connectivity
                )
            if not ok:
                return False

        return True

    async def _apply_pump_mode_with_connectivity_check(
        self, target: dict[str, str], startup: bool, fail_fast: bool = False
    ) -> bool:
        """Apply pump mode with dedicated 3-retry connectivity check phase.
        
        Args:
            target: Target to apply.
            startup: True if during initial integration startup.
            fail_fast: If True, skip retries on connectivity failure (for post-startup to avoid blocking).
        """
        entity_id = target["entity_id"]
        field = target["field"]
        before = target["before"]
        wanted = target["value"]
        verify_delay = _INTERVAL_STARTUP_STEP_VERIFY_DELAY_S if startup else _INTERVAL_STEP_VERIFY_DELAY_S
        connectivity_retry_wait = _INTERVAL_STARTUP_STEP_CONNECTIVITY_RETRY_WAIT_S if startup else _INTERVAL_STEP_CONNECTIVITY_RETRY_WAIT_S

        try:
            await self._apply_target(target)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Smart Pool: failed to apply pump mode %s (%s -> %s): %s",
                entity_id,
                before,
                wanted,
                err,
            )
            return False

        # Wait for controller state propagation
        await asyncio.sleep(verify_delay)

        # Try to verify with connectivity check (up to 3 attempts, or 1 if fail_fast)
        max_attempts = 1 if fail_fast else _INTERVAL_CONNECTIVITY_CHECK_ATTEMPTS
        for attempt in range(1, max_attempts + 1):
            if self._is_pool_connected():
                after = self._normalized_state(entity_id, target["kind"])
                if after == wanted:
                    self.coordinator.add_action_log("set", field, before, wanted, True)
                    return True
                _LOGGER.error(
                    "Smart Pool: pump mode verify failed (attempt %s/%s): expected %s, got %s",
                    attempt,
                    max_attempts,
                    wanted,
                    after,
                )
                self.coordinator.add_action_log("verify_failed", field, after, wanted, False)
                return False
            else:
                # Pool not connected
                current = self._get_state(_POOL_CONNECTIVITY_ENTITY_ID)
                _LOGGER.warning(
                    "Smart Pool: pool not connected before verifying pump mode (attempt %s/%s), state: %s",
                    attempt,
                    max_attempts,
                    current,
                )
                self.coordinator.add_action_log("connectivity_wait", field, current, "connected|on", False)

                if attempt < max_attempts:
                    # Wait before retrying connectivity check
                    await asyncio.sleep(connectivity_retry_wait)

        # All connectivity checks failed
        _LOGGER.error(
            "Smart Pool: exhausted %s connectivity checks for pump mode verification",
            max_attempts,
        )
        return False

    def _is_pool_connected(self) -> bool:
        state = self.hass.states.get(_POOL_CONNECTIVITY_ENTITY_ID)
        if not state:
            return False
        return str(state.state).strip().lower() in _POOL_CONNECTED_STATES

    async def _apply_target_with_verify(self, target: dict[str, str], startup: bool, fail_fast: bool = False) -> bool:
        """Apply a single target (non-pump-mode) and verify it was set correctly.
        
        Args:
            target: Target to apply.
            startup: True if during initial integration startup.
            fail_fast: If True, fail immediately if pool not connected (for post-startup to avoid blocking).
        """
        entity_id = target["entity_id"]
        field = target["field"]
        before = target["before"]
        wanted = target["value"]
        verify_delay = _INTERVAL_STARTUP_STEP_VERIFY_DELAY_S if startup else _INTERVAL_STEP_VERIFY_DELAY_S

        # Check connectivity before write
        if not self._is_pool_connected():
            current = self._get_state(_POOL_CONNECTIVITY_ENTITY_ID)
            _LOGGER.warning(
                "Smart Pool: pool not connected before writing %s, state: %s",
                entity_id,
                current,
            )
            self.coordinator.add_action_log("connectivity_wait", field, current, "connected|on", False)
            if fail_fast:
                # Skip write on post-startup if no connectivity (avoid blocking)
                _LOGGER.info("Smart Pool: skipping %s write on post-startup due to no connectivity", field)
                return False
            # During normal operation, fail and trigger retry
            return False

        # Apply the target
        try:
            await self._apply_target(target)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Smart Pool: failed to apply %s (%s -> %s): %s",
                entity_id,
                before,
                wanted,
                err,
            )
            return False

        # Wait for controller state propagation
        await asyncio.sleep(verify_delay)

        # Verify the change was applied
        after = self._normalized_state(entity_id, target["kind"])
        if after == wanted:
            self.coordinator.add_action_log("set", field, before, wanted, True)
            return True

        _LOGGER.error(
            "Smart Pool: verification failed for %s: expected %s, got %s",
            entity_id,
            wanted,
            after,
        )
        self.coordinator.add_action_log("verify_failed", field, after, wanted, False)
        return False

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
        if target["kind"] == "switch":
            service = "turn_on" if value == "on" else "turn_off"
            await self.hass.services.async_call(
                "homeassistant",
                service,
                {"entity_id": entity_id},
                blocking=True,
            )
            return

        domain = entity_id.split(".")[0]
        if domain == "time":
            # Some time entities accept 'time', others use 'value'. Try 'value'
            # first, then fallback to 'time' for stricter schemas.
            try:
                await self.hass.services.async_call(
                    "time",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                err_text = str(err).lower()
                if "data['value']" not in err_text and "extra keys not allowed" not in err_text:
                    raise
                await self.hass.services.async_call(
                    "time",
                    "set_value",
                    {"entity_id": entity_id, "time": value},
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

    async def _handle_interval_apply_failure(self, plan: list[tuple[str, str]], startup: bool) -> None:
        if self._interval_failure_notified:
            return

        self._interval_failure_notified = True
        current_plan = " | ".join(f"{a}-{b}" for a, b in plan)

        _LOGGER.error(
            "Smart Pool: failed to apply interval settings. Wanted plan: %s. Retrying in 30 minutes.",
            current_plan,
        )

        await self.coordinator.async_send_notification(
            "Smart Pool Alert",
            "Smart Pool: failed to apply/verify interval settings. "
            f"Wanted plan: {current_plan}. Retrying in 30 minutes.",
        )

        self._schedule_interval_retry(startup=startup)

    def _schedule_interval_retry(self, startup: bool) -> None:
        if self._interval_retry_cancel:
            self._interval_retry_cancel()

        async def _retry_callback(_now: datetime) -> None:
            self._interval_retry_cancel = None
            await self.async_run_now(force_schedule=True)

        retry_delay = _INTERVAL_APPLY_STARTUP_RETRY_DELAY_S if startup else _INTERVAL_APPLY_RETRY_DELAY_S
        self._interval_retry_cancel = async_call_later(self.hass, retry_delay, _retry_callback)

    def _clear_interval_retry_state(self) -> None:
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
