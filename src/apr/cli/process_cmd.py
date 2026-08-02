"""svcctl process start|stop|logs — for local use and remote SSH control plane."""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import typer

from apr.cli.client import RegistryConnectionError, request_json
from apr.config import Config


def _cfg(ctx: typer.Context) -> Config:
    return ctx.obj["config"]


def _request(cfg: Config, method: str, path: str, **kwargs: Any) -> Any:
    try:
        status, data = request_json(cfg, method, path, **kwargs)
    except RegistryConnectionError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    if status >= 400:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False), err=True)
        raise SystemExit(1)
    return data


def register(app: typer.Typer) -> None:
    proc = typer.Typer(
        name="process",
        help="Manage service processes (requires process_management.enabled).",
        no_args_is_help=True,
    )
    app.add_typer(proc, name="process")

    @proc.command("start")
    def start_cmd(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
    ) -> None:
        """Start a service via Registry (POST /v1/services/{id}/start)."""
        data = _request(_cfg(ctx), "POST", f"/v1/services/{service_id}/start")
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))

    @proc.command("stop")
    def stop_cmd(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
    ) -> None:
        """Stop a managed service process."""
        data = _request(_cfg(ctx), "POST", f"/v1/services/{service_id}/stop")
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))

    @proc.command("logs")
    def logs_cmd(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
        tail: Annotated[
            Optional[int],
            typer.Option("--tail", help="Number of log lines"),
        ] = 200,
    ) -> None:
        """Fetch recent process logs as JSON."""
        n = 200 if tail is None else tail
        data = _request(
            _cfg(ctx), "GET", f"/v1/services/{service_id}/logs", params={"tail": n}
        )
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))

    @proc.command("status")
    def status_cmd(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
    ) -> None:
        """Show managed process status for a service."""
        data = _request(_cfg(ctx), "GET", f"/v1/services/{service_id}/process")
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
