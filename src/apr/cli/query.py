"""svcctl list / search / inspect / check commands."""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import typer

from apr.cli.client import RegistryConnectionError, request_json
from apr.config import Config


def _cfg(ctx: typer.Context) -> Config:
    return ctx.obj["config"]


def _get(cfg: Config, path: str, params: dict | None = None) -> Any:
    try:
        status, data = request_json(cfg, "GET", path, params=params)
    except RegistryConnectionError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    if status >= 400:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False), err=True)
        raise SystemExit(1)
    return data


def _print_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


def _print_service_table(services: list[dict]) -> None:
    if not services:
        typer.echo("(no services)")
        return
    headers = [
        "ID",
        "Agent",
        "Project",
        "Key",
        "Instance",
        "Name",
        "Ports",
    ]
    rows = []
    for s in services:
        ports: list[str] = []
        for a in s.get("allocations") or []:
            if a.get("state") != "reserved":
                continue
            for p in a.get("ports") or []:
                label = p.get("port_name") or p.get("resource_name")
                ports.append(f"{label}={p['port']}")
        rows.append(
            [
                s.get("id", "")[:16],
                s.get("agent_type_key") or "-",
                s.get("agent_project_key") or "-",
                s.get("service_key") or "",
                s.get("instance_key") or "",
                s.get("name") or "",
                ", ".join(ports) if ports else "-",
            ]
        )
    # simple column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    typer.echo(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        typer.echo(fmt.format(*row))


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_cmd(
        ctx: typer.Context,
        agent: Annotated[
            Optional[str],
            typer.Option("--agent", help="Filter by agent type key"),
        ] = None,
        agent_project: Annotated[
            Optional[str],
            typer.Option("--agent-project", help="Filter by agent project id"),
        ] = None,
        table: Annotated[
            bool,
            typer.Option("--table", help="Human-readable table (default for TTY)"),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Force JSON output"),
        ] = False,
    ) -> None:
        """List registered services."""
        params: dict[str, str] = {}
        if agent is not None:
            params["agent_type"] = agent
        if agent_project is not None:
            params["agent_project_id"] = agent_project
        data = _get(_cfg(ctx), "/v1/services", params or None)
        if as_json or (not table and not sys_stdout_is_tty_prefer_json()):
            if as_json or not table:
                # Default to JSON for Agent consumption unless --table
                if table:
                    _print_service_table(data.get("services") or [])
                else:
                    _print_json(data)
            return
        _print_service_table(data.get("services") or [])

    @app.command("search")
    def search_cmd(
        ctx: typer.Context,
        query: Annotated[str, typer.Argument(help="Search string")],
        as_json: Annotated[bool, typer.Option("--json")] = True,
        table: Annotated[bool, typer.Option("--table")] = False,
    ) -> None:
        """Search services by name, key, description, agent, path."""
        data = _get(_cfg(ctx), "/v1/services", {"query": query})
        if table:
            _print_service_table(data.get("services") or [])
        else:
            _print_json(data)

    @app.command("inspect-service")
    def inspect_service_cmd(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
    ) -> None:
        """Show full service record and allocations."""
        data = _get(_cfg(ctx), f"/v1/services/{service_id}")
        _print_json(data)

    @app.command("inspect-port")
    def inspect_port_cmd(
        ctx: typer.Context,
        port: Annotated[int, typer.Argument(help="Port number")],
    ) -> None:
        """Look up which service owns a port."""
        data = _get(_cfg(ctx), f"/v1/ports/{port}")
        _print_json(data)

    @app.command("check")
    def check_cmd(
        ctx: typer.Context,
        target: Annotated[
            str,
            typer.Argument(help="Service id or allocation id"),
        ],
    ) -> None:
        """Check listen status for a service or allocation."""
        cfg = _cfg(ctx)
        # Heuristic: alloc ids start with ALLOC_ / alloc_
        if target.lower().startswith("alloc"):
            data = _get(cfg, f"/v1/allocations/{target}/check")
            _print_json(data)
            return
        # Service: check all reserved allocations
        svc = _get(cfg, f"/v1/services/{target}")
        results = []
        for a in svc.get("allocations") or []:
            if a.get("state") != "reserved":
                continue
            results.append(_get(cfg, f"/v1/allocations/{a['id']}/check"))
        _print_json({"service_id": target, "checks": results})

    @app.command("check-all")
    def check_all_cmd(ctx: typer.Context) -> None:
        """Check listen status for all reserved allocations."""
        cfg = _cfg(ctx)
        data = _get(cfg, "/v1/services")
        results = []
        for s in data.get("services") or []:
            for a in s.get("allocations") or []:
                if a.get("state") != "reserved":
                    continue
                results.append(_get(cfg, f"/v1/allocations/{a['id']}/check"))
        _print_json({"checks": results})


def sys_stdout_is_tty_prefer_json() -> bool:
    """Default list output is JSON (Agent-friendly). --table for humans."""
    return False
