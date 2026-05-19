"""Constants for Smart Pool."""

from __future__ import annotations

DOMAIN = "smart_pool_pump"

PLATFORMS = ["sensor", "binary_sensor", "select"]

MODE_SUMMER = "summer"
MODE_WINTER = "winter"
SEASON_OPTIONS = [MODE_WINTER, MODE_SUMMER]

WINTER_STATE_NORMAL = "normal"
WINTER_STATE_FREEZE = "freeze"
WINTER_STATE_EXTREME = "extreme_freeze"

# Core entities
CONF_PUMP_SWITCH = "pump_switch_entity"
CONF_PUMP_MODE_SELECT = "pump_mode_select_entity"
CONF_PUMP_SPEED_SELECT = "pump_speed_select_entity"
CONF_PUMP_RUNNING_SENSOR = "pump_running_sensor_entity"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor_entity"
CONF_POOL_TEMP_SENSOR = "pool_temp_sensor_entity"

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

CONF_SLOT1_SPEED_LEVEL = "slot1_speed_level"
CONF_SLOT2_SPEED_LEVEL = "slot2_speed_level"
CONF_SLOT3_SPEED_LEVEL = "slot3_speed_level"

SPEED_LEVEL_LOW = "low"
SPEED_LEVEL_MEDIUM = "medium"
SPEED_LEVEL_HIGH = "high"
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
CONF_UPDATE_INTERVAL_MIN = "update_interval_minutes"
CONF_TEST_MODE = "test_mode"
CONF_NOTIFY_SERVICE = "notify_service"

DEFAULT_WINTER_MIN_RUNTIME_MIN = 240
DEFAULT_FREEZE_TEMP_C = 2.0
DEFAULT_EXTREME_FREEZE_TEMP_C = -10.0
DEFAULT_UPDATE_INTERVAL_MIN = 5
DEFAULT_TEST_MODE = True
DEFAULT_NOTIFY_SERVICE = ""

DEFAULT_PUMP_MODE_HEAT_VALUE = "Heat"
DEFAULT_PUMP_MODE_AUTO_VALUE = "Auto"
DEFAULT_PUMP_MODE_MANUAL_VALUE = "Manual"
DEFAULT_PUMP_SPEED_LOW_VALUE = "low"
DEFAULT_PUMP_SPEED_MEDIUM_VALUE = "medium"
DEFAULT_PUMP_SPEED_HIGH_VALUE = "high"

DEFAULT_SLOT1_SPEED_LEVEL = SPEED_LEVEL_LOW
DEFAULT_SLOT2_SPEED_LEVEL = SPEED_LEVEL_MEDIUM
DEFAULT_SLOT3_SPEED_LEVEL = SPEED_LEVEL_LOW

DEFAULT_SEASON_MODE = MODE_WINTER

# Runtime storage keys in hass.data
DATA_COORDINATOR = "coordinator"
DATA_SCHEDULER = "scheduler"
