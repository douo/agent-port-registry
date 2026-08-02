"""svcctl serve — start the APR Registry daemon."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import Annotated, Iterator

import typer
import uvicorn

from apr.api.app import create_app
from apr.config import Config, load_config
from apr.webui import is_built as webui_is_built


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


class _ManagedSignalServer(uvicorn.Server):
    """A uvicorn Server whose signal handling is owned by :func:`run_server`.

    uvicorn installs its own ``signal.signal`` handler per Server. With two
    Servers sharing one event loop (Unix socket + TCP) the second would clobber
    the first's handler, so on SIGTERM only one of them would ever be told to
    exit and shutdown would hang. We disable per-server capture and drive
    ``should_exit`` centrally instead.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def _uvicorn_configs(cfg: Config, app: object) -> list[uvicorn.Config]:
    """One Config per transport we need to bind."""
    configs: list[uvicorn.Config] = []
    if cfg.use_unix_socket:
        _remove_stale_socket(cfg.socket_path)
        configs.append(
            uvicorn.Config(app, uds=str(cfg.socket_path), log_level="info")
        )
    if cfg.needs_tcp():
        configs.append(
            uvicorn.Config(
                app,
                host=cfg.http_host,
                port=cfg.http_port,
                log_level="info",
            )
        )
    return configs


async def _serve_all(servers: list[_ManagedSignalServer]) -> None:
    loop = asyncio.get_running_loop()

    def _request_exit() -> None:
        for server in servers:
            server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_exit)

    await asyncio.gather(*(server.serve() for server in servers))


def _cleanup_runtime_files(cfg: Config) -> None:
    try:
        if cfg.pid_path.exists():
            cfg.pid_path.unlink()
    except OSError:
        pass
    if cfg.use_unix_socket:
        _remove_stale_socket(cfg.socket_path)


def run_server(cfg: Config) -> None:
    cfg.ensure_dirs()
    _write_pid(cfg.pid_path)
    os.umask(0o077)

    app = create_app(
        state={
            "config": cfg,
            "db_path": str(cfg.db_path),
        }
    )

    configs = _uvicorn_configs(cfg, app)
    if not configs:
        raise SystemExit("No transport enabled: neither Unix socket nor TCP.")

    if cfg.web_enabled:
        if webui_is_built():
            print(f"APR Web UI: {cfg.web_url()}", flush=True)
        else:
            print(
                "APR Web UI requested but no built bundle found "
                "(src/apr/webui/static/index.html). Run: cd web && npm run build",
                file=sys.stderr,
                flush=True,
            )

    servers = [_ManagedSignalServer(c) for c in configs]
    try:
        asyncio.run(_serve_all(servers))
    finally:
        _cleanup_runtime_files(cfg)


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
            typer.Option("--http-port", help="TCP port when using --tcp / --web"),
        ] = None,
        web: Annotated[
            bool | None,
            typer.Option(
                "--web/--no-web",
                help="Also serve the Web UI over 127.0.0.1 TCP (Unix socket stays up)",
            ),
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
        if web is not None:
            cfg.web_enabled = web

        # state_dir comes from XDG / config; load_config colocates under data_dir
        # when a custom data_dir is used (tests / isolation).

        if daemon and not foreground:
            cfg.ensure_dirs()
            _daemonize(cfg.log_path)
            run_server(cfg)
            return

        run_server(cfg)
