"""Tests for the SteamCMD client."""

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

    @patch('subprocess.run')
    def test_run_command_success(self, mock_run, manager, tmp_path):
        """FS-7.2: Successful SteamCMD execution."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = manager.run_command(["+quit"])
        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_run_command_failure(self, mock_run, manager, tmp_path):
        """FS-7.2: Failed SteamCMD execution."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        mock_run.return_value = MagicMock(returncode=1, stdout="error", stderr="fail")

        result = manager.run_command(["+quit"])
        assert result is False

    @patch('subprocess.run')
    def test_run_command_sets_env_vars(self, mock_run, manager, tmp_path):
        """FS-7.3: SteamCMD env vars are set."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        manager.run_command(["+quit"])
        call_kwargs = mock_run.call_args[1]
        env = call_kwargs['env']
        assert 'STEAM_COMPAT_DATA_PATH' in env
        assert 'STEAM_COMPAT_CLIENT_INSTALL_PATH' in env
        args, _ = mock_run.call_args
        assert "FEXBash" in args[0]

    @patch('subprocess.run')
    def test_run_command_timeout(self, mock_run, manager, tmp_path):
        """FS-7.4: Timeout handling."""
        script = tmp_path / "steamcmd.sh"
        script.write_text("#!/bin/bash")
        script.chmod(0o755)
        manager.steamcmd_script = script
        manager.steamcmd_path = tmp_path

        mock_run.side_effect = TimeoutError("timeout")

        result = manager.run_command(["+quit"], timeout=10)
        assert result is False
