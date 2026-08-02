"""Service identity normalization tests."""

from apr.domain.identity import ServiceIdentity


def test_normalize_empty_agent_to_human() -> None:
    ident = ServiceIdentity.from_raw(
        agent_type=None,
        agent_project_id=None,
        service_key="local-dashboard",
        instance=None,
    )
    assert ident.agent_type_key == "human"
    assert ident.agent_project_key == "-"
    assert ident.instance_key == "default"
    assert ident.agent_type is None
    assert ident.agent_project_id is None


def test_normalize_codex_identity() -> None:
    ident = ServiceIdentity.from_raw(
        agent_type="codex",
        agent_project_id="project-model-platform",
        service_key="model-api",
        instance="main",
    )
    assert ident.display_key() == "codex + project-model-platform + model-api + main"


def test_whitespace_instance_defaults() -> None:
    ident = ServiceIdentity.from_raw(
        agent_type="  ",
        agent_project_id="  ",
        service_key="svc",
        instance="  ",
    )
    assert ident.agent_type_key == "human"
    assert ident.agent_project_key == "-"
    assert ident.instance_key == "default"
