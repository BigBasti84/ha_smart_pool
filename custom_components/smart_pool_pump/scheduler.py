"""Scheduler logic for Smart Pool."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    CONF_SLOT1_SPEED_SELECT,
    CONF_SLOT1_START,
    CONF_SLOT2_END,
    CONF_SLOT2_SPEED_SELECT,
    CONF_SLOT2_START,
    CONF_SLOT3_END,
    CONF_SLOT3_SPEED_SELECT,
    CONF_SLOT3_START,
    CONF_WINTER_FILTRATION_SPEED_LEVEL,
    CONF_SOLAR_EXCESS_SENSOR,
    CONF_BACKWASH_SENSOR,
    CONF_SUMMER_BATHER_LOAD_FACTOR,
    CONF_SUMMER_COVER_REDUCTION_PCT,
    CONF_SUMMER_HEAT_HYSTERESIS_C,
    CONF_SUMMER_HEAT_TARGET_TEMP_C,
    CONF_SUMMER_DAY_END_HOUR,
    CONF_SUMMER_DAY_START_HOUR,
    CONF_SUMMER_MANDATORY_1_END,
    CONF_SUMMER_MANDATORY_1_START,
    CONF_SUMMER_MANDATORY_2_END,
    CONF_SUMMER_MANDATORY_2_START,
    CONF_SUMMER_MAX_RUNTIME_MIN,
    CONF_SUMMER_MIN_RUNTIME_MIN,
    CONF_SUMMER_POOL_VOLUME_M3,
    CONF_SUMMER_PUMP_FLOW_M3H,
    CONF_TEST_MODE,
    CONF_UPDATE_INTERVAL_MIN,
    CONF_VOLUME_HYSTERESIS_M3,
    CONF_WINTER_MIN_RUNTIME_MIN,
    DEFAULT_PUMP_MODE_AUTO_VALUE,
    DEFAULT_PUMP_MODE_HEAT_VALUE,
    DEFAULT_PUMP_MODE_MANUAL_VALUE,
    DEFAULT_PUMP_SPEED_HIGH_VALUE,
    DEFAULT_PUMP_SPEED_LOW_VALUE,
    DEFAULT_PUMP_SPEED_MEDIUM_VALUE,
    DEFAULT_SUMMER_BATHER_LOAD_FACTOR,
    DEFAULT_SUMMER_COVER_REDUCTION_PCT,
    DEFAULT_SUMMER_HEAT_HYSTERESIS_C,
    DEFAULT_SUMMER_HEAT_TARGET_TEMP_C,
    DEFAULT_SUMMER_MANDATORY_1_END,
    DEFAULT_SUMMER_DAY_START_HOUR,
    DEFAULT_SUMMER_MANDATORY_1_START,
    DEFAULT_SUMMER_MANDATORY_2_END,
    DEFAULT_SUMMER_MANDATORY_2_START,
    DEFAULT_SUMMER_MAX_RUNTIME_MIN,
    DEFAULT_SUMMER_MIN_RUNTIME_MIN,
    DEFAULT_SUMMER_POOL_VOLUME_M3,
    DEFAULT_SUMMER_PUMP_FLOW_M3H,
    DEFAULT_FREEZE_HYSTERESIS_C,
    DEFAULT_VOLUME_HYSTERESIS_M3,
    FLOW_RATE_HEAT_M3H,
    FLOW_RATE_MEDIUM_M3H,
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
_SUMMER_STATE_VERIFY_INITIAL_DELAY_S = 30    # wait after write before first check
_SUMMER_STATE_VERIFY_CONNECTIVITY_WAIT_S = 15  # wait between connectivity rechecks
_SUMMER_STATE_VERIFY_MAX_ATTEMPTS = 4          # 30 + 4 × 15 = 90 s total before giving up
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
        self.config = dict(entry.data)
        # Pump mode and speed option strings are hardcoded (Bestway hardware).
        # They are not user-configurable and override anything stored in entry.data.
        self.config[CONF_PUMP_MODE_HEAT_VALUE] = DEFAULT_PUMP_MODE_HEAT_VALUE
        self.config[CONF_PUMP_MODE_AUTO_VALUE] = DEFAULT_PUMP_MODE_AUTO_VALUE
        self.config[CONF_PUMP_MODE_MANUAL_VALUE] = DEFAULT_PUMP_MODE_MANUAL_VALUE
        self.config[CONF_PUMP_SPEED_LOW_VALUE] = DEFAULT_PUMP_SPEED_LOW_VALUE
        self.config[CONF_PUMP_SPEED_MEDIUM_VALUE] = DEFAULT_PUMP_SPEED_MEDIUM_VALUE
        self.config[CONF_PUMP_SPEED_HIGH_VALUE] = DEFAULT_PUMP_SPEED_HIGH_VALUE
        self._previous_winter_state: str | None = None  # tracks last confirmed state for hysteresis
        self._summer_heat_demand_active: bool = False
        self._summer_check_day: str | None = None
        self._summer_checks_done: set[int] = set()
        self._interval_failure_notified: bool = False
        self._interval_retry_cancel: Any = None
        self._evaluating: bool = False  # guard against concurrent/overlapping evaluation calls
        self._summer_verify_cancel: Any = None  # handle for pending summer-state verify callback
        self._summer_verify_target: str | None = None  # target state being verified
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
        if self._summer_verify_cancel:
            self._summer_verify_cancel()
            self._summer_verify_cancel = None

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

    async def _evaluate(  # noqa: C901
        self,
        now: datetime,
        force_schedule: bool,
        startup: bool,
        allow_writes: bool,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
        # Prevent concurrent/overlapping evaluations (e.g. post-startup pass racing with first tick).
        # If an evaluation is already in progress, this call is redundant — the running evaluation
        # will apply the current state. Drop it rather than queuing a duplicate.
        if self._evaluating:
            return
        self._evaluating = True
        try:
            await self._evaluate_body(
                now=now,
                force_schedule=force_schedule,
                startup=startup,
                allow_writes=allow_writes,
                fail_fast_on_no_connectivity=fail_fast_on_no_connectivity,
            )
        finally:
            self._evaluating = False

    async def _evaluate_body(  # noqa: C901
        self,
        now: datetime,
        force_schedule: bool,
        startup: bool,
        allow_writes: bool,
        fail_fast_on_no_connectivity: bool = False,
    ) -> None:
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}

        # --- backwash protection: freeze all pump changes while backwash sensor is on ---
        if self._is_backwash_active():
            if not self.coordinator.backwash_active:
                _LOGGER.info("Smart Pool: backwash started — suspending all pump mode changes")
                self.coordinator.add_action_log("backwash_started", "backwash_active", "False", "True", False)
            self.coordinator.backwash_active = True
            self.coordinator.current_flow_rate_m3h = 0.0
            self.coordinator.notify_listeners()
            return
        if self.coordinator.backwash_active:
            _LOGGER.info("Smart Pool: backwash ended — resuming normal control")
            self.coordinator.add_action_log("backwash_ended", "backwash_active", "True", "False", False)
            self.coordinator.backwash_active = False

        # target_runtime_minutes is only meaningful for winter slot planning.
        if self.coordinator.season_mode != MODE_SUMMER:
            self.coordinator.target_runtime_minutes = self._calculate_target_runtime_minutes(data)

        if self.coordinator.season_mode == MODE_SUMMER:
            await self._evaluate_summer(now, data, allow_writes, startup, fail_fast_on_no_connectivity)
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
        # Summer: derive from target volume at Medium-speed reference rate for display
        target_vol = self._calculate_target_volume_m3(data)
        return int(target_vol / FLOW_RATE_MEDIUM_M3H * 60.0)

    # ---------------------------------------------------------------------------
    # Summer volume-based control (v0.3+)
    # ---------------------------------------------------------------------------

    async def _evaluate_summer(
        self,
        now: datetime,
        data: dict[str, Any],
        allow_writes: bool,
        startup: bool,
        fail_fast: bool,
    ) -> None:
        """Summer mode: volume-based direct pump control (no slot scheduling).

        Priority order on each tick:
          1. Mandatory windows (09:00-09:30, 19:00-19:30) always force pump on.
          2. Volume target achieved → stop pump (manual mode, switch off).
          3. Solar excess available + heating enabled → Heat mode (Medium display, Slow hardware).
          4. Otherwise → Manual mode, Medium speed, switch on (4 m³/h filtration).
        """
        # --- target volume ---
        target_vol = self._calculate_target_volume_m3(data)
        self.coordinator.target_volume_m3 = target_vol
        # Note: target_runtime_minutes is NOT set here — summer mode stops on volume,
        # not on time. The hard time cap is max_runtime (enforced below).
        actual_vol = self.coordinator.actual_volume_m3
        hysteresis = float(self.config.get(CONF_VOLUME_HYSTERESIS_M3, DEFAULT_VOLUME_HYSTERESIS_M3))

        # --- min / max runtime limits ---
        min_runtime = int(self.config.get(CONF_SUMMER_MIN_RUNTIME_MIN, DEFAULT_SUMMER_MIN_RUNTIME_MIN))
        max_runtime = int(self.config.get(CONF_SUMMER_MAX_RUNTIME_MIN, DEFAULT_SUMMER_MAX_RUNTIME_MIN))
        if min_runtime > max_runtime:
            min_runtime, max_runtime = max_runtime, min_runtime
        # min_volume: even if target < this, always filter at least min_runtime worth of volume
        min_volume = (min_runtime / 60.0) * FLOW_RATE_MEDIUM_M3H
        # Use actual_runtime_minutes for the max_runtime check — this is the same value the
        # "Actual Runtime" sensor displays, so it can never diverge from what the user sees.
        # (summer_mode_runtimes is kept for per-state breakdown in the daily summary sensor.)
        total_runtime_min = self.coordinator.actual_runtime_minutes
        max_runtime_exceeded = total_runtime_min >= max_runtime

        # --- volume hysteresis state machine ---
        if not self.coordinator.volume_target_achieved:
            if actual_vol >= target_vol:
                self.coordinator.volume_target_achieved = True
                _LOGGER.info(
                    "Smart Pool: daily volume target achieved (%.2f / %.2f m³)",
                    actual_vol, target_vol,
                )
                self.coordinator.add_action_log(
                    "volume_target_met", "actual_volume_m3",
                    f"{actual_vol:.2f}", f"{target_vol:.2f}", True,
                )
        else:
            # Already achieved — only restart if target grew beyond actual + hysteresis
            if target_vol > actual_vol + hysteresis:
                self.coordinator.volume_target_achieved = False
                _LOGGER.info(
                    "Smart Pool: volume target increased, resuming filtration (%.2f / %.2f m³)",
                    actual_vol, target_vol,
                )
                self.coordinator.add_action_log(
                    "volume_target_raised", "actual_volume_m3",
                    f"{actual_vol:.2f}", f"{target_vol:.2f}", True,
                )

        in_mandatory = self._is_mandatory_window(now)
        # The daytime start hour is a soft focus gate: filtration will not pre-run
        # before this hour (avoids burning through the daily quota at night), but
        # is free to continue past the end hour if the volume target is not yet met.
        # Mandatory circulation windows always override this gate.
        after_day_start = (
            now.hour >= int(self.config.get(CONF_SUMMER_DAY_START_HOUR, DEFAULT_SUMMER_DAY_START_HOUR))
        )

        # Pump should run if:
        #   - max_runtime is NOT exceeded, AND
        #   - either we are in a mandatory window, OR the daytime window has opened
        #     AND the daily volume target (or min-volume floor) has not yet been reached.
        pump_should_run = (
            not max_runtime_exceeded
            and (
                in_mandatory
                or (
                    after_day_start
                    and (not self.coordinator.volume_target_achieved or actual_vol < min_volume)
                )
            )
        )

        if not self.coordinator.max_runtime_exceeded and max_runtime_exceeded:
            self.coordinator.max_runtime_exceeded = True
            _LOGGER.info(
                "Smart Pool: max daily runtime reached (%d min), stopping pump"
                " (actual volume %.2f / target %.2f m³)",
                max_runtime, actual_vol, target_vol,
            )
            self.coordinator.add_action_log(
                "max_runtime_reached", "total_runtime_min",
                f"{total_runtime_min:.0f}", f"{max_runtime}", True,
            )

        if pump_should_run:
            solar_active = self._is_solar_excess_active()
            heating_enabled = self.coordinator.summer_heating_mode == SUMMER_HEATING_ON
            if solar_active and heating_enabled:
                target_state = "heat"         # Medium display, Slow hardware (2 m³/h)
                new_flow_rate = FLOW_RATE_HEAT_M3H
            else:
                target_state = "filtration"   # Manual ON, Medium speed (4 m³/h)
                new_flow_rate = FLOW_RATE_MEDIUM_M3H
        else:
            target_state = "stopped"
            new_flow_rate = 0.0

        self.coordinator.summer_pump_state = target_state
        self.coordinator.current_flow_rate_m3h = new_flow_rate
        self.coordinator.winter_state = "summer"
        self.coordinator.notify_listeners()

        if not allow_writes:
            return

        changed = await self._apply_summer_state(target_state)
        if changed:
            self._schedule_summer_state_verify(target_state)

    def _schedule_summer_state_verify(self, target_state: str) -> None:
        """Schedule a deferred check that the applied summer state was actually confirmed."""
        # Cancel any verify that was pending for a previous (now superseded) state.
        if self._summer_verify_cancel:
            self._summer_verify_cancel()
            self._summer_verify_cancel = None
        self._summer_verify_target = target_state

        @callback
        def _callback(_now: Any) -> None:
            self._summer_verify_cancel = None
            self.hass.async_create_task(
                self._async_summer_state_verify(target_state, attempt=1)
            )

        self._summer_verify_cancel = async_call_later(
            self.hass, _SUMMER_STATE_VERIFY_INITIAL_DELAY_S, _callback
        )

    async def _async_summer_state_verify(self, target_state: str, attempt: int) -> None:
        """Check that the summer state was applied; retry once if not, wait for connectivity."""
        # Abort if the target has already changed (a new state was applied after us).
        if self._summer_verify_target != target_state:
            return

        if not self._is_pool_connected():
            if attempt < _SUMMER_STATE_VERIFY_MAX_ATTEMPTS:
                _LOGGER.debug(
                    "Smart Pool: summer state verify attempt %d/%d — pool not connected yet, retrying in %ds",
                    attempt, _SUMMER_STATE_VERIFY_MAX_ATTEMPTS, _SUMMER_STATE_VERIFY_CONNECTIVITY_WAIT_S,
                )

                @callback
                def _retry(_now: Any) -> None:
                    self._summer_verify_cancel = None
                    self.hass.async_create_task(
                        self._async_summer_state_verify(target_state, attempt + 1)
                    )

                self._summer_verify_cancel = async_call_later(
                    self.hass, _SUMMER_STATE_VERIFY_CONNECTIVITY_WAIT_S, _retry
                )
            else:
                _LOGGER.warning(
                    "Smart Pool: summer state '%s' verify timed out — pool not connected after %ds; "
                    "next scheduler tick will retry if needed",
                    target_state,
                    _SUMMER_STATE_VERIFY_INITIAL_DELAY_S
                    + _SUMMER_STATE_VERIFY_MAX_ATTEMPTS * _SUMMER_STATE_VERIFY_CONNECTIVITY_WAIT_S,
                )
                self.coordinator.add_action_log(
                    "summer_verify_timeout", "pool_connected", "disconnected", target_state, False
                )
            return

        # Pool is connected — read entity states and compare.
        mode_entity = self.config[CONF_PUMP_MODE_SELECT]
        switch_entity = self.config[CONF_PUMP_SWITCH]
        mode_state = self._get_state(mode_entity)
        switch_state = self._get_state(switch_entity)

        if target_state == "stopped":
            expected_mode = self.config[CONF_PUMP_MODE_MANUAL_VALUE]
            expected_switch = "off"
        elif target_state == "filtration":
            expected_mode = self.config[CONF_PUMP_MODE_AUTO_VALUE]
            expected_switch = "on"
        else:  # heat
            expected_mode = self.config[CONF_PUMP_MODE_HEAT_VALUE]
            expected_switch = None  # heat mode does not use the filtration switch

        mode_ok = mode_state == expected_mode
        switch_ok = expected_switch is None or switch_state == expected_switch

        if mode_ok and switch_ok:
            _LOGGER.debug("Smart Pool: summer state '%s' confirmed by verify", target_state)
            return

        # State not applied — log and retry once.
        _LOGGER.warning(
            "Smart Pool: summer state '%s' not confirmed (mode=%s expected=%s, switch=%s expected=%s) — retrying",
            target_state, mode_state, expected_mode, switch_state, expected_switch,
        )
        self.coordinator.add_action_log(
            "summer_verify_retry", "summer_state",
            f"mode={mode_state},switch={switch_state}", target_state, True,
        )
        # Retry without scheduling another verify (one retry is sufficient;
        # the next periodic tick will catch any remaining failure).
        await self._apply_summer_state(target_state)

    async def _apply_summer_state(self, target_state: str) -> bool:
        """Apply a summer pump state: 'heat', 'filtration', or 'stopped'.

        Returns True if any command was actually sent to hardware (i.e. at least
        one entity state differed from the target), False if everything was already
        correct and all writes were skipped.
        """
        changed = False
        if target_state == "heat":
            # Heat mode: controller shows Medium, hardware forces Slow (2 m³/h)
            changed |= await self._set_select(
                self.config[CONF_PUMP_MODE_SELECT],
                self.config[CONF_PUMP_MODE_HEAT_VALUE],
                "pump_mode",
            )
            changed |= await self._set_select(
                self.config[CONF_PUMP_SPEED_SELECT],
                self.config[CONF_PUMP_SPEED_MEDIUM_VALUE],
                "pump_speed",
            )
        elif target_state == "filtration":
            # Auto mode, Medium speed, pump on (4 m³/h).
            # Auto lets the controller run its own schedule at the configured speed;
            # the filtration switch must be On so the Auto schedule is not paused.
            changed |= await self._set_select(
                self.config[CONF_PUMP_MODE_SELECT],
                self.config[CONF_PUMP_MODE_AUTO_VALUE],
                "pump_mode",
            )
            changed |= await self._set_select(
                self.config[CONF_PUMP_SPEED_SELECT],
                self.config[CONF_PUMP_SPEED_MEDIUM_VALUE],
                "pump_speed",
            )
            changed |= await self._set_switch(self.config[CONF_PUMP_SWITCH], True, "pump_switch")
        else:
            # Stopped: Manual mode, filtration switch off.
            # This is the only correct way to stop summer-mode filtration —
            # no slot/timer is used; the pump is stopped by explicit command.
            # The Bestway hardware only accepts the switch-off after it has fully
            # transitioned to Manual mode, so we wait 5 s after sending the mode
            # change before issuing the switch-off.
            mode_changed = await self._set_select(
                self.config[CONF_PUMP_MODE_SELECT],
                self.config[CONF_PUMP_MODE_MANUAL_VALUE],
                "pump_mode",
            )
            changed |= mode_changed
            if mode_changed:
                await asyncio.sleep(5)
            changed |= await self._set_switch(self.config[CONF_PUMP_SWITCH], False, "pump_switch")
        return changed

    def _calculate_target_volume_m3(self, data: dict[str, Any]) -> float:
        """Return today's filtration target in m³.

        Formula: pool_volume × combined_factor (temp, cover, bather load).
        The flow rate cancels out: (pool_vol/flow × factor) × flow = pool_vol × factor.
        Clamped to min/max runtime equivalents at Medium reference speed.
        """
        pool_volume_m3 = float(self.config.get(CONF_SUMMER_POOL_VOLUME_M3, DEFAULT_SUMMER_POOL_VOLUME_M3))
        pool_temp = data.get("pool_temp")
        # Use the fresh outdoor reading only — if the sensor is currently unavailable
        # the outdoor_temp_factor is excluded from the calculation (stays at 1.0).
        outdoor_temp = data.get("outdoor_temp_current")
        cover_reduction_pct = float(
            self.config.get(CONF_SUMMER_COVER_REDUCTION_PCT, DEFAULT_SUMMER_COVER_REDUCTION_PCT)
        )
        bather_load_factor = float(
            self.config.get(CONF_SUMMER_BATHER_LOAD_FACTOR, DEFAULT_SUMMER_BATHER_LOAD_FACTOR)
        )

        pool_temp_factor = 1.0
        if pool_temp is not None:
            # 1 full turnover at 20 °C, 2 turnovers at 30 °C (slope = 0.1 / °C)
            pool_temp_factor = 1.0 + 0.1 * (float(pool_temp) - 20.0)
        pool_temp_factor = max(0.5, min(3.0, pool_temp_factor))

        outdoor_temp_factor = 1.0
        if outdoor_temp is not None:
            outdoor_temp_factor = 0.9 + 0.02 * (float(outdoor_temp) - 20.0)
        outdoor_temp_factor = max(0.7, min(1.4, outdoor_temp_factor))

        cover_factor = 1.0 - max(0.0, min(60.0, cover_reduction_pct)) / 100.0
        bather_factor = max(0.6, min(2.5, bather_load_factor))

        target_volume = pool_volume_m3 * pool_temp_factor * outdoor_temp_factor * cover_factor * bather_factor

        # Return the raw physics-based target — no runtime clamping.
        # The max/min runtime limits are enforced separately in _evaluate_summer.
        return target_volume

    def _is_mandatory_window(self, now: datetime) -> bool:
        """Return True if now falls inside a configured mandatory pump window."""
        cur = now.time()

        def _parse(key: str, default: str) -> datetime:
            raw = str(self.config.get(key, default))
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(raw, fmt).time()
                except ValueError:
                    continue
            return datetime.strptime(default, "%H:%M").time()

        w1s = _parse(CONF_SUMMER_MANDATORY_1_START, DEFAULT_SUMMER_MANDATORY_1_START)
        w1e = _parse(CONF_SUMMER_MANDATORY_1_END,   DEFAULT_SUMMER_MANDATORY_1_END)
        w2s = _parse(CONF_SUMMER_MANDATORY_2_START, DEFAULT_SUMMER_MANDATORY_2_START)
        w2e = _parse(CONF_SUMMER_MANDATORY_2_END,   DEFAULT_SUMMER_MANDATORY_2_END)
        return (w1s <= cur < w1e) or (w2s <= cur < w2e)

    def _is_solar_excess_active(self) -> bool:
        """Return True if the configured solar excess sensor is in an active state."""
        entity_id = self.config.get(CONF_SOLAR_EXCESS_SENSOR, "")
        if not entity_id:
            return False
        state = self._get_state(entity_id).strip().lower()
        return state in {"on", "true", "1", "available", "excess", "surplus"}

    def _is_backwash_active(self) -> bool:
        """Return True if the backwash binary sensor is on."""
        entity_id = self.config.get(CONF_BACKWASH_SENSOR, "")
        if not entity_id:
            return False
        return self._get_state(entity_id).strip().lower() == "on"

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
        pool_temp_factor = 1.0
        if pool_temp is not None:
            # 1 full turnover at 20 °C, 2 turnovers at 30 °C (slope = 0.1 / °C)
            pool_temp_factor = 1.0 + 0.1 * (float(pool_temp) - 20.0)
        pool_temp_factor = max(0.5, min(3.0, pool_temp_factor))

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

        self.coordinator.mark_controller_update_started("summer_heat_mode")
        ok = await self._apply_pump_mode_with_connectivity_check(target, startup=startup, fail_fast=fail_fast)
        self.coordinator.mark_controller_update_finished(ok, "summer_heat_mode")

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

        self.coordinator.mark_controller_update_started("continuous_freeze")
        success = False

        first_target = changed_targets[0]
        remaining_targets = changed_targets[1:]

        if first_target["field"] == "pump_mode":
            if not await self._apply_pump_mode_with_connectivity_check(first_target, startup=startup, fail_fast=fail_fast):
                self.coordinator.mark_controller_update_finished(False, "continuous_freeze")
                return
        else:
            if not await self._apply_target_with_verify(first_target, startup=startup, fail_fast=fail_fast):
                self.coordinator.mark_controller_update_finished(False, "continuous_freeze")
                return

        for target in remaining_targets:
            if not await self._apply_target_with_verify(target, startup=startup, fail_fast=fail_fast):
                self.coordinator.mark_controller_update_finished(False, "continuous_freeze")
                return

        success = True
        self.coordinator.mark_controller_update_finished(success, "continuous_freeze")

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

        # Only reset pump to Auto after a plan write when no summer heating demand is active.
        # When demand IS active, pump_mode is managed at the end of _evaluate to avoid oscillation.
        if not (self.coordinator.season_mode == MODE_SUMMER and self._summer_heat_demand_active):
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

            # Winter: all three slots run at the single configured filtration speed.
            return self._speed_level_to_option(self.config.get(CONF_WINTER_FILTRATION_SPEED_LEVEL, SPEED_LEVEL_LOW))

        # FIRST: Pump mode (prerequisite for all other changes).
        # Skip the Auto reset when summer heating demand is currently active — pump_mode is managed
        # at the end of _evaluate in that case to avoid oscillation between Auto and Heat.
        if not (self.coordinator.season_mode == MODE_SUMMER and self._summer_heat_demand_active):
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

        self.coordinator.mark_controller_update_started("interval_plan_apply")

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
                self.coordinator.mark_controller_update_finished(False, "interval_plan_apply")
                return False
        self.coordinator.mark_controller_update_finished(True, "interval_plan_apply")
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

        if not self._entity_is_available_for_write(entity_id, field):
            return False

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

        if not self._entity_is_available_for_write(entity_id, field):
            return False

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

        if not self._entity_is_available_for_write(entity_id, field):
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

    async def _set_select(self, entity_id: str, option: str, field: str, force: bool = False) -> bool:
        before = self._get_state(entity_id)
        if not force and before == option:
            return False

        if not self._entity_is_available_for_write(entity_id, field):
            return False

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, option, False)
            return False

        try:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": option},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Smart Pool: failed to set select %s to '%s': %s", entity_id, option, err)
            return False

        self.coordinator.add_action_log("set", field, before, option, True)
        return True

    async def _set_switch(self, entity_id: str, on: bool, field: str, force: bool = False) -> bool:
        before = self._get_state(entity_id)
        target = "on" if on else "off"
        if not force and before == target:
            return False

        if not self._entity_is_available_for_write(entity_id, field):
            return False

        if self._is_test_mode:
            self.coordinator.add_action_log("would_set", field, before, target, False)
            return False

        service = "turn_on" if on else "turn_off"
        await self.hass.services.async_call(
            "homeassistant",
            service,
            {"entity_id": entity_id},
            blocking=True,
        )
        self.coordinator.add_action_log("set", field, before, target, True)
        return True

    def _get_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.state if state else "unknown"

    def _entity_is_available_for_write(self, entity_id: str, field: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning(
                "Smart Pool: skipping %s write because configured entity %s does not exist",
                field,
                entity_id,
            )
            self.coordinator.add_action_log("missing_entity", field, "missing", "configured", False)
            return False
        if state.state in {"unknown", "unavailable"}:
            _LOGGER.warning(
                "Smart Pool: skipping %s write because configured entity %s is %s",
                field,
                entity_id,
                state.state,
            )
            self.coordinator.add_action_log("entity_unavailable", field, state.state, "available", False)
            return False
        return True

    @property
    def _is_test_mode(self) -> bool:
        return bool(self.config.get(CONF_TEST_MODE, True))
