"""Config flow for Smart Pool."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_EXTREME_FREEZE_TEMP_C,
    CONF_FREEZE_TEMP_C,
    CONF_NOTIFY_SERVICE,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POOL_TEMP_SENSOR,
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
    CONF_SLOT1_START,
    CONF_SLOT2_END,
    CONF_SLOT2_START,
    CONF_SLOT3_END,
    CONF_SLOT3_START,
    CONF_TEST_MODE,
    CONF_UPDATE_INTERVAL_MIN,
    CONF_WINTER_MIN_RUNTIME_MIN,
    DEFAULT_EXTREME_FREEZE_TEMP_C,
    DEFAULT_FREEZE_TEMP_C,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_PUMP_MODE_AUTO_VALUE,
    DEFAULT_PUMP_MODE_HEAT_VALUE,
    DEFAULT_PUMP_MODE_MANUAL_VALUE,
    DEFAULT_PUMP_SPEED_HIGH_VALUE,
    DEFAULT_PUMP_SPEED_LOW_VALUE,
    DEFAULT_PUMP_SPEED_MEDIUM_VALUE,
    DEFAULT_TEST_MODE,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DEFAULT_WINTER_MIN_RUNTIME_MIN,
    DOMAIN,
)

STEP_ENTITIES = "entities"
STEP_SETTINGS = "settings"
STEP_MODES = "modes"


def _entity_selector(domain: str | list[str], device_class: str | None = None) -> selector.EntitySelector:
    cfg: dict = {"domain": domain}
    if device_class:
        cfg["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


class SmartPoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Smart Pool config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        return await self.async_step_entities(user_input)

    async def async_step_entities(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings()

        schema = vol.Schema(
            {
                vol.Required(CONF_PUMP_SWITCH): _entity_selector("switch"),
                vol.Required(CONF_PUMP_MODE_SELECT): _entity_selector("select"),
                vol.Required(CONF_PUMP_SPEED_SELECT): _entity_selector("select"),
                vol.Required(CONF_OUTDOOR_TEMP_SENSOR): _entity_selector("sensor", "temperature"),
                vol.Required(CONF_POOL_TEMP_SENSOR): _entity_selector("sensor", "temperature"),
                vol.Required(CONF_SLOT1_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT1_END): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_END): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_END): _entity_selector(["time", "input_datetime"]),
            }
        )
        return self.async_show_form(step_id=STEP_ENTITIES, data_schema=schema)

    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_modes()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WINTER_MIN_RUNTIME_MIN,
                    default=DEFAULT_WINTER_MIN_RUNTIME_MIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(
                    CONF_FREEZE_TEMP_C,
                    default=DEFAULT_FREEZE_TEMP_C,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-20, max=15, step=0.5, unit_of_measurement="degC")
                ),
                vol.Required(
                    CONF_EXTREME_FREEZE_TEMP_C,
                    default=DEFAULT_EXTREME_FREEZE_TEMP_C,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-30, max=5, step=0.5, unit_of_measurement="degC")
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL_MIN,
                    default=DEFAULT_UPDATE_INTERVAL_MIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min")
                ),
                vol.Required(CONF_TEST_MODE, default=DEFAULT_TEST_MODE): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFY_SERVICE, default=DEFAULT_NOTIFY_SERVICE): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id=STEP_SETTINGS, data_schema=schema)

    async def async_step_modes(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Smart Pool", data=self._data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PUMP_MODE_HEAT_VALUE,
                    default=DEFAULT_PUMP_MODE_HEAT_VALUE,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PUMP_MODE_AUTO_VALUE,
                    default=DEFAULT_PUMP_MODE_AUTO_VALUE,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PUMP_MODE_MANUAL_VALUE,
                    default=DEFAULT_PUMP_MODE_MANUAL_VALUE,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PUMP_SPEED_LOW_VALUE,
                    default=DEFAULT_PUMP_SPEED_LOW_VALUE,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PUMP_SPEED_MEDIUM_VALUE,
                    default=DEFAULT_PUMP_SPEED_MEDIUM_VALUE,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PUMP_SPEED_HIGH_VALUE,
                    default=DEFAULT_PUMP_SPEED_HIGH_VALUE,
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id=STEP_MODES, data_schema=schema)
