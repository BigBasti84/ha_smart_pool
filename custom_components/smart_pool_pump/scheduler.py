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


class SmartPoolScheduler:
    """Applies winter logic with minimal hardware writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartPoolCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = entry.data
        self._previous_winter_state: str | None = None  # tracks last confirmed state for hysteresis
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

        # Keep configured target visible in UI, even during freeze override.
        self.coordinator.target_runtime_minutes = int(self.config[CONF_WINTER_MIN_RUNTIME_MIN])

        if self.coordinator.season_mode != MODE_WINTER:
            self.coordinator.winter_state = "summer"
            self.coordinator.notify_listeners()
            return

        # CRITICAL: Check data availability FIRST, before any scheduling logic
        outdoor_temp_available = data.get("outdoor_temp_available", False)
        if not outdoor_temp_available:
            self.coordinator.winter_state = WINTER_STATE_WAITING_FOR_DATA
            self.coordinator.notify_listeners()
            _LOGGER.debug("Smart Pool: outdoor temperature not yet available, waiting for data")
            return

        # Now safe to plan and schedule
        await self._ensure_daily_plan(
            now,
            force_schedule=force_schedule,
            startup=startup,
            allow_writes=allow_writes,
            fail_fast_on_no_connectivity=fail_fast_on_no_connectivity,
        )

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

        if not allow_writes:
            return

        if new_state == WINTER_STATE_EXTREME:
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_MEDIUM_VALUE])
        elif new_state == WINTER_STATE_FREEZE:
            await self._apply_continuous(speed=self.config[CONF_PUMP_SPEED_LOW_VALUE])
        else:
            # Normal winter — Auto mode and slots are already enforced in _ensure_daily_plan.
            pass

    async def _apply_continuous(self, speed: str) -> None:
        await self._set_select(self.config[CONF_PUMP_MODE_SELECT], self.config[CONF_PUMP_MODE_MANUAL_VALUE], "pump_mode")
        await self._set_select(self.config[CONF_PUMP_SPEED_SELECT], speed, "pump_speed")
        await self._set_switch(self.config[CONF_PUMP_SWITCH], True, "pump_switch")

    async def _ensure_daily_plan(
        self,
        now: datetime,
        force_schedule: bool,
        startup: bool,
        allow_writes: bool,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
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

    def _build_interval_targets(self, plan: list[tuple[str, str]]) -> list[dict[str, str]]:
        ordered_targets: list[dict[str, str]] = []

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
                    ordered_targets.append(
                        {
                            "kind": "select",
                            "entity_id": entity_id,
                            "field": field,
                            "value": self._speed_level_to_option(self.config.get(level_key, SPEED_LEVEL_LOW)),
                        }
                    )

        # Also align the main pump speed select with slot-1 desired speed.
        ordered_targets.append(
            {
                "kind": "select",
                "entity_id": self.config[CONF_PUMP_SPEED_SELECT],
                "field": "pump_speed",
                "value": self._speed_level_to_option(self.config.get(CONF_SLOT1_SPEED_LEVEL, SPEED_LEVEL_LOW)),
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
