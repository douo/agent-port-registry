"""HTTP client for talking to the APR Registry."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from apr.config import Config


class RegistryConnectionError(RuntimeError):
    """Raised when the Registry cannot be reached."""


def _unix_transport(socket_path: Path) -> httpx.HTTPTransport:
    return httpx.HTTPTransport(uds=str(socket_path))


def build_client(cfg: Config, *, timeout: float = 5.0) -> httpx.Client:
    if cfg.use_unix_socket:
        return httpx.Client(
            transport=_unix_transport(cfg.socket_path),
            base_url=cfg.base_url(),
            timeout=timeout,
        )
    return httpx.Client(base_url=cfg.base_url(), timeout=timeout)


def health_check(cfg: Config, *, timeout: float = 2.0) -> dict[str, Any] | None:
    """Return health payload or None if unreachable."""
    try:
        with build_client(cfg, timeout=timeout) as client:
            resp = client.get("/healthz")
            if resp.status_code == 200:
                return resp.json()
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


def is_registry_up(cfg: Config) -> bool:
    return health_check(cfg) is not None


def try_auto_start(cfg: Config, *, wait_seconds: float = 3.0) -> bool:
    """Spawn `svcctl serve --daemon` in the background and wait for healthz."""
    if not cfg.auto_start:
        return False

    cfg.ensure_dirs()
    # Prefer the same interpreter / entrypoint currently running.
    cmd = [
        sys.executable,
        "-m",
        "apr",
        "serve",
        "--daemon",
        "--data-dir",
        str(cfg.data_dir),
    ]
    if not cfg.use_unix_socket:
        cmd.extend(["--tcp", "--http-port", str(cfg.http_port)])

    env = os.environ.copy()
    env["APR_DATA_DIR"] = str(cfg.data_dir)
    if cfg.config_path:
        env["APR_CONFIG"] = str(cfg.config_path)

    subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_registry_up(cfg):
            return True
        time.sleep(0.05)
    return False


def ensure_connected(cfg: Config) -> httpx.Client:
    """Return a live client; auto-start Registry if configured and needed."""
    if not is_registry_up(cfg):
        if not try_auto_start(cfg):
            raise RegistryConnectionError(
                f"APR Registry is not running ({cfg.transport_description()}). "
                "Start it with: svcctl serve"
            )
    return build_client(cfg)


def request_json(
    cfg: Config,
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Perform an HTTP request and return (status_code, parsed body)."""
    with ensure_connected(cfg) as client:
        resp = client.request(method, path, json=json, params=params)
        try:
            body: Any = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return resp.status_code, body
