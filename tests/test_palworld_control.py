"""Tests for the out-of-process pause control CLI."""

import json
import signal
from unittest.mock import patch

import pytest

from scripts import palworld_control


def write_state(runtime_dir, *, state="paused", ticks=42):
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "server-state.json").write_text(json.dumps({
        "pid": 123,
        "pgid": 123,
        "process_start_ticks": ticks,
        "state": state,
    }))


def test_status_rejects_stale_process_identity(tmp_path):
    write_state(tmp_path, ticks=42)
    with patch.object(palworld_control, "read_start_ticks", return_value=99):
        with pytest.raises(RuntimeError, match="Stale"):
            palworld_control.show_status(tmp_path)


def test_resume_signals_group_and_writes_marker(tmp_path):
    write_state(tmp_path)
    with patch.object(palworld_control, "read_start_ticks", return_value=42), \
         patch.object(palworld_control.os, "killpg", create=True) as killpg:
        assert palworld_control.resume(tmp_path) == 0

    killpg.assert_called_once_with(123, signal.SIGCONT)
    assert (tmp_path / "manual-resume").exists()


def test_resume_rejects_running_server(tmp_path):
    write_state(tmp_path, state="running")
    with patch.object(palworld_control, "read_start_ticks", return_value=42):
        with pytest.raises(RuntimeError, match="not paused"):
            palworld_control.resume(tmp_path)
