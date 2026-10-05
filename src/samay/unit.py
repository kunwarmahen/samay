"""Keeping the clock running: a systemd user unit for ``samay serve``.

A schedule runs only while ``samay serve`` does. Started in a terminal,
it stops when the terminal closes, the laptop restarts, or a Python
error takes it down -- and nothing says so until the person wonders why
the 08:00 check never came. The fix is the machine's own service
manager, which starts it at login and starts it again if it dies.

    samay unit                 print the unit, change nothing
    samay unit --install       write it, and the settings it needs

WHAT THE UNIT CANNOT SEE IS WRITTEN DOWN FOR IT. A service starts with
almost nothing in its environment: not the PATH a ``uv run`` needs, not
``SAMAY_YANTRA`` saying which Yantra to start, not ``SAMAY_DVARA_URL``
saying where answers go. ``--install`` copies every ``SAMAY_*`` and
``YANTRA_*`` setting of the shell it is run from, and its PATH, into an
env file the unit reads. That file can hold tokens, so it is made
readable by its owner alone; the unit itself holds no setting, so it can
be shown and shared.

STARTING IT IS THE PERSON'S CALL. ``--install`` writes two files and
prints the ``systemctl --user`` lines that start it. It runs none of
them: a service that keeps running when you log out (``loginctl
enable-linger``) is a decision about your machine, not a side effect of
a command that writes a file.

Linux with systemd only. Elsewhere, ``samay serve`` under whatever keeps
programs running there does the same job.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

#: The service's name: ``systemctl --user status samay``.
NAME = "samay"
#: Which settings a service would otherwise not have.
PREFIXES = ("SAMAY_", "YANTRA_")


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def unit_path() -> Path:
    return config_home() / "systemd" / "user" / f"{NAME}.service"


def env_path() -> Path:
    return config_home() / "samay" / "samay.env"


def unit_text(command: str, state: Path, port: int) -> str:
    """The unit: how to start the clock, where its settings are, and to
    start it again when it stops for any reason but being stopped."""
    start = " ".join(shlex.quote(part) for part in
                     [command, "--state", str(state), "serve", "--port", str(port)])
    return f"""[Unit]
Description=Samay -- runs your agent's schedules on time

[Service]
Type=simple
EnvironmentFile=-{env_path()}
ExecStart={start}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def env_text(environ: dict[str, str]) -> str:
    """The settings the service needs, from the shell this is run in."""
    keep = {k: v for k, v in environ.items() if k.startswith(PREFIXES)}
    if environ.get("PATH"):
        keep["PATH"] = environ["PATH"]
    lines = ["# Written by `samay unit --install` from the shell it ran in.",
             "# Readable by you alone: it may hold tokens."]
    lines += [f"{key}={_quote(value)}" for key, value in sorted(keep.items())]
    return "\n".join(lines) + "\n"


def _quote(value: str) -> str:
    """systemd's own quoting: double quotes, backslash and quote escaped."""
    if value and all(c.isalnum() or c in "/._-:,@+=" for c in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def install(command: str, state: Path, port: int,
            environ: dict[str, str]) -> tuple[Path, Path, list[str]]:
    """Write the unit and its env file. Returns both paths and the
    setting names copied (never their values: they may be tokens)."""
    unit, env = unit_path(), env_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    env.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(command, state, port))
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(env_text(environ))
    os.chmod(env, 0o600)                 # an existing file keeps its old mode otherwise
    names = sorted(k for k in environ if k.startswith(PREFIXES))
    return unit, env, names


NEXT = ["systemctl --user daemon-reload",
        f"systemctl --user enable --now {NAME}",
        f"systemctl --user status {NAME}            # is it running",
        f"journalctl --user -u {NAME} -f            # what it says",
        "loginctl enable-linger $USER     # optional: keep running when you log out"]
