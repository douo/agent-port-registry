"""APR configuration: paths, port pool, transport."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PORT_POOL_START = 20000
DEFAULT_PORT_POOL_END = 39999
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 17989


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "share"


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config"


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state"


@dataclass
class PortPoolConfig:
    start: int = DEFAULT_PORT_POOL_START
    end: int = DEFAULT_PORT_POOL_END
    exclude: list[str | int] = field(default_factory=list)


@dataclass
class Config:
    """Runtime configuration for Registry and CLI."""

    data_dir: Path
    config_path: Path
    state_dir: Path
    db_path: Path
    socket_path: Path
    log_path: Path
    pid_path: Path
    http_host: str = DEFAULT_HTTP_HOST
    http_port: int = DEFAULT_HTTP_PORT
    use_unix_socket: bool = True
    auto_start: bool = True
    web_enabled: bool = False
    # "Run arbitrary start_command via the API / Web UI". Default OFF.
    process_management_enabled: bool = False
    process_stop_timeout_seconds: int = 10
    port_pool: PortPoolConfig = field(default_factory=PortPoolConfig)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.config_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Tighten permissions if already existed with looser mode.
        try:
            os.chmod(self.data_dir, 0o700)
            os.chmod(self.state_dir, 0o700)
        except OSError:
            pass

    def base_url(self) -> str:
        """HTTP base URL used by httpx (host is ignored for Unix sockets)."""
        if self.use_unix_socket:
            return "http://apr"
        return f"http://{self.http_host}:{self.http_port}"

    def transport_description(self) -> str:
        if self.use_unix_socket:
            return f"unix:{self.socket_path}"
        return f"http://{self.http_host}:{self.http_port}"

    def web_url(self) -> str:
        """Browser-facing URL of the Web UI (only bound when web_enabled)."""
        return f"http://{self.http_host}:{self.http_port}"

    def needs_tcp(self) -> bool:
        """TCP has to be bound for the API fallback or for the browser UI."""
        return (not self.use_unix_socket) or self.web_enabled


def default_config() -> Config:
    data_dir = _xdg_data_home() / "apr"
    config_dir = _xdg_config_home() / "apr"
    state_dir = _xdg_state_home() / "apr"
    return Config(
        data_dir=data_dir,
        config_path=config_dir / "config.yaml",
        state_dir=state_dir,
        db_path=data_dir / "apr.db",
        socket_path=data_dir / "apr.sock",
        log_path=state_dir / "apr.log",
        pid_path=state_dir / "apr.pid",
    )


def _parse_port_pool(raw: dict[str, Any] | None) -> PortPoolConfig:
    if not raw:
        return PortPoolConfig()
    return PortPoolConfig(
        start=int(raw.get("start", DEFAULT_PORT_POOL_START)),
        end=int(raw.get("end", DEFAULT_PORT_POOL_END)),
        exclude=list(raw.get("exclude") or []),
    )


def load_config(
    config_path: Path | None = None,
    *,
    data_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Load config from defaults, optional YAML file, and environment overrides.

    Environment variables (highest precedence after explicit args):
      APR_DATA_DIR, APR_SOCKET, APR_DB, APR_HTTP_HOST, APR_HTTP_PORT,
      APR_USE_TCP=1, APR_AUTO_START=0, APR_CONFIG, APR_WEB=1,
      APR_PROCESS_MANAGEMENT=1
    """
    env = env if env is not None else os.environ
    cfg = default_config()

    path = config_path
    if path is None and env.get("APR_CONFIG"):
        path = Path(env["APR_CONFIG"])
    if path is None:
        path = cfg.config_path

    file_data: dict[str, Any] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Config file must be a mapping: {path}")
            file_data = loaded

    custom_data_dir = False
    if data_dir is not None:
        cfg.data_dir = Path(data_dir)
        custom_data_dir = True
    elif env.get("APR_DATA_DIR"):
        cfg.data_dir = Path(env["APR_DATA_DIR"])
        custom_data_dir = True
    elif file_data.get("data_dir"):
        cfg.data_dir = Path(str(file_data["data_dir"]))
        custom_data_dir = True

    cfg.config_path = path
    cfg.db_path = cfg.data_dir / "apr.db"
    cfg.socket_path = cfg.data_dir / "apr.sock"

    if env.get("APR_STATE_DIR"):
        cfg.state_dir = Path(env["APR_STATE_DIR"])
    elif file_data.get("state_dir"):
        cfg.state_dir = Path(str(file_data["state_dir"]))
    elif custom_data_dir:
        # Isolate state next to a non-default data dir (tests / custom roots).
        cfg.state_dir = cfg.data_dir / "state"
    cfg.log_path = cfg.state_dir / "apr.log"
    cfg.pid_path = cfg.state_dir / "apr.pid"

    if env.get("APR_DB"):
        cfg.db_path = Path(env["APR_DB"])
    elif file_data.get("db_path"):
        cfg.db_path = Path(str(file_data["db_path"]))

    if env.get("APR_SOCKET"):
        cfg.socket_path = Path(env["APR_SOCKET"])
    elif file_data.get("socket_path"):
        cfg.socket_path = Path(str(file_data["socket_path"]))

    if env.get("APR_HTTP_HOST"):
        cfg.http_host = env["APR_HTTP_HOST"]
    elif file_data.get("http_host"):
        cfg.http_host = str(file_data["http_host"])

    if env.get("APR_HTTP_PORT"):
        cfg.http_port = int(env["APR_HTTP_PORT"])
    elif file_data.get("http_port") is not None:
        cfg.http_port = int(file_data["http_port"])

    if env.get("APR_USE_TCP") in ("1", "true", "True", "yes"):
        cfg.use_unix_socket = False
    elif "use_unix_socket" in file_data:
        cfg.use_unix_socket = bool(file_data["use_unix_socket"])

    if env.get("APR_AUTO_START") in ("0", "false", "False", "no"):
        cfg.auto_start = False
    elif "auto_start" in file_data:
        cfg.auto_start = bool(file_data["auto_start"])

    web_raw = file_data.get("web")
    if isinstance(web_raw, dict):
        if "enabled" in web_raw:
            cfg.web_enabled = bool(web_raw["enabled"])
        if web_raw.get("host"):
            cfg.http_host = str(web_raw["host"])
        if web_raw.get("port") is not None:
            cfg.http_port = int(web_raw["port"])
    if env.get("APR_WEB") in ("1", "true", "True", "yes"):
        cfg.web_enabled = True
    elif env.get("APR_WEB") in ("0", "false", "False", "no"):
        cfg.web_enabled = False

    pm_raw = file_data.get("process_management")
    if isinstance(pm_raw, dict):
        if "enabled" in pm_raw:
            cfg.process_management_enabled = bool(pm_raw["enabled"])
        if pm_raw.get("stop_timeout_seconds") is not None:
            cfg.process_stop_timeout_seconds = max(
                1, int(pm_raw["stop_timeout_seconds"])
            )
    if env.get("APR_PROCESS_MANAGEMENT") in ("1", "true", "True", "yes"):
        cfg.process_management_enabled = True
    elif env.get("APR_PROCESS_MANAGEMENT") in ("0", "false", "False", "no"):
        cfg.process_management_enabled = False

    pool_raw = file_data.get("port_pool")
    if isinstance(pool_raw, dict):
        cfg.port_pool = _parse_port_pool(pool_raw)

    return cfg
