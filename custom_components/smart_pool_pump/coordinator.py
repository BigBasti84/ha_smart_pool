"""Coordinator for Smart Pool runtime state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
)

_LOGGER = logging.getLogger(__name__)


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
        self.winter_state: str = "unknown"
        self.target_runtime_minutes: int = 0
        self.actual_runtime_minutes: float = 0.0
        self.last_schedule_day: str | None = None
        self.last_plan: list[tuple[str, str]] = []
        self.last_tick: datetime | None = None
        self._pump_last_on: bool = False
        self._last_outdoor_temp: float | None = None
        self._last_pool_temp: float | None = None
        self._outdoor_temp_unavailable: bool = False  # True when primary sensor is unavailable
        self.action_log: deque[ActionLogEntry] = deque(maxlen=5)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot, primary_unavailable, used_fallback = self._collect_snapshot()
            self._update_runtime(snapshot)
            await self._handle_temp_sensor_availability(primary_unavailable, used_fallback)
            return snapshot
        except Exception as err:  # pragma: no cover - HA logs details
            raise UpdateFailed(f"Smart Pool update failed: {err}") from err

    async def _handle_temp_sensor_availability(self, primary_unavailable: bool, used_fallback: bool) -> None:
        """Send a notification when outdoor temp sensor availability changes."""
        notify_service = self.config.get(CONF_NOTIFY_SERVICE, "").strip()
        if primary_unavailable and not self._outdoor_temp_unavailable:
            # Transition: became unavailable
            self._outdoor_temp_unavailable = True
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
            msg = "Smart Pool: outdoor temperature sensor is back online."
            _LOGGER.info(msg)
            if notify_service:
                await self._async_notify(notify_service, "Smart Pool", msg)

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
        """Return (snapshot, primary_outdoor_unavailable, used_fallback)."""
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

        return (
            {
                "outdoor_temp": self._last_outdoor_temp,
                "pool_temp": self._last_pool_temp,
                "pump_on": pump_on,
            },
            primary_unavailable,
            used_fallback,
        )

    def _update_runtime(self, snapshot: dict[str, Any]) -> None:
        now = datetime.now()
        if self.last_tick is None:
            self.last_tick = now
            self._pump_last_on = bool(snapshot.get("pump_on", False))
            return

        delta_minutes = (now - self.last_tick).total_seconds() / 60.0
        if self._pump_last_on:
            self.actual_runtime_minutes += max(delta_minutes, 0.0)

        if now.date() != self.last_tick.date():
            self.actual_runtime_minutes = 0.0

        self.last_tick = now
        self._pump_last_on = bool(snapshot.get("pump_on", False))

    def add_action_log(self, action: str, field: str, before: str, after: str, applied: bool) -> None:
        self.action_log.appendleft(
            ActionLogEntry(
                at=datetime.now().isoformat(timespec="seconds"),
                action=action,
                field=field,
                before=str(before),
                after=str(after),
                applied=applied,
            )
        )

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
