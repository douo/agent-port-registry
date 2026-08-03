"""Deployment identity normalization tests."""

from apr.domain.identity import ServiceIdentity


def test_defaults_to_local_device_and_default_project() -> None:
    ident = ServiceIdentity.from_raw(
        device_id=None,
        project_id=None,
        service_key="local-dashboard",
        instance=None,
    )
    assert ident.device_id == "NODE_LOCAL"
    assert ident.project_key == "-"
    assert ident.instance_key == "default"
    assert ident.project_id is None


def test_device_project_service_identity() -> None:
    ident = ServiceIdentity.from_raw(
        device_id="NODE_P44",
        project_id="project-model-platform",
        service_key="model-api",
        instance="main",
    )
    assert ident.display_key() == (
        "NODE_P44 + project-model-platform + model-api + main"
    )


def test_whitespace_defaults() -> None:
    ident = ServiceIdentity.from_raw(
        device_id="  ",
        project_id="  ",
        service_key="svc",
        instance="  ",
    )
    assert ident.device_id == "NODE_LOCAL"
    assert ident.project_key == "-"
    assert ident.instance_key == "default"
