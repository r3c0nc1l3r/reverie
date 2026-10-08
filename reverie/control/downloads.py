"""Where a session's browser saves downloads. Never the user's own ~/Downloads unless asked for by path."""

import json
import os
from pathlib import Path

ENV_VAR = "REVERIE_DOWNLOAD_DIR"
DEFAULT_NAME = "downloads"


def resolve(option=None, environ=None):
    """The configured download dir: the --download-dir option, else REVERIE_DOWNLOAD_DIR, else None."""
    environ = os.environ if environ is None else environ
    for value in (option, environ.get(ENV_VAR)):
        if value and str(value).strip():
            return Path(str(value).strip()).expanduser().resolve()
    return None


def default_for(trail_dir):
    """The default: a downloads/ folder inside the session's run (trail) directory."""
    return Path(trail_dir) / DEFAULT_NAME


def write_profile_preferences(profile_dir, download_dir):
    """Set Chromium's download.default_directory in the profile, so persistent profiles do not keep an old one."""
    default = Path(profile_dir) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    path = default / "Preferences"
    try:
        prefs = json.loads(path.read_text())
    except (OSError, ValueError):
        prefs = {}
    prefs.setdefault("download", {}).update(
        {"default_directory": str(download_dir), "prompt_for_download": False})
    prefs.setdefault("savefile", {})["default_directory"] = str(download_dir)
    path.write_text(json.dumps(prefs))
