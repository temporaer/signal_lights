DOMAIN = "signal_lights"
DATA_MANAGER = "manager"

SERVICE_PUSH_SIGNAL = "push_signal"
SERVICE_CLEAR_SIGNAL = "clear_signal"
SERVICE_REFRESH_ON_LIGHTS = "refresh_on_lights"
SERVICE_DUMP_STATE = "dump_state"
SERVICE_TEST_SIGNAL = "test_signal"

EVENT_SIGNAL_PUSHED = "signal_lights_signal_pushed"
EVENT_SIGNAL_CLEARED = "signal_lights_signal_cleared"
EVENT_SIGNAL_RENDERED = "signal_lights_signal_rendered"
EVENT_SIGNAL_SKIPPED = "signal_lights_signal_skipped"

CONF_RENDERERS = "renderers"
CONF_LIGHTS = "lights"
CONF_BASELINE = "baseline"
CONF_TIME_WINDOW = "time_window"
CONF_LAMP_PROFILES = "lamp_profiles"
CONF_SIGNAL_RULES = "signal_rules"
CONF_NIGHT_MODE_ENTITY = "night_mode_entity"

DEFAULT_NIGHT_MODE_ENTITY = "input_boolean.night_mode"
DEFAULT_PRIORITY = 50
DEFAULT_COLOR = [0, 255, 0]
DEFAULT_DURATION = 3

