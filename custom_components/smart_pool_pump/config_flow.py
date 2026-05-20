"""Config flow for Smart Pool."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_EXTREME_FREEZE_TEMP_C,
    CONF_FREEZE_TEMP_C,
    CONF_NOTIFY_SERVICE,
    CONF_OUTDOOR_TEMP_FALLBACK_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POOL_TEMP_SENSOR,
    CONF_PUMP_RUNNING_SENSOR,
    CONF_PUMP_MODE_AUTO_VALUE,
    CONF_PUMP_MODE_HEAT_VALUE,
    CONF_PUMP_MODE_MANUAL_VALUE,
    CONF_PUMP_MODE_SELECT,
    CONF_PUMP_SPEED_HIGH_VALUE,
    CONF_PUMP_SPEED_LOW_VALUE,
    CONF_PUMP_SPEED_MEDIUM_VALUE,
    CONF_PUMP_SPEED_SELECT,
    CONF_SOLAR_EXCESS_SENSOR,
    CONF_BACKWASH_SENSOR,
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
    CONF_SUMMER_BATHER_LOAD_FACTOR,
    CONF_SUMMER_COVER_REDUCTION_PCT,
    CONF_SUMMER_HEAT_HYSTERESIS_C,
    CONF_SUMMER_HEAT_TARGET_TEMP_C,
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
    DEFAULT_SUMMER_BATHER_LOAD_FACTOR,
    DEFAULT_SUMMER_COVER_REDUCTION_PCT,
    DEFAULT_SUMMER_HEAT_HYSTERESIS_C,
    DEFAULT_SUMMER_HEAT_TARGET_TEMP_C,
    DEFAULT_SUMMER_MANDATORY_1_END,
    DEFAULT_SUMMER_MANDATORY_1_START,
    DEFAULT_SUMMER_MANDATORY_2_END,
    DEFAULT_SUMMER_MANDATORY_2_START,
    DEFAULT_SUMMER_MAX_RUNTIME_MIN,
    DEFAULT_SUMMER_MIN_RUNTIME_MIN,
    DEFAULT_SUMMER_POOL_VOLUME_M3,
    DEFAULT_SUMMER_PUMP_FLOW_M3H,
    DEFAULT_EXTREME_FREEZE_TEMP_C,
    DEFAULT_FREEZE_TEMP_C,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_PUMP_MODE_AUTO_VALUE,
    DEFAULT_PUMP_MODE_HEAT_VALUE,
    DEFAULT_PUMP_MODE_MANUAL_VALUE,
    DEFAULT_PUMP_SPEED_HIGH_VALUE,
    DEFAULT_PUMP_SPEED_LOW_VALUE,
    DEFAULT_PUMP_SPEED_MEDIUM_VALUE,
    DEFAULT_SLOT1_SPEED_LEVEL,
    DEFAULT_SLOT2_SPEED_LEVEL,
    DEFAULT_SLOT3_SPEED_LEVEL,
    DEFAULT_TEST_MODE,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DEFAULT_VOLUME_HYSTERESIS_M3,
    DEFAULT_WINTER_MIN_RUNTIME_MIN,
    DOMAIN,
    SPEED_LEVEL_OPTIONS,
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

    @staticmethod
    def async_get_options_flow(config_entry):
        return SmartPoolOptionsFlow(config_entry)

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
                vol.Optional(CONF_PUMP_RUNNING_SENSOR): _entity_selector(["binary_sensor", "sensor", "switch"]),
                vol.Required(CONF_OUTDOOR_TEMP_SENSOR): _entity_selector("sensor", "temperature"),
                vol.Optional(CONF_OUTDOOR_TEMP_FALLBACK_SENSOR): _entity_selector("sensor", "temperature"),
                vol.Required(CONF_POOL_TEMP_SENSOR): _entity_selector("sensor", "temperature"),
                vol.Optional(CONF_SOLAR_EXCESS_SENSOR): _entity_selector(["binary_sensor", "sensor", "switch"]),
                vol.Optional(CONF_BACKWASH_SENSOR): _entity_selector("binary_sensor"),
                vol.Required(CONF_SLOT1_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT1_END): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_END): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_START): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_END): _entity_selector(["time", "input_datetime"]),
                vol.Optional(CONF_SLOT1_SPEED_SELECT): _entity_selector("select"),
                vol.Optional(CONF_SLOT2_SPEED_SELECT): _entity_selector("select"),
                vol.Optional(CONF_SLOT3_SPEED_SELECT): _entity_selector("select"),
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
                    CONF_SUMMER_POOL_VOLUME_M3,
                    default=DEFAULT_SUMMER_POOL_VOLUME_M3,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=500, step=0.5, unit_of_measurement="m3")
                ),
                vol.Required(
                    CONF_SUMMER_PUMP_FLOW_M3H,
                    default=DEFAULT_SUMMER_PUMP_FLOW_M3H,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=80, step=0.5, unit_of_measurement="m3/h")
                ),
                vol.Required(
                    CONF_SUMMER_COVER_REDUCTION_PCT,
                    default=DEFAULT_SUMMER_COVER_REDUCTION_PCT,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="%")
                ),
                vol.Required(
                    CONF_SUMMER_BATHER_LOAD_FACTOR,
                    default=DEFAULT_SUMMER_BATHER_LOAD_FACTOR,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.6, max=2.5, step=0.1)
                ),
                vol.Required(
                    CONF_SUMMER_MIN_RUNTIME_MIN,
                    default=DEFAULT_SUMMER_MIN_RUNTIME_MIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(
                    CONF_SUMMER_MAX_RUNTIME_MIN,
                    default=DEFAULT_SUMMER_MAX_RUNTIME_MIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=60, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(
                    CONF_SUMMER_HEAT_TARGET_TEMP_C,
                    default=DEFAULT_SUMMER_HEAT_TARGET_TEMP_C,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=40, step=0.1, unit_of_measurement="degC")
                ),
                vol.Required(
                    CONF_SUMMER_HEAT_HYSTERESIS_C,
                    default=DEFAULT_SUMMER_HEAT_HYSTERESIS_C,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=3.0, step=0.1, unit_of_measurement="degC")
                ),
                vol.Optional(
                    CONF_VOLUME_HYSTERESIS_M3,
                    default=DEFAULT_VOLUME_HYSTERESIS_M3,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10.0, step=0.1, unit_of_measurement="m3")
                ),
                vol.Optional(
                    CONF_SUMMER_MANDATORY_1_START,
                    default=DEFAULT_SUMMER_MANDATORY_1_START,
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_SUMMER_MANDATORY_1_END,
                    default=DEFAULT_SUMMER_MANDATORY_1_END,
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_SUMMER_MANDATORY_2_START,
                    default=DEFAULT_SUMMER_MANDATORY_2_START,
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_SUMMER_MANDATORY_2_END,
                    default=DEFAULT_SUMMER_MANDATORY_2_END,
                ): selector.TextSelector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL_MIN,
                    default=DEFAULT_UPDATE_INTERVAL_MIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min")
                ),
                vol.Required(
                    CONF_SLOT1_SPEED_LEVEL,
                    default=DEFAULT_SLOT1_SPEED_LEVEL,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(
                    CONF_SLOT2_SPEED_LEVEL,
                    default=DEFAULT_SLOT2_SPEED_LEVEL,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(
                    CONF_SLOT3_SPEED_LEVEL,
                    default=DEFAULT_SLOT3_SPEED_LEVEL,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
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


class SmartPoolOptionsFlow(config_entries.OptionsFlow):
    """Allow reconfiguring a Smart Pool entry after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict = {}

    async def async_step_init(self, user_input=None):
        return await self.async_step_entities(user_input)

    async def async_step_entities(self, user_input=None):
        d = self._entry.data
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings()

        schema = vol.Schema(
            {
                vol.Required(CONF_PUMP_SWITCH, default=d.get(CONF_PUMP_SWITCH, "")): _entity_selector("switch"),
                vol.Required(CONF_PUMP_MODE_SELECT, default=d.get(CONF_PUMP_MODE_SELECT, "")): _entity_selector("select"),
                vol.Required(CONF_PUMP_SPEED_SELECT, default=d.get(CONF_PUMP_SPEED_SELECT, "")): _entity_selector("select"),
                vol.Optional(CONF_PUMP_RUNNING_SENSOR, description={"suggested_value": d.get(CONF_PUMP_RUNNING_SENSOR)}): _entity_selector(["binary_sensor", "sensor", "switch"]),
                vol.Required(CONF_OUTDOOR_TEMP_SENSOR, default=d.get(CONF_OUTDOOR_TEMP_SENSOR, "")): _entity_selector("sensor", "temperature"),
                vol.Optional(CONF_OUTDOOR_TEMP_FALLBACK_SENSOR, description={"suggested_value": d.get(CONF_OUTDOOR_TEMP_FALLBACK_SENSOR)}): _entity_selector("sensor", "temperature"),
                vol.Required(CONF_POOL_TEMP_SENSOR, default=d.get(CONF_POOL_TEMP_SENSOR, "")): _entity_selector("sensor", "temperature"),
                vol.Optional(CONF_SOLAR_EXCESS_SENSOR, description={"suggested_value": d.get(CONF_SOLAR_EXCESS_SENSOR)}): _entity_selector(["binary_sensor", "sensor", "switch"]),
                vol.Optional(CONF_BACKWASH_SENSOR, description={"suggested_value": d.get(CONF_BACKWASH_SENSOR)}): _entity_selector("binary_sensor"),
                vol.Required(CONF_SLOT1_START, default=d.get(CONF_SLOT1_START, "")): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT1_END, default=d.get(CONF_SLOT1_END, "")): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_START, default=d.get(CONF_SLOT2_START, "")): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT2_END, default=d.get(CONF_SLOT2_END, "")): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_START, default=d.get(CONF_SLOT3_START, "")): _entity_selector(["time", "input_datetime"]),
                vol.Required(CONF_SLOT3_END, default=d.get(CONF_SLOT3_END, "")): _entity_selector(["time", "input_datetime"]),
                vol.Optional(CONF_SLOT1_SPEED_SELECT, description={"suggested_value": d.get(CONF_SLOT1_SPEED_SELECT)}): _entity_selector("select"),
                vol.Optional(CONF_SLOT2_SPEED_SELECT, description={"suggested_value": d.get(CONF_SLOT2_SPEED_SELECT)}): _entity_selector("select"),
                vol.Optional(CONF_SLOT3_SPEED_SELECT, description={"suggested_value": d.get(CONF_SLOT3_SPEED_SELECT)}): _entity_selector("select"),
            }
        )
        return self.async_show_form(step_id=STEP_ENTITIES, data_schema=schema)

    async def async_step_settings(self, user_input=None):
        d = self._entry.data
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_modes()

        schema = vol.Schema(
            {
                vol.Required(CONF_WINTER_MIN_RUNTIME_MIN, default=d.get(CONF_WINTER_MIN_RUNTIME_MIN, DEFAULT_WINTER_MIN_RUNTIME_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(CONF_FREEZE_TEMP_C, default=d.get(CONF_FREEZE_TEMP_C, DEFAULT_FREEZE_TEMP_C)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-20, max=15, step=0.5, unit_of_measurement="degC")
                ),
                vol.Required(CONF_EXTREME_FREEZE_TEMP_C, default=d.get(CONF_EXTREME_FREEZE_TEMP_C, DEFAULT_EXTREME_FREEZE_TEMP_C)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-30, max=5, step=0.5, unit_of_measurement="degC")
                ),
                vol.Required(CONF_SUMMER_POOL_VOLUME_M3, default=d.get(CONF_SUMMER_POOL_VOLUME_M3, DEFAULT_SUMMER_POOL_VOLUME_M3)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=500, step=0.5, unit_of_measurement="m3")
                ),
                vol.Required(CONF_SUMMER_PUMP_FLOW_M3H, default=d.get(CONF_SUMMER_PUMP_FLOW_M3H, DEFAULT_SUMMER_PUMP_FLOW_M3H)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=80, step=0.5, unit_of_measurement="m3/h")
                ),
                vol.Required(CONF_SUMMER_COVER_REDUCTION_PCT, default=d.get(CONF_SUMMER_COVER_REDUCTION_PCT, DEFAULT_SUMMER_COVER_REDUCTION_PCT)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="%")
                ),
                vol.Required(CONF_SUMMER_BATHER_LOAD_FACTOR, default=d.get(CONF_SUMMER_BATHER_LOAD_FACTOR, DEFAULT_SUMMER_BATHER_LOAD_FACTOR)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.6, max=2.5, step=0.1)
                ),
                vol.Required(CONF_SUMMER_MIN_RUNTIME_MIN, default=d.get(CONF_SUMMER_MIN_RUNTIME_MIN, DEFAULT_SUMMER_MIN_RUNTIME_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(CONF_SUMMER_MAX_RUNTIME_MIN, default=d.get(CONF_SUMMER_MAX_RUNTIME_MIN, DEFAULT_SUMMER_MAX_RUNTIME_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=60, max=1440, step=5, unit_of_measurement="min")
                ),
                vol.Required(CONF_SUMMER_HEAT_TARGET_TEMP_C, default=d.get(CONF_SUMMER_HEAT_TARGET_TEMP_C, DEFAULT_SUMMER_HEAT_TARGET_TEMP_C)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=40, step=0.1, unit_of_measurement="degC")
                ),
                vol.Required(CONF_SUMMER_HEAT_HYSTERESIS_C, default=d.get(CONF_SUMMER_HEAT_HYSTERESIS_C, DEFAULT_SUMMER_HEAT_HYSTERESIS_C)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=3.0, step=0.1, unit_of_measurement="degC")
                ),
                vol.Optional(CONF_VOLUME_HYSTERESIS_M3, default=d.get(CONF_VOLUME_HYSTERESIS_M3, DEFAULT_VOLUME_HYSTERESIS_M3)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10.0, step=0.1, unit_of_measurement="m3")
                ),
                vol.Optional(CONF_SUMMER_MANDATORY_1_START, description={"suggested_value": d.get(CONF_SUMMER_MANDATORY_1_START, DEFAULT_SUMMER_MANDATORY_1_START)}): selector.TextSelector(),
                vol.Optional(CONF_SUMMER_MANDATORY_1_END, description={"suggested_value": d.get(CONF_SUMMER_MANDATORY_1_END, DEFAULT_SUMMER_MANDATORY_1_END)}): selector.TextSelector(),
                vol.Optional(CONF_SUMMER_MANDATORY_2_START, description={"suggested_value": d.get(CONF_SUMMER_MANDATORY_2_START, DEFAULT_SUMMER_MANDATORY_2_START)}): selector.TextSelector(),
                vol.Optional(CONF_SUMMER_MANDATORY_2_END, description={"suggested_value": d.get(CONF_SUMMER_MANDATORY_2_END, DEFAULT_SUMMER_MANDATORY_2_END)}): selector.TextSelector(),
                vol.Required(CONF_UPDATE_INTERVAL_MIN, default=d.get(CONF_UPDATE_INTERVAL_MIN, DEFAULT_UPDATE_INTERVAL_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min")
                ),
                vol.Required(CONF_SLOT1_SPEED_LEVEL, default=d.get(CONF_SLOT1_SPEED_LEVEL, DEFAULT_SLOT1_SPEED_LEVEL)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_SLOT2_SPEED_LEVEL, default=d.get(CONF_SLOT2_SPEED_LEVEL, DEFAULT_SLOT2_SPEED_LEVEL)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_SLOT3_SPEED_LEVEL, default=d.get(CONF_SLOT3_SPEED_LEVEL, DEFAULT_SLOT3_SPEED_LEVEL)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=SPEED_LEVEL_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_TEST_MODE, default=d.get(CONF_TEST_MODE, DEFAULT_TEST_MODE)): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFY_SERVICE, description={"suggested_value": d.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE)}): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id=STEP_SETTINGS, data_schema=schema)

    async def async_step_modes(self, user_input=None):
        d = self._entry.data
        if user_input is not None:
            self._data.update(user_input)
            # Update entry.data in place so coordinator/scheduler pick up new values on reload.
            self.hass.config_entries.async_update_entry(self._entry, data=self._data)
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_PUMP_MODE_HEAT_VALUE, default=d.get(CONF_PUMP_MODE_HEAT_VALUE, DEFAULT_PUMP_MODE_HEAT_VALUE)): selector.TextSelector(),
                vol.Required(CONF_PUMP_MODE_AUTO_VALUE, default=d.get(CONF_PUMP_MODE_AUTO_VALUE, DEFAULT_PUMP_MODE_AUTO_VALUE)): selector.TextSelector(),
                vol.Required(CONF_PUMP_MODE_MANUAL_VALUE, default=d.get(CONF_PUMP_MODE_MANUAL_VALUE, DEFAULT_PUMP_MODE_MANUAL_VALUE)): selector.TextSelector(),
                vol.Required(CONF_PUMP_SPEED_LOW_VALUE, default=d.get(CONF_PUMP_SPEED_LOW_VALUE, DEFAULT_PUMP_SPEED_LOW_VALUE)): selector.TextSelector(),
                vol.Required(CONF_PUMP_SPEED_MEDIUM_VALUE, default=d.get(CONF_PUMP_SPEED_MEDIUM_VALUE, DEFAULT_PUMP_SPEED_MEDIUM_VALUE)): selector.TextSelector(),
                vol.Required(CONF_PUMP_SPEED_HIGH_VALUE, default=d.get(CONF_PUMP_SPEED_HIGH_VALUE, DEFAULT_PUMP_SPEED_HIGH_VALUE)): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id=STEP_MODES, data_schema=schema)
