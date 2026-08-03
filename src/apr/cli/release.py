"""svcctl service / allocation CRUD and release commands."""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import typer

from apr.cli.client import RegistryConnectionError, request_json
from apr.config import Config


def _echo(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


def _req(
    cfg: Config,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        status, data = request_json(cfg, method, path, json=json_body, params=params)
    except RegistryConnectionError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    _echo(data)
    if status >= 400:
        raise SystemExit(1)
    return data


def register(app: typer.Typer) -> None:
    service_app = typer.Typer(
        help="Service index CRUD (create / get / list / update / delete).",
        no_args_is_help=True,
    )
    app.add_typer(service_app, name="service")

    allocation_app = typer.Typer(
        help="Allocation CRUD (get / release / delete).",
        no_args_is_help=True,
    )
    app.add_typer(allocation_app, name="allocation")

    # ── Service C ────────────────────────────────────────────
    @service_app.command("create")
    def service_create(
        ctx: typer.Context,
        service: Annotated[str, typer.Option("--service", help="Service key")],
        instance: Annotated[str, typer.Option("--instance")] = "default",
        name: Annotated[Optional[str], typer.Option("--name")] = None,
        description: Annotated[Optional[str], typer.Option("--description")] = None,
        code_path: Annotated[Optional[str], typer.Option("--code-path")] = None,
        working_directory: Annotated[
            Optional[str], typer.Option("--working-directory")
        ] = None,
        start_command: Annotated[Optional[str], typer.Option("--start-command")] = None,
        stop_command: Annotated[Optional[str], typer.Option("--stop-command")] = None,
        health_check: Annotated[Optional[str], typer.Option("--health-check")] = None,
        configuration: Annotated[Optional[str], typer.Option("--configuration")] = None,
        auto_start: Annotated[
            bool, typer.Option("--auto-start/--no-auto-start")
        ] = False,
        project_origin: Annotated[Optional[str], typer.Option("--project-origin")] = None,
        agent: Annotated[Optional[str], typer.Option("--agent")] = None,
        project: Annotated[
            Optional[str], typer.Option("--project")
        ] = None,
    ) -> None:
        """Create a service index entry without allocating ports."""
        cfg: Config = ctx.obj["config"]
        body: dict[str, Any] = {
            "agent": (
                {"type": agent} if agent else None
            ),
            "service": {
                "key": service,
                "instance": instance,
                "project_id": project,
                "name": name or service,
                "description": description,
                "code_path": code_path,
                "working_directory": working_directory,
                "start_command": start_command,
                "stop_command": stop_command,
                "health_check": health_check,
                "configuration": configuration,
                "auto_start": auto_start,
                "project_origin": project_origin,
            },
        }
        _req(cfg, "POST", "/v1/services", json_body=body)

    # ── Service R ────────────────────────────────────────────
    @service_app.command("get")
    def service_get(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
    ) -> None:
        """Get one service with allocations."""
        _req(ctx.obj["config"], "GET", f"/v1/services/{service_id}")

    @service_app.command("list")
    def service_list(
        ctx: typer.Context,
        agent: Annotated[Optional[str], typer.Option("--agent")] = None,
        project: Annotated[
            Optional[str], typer.Option("--project")
        ] = None,
        query: Annotated[Optional[str], typer.Option("--query", "-q")] = None,
    ) -> None:
        """List services (same data as `svcctl list`)."""
        params: dict[str, str] = {}
        if agent is not None:
            params["agent"] = agent
        if project is not None:
            params["project_id"] = project
        if query is not None:
            params["query"] = query
        _req(ctx.obj["config"], "GET", "/v1/services", params=params or None)

    # ── Service U ────────────────────────────────────────────
    @service_app.command("update")
    def service_update(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument()],
        name: Annotated[Optional[str], typer.Option("--name")] = None,
        description: Annotated[Optional[str], typer.Option("--description")] = None,
        code_path: Annotated[Optional[str], typer.Option("--code-path")] = None,
        working_directory: Annotated[
            Optional[str], typer.Option("--working-directory")
        ] = None,
        start_command: Annotated[Optional[str], typer.Option("--start-command")] = None,
        stop_command: Annotated[Optional[str], typer.Option("--stop-command")] = None,
        health_check: Annotated[Optional[str], typer.Option("--health-check")] = None,
        configuration: Annotated[Optional[str], typer.Option("--configuration")] = None,
        auto_start: Annotated[
            Optional[bool], typer.Option("--auto-start/--no-auto-start")
        ] = None,
        project_origin: Annotated[Optional[str], typer.Option("--project-origin")] = None,
    ) -> None:
        """Update service index metadata (does not change ports)."""
        cfg: Config = ctx.obj["config"]
        body = {
            k: v
            for k, v in {
                "name": name,
                "description": description,
                "code_path": code_path,
                "working_directory": working_directory,
                "start_command": start_command,
                "stop_command": stop_command,
                "health_check": health_check,
                "configuration": configuration,
                "auto_start": auto_start,
                "project_origin": project_origin,
            }.items()
            if v is not None
        }
        if not body:
            typer.echo("No fields to update", err=True)
            raise SystemExit(2)
        _req(cfg, "PATCH", f"/v1/services/{service_id}", json_body=body)

    # ── Service D ────────────────────────────────────────────
    @service_app.command("delete")
    def service_delete(
        ctx: typer.Context,
        service_id: Annotated[str, typer.Argument(help="Service id")],
        reason: Annotated[Optional[str], typer.Option("--reason")] = None,
        yes: Annotated[
            bool, typer.Option("--yes", "-y", help="Skip confirmation")
        ] = False,
    ) -> None:
        """Hard-delete a service and all its allocations / port claims."""
        if not yes:
            confirm = typer.confirm(
                f"Delete service {service_id} and free all its ports? This cannot be undone."
            )
            if not confirm:
                typer.echo("Aborted")
                raise SystemExit(1)
        _req(
            ctx.obj["config"],
            "DELETE",
            f"/v1/services/{service_id}",
            json_body={"reason": reason},
        )

    # ── Allocation R ─────────────────────────────────────────
    @allocation_app.command("get")
    def allocation_get(
        ctx: typer.Context,
        allocation_id: Annotated[str, typer.Argument()],
    ) -> None:
        """Get one allocation (ports, state, parent service)."""
        _req(ctx.obj["config"], "GET", f"/v1/allocations/{allocation_id}")

    # ── Allocation release (soft delete claim, keep history) ─
    @allocation_app.command("release")
    def allocation_release(
        ctx: typer.Context,
        allocation_id: Annotated[str, typer.Argument()],
        reason: Annotated[Optional[str], typer.Option("--reason")] = None,
        yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    ) -> None:
        """Release port claims but keep allocation history."""
        if not yes:
            if not typer.confirm(f"Release allocation {allocation_id}?"):
                typer.echo("Aborted")
                raise SystemExit(1)
        _req(
            ctx.obj["config"],
            "POST",
            f"/v1/allocations/{allocation_id}/release",
            json_body={"reason": reason},
        )

    # ── Allocation D (hard delete) ───────────────────────────
    @allocation_app.command("delete")
    def allocation_delete(
        ctx: typer.Context,
        allocation_id: Annotated[str, typer.Argument()],
        reason: Annotated[Optional[str], typer.Option("--reason")] = None,
        force: Annotated[
            bool,
            typer.Option(
                "--force/--no-force",
                help="Also delete if still reserved (default: force)",
            ),
        ] = True,
        yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    ) -> None:
        """Hard-delete allocation history and free claims."""
        if not yes:
            if not typer.confirm(
                f"Permanently delete allocation {allocation_id}? This cannot be undone."
            ):
                typer.echo("Aborted")
                raise SystemExit(1)
        params = {"force": "true" if force else "false"}
        _req(
            ctx.obj["config"],
            "DELETE",
            f"/v1/allocations/{allocation_id}",
            json_body={"reason": reason},
            params=params,
        )

    # Top-level aliases kept for PRD / muscle memory
    @app.command("release")
    def release_cmd(
        ctx: typer.Context,
        allocation_id: Annotated[str, typer.Argument(help="Allocation id")],
        reason: Annotated[
            Optional[str],
            typer.Option("--reason", help="Release reason"),
        ] = None,
        yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Skip confirmation"),
        ] = False,
    ) -> None:
        """Release an allocation (alias of `allocation release`)."""
        allocation_release(ctx, allocation_id, reason=reason, yes=yes)

    @app.command("delete")
    def delete_cmd(
        ctx: typer.Context,
        target_id: Annotated[
            str,
            typer.Argument(help="Service id (svc_…) or allocation id (alloc_…)"),
        ],
        reason: Annotated[Optional[str], typer.Option("--reason")] = None,
        yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    ) -> None:
        """Delete a service or allocation by id prefix."""
        lower = target_id.lower()
        if lower.startswith("svc"):
            service_delete(ctx, target_id, reason=reason, yes=yes)
        elif lower.startswith("alloc"):
            allocation_delete(ctx, target_id, reason=reason, force=True, yes=yes)
        else:
            typer.echo(
                "Id must start with svc_… (service) or alloc_… (allocation)",
                err=True,
            )
            raise SystemExit(2)
