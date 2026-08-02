"""svcctl — Agent Port Registry CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from apr import __version__
from apr.cli import ensure as ensure_mod
from apr.cli import query as query_mod
from apr.cli import release as release_mod
from apr.cli import serve as serve_mod
from apr.cli import user_service as user_service_mod
from apr.cli.client import health_check
from apr.config import load_config

app = typer.Typer(
    name="svcctl",
    help="Agent Port Registry CLI — fixed local port allocation and service index.",
    no_args_is_help=True,
    add_completion=False,
)

serve_mod.register(app)
ensure_mod.register(app)
query_mod.register(app)
release_mod.register(app)
user_service_mod.register(app)


def _resolve_config(
    data_dir: Path | None,
    config: Path | None,
    tcp: bool,
    http_port: int | None,
):
    cfg = load_config(config_path=config, data_dir=data_dir)
    if tcp:
        cfg.use_unix_socket = False
    if http_port is not None:
        cfg.http_port = http_port
    return cfg


@app.callback()
def main_callback(
    ctx: typer.Context,
    data_dir: Annotated[
        Optional[Path],
        typer.Option("--data-dir", help="APR data directory", envvar="APR_DATA_DIR"),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", help="Path to config.yaml", envvar="APR_CONFIG"),
    ] = None,
    tcp: Annotated[
        bool,
        typer.Option("--tcp", help="Use TCP 127.0.0.1 instead of Unix socket"),
    ] = False,
    http_port: Annotated[
        Optional[int],
        typer.Option("--http-port", help="TCP port when using --tcp"),
    ] = None,
) -> None:
    """Global options shared by all subcommands."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = _resolve_config(data_dir, config, tcp, http_port)


@app.command("version")
def version_cmd() -> None:
    """Print svcctl / APR version."""
    typer.echo(__version__)


@app.command("status")
def status_cmd(
    ctx: typer.Context,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON"),
    ] = False,
) -> None:
    """Show whether the APR Registry is reachable."""
    cfg = ctx.obj["config"]
    health = health_check(cfg)
    payload = {
        "up": health is not None,
        "transport": cfg.transport_description(),
        "data_dir": str(cfg.data_dir),
        "db_path": str(cfg.db_path),
        "health": health,
    }
    if json_out:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        raise SystemExit(0 if payload["up"] else 1)

    if payload["up"]:
        ver = (health or {}).get("version", "?")
        typer.echo(f"APR Registry: up (version {ver})")
        typer.echo(f"  transport: {payload['transport']}")
        typer.echo(f"  data_dir:  {payload['data_dir']}")
        raise SystemExit(0)

    typer.echo("APR Registry: down", err=True)
    typer.echo(f"  transport: {payload['transport']}", err=True)
    typer.echo("  start with: svcctl serve", err=True)
    raise SystemExit(1)


@app.command("backup")
def backup_cmd(
    ctx: typer.Context,
    dest: Annotated[
        Path,
        typer.Argument(help="Destination .db path for consistent backup"),
    ],
) -> None:
    """Create a consistent SQLite backup of the registry database."""
    import sqlite3

    cfg = ctx.obj["config"]
    if not cfg.db_path.exists():
        typer.echo(f"Database not found: {cfg.db_path}", err=True)
        raise SystemExit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(cfg.db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    typer.echo(json.dumps({"ok": True, "source": str(cfg.db_path), "dest": str(dest)}))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
