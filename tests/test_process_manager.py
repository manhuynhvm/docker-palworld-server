"""Tests for the process manager (including signal delivery and pause/resume)."""

import pytest
import asyncio
import signal
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from src.managers.process_manager import ProcessManager


class TestProcessManager:
    """FS-10.x: Process manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_logger):
        return ProcessManager(palworld_config, mock_logger)

    def test_init(self, manager):
        """FS-10.1: Manager initializes without errors."""
        assert manager is not None
        assert manager.server_process is None

    def test_is_server_running_none(self, manager):
        """FS-10.2: Returns False when process is None."""
        assert manager.is_server_running() is False

    def test_is_server_running_poll_returns_none(self, manager):
        """FS-10.3: Returns True when process.poll() returns None."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        assert manager.is_server_running() is True

    def test_is_server_running_poll_returns_int(self, manager):
        """FS-10.4: Returns False when process has exited."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        manager.server_process = mock_process
        assert manager.is_server_running() is False

    def test_get_server_status_not_running(self, manager):
        """FS-10.5: Status returns not-running info."""
        status = manager.get_server_status()
        assert status["running"] is False
        assert status["pid"] is None

    def test_get_startup_options_summary(self, manager):
        """FS-10.6: Options summary returns dict."""
        summary = manager.get_startup_options_summary()
        assert "performance_optimization" in summary
        assert "query_port" in summary

    # ---- Signal / hot-reload tests ----

    def test_send_signal_not_running(self, manager):
        """FS-10.7: send_signal returns False when server not running."""
        result = asyncio.run(manager.send_signal(signal.SIGHUP))
        assert result is False

    def test_send_signal_success(self, manager):
        """FS-10.8: send_signal sends signal to process group."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        
        with patch('os.killpg') as mock_killpg:
            result = asyncio.run(manager.send_signal(signal.SIGHUP))
            assert result is True
            mock_killpg.assert_called_once_with(12345, signal.SIGHUP)

    def test_send_signal_process_lookup_error(self, manager):
        """FS-10.9: send_signal returns False on ProcessLookupError."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        
        with patch('os.killpg', side_effect=ProcessLookupError):
            result = asyncio.run(manager.send_signal(signal.SIGHUP))
            assert result is False

    def test_reload_config_not_running(self, manager):
        """FS-10.10: reload_config returns False when server not running."""
        result = asyncio.run(manager.reload_config())
        assert result is False

    def test_reload_config_success(self, manager):
        """FS-10.11: reload_config sends SIGHUP to server."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        
        with patch('os.killpg') as mock_killpg:
            result = asyncio.run(manager.reload_config())
            assert result is True
            mock_killpg.assert_called_once_with(12345, signal.SIGHUP)

    # ---- Pause / Resume tests ----

    def test_pause_server_sends_sigstop(self, manager):
        """FS-10.12: pause_server sends SIGSTOP."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        
        with patch('os.killpg') as mock_killpg:
            result = asyncio.run(manager.pause_server())
            assert result is True
            mock_killpg.assert_called_once_with(12345, signal.SIGSTOP)

    def test_resume_server_sends_sigcont(self, manager):
        """FS-10.13: resume_server sends SIGCONT."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        manager.server_process = mock_process
        
        with patch('os.killpg') as mock_killpg:
            result = asyncio.run(manager.resume_server())
            assert result is True
            mock_killpg.assert_called_once_with(12345, signal.SIGCONT)

    def test_pause_server_not_running(self, manager):
        """FS-10.14: pause_server returns False when not running."""
        result = asyncio.run(manager.pause_server())
        assert result is False
