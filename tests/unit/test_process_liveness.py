"""Cross-platform process liveness checks used by processes and forwards."""

from __future__ import annotations

from unittest.mock import patch

from apr.service.process import _pid_alive


def test_pid_alive_falls_back_to_signal_probe_without_proc() -> None:
    """macOS has no /proc; a successful signal-0 probe still means alive."""
    with (
        patch("apr.service.process._try_reap", return_value=None),
        patch("apr.service.process._proc_state_letter", return_value=None),
        patch("apr.service.process.os.kill") as kill,
    ):
        assert _pid_alive(4242) is True
        kill.assert_called_once_with(4242, 0)


def test_pid_alive_rejects_proc_zombie_without_signal_probe() -> None:
    with (
        patch("apr.service.process._try_reap", return_value=None),
        patch("apr.service.process._proc_state_letter", return_value="Z"),
        patch("apr.service.process.os.kill") as kill,
    ):
        assert _pid_alive(4242) is False
        kill.assert_not_called()


def test_pid_alive_rejects_missing_process_without_proc() -> None:
    with (
        patch("apr.service.process._try_reap", return_value=None),
        patch("apr.service.process._proc_state_letter", return_value=None),
        patch(
            "apr.service.process.os.kill",
            side_effect=ProcessLookupError,
        ),
    ):
        assert _pid_alive(4242) is False
