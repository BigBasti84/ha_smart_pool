"""Coordinator for Smart Pool runtime state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_NOTIFY_SERVICE,
    CONF_OUTDOOR_TEMP_FALLBACK_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POOL_TEMP_SENSOR,
    CONF_PUMP_RUNNING_SENSOR,
    CONF_PUMP_SWITCH,
    DEFAULT_SEASON_MODE,
    DOMAIN,
    SUMMER_HEATING_ON,
)

_LOGGER = logging.getLogger(__name__)

_RUNTIME_STORE_VERSION = 1
_RUNTIME_SAVE_DELAY_S = 10

# Datetime format for action logs: DD-MM-YYYY - HH:MM:SS
_DATETIME_FORMAT = "%d-%m-%Y - %H:%M:%S"


@dataclass
class ActionLogEntry:
    """Represents one planned/applied hardware change."""

    at: str
    action: str
    field: str
    before: str
    after: str
    applied: bool


class SmartPoolCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Collect and keep Smart Pool state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        super().__init__(hass, logger=_LOGGER, name=DOMAIN, update_interval=update_interval)
        self.entry = entry
        self.config = entry.data

        self.season_mode: str = DEFAULT_SEASON_MODE
        self.summer_heating_mode: str = SUMMER_HEATING_ON
        self.winter_state: str = "unknown"
        self.target_runtime_minutes: int = 0
        self.actual_runtime_minutes: float = 0.0
        self.last_schedule_day: str | None = None
        self.last_plan: list[tuple[str, str]] = []
        self.controller_update_running: bool = False
        self.controller_update_last_at: str | None = None
        self.controller_update_last_result: str = "none"
        self.controller_update_last_context: str = ""
        # Volume-based filtration tracking (summer mode v0.3+)
        self.actual_volume_m3: float = 0.0
        self.target_volume_m3: float = 0.0
        self.volume_target_achieved: bool = False
        self.current_flow_rate_m3h: float = 0.0  # updated by scheduler on each state change
        self.summer_pump_state: str = "unknown"  # "heat" | "filtration" | "stopped" | "unknown"
        self.last_tick: datetime | None = None
        self._pump_last_on: bool = False
        self._last_outdoor_temp: float | None = None
        self._last_pool_temp: float | None = None
        self._outdoor_temp_unavailable: bool = False  # True when primary sensor is unavailable
        self._outdoor_temp_unavailable_since: datetime | None = None  # When unavailability started
        self._outdoor_temp_timeout_notified: bool = False  # Track if 120-min timeout notification was sent
        self.action_log: deque[ActionLogEntry] = deque(maxlen=20)
        self._runtime_store: Store[dict[str, Any]] = Store(
            hass,
            _RUNTIME_STORE_VERSION,
            f"{DOMAIN}_{entry.entry_id}_runtime",
        )

    async def async_initialize(self) -> None:
        """Restore persisted runtime and tick timestamp for the current day."""
        data = await self._runtime_store.async_load()
        if not data:
            return

        saved_date = str(data.get("runtime_date", "")).strip()
        today = datetime.now().date().isoformat()
        if saved_date != today:
            self.actual_runtime_minutes = 0.0
            self.last_tick = None
            self._schedule_runtime_save()
            return

        try:
            self.actual_runtime_minutes = max(0.0, float(data.get("actual_runtime_minutes", 0.0)))
        except (TypeError, ValueError):
            self.actual_runtime_minutes = 0.0

        try:
            self.actual_volume_m3 = max(0.0, float(data.get("actual_volume_m3", 0.0)))
            self.volume_target_achieved = bool(data.get("volume_target_achieved", False))
        except (TypeError, ValueError):
            self.actual_volume_m3 = 0.0
            self.volume_target_achieved = False

        # Restore last_tick timestamp so we can correctly calculate runtime on restart
        try:
            last_tick_str = data.get("last_tick_iso", None)
            if last_tick_str:
                self.last_tick = datetime.fromisoformat(last_tick_str)
                _LOGGER.debug(
                    "Smart Pool: restored runtime state - %.1f min, %.2f m³, last_tick: %s",
                    self.actual_runtime_minutes,
                    self.actual_volume_m3,
                    self.last_tick.isoformat(),
                )
        except (ValueError, TypeError):
            pass  # If invalid, last_tick stays None and will be set on next update

    async def async_shutdown(self) -> None:
        """Persist runtime state immediately on unload/shutdown."""
        await self._runtime_store.async_save(self._runtime_store_payload())

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot, primary_unavailable, used_fallback = self._collect_snapshot()
            self._update_runtime(snapshot)
            await self._handle_temp_sensor_availability(primary_unavailable, used_fallback)
            return snapshot
        except Exception as err:  # pragma: no cover - HA logs details
            raise UpdateFailed(f"Smart Pool update failed: {err}") from err

    async def _handle_temp_sensor_availability(self, primary_unavailable: bool, used_fallback: bool) -> None:
        """Track outdoor temp sensor availability and send notifications on state change and timeout."""
        notify_service = self.config.get(CONF_NOTIFY_SERVICE, "").strip()
        now = datetime.now()

        if primary_unavailable and not self._outdoor_temp_unavailable:
            # Transition: became unavailable
            self._outdoor_temp_unavailable = True
            self._outdoor_temp_unavailable_since = now
            self._outdoor_temp_timeout_notified = False
            msg = (
                "Smart Pool: outdoor temperature sensor is unavailable. "
                + ("Using fallback sensor." if used_fallback else "No fallback configured — last known value is being used.")
            )
            _LOGGER.warning(msg)
            if notify_service:
                await self._async_notify(notify_service, "Smart Pool Alert", msg)
        elif not primary_unavailable and self._outdoor_temp_unavailable:
            # Transition: recovered
            self._outdoor_temp_unavailable = False
            self._outdoor_temp_unavailable_since = None
            self._outdoor_temp_timeout_notified = False
            msg = "Smart Pool: outdoor temperature sensor is back online."
            _LOGGER.info(msg)
            if notify_service:
                await self._async_notify(notify_service, "Smart Pool", msg)
        elif primary_unavailable and self._outdoor_temp_unavailable and self._outdoor_temp_unavailable_since:
            # Already unavailable — check if 120 minutes have passed
            elapsed_minutes = (now - self._outdoor_temp_unavailable_since).total_seconds() / 60.0
            if elapsed_minutes >= 120 and not self._outdoor_temp_timeout_notified:
                self._outdoor_temp_timeout_notified = True
                msg = (
                    "Smart Pool: outdoor temperature sensor has been unavailable for 120+ minutes. "
                    + ("Using fallback sensor." if used_fallback else "Using last known value.")
                    + " Winter mode control is limited."
                )
                _LOGGER.error(msg)
                if notify_service:
                    await self._async_notify(notify_service, "Smart Pool Alert - Sensor Timeout", msg)

    async def _async_notify(self, service_string: str, title: str, message: str) -> None:
        """Call a notify service, e.g. 'notify.mobile_app_iphone'."""
        parts = service_string.split(".", 1)
        if len(parts) != 2:
            _LOGGER.warning("Smart Pool: invalid notify_service '%s', expected 'domain.service'", service_string)
            return
        domain, service = parts
        try:
            await self.hass.services.async_call(
                domain, service, {"title": title, "message": message}, blocking=False
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Smart Pool: failed to send notification via '%s': %s", service_string, err)

    async def async_send_notification(self, title: str, message: str) -> None:
        """Send a notification if a notify service is configured."""
        notify_service = self.config.get(CONF_NOTIFY_SERVICE, "").strip()
        if not notify_service:
            return
        await self._async_notify(notify_service, title, message)

    def notify_listeners(self) -> None:
        """Trigger an update notification to all listeners (CoordinatorEntity instances)."""
        self.async_set_updated_data(self.data)

    def _state(self, entity_id: str, fallback: Any = None) -> Any:
        if not entity_id:
            return fallback
        st = self.hass.states.get(entity_id)
        return st.state if st else fallback

    def _float_state(self, entity_id: str, fallback: float = 0.0) -> float:
        val = self._state(entity_id, None)
        try:
            if val in (None, "unknown", "unavailable"):
                return fallback
            if isinstance(val, str):
                val = val.replace(",", ".")
            return float(val)
        except (TypeError, ValueError):
            return fallback

    def _bool_state(self, entity_id: str, fallback: bool = False) -> bool:
        val = self._state(entity_id, None)
        if val is None:
            return fallback
        s = str(val).strip().lower()
        if s in {"on", "true", "1", "running", "active", "filtering", "heat"}:
            return True
        if s in {"off", "false", "0", "idle", "standby"}:
            return False
        return fallback

    def _is_sensor_unavailable(self, entity_id: str) -> bool:
        """Return True if the entity is missing or in an unavailable/unknown state."""
        if not entity_id:
            return True
        st = self.hass.states.get(entity_id)
        return st is None or st.state in ("unknown", "unavailable")

    def _collect_snapshot(self) -> tuple[dict[str, Any], bool, bool]:
        """Return (snapshot, primary_outdoor_unavailable, used_fallback).
        
        Snapshot includes:
        - outdoor_temp: current (or last-known) outdoor temperature, or None if never available
        - outdoor_temp_available: True if outdoor_temp is current or last-known and usable
        - pool_temp: current pool temperature or None
        - pump_on: current pump state
        """
        cfg = self.config

        primary_entity = cfg.get(CONF_OUTDOOR_TEMP_SENSOR, "")
        fallback_entity = cfg.get(CONF_OUTDOOR_TEMP_FALLBACK_SENSOR, "")
        primary_unavailable = self._is_sensor_unavailable(primary_entity)
        used_fallback = False

        if not primary_unavailable:
            outdoor = self._float_state(primary_entity, None)
        else:
            # Primary is unavailable — try fallback
            if fallback_entity and not self._is_sensor_unavailable(fallback_entity):
                outdoor = self._float_state(fallback_entity, None)
                used_fallback = True
            else:
                outdoor = None

        pool = self._float_state(cfg.get(CONF_POOL_TEMP_SENSOR, ""), None)

        if outdoor is not None:
            self._last_outdoor_temp = outdoor
        if pool is not None:
            self._last_pool_temp = pool

        running_entity = cfg.get(CONF_PUMP_RUNNING_SENSOR, "")
        if running_entity:
            pump_on = self._bool_state(running_entity, fallback=False)
        else:
            pump_on = self._bool_state(cfg.get(CONF_PUMP_SWITCH, ""), fallback=False)

        # Track if outdoor temp is usable (either fresh or last-known)
        outdoor_temp_available = self._last_outdoor_temp is not None

        return (
            {
                "outdoor_temp": self._last_outdoor_temp,
                "outdoor_temp_available": outdoor_temp_available,
                "pool_temp": self._last_pool_temp,
                "pump_on": pump_on,
            },
            primary_unavailable,
            used_fallback,
        )

    def _update_runtime(self, snapshot: dict[str, Any]) -> None:
        """Update runtime tracking based on pump state.
        
        Runtime is accumulated based on whether the pump was ON during the last interval.
        On HA restart, we continue from the last saved tick timestamp, preventing loss of time.
        """
        now = datetime.now()
        pump_on = bool(snapshot.get("pump_on", False))

        # Check for day change
        if self.last_tick and now.date() != self.last_tick.date():
            _LOGGER.info(
                "Smart Pool: day changed, resetting runtime/volume. Day %s runtime: %.1f min, volume: %.2f m³",
                self.last_tick.date().isoformat(),
                self.actual_runtime_minutes,
                self.actual_volume_m3,
            )
            self.actual_runtime_minutes = 0.0
            self.actual_volume_m3 = 0.0
            self.volume_target_achieved = False

        if self.last_tick is None:
            # First update (or after HA restart if last_tick wasn't persisted)
            _LOGGER.debug("Smart Pool: initializing runtime tracking from %s", now.isoformat())
            self.last_tick = now
            self._pump_last_on = pump_on
            self._schedule_runtime_save()
            return

        # Calculate time delta since last update
        delta_minutes = (now - self.last_tick).total_seconds() / 60.0

        # If pump was ON during this interval, add to runtime
        # (We use the previous state to determine if it was on during this interval)
        if self._pump_last_on and delta_minutes > 0:
            self.actual_runtime_minutes += delta_minutes
            # Accumulate filtered volume using the flow rate the scheduler last set
            if self.current_flow_rate_m3h > 0:
                self.actual_volume_m3 += self.current_flow_rate_m3h * (delta_minutes / 60.0)
            _LOGGER.debug(
                "Smart Pool: pump ran %.2f min @ %.1f m³/h — runtime: %.1f min, volume: %.2f m³",
                delta_minutes,
                self.current_flow_rate_m3h,
                self.actual_runtime_minutes,
                self.actual_volume_m3,
            )

        self.last_tick = now
        self._pump_last_on = pump_on
        self._schedule_runtime_save()

    def _runtime_store_payload(self) -> dict[str, Any]:
        payload = {
            "runtime_date": datetime.now().date().isoformat(),
            "actual_runtime_minutes": round(self.actual_runtime_minutes, 3),
            "actual_volume_m3": round(self.actual_volume_m3, 4),
            "volume_target_achieved": self.volume_target_achieved,
        }
        # Also persist last_tick so we can continue from where we left off on restart
        if self.last_tick:
            payload["last_tick_iso"] = self.last_tick.isoformat()
        return payload

    def _schedule_runtime_save(self) -> None:
        self._runtime_store.async_delay_save(self._runtime_store_payload, _RUNTIME_SAVE_DELAY_S)

    def add_action_log(self, action: str, field: str, before: str, after: str, applied: bool) -> None:
        self.action_log.appendleft(
            ActionLogEntry(
                at=datetime.now().strftime(_DATETIME_FORMAT),
                action=action,
                field=field,
                before=str(before),
                after=str(after),
                applied=applied,
            )
        )
        self.notify_listeners()

    def mark_controller_update_started(self, context: str) -> None:
        self.controller_update_running = True
        self.controller_update_last_context = context
        self.notify_listeners()

    def mark_controller_update_finished(self, success: bool, context: str) -> None:
        self.controller_update_running = False
        self.controller_update_last_at = datetime.now().strftime(_DATETIME_FORMAT)
        self.controller_update_last_result = "success" if success else "failed"
        self.controller_update_last_context = context
        self.notify_listeners()

    def action_log_as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "at": e.at,
                "action": e.action,
                "field": e.field,
                "before": e.before,
                "after": e.after,
                "applied": e.applied,
            }
            for e in self.action_log
        ]
