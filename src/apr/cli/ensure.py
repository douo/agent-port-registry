"""svcctl ensure command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from apr.cli.client import RegistryConnectionError, request_json
from apr.config import Config


def _build_resources_from_flags(
    port: list[str],
    ports: Optional[str],
    block: list[str],
) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for name in port:
        name = name.strip()
        if name:
            resources.append({"name": name, "type": "single"})
    if ports:
        names = [n.strip() for n in ports.split(",") if n.strip()]
        if names:
            resources.append(
                {
                    "name": "service-ports",
                    "type": "count",
                    "count": len(names),
                    "contiguous": False,
                    "port_names": names,
                }
            )
    for b in block:
        # format: name=size
        if "=" not in b:
            raise typer.BadParameter(f"block must be name=size, got: {b}")
        name, _, size_s = b.partition("=")
        resources.append(
            {"name": name.strip(), "type": "block", "size": int(size_s.strip())}
        )
    return resources


def register(app: typer.Typer) -> None:
    @app.command("ensure")
    def ensure_cmd(
        ctx: typer.Context,
        json_in: Annotated[
            Optional[str],
            typer.Option(
                "--json",
                help="JSON request body, or '-' to read from stdin",
            ),
        ] = None,
        file: Annotated[
            Optional[Path],
            typer.Option("--file", help="Read JSON request from file"),
        ] = None,
        service: Annotated[
            Optional[str],
            typer.Option("--service", help="Service key"),
        ] = None,
        instance: Annotated[
            str,
            typer.Option("--instance", help="Service instance"),
        ] = "default",
        name: Annotated[
            Optional[str],
            typer.Option("--name", help="Human-readable service name"),
        ] = None,
        description: Annotated[
            Optional[str],
            typer.Option("--description", help="Service purpose"),
        ] = None,
        code_path: Annotated[
            Optional[str],
            typer.Option("--code-path", help="Code path"),
        ] = None,
        working_directory: Annotated[
            Optional[str],
            typer.Option("--working-directory", help="Working directory"),
        ] = None,
        start_command: Annotated[
            Optional[str],
            typer.Option("--start-command", help="Start command template"),
        ] = None,
        stop_command: Annotated[
            Optional[str],
            typer.Option("--stop-command", help="Stop command template"),
        ] = None,
        health_check: Annotated[
            Optional[str],
            typer.Option("--health-check", help="Health URL or TCP check description"),
        ] = None,
        configuration: Annotated[
            Optional[str],
            typer.Option("--configuration", help="Where the Agent persists the port"),
        ] = None,
        auto_start: Annotated[
            Optional[bool],
            typer.Option(
                "--auto-start/--no-auto-start",
                help="Start this service when APR starts",
            ),
        ] = None,
        project_origin: Annotated[
            Optional[str],
            typer.Option("--project-origin", help="self-built, third-party-open-source, external"),
        ] = None,
        agent_type: Annotated[
            Optional[str],
            typer.Option("--agent", help="Agent type (codex, claude-code, …)"),
        ] = None,
        project_id: Annotated[
            Optional[str],
            typer.Option("--project", help="Stable project id"),
        ] = None,
        allocation_name: Annotated[
            str,
            typer.Option("--allocation", help="Allocation name"),
        ] = "default",
        port: Annotated[
            Optional[list[str]],
            typer.Option("--port", help="Single named port resource (repeatable)"),
        ] = None,
        ports: Annotated[
            Optional[str],
            typer.Option("--ports", help="Comma-separated named ports (count)"),
        ] = None,
        block: Annotated[
            Optional[list[str]],
            typer.Option("--block", help="Contiguous block name=size (repeatable)"),
        ] = None,
    ) -> None:
        """Create or return a fixed port allocation (idempotent)."""
        cfg: Config = ctx.obj["config"]
        body: dict[str, Any]

        if json_in is not None:
            raw = sys.stdin.read() if json_in == "-" else json_in
            try:
                body = json.loads(raw)
            except json.JSONDecodeError as exc:
                typer.echo(f"Invalid JSON: {exc}", err=True)
                raise SystemExit(2) from exc
        elif file is not None:
            try:
                body = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                typer.echo(f"Failed to read request file: {exc}", err=True)
                raise SystemExit(2) from exc
        else:
            if not service:
                typer.echo(
                    "Either --json/--file or --service with port flags is required",
                    err=True,
                )
                raise SystemExit(2)
            resources = _build_resources_from_flags(port or [], ports, block or [])
            if not resources:
                resources = [{"name": "http", "type": "single"}]
            body = {
                "agent": (
                    {"type": agent_type} if agent_type else None
                ),
                "service": {
                    "key": service,
                    "instance": instance,
                    "project_id": project_id,
                    "project_origin": project_origin,
                    "name": name or service,
                    "description": description,
                    "code_path": code_path,
                    "working_directory": working_directory,
                    "start_command": start_command,
                    "stop_command": stop_command,
                    "health_check": health_check,
                    "configuration": configuration,
                    "auto_start": auto_start,
                },
                "allocation_name": allocation_name,
                "resources": resources,
            }

        try:
            status, data = request_json(cfg, "POST", "/v1/allocations/ensure", json=body)
        except RegistryConnectionError as exc:
            typer.echo(str(exc), err=True)
            raise SystemExit(1) from exc

        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        if status >= 400:
            raise SystemExit(1)
