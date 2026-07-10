"""Tests for the monitoring manager."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.monitoring.monitoring_manager import MonitoringManager
import asyncio
from src.monitoring.player_monitor import PlayerEventType


class TestMonitoringManager:
    """FS-13.2.x: Monitoring manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_process_manager, mock_api_facade):
        return MonitoringManager(
            palworld_config, mock_process_manager, mock_api_facade
        )

    def test_initialization(self, manager):
        """FS-13.2.1: All monitors initialized."""
        assert manager.player_monitor is not None
        assert manager.server_monitor is not None
        assert manager.event_dispatcher is not None
        assert manager.idle_restart_manager is not None

    def test_setup_event_callbacks(self, manager):
        """FS-13.2.5: Event callbacks registered (system callbacks only)."""
        # Verify that after init, callbacks are set up properly
        cb_count = len(manager.player_monitor._event_callbacks.get(
            PlayerEventType.JOINED, []
        ))
        assert cb_count > 0

    def test_get_monitoring_status(self, manager):
        """FS-13.2: Full monitoring status."""
        manager.player_monitor.get_current_players = MagicMock(return_value=set())
        manager.player_monitor.get_current_player_count = MagicMock(return_value=0)
        manager.server_monitor.get_last_status = MagicMock(return_value=None)
        manager.idle_restart_manager.get_idle_status = MagicMock(
            return_value={"enabled": True}
        )
        manager._monitoring_active = True

        status = manager.get_monitoring_status()
        assert "monitoring_active" in status
        assert status["monitoring_active"] is True
        assert "player_count" in status
        assert "background_tasks" in status

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, manager):
        """FS-13.2.1: Start and stop monitoring lifecycle."""
        manager.player_monitor.start_monitoring = AsyncMock()
        manager.server_monitor.start_monitoring = AsyncMock()
        manager.idle_restart_manager.start_monitoring = AsyncMock()

        await manager.start_monitoring()
        assert manager._monitoring_active is True

        # start_monitoring uses asyncio.create_task internally, so yield to event loop
        await asyncio.sleep(0)

        # discord.enabled is False in fixture, so player_monitor is skipped
        manager.player_monitor.start_monitoring.assert_not_called()
        # server and idle_restart are always started
        manager.server_monitor.start_monitoring.assert_called()
        manager.idle_restart_manager.start_monitoring.assert_called()

        await manager.stop_monitoring()
        assert manager._monitoring_active is False

    def test_is_monitoring_active(self, manager):
        """FS-13.2: Active state tracking."""
        assert manager.is_monitoring_active() is False
        manager._monitoring_active = True
        assert manager.is_monitoring_active() is True

    @pytest.mark.asyncio
    async def test_handle_backup_completion(self, manager):
        """FS-13.2.5: Backup events forwarded to dispatcher."""
        manager.event_dispatcher.handle_backup_completion = AsyncMock()
        await manager.handle_backup_completion({"file": "backup.tar.gz"})
        manager.event_dispatcher.handle_backup_completion.assert_awaited_with(
            {"file": "backup.tar.gz"}
        )

    @pytest.mark.asyncio
    async def test_handle_error(self, manager):
        """FS-13.2.5: Errors forwarded to dispatcher."""
        manager.event_dispatcher.handle_error_event = AsyncMock()
        await manager.handle_error("Something went wrong")
        manager.event_dispatcher.handle_error_event.assert_awaited_with(
            "Something went wrong", None
        )

    def test_reset_callbacks(self, manager):
        """FS-13.2.5: Callback reset."""
        manager._setup_event_callbacks = MagicMock()
        manager.reset_callbacks()
        manager._setup_event_callbacks.assert_called_once()
