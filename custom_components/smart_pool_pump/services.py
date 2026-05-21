"""Service handlers for Smart Pool."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DATA_COORDINATOR, DATA_SCHEDULER, DOMAIN, MODE_SUMMER, MODE_WINTER

SERVICE_SET_SEASON = "set_season_mode"
SERVICE_RECALCULATE = "recalculate_now"
SERVICE_RUN_NOW = "run_now"


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Smart Pool services."""

    async def _set_season(call: ServiceCall) -> None:
        payload = hass.data.get(DOMAIN, {})
        coordinator = payload.get(DATA_COORDINATOR)
        if coordinator is None:
            return
        coordinator.season_mode = call.data["season"]

    async def _recalculate(call: ServiceCall) -> None:
        payload = hass.data.get(DOMAIN, {})
        scheduler = payload.get(DATA_SCHEDULER)
        if scheduler is None:
            return
        scheduler.coordinator.last_schedule_day = None

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SEASON):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_SEASON,
            _set_season,
            schema=vol.Schema({vol.Required("season"): vol.In([MODE_WINTER, MODE_SUMMER])}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RECALCULATE):
        hass.services.async_register(DOMAIN, SERVICE_RECALCULATE, _recalculate)

    async def _run_now(call: ServiceCall) -> None:
        payload = hass.data.get(DOMAIN, {})
        scheduler = payload.get(DATA_SCHEDULER)
        if scheduler is None:
            return
        await scheduler.async_run_now(allow_writes=True)

    if not hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        hass.services.async_register(DOMAIN, SERVICE_RUN_NOW, _run_now)


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Smart Pool services."""
    for service in (SERVICE_SET_SEASON, SERVICE_RECALCULATE, SERVICE_RUN_NOW):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
