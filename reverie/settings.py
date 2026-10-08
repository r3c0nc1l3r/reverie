"""Reverie's own settings, named by role under REVERIE_*. The old LAYA_AGENT_* names still work as aliases.

The new name wins when both are set. Settings of the Laya backend itself (LAYA_BACKEND, LAYA_BASE_URL,
LAYA_HTTP_TIMEOUT, LAYA_TLS_CA) and of the model endpoints (TEXT_MODEL_*) keep their names.
"""

import os

# New name -> old name.
RENAMED = {
    "REVERIE_DECISION_ENGINE": "LAYA_AGENT_ENGINE",
    "REVERIE_DECISION_MIN_CONFIDENCE": "LAYA_AGENT_LAYA_MIN",
    "REVERIE_ESCALATION": "LAYA_AGENT_MERCURY",
    "REVERIE_SESSION": "LAYA_AGENT_SESSION",
    "REVERIE_BROWSER": "LAYA_AGENT_BROWSER",
    "REVERIE_VIEWPORT": "LAYA_AGENT_VIEWPORT",
    "REVERIE_DIALOGS": "LAYA_AGENT_DIALOGS",
    "REVERIE_STEP_CEILING": "LAYA_AGENT_STEP_CEILING",
    "REVERIE_STALL_SECONDS": "LAYA_AGENT_STALL_SECONDS",
    "REVERIE_PLAYBOOK": "LAYA_AGENT_PLAYBOOK",
    "REVERIE_PILOT_MODEL": "LAYA_AGENT_PILOT_MODEL",
    "REVERIE_PILOT_PROVIDER": "LAYA_AGENT_PILOT_PROVIDER",
    "REVERIE_PILOT_BASE_URL": "LAYA_AGENT_PILOT_BASE_URL",
    "REVERIE_PILOT_API_KEY": "LAYA_AGENT_PILOT_API_KEY",
    "REVERIE_PILOT_VISION": "LAYA_AGENT_PILOT_VISION",
    "REVERIE_PILOT_STUCK": "LAYA_AGENT_PILOT_STUCK",
    "REVERIE_UI_REVIEW": "LAYA_AGENT_UI_REVIEW",
    "REVERIE_UI_PORT": "LAYA_AGENT_UI_PORT",
    "REVERIE_NARRATION": "LAYA_AGENT_NARRATION",
    "REVERIE_SPEECH_RATE": "LAYA_AGENT_SPEECH_RATE",
    "REVERIE_BLUETOOTH_AUDIO": "LAYA_AGENT_BLUETOOTH_AUDIO",
    "REVERIE_AUDIO_WAKE": "LAYA_AGENT_AUDIO_WAKE",
    "REVERIE_AUDIO_WAKE_IDLE": "LAYA_AGENT_AUDIO_WAKE_IDLE",
}
OLD_TO_NEW = {old: new for new, old in RENAMED.items()}


def setting(name, default=None):
    """The value of a REVERIE_* setting, else its old LAYA_AGENT_* alias, else `default`. Empty counts as unset."""
    for key in (name, RENAMED.get(name)):
        value = os.environ.get(key) if key else None
        if value not in (None, ""):
            return value
    return default


def is_on(name, default):
    return str(setting(name, default)).strip().lower() in {"1", "true", "on", "yes"}


def is_off(name, default):
    return str(setting(name, default)).strip().lower() in {"0", "false", "off", "no"}


def current_name(key):
    """The REVERIE_* name for a key given by either name (for whitelists that accept both)."""
    return OLD_TO_NEW.get(key, key)
