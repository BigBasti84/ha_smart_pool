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
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POOL_TEMP_SENSOR,
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
        self.action_log: deque[ActionLogEntry] = deque(maxlen=5)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot = self._collect_snapshot()
            self._update_runtime(snapshot)
            return snapshot
        except Exception as err:  # pragma: no cover - HA logs details
            raise UpdateFailed(f"Smart Pool update failed: {err}") from err

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
            return float(val)
        except (TypeError, ValueError):
            return fallback

    def _collect_snapshot(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "outdoor_temp": self._float_state(cfg.get(CONF_OUTDOOR_TEMP_SENSOR, ""), 0.0),
            "pool_temp": self._float_state(cfg.get(CONF_POOL_TEMP_SENSOR, ""), 0.0),
            "pump_on": self._state(cfg.get(CONF_PUMP_SWITCH, ""), "off") == "on",
        }

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
