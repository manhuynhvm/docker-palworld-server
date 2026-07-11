"""Tests for the SteamCMD client."""

import subprocess
import pytest
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from src.clients.steamcmd_client import SteamCMDManager


class TestSteamCMDClient:
    """FS-7.x: SteamCMD client behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_logger):
        return SteamCMDManager(palworld_config.paths.steamcmd_dir, mock_logger)

    def test_validate_steamcmd_not_found(self, manager):
        """FS-7.1: Validate returns False when script missing."""
        manager.steamcmd_script = Path("/nonexistent/steamcmd.sh")
        assert manager.validate_steamcmd() is False

    def test_validate_steamcmd_not_executable(self, manager, tmp_path):
        """FS-7.1: Validate sets execute bit if missing."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash\necho steamcmd")
        script.chmod(0o644)
        manager.steamcmd_script = script
        result = manager.validate_steamcmd()
        assert result is True
        # Check execute bit was set
        mode = script.stat().st_mode
        assert mode & stat.S_IEXEC

    def test_run_command_validates_first(self, manager):
        """FS-7.1: run_command returns False if validation fails."""
        manager.steamcmd_script = Path("/nonexistent/steamcmd.sh")
        result = manager.run_command(["+quit"])
        assert result is False

    # ------------------------------------------------------------------
    # Helper: build a mock Popen process whose stdout/stderr readline()
    # returns the provided lines then '' (signalling EOF).
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_process(returncode=0, stdout_lines=None, stderr_lines=None):
        proc = MagicMock()
        proc.wait.return_value = returncode

        def _make_stream(lines):
            stream = MagicMock()
            if not lines:
                stream.readline.return_value = ''
            else:
                it = iter(list(lines) + [''])
                stream.readline.side_effect = lambda: next(it)
            stream.close = MagicMock()
            return stream

        proc.stdout = _make_stream(stdout_lines)
        proc.stderr = _make_stream(stderr_lines)
        return proc

    # ------------------------------------------------------------------
    # run_command tests  (now mock Popen instead of subprocess.run)
    # ------------------------------------------------------------------
    @patch('subprocess.Popen')
    def test_run_command_success(self, mock_popen, manager, tmp_path):
        """FS-7.2: Successful SteamCMD execution."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        # Warmup process + real command process, both succeed
        mock_popen.side_effect = [
            self._mock_process(returncode=0),
            self._mock_process(returncode=0),
        ]

        result = manager.run_command(["+quit"])
        assert result is True
        assert mock_popen.call_count == 2

    @patch('subprocess.Popen')
    def test_run_command_failure(self, mock_popen, manager, tmp_path):
        """FS-7.2: Failed SteamCMD execution."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        # Warmup succeeds, real command fails
        mock_popen.side_effect = [
            self._mock_process(returncode=0),
            self._mock_process(returncode=1, stderr_lines=["error"]),
        ]

        result = manager.run_command(["+quit"])
        assert result is False

    @patch('subprocess.Popen')
    def test_run_command_sets_env_vars(self, mock_popen, manager, tmp_path):
        """FS-7.3: SteamCMD env vars are set."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        mock_popen.side_effect = [
            self._mock_process(returncode=0),
            self._mock_process(returncode=0),
        ]

        manager.run_command(["+quit"])

        # Check the second call (index 1) = the actual command
        call_args, call_kwargs = mock_popen.call_args_list[1]
        env = call_kwargs['env']
        assert 'STEAM_COMPAT_DATA_PATH' in env
        assert 'STEAM_COMPAT_CLIENT_INSTALL_PATH' in env
        assert "FEXBash" in call_args[0]

    @patch('subprocess.Popen')
    def test_run_command_timeout(self, mock_popen, manager, tmp_path):
        """FS-7.4: Timeout handling."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        # Warmup succeeds; real command times out
        warmup_proc = self._mock_process(returncode=0)
        timeout_proc = MagicMock()
        timeout_proc.stdout.readline.return_value = ''
        timeout_proc.stderr.readline.return_value = ''
        timeout_proc.stdout.close = MagicMock()
        timeout_proc.stderr.close = MagicMock()
        timeout_proc.wait.side_effect = subprocess.TimeoutExpired("FEXBash", 10)

        mock_popen.side_effect = [warmup_proc, timeout_proc]

        result = manager.run_command(["+quit"], timeout=10)
        assert result is False
