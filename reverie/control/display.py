"""Resolve the current user's display for a headed browser launch."""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

PROC_ROOT = Path("/proc")
X11_SOCKET_ROOT = Path("/tmp/.X11-unix")
_DISPLAY = re.compile(r"^:\d+(?:\.\d+)?$")
_X11_DISPLAY = re.compile(r"^(?:(?:[A-Za-z0-9_.-]+(?:/unix)?|unix/)?)?:\d+(?:\.\d+)?$")


def _readable_file(path):
    return bool(path) and Path(path).is_file() and os.access(path, os.R_OK)


def _run(args, env):
    try:
        result = subprocess.run(args, env=env, capture_output=True, timeout=2, check=False, text=True)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _servers(env):
    """Read command lines only for same-UID Xwayland and Xorg processes."""
    servers = []
    uid = os.getuid()
    for name in ("Xwayland", "Xorg"):
        for pid in _run(["pgrep", "-u", str(uid), "-x", name], env).splitlines():
            if not pid.isdecimal():
                continue
            proc = PROC_ROOT / pid
            try:
                if proc.stat().st_uid != uid:
                    continue
                args = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")
            except OSError:
                continue
            # Recheck the executable name as well as the UID after pgrep.
            if not args or Path(args[0]).name != name:
                continue
            display = next((arg for arg in args[1:] if _DISPLAY.fullmatch(arg)), None)
            auth = None
            if "-auth" in args:
                index = args.index("-auth")
                if index + 1 < len(args):
                    auth = args[index + 1]
            if display:
                servers.append((display, auth))
    return servers


def _systemd_env(env):
    result = {}
    for line in _run(["systemctl", "--user", "show-environment"], env).splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY"}:
            result[key] = value
    return result


def _socket(path):
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def _fallback(env):
    runtime = Path(env["XDG_RUNTIME_DIR"]) if env.get("XDG_RUNTIME_DIR") else None
    if not runtime:
        return None
    try:
        if runtime.stat().st_uid != os.getuid():
            return None
        auth_files = sorted(runtime.glob("xauth*"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    if not shutil.which("xauth", path=env.get("PATH")):
        return None
    for auth in auth_files:
        if not _readable_file(str(auth)):
            continue
        entries = _run(["xauth", "-f", str(auth), "list"], env).splitlines()
        try:
            sockets = sorted(X11_SOCKET_ROOT.glob("X*"))
        except OSError:
            return None
        for socket in sockets:
            number = socket.name[1:]
            if number.isdecimal() and _socket(socket) and any(
                line.split() and line.split()[0].endswith(f":{number}") for line in entries
            ):
                return f":{number}", str(auth)
    return None


def _wayland_display(env, systemd):
    """Find a validated same-user Wayland socket in the runtime directory."""
    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime:
        return False
    candidates = [systemd.get("WAYLAND_DISPLAY")]
    try:
        root = Path(runtime).resolve(strict=True)
        if not root.is_dir() or root.stat().st_uid != os.getuid():
            return False
        candidates.extend(socket.name for socket in sorted(root.glob("wayland-*")))
    except OSError:
        return False
    for candidate in candidates:
        if candidate and _explicit_wayland({**env, "WAYLAND_DISPLAY": candidate}):
            env["WAYLAND_DISPLAY"] = candidate
            return True
    return False


def _explicit_wayland(env):
    """Accept only an explicit socket directly inside this user's runtime directory."""
    runtime, display = env.get("XDG_RUNTIME_DIR"), env.get("WAYLAND_DISPLAY")
    if not runtime or not display:
        return False
    try:
        root = Path(runtime).resolve(strict=True)
        if not root.is_dir() or root.stat().st_uid != os.getuid():
            return False
        requested = Path(display)
        socket = requested if requested.is_absolute() else root / requested
        if socket.parent != root or socket.name in {"", ".", ".."}:
            return False
        info = socket.lstat()
        return info.st_uid == os.getuid() and stat.S_ISSOCK(info.st_mode)
    except (OSError, ValueError):
        return False


def resolve_display(environ=None):
    """Return a fresh environment with a usable display, or raise an actionable error."""
    env = dict(os.environ if environ is None else environ)
    if not env.get("XDG_RUNTIME_DIR"):
        runtime = Path(f"/run/user/{os.getuid()}")
        try:
            if runtime.is_dir() and runtime.stat().st_uid == os.getuid():
                env["XDG_RUNTIME_DIR"] = str(runtime)
        except OSError:
            pass
    servers = _servers(env)
    systemd = _systemd_env(env)

    def select(display, auth):
        if not display:
            return False
        # The server's current auth path corrects stale inherited or systemd values.
        local = display.removeprefix("unix/")
        local_display = local.split(".", 1)[0]
        matching = next(((d, a) for d, a in servers if d.split(".", 1)[0] == local_display), None)
        if _DISPLAY.fullmatch(local) and not matching:
            number = local[1:].split(".", 1)[0]
            if not _socket(X11_SOCKET_ROOT / f"X{number}"):
                return False
        if matching and matching[1]:
            auth = matching[1]
        if auth and not _readable_file(auth):
            return False
        env["DISPLAY"] = display
        if auth:
            env["XAUTHORITY"] = auth
        else:
            env.pop("XAUTHORITY", None)
        return True

    override = env.get("REVERIE_DISPLAY", "").strip()
    if override:
        if not _X11_DISPLAY.fullmatch(override):
            raise RuntimeError("REVERIE_DISPLAY must be a valid X11 display, such as :0.")
        if select(override, env.get("XAUTHORITY")):
            return env
        raise RuntimeError("REVERIE_DISPLAY cannot be used: no matching active X server or readable XAUTHORITY.")
    if select(env.get("DISPLAY"), env.get("XAUTHORITY")):
        return env
    if _explicit_wayland(env):
        env.pop("DISPLAY", None)
        env.pop("XAUTHORITY", None)
        return env

    if select(systemd.get("DISPLAY"), systemd.get("XAUTHORITY")):
        return env
    for display, auth in servers:
        if select(display, auth):
            return env
    fallback = _fallback(env)
    if fallback and select(*fallback):
        return env
    if _wayland_display(env, systemd):
        env.pop("DISPLAY", None)
        env.pop("XAUTHORITY", None)
        return env
    raise RuntimeError(
        "No usable display found for headed Chromium. Start a desktop session, set REVERIE_DISPLAY "
        "and XAUTHORITY for X11, or set WAYLAND_DISPLAY to an owned socket in XDG_RUNTIME_DIR."
    )
