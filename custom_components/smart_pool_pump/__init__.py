"""Smart Pool integration setup."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DATA_SCHEDULER, DOMAIN, PLATFORMS, CONF_UPDATE_INTERVAL_MIN
from .coordinator import SmartPoolCoordinator
from .scheduler import SmartPoolScheduler
from .services import async_register_services, async_unregister_services


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Pool from config entry."""
    hass.data.setdefault(DOMAIN, {})

    interval = timedelta(minutes=int(entry.data.get(CONF_UPDATE_INTERVAL_MIN, 5)))
    coordinator = SmartPoolCoordinator(hass, entry, interval)
    await coordinator.async_config_entry_first_refresh()

    scheduler = SmartPoolScheduler(hass, entry, coordinator)

    hass.data[DOMAIN][DATA_COORDINATOR] = coordinator
    hass.data[DOMAIN][DATA_SCHEDULER] = scheduler

    # Do one immediate evaluation so sensors are populated right after startup.
    await scheduler.async_run_now(force_schedule=True)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (reconfigure) are saved."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Smart Pool config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    payload = hass.data.get(DOMAIN, {})
    scheduler = payload.get(DATA_SCHEDULER)
    if scheduler:
        await scheduler.async_shutdown()

    payload.pop(DATA_COORDINATOR, None)
    payload.pop(DATA_SCHEDULER, None)

    await async_unregister_services(hass)
    return True
