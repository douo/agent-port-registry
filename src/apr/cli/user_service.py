"""Install / manage systemd --user unit for login auto-start."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from apr.config import (
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_PORT_POOL_END,
    DEFAULT_PORT_POOL_START,
    _xdg_config_home,
    load_config,
)

UNIT_NAME = "apr.service"

DEFAULT_CONFIG_YAML = f"""\
# Agent Port Registry — user configuration
# Location: $XDG_CONFIG_HOME/apr/config.yaml  (default: ~/.config/apr/config.yaml)
# See: https://specifications.freedesktop.org/basedir-spec/

# Optional overrides (defaults follow XDG Base Directory Specification):
# data_dir:  ~/.local/share/apr
# state_dir: ~/.local/state/apr

use_unix_socket: true
auto_start: true

# http_host: {DEFAULT_HTTP_HOST}
# http_port: {DEFAULT_HTTP_PORT}

port_pool:
  start: {DEFAULT_PORT_POOL_START}
  end: {DEFAULT_PORT_POOL_END}
  exclude: []
  # exclude examples:
  # - 22000
  # - 25000-25100
"""


def config_dir() -> Path:
    return _xdg_config_home() / "apr"


def config_file() -> Path:
    return config_dir() / "config.yaml"


def systemd_user_dir() -> Path:
    return _xdg_config_home() / "systemd" / "user"


def unit_path() -> Path:
    return systemd_user_dir() / UNIT_NAME


def resolve_svcctl_executable(explicit: Path | None = None) -> Path:
    """Prefer explicit path, then PATH, then current interpreter's scripts dir."""
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"svcctl not found: {p}")
        return p

    which = shutil.which("svcctl")
    if which:
        return Path(which).resolve()

    # Same environment as `python -m apr` / uv run
    scripts = Path(sys.executable).resolve().parent
    candidate = scripts / "svcctl"
    if candidate.is_file():
        return candidate

    # Fallback: python -m apr (always works if package installed)
    return Path(sys.executable).resolve()


def render_unit(
    *,
    svcctl: Path,
    config_path: Path,
    use_module: bool,
) -> str:
    if use_module:
        # svcctl resolved to a Python interpreter
        exec_line = (
            f'ExecStart={svcctl} -m apr --config "{config_path}" serve --foreground'
        )
    else:
        exec_line = (
            f'ExecStart={svcctl} --config "{config_path}" serve --foreground'
        )

    return f"""\
[Unit]
Description=Agent Port Registry (local port allocation & service index)
Documentation=man:systemd.unit(5)
After=default.target

[Service]
Type=simple
# XDG Base Directory paths (POSIX/user defaults on modern Linux)
Environment=XDG_CONFIG_HOME=%h/.config
Environment=XDG_DATA_HOME=%h/.local/share
Environment=XDG_STATE_HOME=%h/.local/state
Environment=APR_CONFIG={config_path}
{exec_line}
WorkingDirectory=%h
Restart=on-failure
RestartSec=2
TimeoutStopSec=10
# Logs: journalctl --user -u apr.service -f
StandardOutput=journal
StandardError=journal
UMask=0077

[Install]
WantedBy=default.target
"""


def write_default_config(path: Path, *, force: bool = False) -> bool:
    """Write default config.yaml. Returns True if written."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists() and not force:
        return False
    path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    return True


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _daemon_reload() -> None:
    _systemctl("daemon-reload", check=False)


def install_user_service(
    *,
    svcctl_path: Path | None = None,
    enable: bool = True,
    start: bool = True,
    force_config: bool = False,
) -> dict:
    cfg_path = config_file()
    wrote_cfg = write_default_config(cfg_path, force=force_config)

    # Ensure data/state dirs exist with private perms
    load_config(config_path=cfg_path).ensure_dirs()

    exe = resolve_svcctl_executable(svcctl_path)
    use_module = exe.name.startswith("python")
    unit_text = render_unit(svcctl=exe, config_path=cfg_path, use_module=use_module)

    udir = systemd_user_dir()
    udir.mkdir(parents=True, exist_ok=True)
    upath = unit_path()
    upath.write_text(unit_text, encoding="utf-8")
    try:
        os.chmod(upath, 0o644)
    except OSError:
        pass

    _daemon_reload()
    if enable:
        _systemctl("enable", UNIT_NAME)
    if start:
        _systemctl("restart", UNIT_NAME)

    status = service_status()
    return {
        "config_path": str(cfg_path),
        "config_written": wrote_cfg,
        "unit_path": str(upath),
        "exec": str(exe),
        "enabled": enable,
        "started": start,
        "status": status,
    }


def uninstall_user_service(*, remove_config: bool = False) -> dict:
    _systemctl("disable", "--now", UNIT_NAME, check=False)
    upath = unit_path()
    removed_unit = False
    if upath.exists():
        upath.unlink()
        removed_unit = True
    _daemon_reload()
    removed_cfg = False
    if remove_config and config_file().exists():
        config_file().unlink()
        removed_cfg = True
    return {
        "unit_removed": removed_unit,
        "config_removed": removed_cfg,
        "unit_path": str(upath),
        "config_path": str(config_file()),
    }


def service_status() -> dict:
    active = _systemctl("is-active", UNIT_NAME, check=False)
    enabled = _systemctl("is-enabled", UNIT_NAME, check=False)
    return {
        "active": active.stdout.strip() if active.stdout else "unknown",
        "enabled": enabled.stdout.strip() if enabled.stdout else "unknown",
        "unit": UNIT_NAME,
        "unit_path": str(unit_path()),
        "config_path": str(config_file()),
        "unit_exists": unit_path().exists(),
        "config_exists": config_file().exists(),
    }


def register(app: typer.Typer) -> None:
    user_svc = typer.Typer(
        help="Manage systemd user service (start APR on login).",
        no_args_is_help=True,
    )
    app.add_typer(user_svc, name="user-service")

    @user_svc.command("install")
    def install_cmd(
        svcctl_path: Annotated[
            Optional[Path],
            typer.Option(
                "--svcctl",
                help="Absolute path to svcctl (default: resolve from PATH / current venv)",
            ),
        ] = None,
        no_enable: Annotated[
            bool,
            typer.Option("--no-enable", help="Write unit but do not enable"),
        ] = False,
        no_start: Annotated[
            bool,
            typer.Option("--no-start", help="Do not start the service now"),
        ] = False,
        force_config: Annotated[
            bool,
            typer.Option("--force-config", help="Overwrite existing config.yaml"),
        ] = False,
    ) -> None:
        """Install config under ~/.config/apr and enable systemd --user unit."""
        try:
            result = install_user_service(
                svcctl_path=svcctl_path,
                enable=not no_enable,
                start=not no_start,
                force_config=force_config,
            )
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise SystemExit(1) from exc
        except subprocess.CalledProcessError as exc:
            typer.echo(exc.stderr or str(exc), err=True)
            raise SystemExit(1) from exc

        typer.echo("APR user service installed.")
        typer.echo(f"  config:  {result['config_path']}  (written={result['config_written']})")
        typer.echo(f"  unit:    {result['unit_path']}")
        typer.echo(f"  exec:    {result['exec']}")
        st = result["status"]
        typer.echo(f"  active:  {st['active']}")
        typer.echo(f"  enabled: {st['enabled']}")
        typer.echo("")
        typer.echo("On login, systemd --user will start APR automatically.")
        typer.echo("Logs: journalctl --user -u apr.service -f")
        typer.echo("Status: svcctl user-service status")

    @user_svc.command("uninstall")
    def uninstall_cmd(
        remove_config: Annotated[
            bool,
            typer.Option("--remove-config", help="Also delete ~/.config/apr/config.yaml"),
        ] = False,
    ) -> None:
        """Disable and remove the systemd user unit."""
        result = uninstall_user_service(remove_config=remove_config)
        typer.echo("APR user service uninstalled.")
        typer.echo(f"  unit_removed:   {result['unit_removed']}")
        typer.echo(f"  config_removed: {result['config_removed']}")

    @user_svc.command("status")
    def status_cmd() -> None:
        """Show systemd user unit and config paths."""
        import json

        st = service_status()
        typer.echo(json.dumps(st, indent=2))

    @user_svc.command("write-config")
    def write_config_cmd(
        force: Annotated[
            bool,
            typer.Option("--force", help="Overwrite existing file"),
        ] = False,
    ) -> None:
        """Write default config to $XDG_CONFIG_HOME/apr/config.yaml."""
        path = config_file()
        wrote = write_default_config(path, force=force)
        if wrote:
            typer.echo(f"Wrote {path}")
        else:
            typer.echo(f"Already exists (use --force to overwrite): {path}")
