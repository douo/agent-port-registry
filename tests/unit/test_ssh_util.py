"""SSH argv construction and validation."""

from __future__ import annotations

import pytest

from apr.domain.errors import AprError
from apr.service.ssh_util import (
    SshTarget,
    build_ssh_argv,
    split_apr_command,
    validate_apr_command,
    validate_ssh_host,
)


def test_build_ssh_argv_basic() -> None:
    argv = build_ssh_argv(
        SshTarget(host="box.local", user="me", port=2222, identity_file="/home/me/.ssh/id"),
        ["svcctl", "list", "--json"],
    )
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "-p" in argv and "2222" in argv
    assert "-i" in argv and "/home/me/.ssh/id" in argv
    assert "me@box.local" in argv
    assert argv[argv.index("--") + 1 :] == ["svcctl", "list", "--json"]


def test_reject_shell_injection_host() -> None:
    with pytest.raises(AprError):
        validate_ssh_host("host;id")


def test_apr_command_split() -> None:
    assert split_apr_command("uv run svcctl") == ["uv", "run", "svcctl"]
    with pytest.raises(AprError):
        validate_apr_command("svcctl; rm -rf /")
