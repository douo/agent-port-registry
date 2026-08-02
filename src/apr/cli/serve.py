"""svcctl serve — start the APR Registry daemon."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from apr.api.app import create_app
from apr.config import Config, load_config


def _write_pid(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        os.chmod(pid_path, 0o600)
    except OSError:
        pass


def _remove_stale_socket(socket_path: Path) -> None:
    if socket_path.exists():
        try:
            socket_path.unlink()
        except OSError:
            pass


def _daemonize(log_path: Path) -> None:
    """Simple double-fork daemonization (Linux)."""
    if os.fork() > 0:
        raise SystemExit(0)
    os.setsid()
    if os.fork() > 0:
        raise SystemExit(0)

    sys.stdout.flush()
    sys.stderr.flush()
    log_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    os.dup2(log_f.fileno(), sys.stdout.fileno())
    os.dup2(log_f.fileno(), sys.stderr.fileno())
    devnull = open(os.devnull, "r")  # noqa: SIM115
    os.dup2(devnull.fileno(), sys.stdin.fileno())


def run_server(cfg: Config) -> None:
    cfg.ensure_dirs()
    _write_pid(cfg.pid_path)
    os.umask(0o077)

    def _cleanup(*_args: object) -> None:
        try:
            if cfg.pid_path.exists():
                cfg.pid_path.unlink()
        except OSError:
            pass
        if cfg.use_unix_socket:
            _remove_stale_socket(cfg.socket_path)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    app = create_app(
        state={
            "config": cfg,
            "db_path": str(cfg.db_path),
        }
    )

    if cfg.use_unix_socket:
        _remove_stale_socket(cfg.socket_path)
        uvicorn.run(app, uds=str(cfg.socket_path), log_level="info")
    else:
        uvicorn.run(
            app,
            host=cfg.http_host,
            port=cfg.http_port,
            log_level="info",
        )


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve_cmd(
        ctx: typer.Context,
        daemon: Annotated[
            bool,
            typer.Option("--daemon", "-d", help="Run in background"),
        ] = False,
        foreground: Annotated[
            bool,
            typer.Option("--foreground", "-f", help="Run in foreground (default)"),
        ] = False,
        tcp: Annotated[
            bool,
            typer.Option("--tcp", help="Listen on 127.0.0.1 TCP instead of Unix socket"),
        ] = False,
        http_port: Annotated[
            int | None,
            typer.Option("--http-port", help="TCP port when using --tcp"),
        ] = None,
    ) -> None:
        """Start the APR Registry (port allocator + service index)."""
        cfg: Config
        if ctx.obj and "config" in ctx.obj:
            cfg = ctx.obj["config"]
        else:
            cfg = load_config()

        if tcp:
            cfg.use_unix_socket = False
        if http_port is not None:
            cfg.http_port = http_port

        # state_dir comes from XDG / config; load_config colocates under data_dir
        # when a custom data_dir is used (tests / isolation).

        if daemon and not foreground:
            cfg.ensure_dirs()
            _daemonize(cfg.log_path)
            run_server(cfg)
            return

        run_server(cfg)
