"""Constants for Smart Pool."""

from __future__ import annotations

DOMAIN = "smart_pool_pump"

PLATFORMS = ["sensor", "binary_sensor", "select", "button"]

MODE_SUMMER = "summer"
MODE_WINTER = "winter"
SEASON_OPTIONS = [MODE_WINTER, MODE_SUMMER]

SUMMER_HEATING_ON = "on"
SUMMER_HEATING_OFF = "off"
SUMMER_HEATING_OPTIONS = [SUMMER_HEATING_ON, SUMMER_HEATING_OFF]

WINTER_STATE_NORMAL = "normal"
WINTER_STATE_FREEZE = "freeze"
WINTER_STATE_EXTREME = "extreme_freeze"
WINTER_STATE_WAITING_FOR_DATA = "waiting_for_sensors"

# Core entities
CONF_PUMP_SWITCH = "pump_switch_entity"
CONF_PUMP_MODE_SELECT = "pump_mode_select_entity"
CONF_PUMP_SPEED_SELECT = "pump_speed_select_entity"
CONF_PUMP_RUNNING_SENSOR = "pump_running_sensor_entity"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor_entity"
CONF_OUTDOOR_TEMP_FALLBACK_SENSOR = "outdoor_temp_fallback_sensor_entity"
CONF_POOL_TEMP_SENSOR = "pool_temp_sensor_entity"
CONF_SOLAR_EXCESS_SENSOR = "solar_excess_sensor_entity"
CONF_BACKWASH_SENSOR = "backwash_sensor_entity"

# Pump schedule entities (3 slots from/to)
CONF_SLOT1_START = "slot1_start_entity"
CONF_SLOT1_END = "slot1_end_entity"
CONF_SLOT2_START = "slot2_start_entity"
CONF_SLOT2_END = "slot2_end_entity"
CONF_SLOT3_START = "slot3_start_entity"
CONF_SLOT3_END = "slot3_end_entity"
CONF_SLOT1_SPEED_SELECT = "slot1_speed_select_entity"
CONF_SLOT2_SPEED_SELECT = "slot2_speed_select_entity"
CONF_SLOT3_SPEED_SELECT = "slot3_speed_select_entity"

# Single speed level used for all three winter filtration slots (replaces per-slot settings).
CONF_WINTER_FILTRATION_SPEED_LEVEL = "winter_filtration_speed_level"

SPEED_LEVEL_LOW = "Slow"
SPEED_LEVEL_MEDIUM = "Medium"
SPEED_LEVEL_HIGH = "High"
SPEED_LEVEL_OPTIONS = [SPEED_LEVEL_LOW, SPEED_LEVEL_MEDIUM, SPEED_LEVEL_HIGH]

SLOT_ENTITY_KEYS = [
    CONF_SLOT1_START,
    CONF_SLOT1_END,
    CONF_SLOT2_START,
    CONF_SLOT2_END,
    CONF_SLOT3_START,
    CONF_SLOT3_END,
]

# Pump mode and speed option strings in the hardware select entities
CONF_PUMP_MODE_HEAT_VALUE = "pump_mode_heat_value"
CONF_PUMP_MODE_AUTO_VALUE = "pump_mode_auto_value"
CONF_PUMP_MODE_MANUAL_VALUE = "pump_mode_manual_value"
CONF_PUMP_SPEED_LOW_VALUE = "pump_speed_low_value"
CONF_PUMP_SPEED_MEDIUM_VALUE = "pump_speed_medium_value"
CONF_PUMP_SPEED_HIGH_VALUE = "pump_speed_high_value"

# Runtime logic
CONF_WINTER_MIN_RUNTIME_MIN = "winter_min_runtime_minutes"
CONF_FREEZE_TEMP_C = "freeze_temp_c"
CONF_EXTREME_FREEZE_TEMP_C = "extreme_freeze_temp_c"
CONF_SUMMER_POOL_VOLUME_M3 = "summer_pool_volume_m3"
CONF_SUMMER_PUMP_FLOW_M3H = "summer_pump_flow_m3h"
CONF_SUMMER_COVER_REDUCTION_PCT = "summer_cover_reduction_pct"
CONF_SUMMER_BATHER_LOAD_FACTOR = "summer_bather_load_factor"
CONF_SUMMER_MIN_RUNTIME_MIN = "summer_min_runtime_minutes"
CONF_SUMMER_MAX_RUNTIME_MIN = "summer_max_runtime_minutes"
CONF_SUMMER_HEAT_TARGET_TEMP_C = "summer_heat_target_temp_c"
CONF_SUMMER_HEAT_HYSTERESIS_C = "summer_heat_hysteresis_c"
CONF_UPDATE_INTERVAL_MIN = "update_interval_minutes"
CONF_TEST_MODE = "test_mode"
CONF_NOTIFY_SERVICE = "notify_service"

DEFAULT_WINTER_MIN_RUNTIME_MIN = 240
DEFAULT_FREEZE_TEMP_C = 2.0
DEFAULT_EXTREME_FREEZE_TEMP_C = -10.0
DEFAULT_SUMMER_POOL_VOLUME_M3 = 45.0
DEFAULT_SUMMER_PUMP_FLOW_M3H = 12.0
DEFAULT_SUMMER_COVER_REDUCTION_PCT = 20.0
DEFAULT_SUMMER_BATHER_LOAD_FACTOR = 1.0
DEFAULT_SUMMER_MIN_RUNTIME_MIN = 120
DEFAULT_SUMMER_MAX_RUNTIME_MIN = 720
DEFAULT_SUMMER_HEAT_TARGET_TEMP_C = 31.5
DEFAULT_SUMMER_HEAT_HYSTERESIS_C = 0.5
DEFAULT_FREEZE_HYSTERESIS_C = 1.0   # must rise this many °C above a threshold before leaving that state
DEFAULT_UPDATE_INTERVAL_MIN = 5
DEFAULT_TEST_MODE = True
DEFAULT_NOTIFY_SERVICE = ""

DEFAULT_PUMP_MODE_HEAT_VALUE = "Heat"
DEFAULT_PUMP_MODE_AUTO_VALUE = "Auto"
DEFAULT_PUMP_MODE_MANUAL_VALUE = "Manual"
DEFAULT_PUMP_SPEED_LOW_VALUE = "Slow"
DEFAULT_PUMP_SPEED_MEDIUM_VALUE = "Medium"
DEFAULT_PUMP_SPEED_HIGH_VALUE = "High"

DEFAULT_WINTER_FILTRATION_SPEED_LEVEL = SPEED_LEVEL_LOW

DEFAULT_SEASON_MODE = MODE_WINTER

# Physical pump flow rates per speed level (m³/h).
# Heat mode forces Slow hardware regardless of the display value.
FLOW_RATE_HIGH_M3H: float = 8.0
FLOW_RATE_MEDIUM_M3H: float = 4.0
FLOW_RATE_LOW_M3H: float = 2.0
FLOW_RATE_HEAT_M3H: float = 2.0  # Heat mode: Medium displayed, Slow hardware

# Summer volume-based control (v0.3+)
CONF_VOLUME_HYSTERESIS_M3 = "volume_hysteresis_m3"
CONF_SUMMER_MANDATORY_1_START = "summer_mandatory_1_start"
CONF_SUMMER_MANDATORY_1_END = "summer_mandatory_1_end"
CONF_SUMMER_MANDATORY_2_START = "summer_mandatory_2_start"
CONF_SUMMER_MANDATORY_2_END = "summer_mandatory_2_end"

DEFAULT_VOLUME_HYSTERESIS_M3: float = 0.5
DEFAULT_SUMMER_MANDATORY_1_START = "09:00"
DEFAULT_SUMMER_MANDATORY_1_END = "09:30"
DEFAULT_SUMMER_MANDATORY_2_START = "19:00"
DEFAULT_SUMMER_MANDATORY_2_END = "19:30"

CONF_SUMMER_DAY_START_HOUR = "summer_day_start_hour"
CONF_SUMMER_DAY_END_HOUR = "summer_day_end_hour"
DEFAULT_SUMMER_DAY_START_HOUR: int = 8
DEFAULT_SUMMER_DAY_END_HOUR: int = 20

# Runtime storage keys in hass.data
DATA_COORDINATOR = "coordinator"
DATA_SCHEDULER = "scheduler"
