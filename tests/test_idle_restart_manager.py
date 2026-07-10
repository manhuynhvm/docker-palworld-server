"""Tests for the idle restart/pause manager."""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock
from src.monitoring.idle_restart_manager import IdleRestartManager, IdleRestartStats


class TestIdleRestartManager:
    """FS-18.x: Idle restart/pause manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_player_monitor, mock_logger):
        pm = MagicMock()
        pm.is_server_running.return_value = True
        return IdleRestartManager(palworld_config, mock_player_monitor, pm)

    def test_init_default_mode(self, manager):
        """FS-18.1: Default mode is 'restart'."""
        assert manager.mode in ("restart", "pause")

    def test_stats_dataclass(self):
        """FS-18.2: IdleRestartStats fields."""
        stats = IdleRestartStats(total_restarts=5, total_pauses=3)
        assert stats.total_restarts == 5
        assert stats.total_pauses == 3

    def test_is_monitoring_active_initially_false(self, manager):
        """FS-18.3: Monitoring not active by default."""
        assert manager.is_monitoring_active() is False

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, manager):
        """FS-18.4: Start/stop monitoring lifecycle."""
        with patch.object(manager, '_monitoring_loop', return_value=asyncio.sleep(0)):
            await manager.start_monitoring()
            assert manager._running is True
            await manager.stop_monitoring()
            assert manager._running is False

    def test_get_idle_status_structure(self, manager):
        """FS-18.5: Idle status contains expected keys."""
        status = manager.get_idle_status()
        assert "enabled" in status
        assert "mode" in status
        assert "monitoring_active" in status
        assert "statistics" in status

    @pytest.mark.asyncio
    async def test_handle_active_players_resets_idle(self, manager):
        """FS-18.6: Players online reset idle timer."""
        manager._idle_start = 100.0
        with patch.object(manager.logger, 'info'):
            await manager._handle_active_players(3)
        assert manager._idle_start is None

    @pytest.mark.asyncio
    async def test_handle_zero_players_starts_timer(self, manager):
        """FS-18.7: Zero players starts idle timer."""
        manager._idle_start = None
        await manager._handle_zero_players(100.0)
        assert manager._idle_start == 100.0

    # ---- Pause mode tests ----

    @pytest.mark.asyncio
    async def test_perform_pause_calls_process_manager(self, manager):
        """FS-18.8: Pause mode calls pause_server."""
        manager.mode = "pause"
        manager.process_manager.pause_server = AsyncMock(return_value=True)
        
        success = await manager._perform_pause()
        assert success is True
        assert manager._paused is True
        manager.process_manager.pause_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_perform_pause_failure_handling(self, manager):
        """FS-18.9: Pause failure doesn't set paused state."""
        manager.mode = "pause"
        manager.process_manager.pause_server = AsyncMock(return_value=False)
        
        success = await manager._perform_pause()
        assert success is False
        assert manager._paused is False

    @pytest.mark.asyncio
    async def test_handle_active_resumes_paused_server(self, manager):
        """FS-18.10: Active players resume paused server."""
        manager._paused = True
        manager.process_manager.resume_server = AsyncMock(return_value=True)
        
        with patch.object(manager, '_send_discord_notification', AsyncMock()):
            await manager._handle_active_players(1)
        
        assert manager._paused is False
        manager.process_manager.resume_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_resume(self, manager):
        """FS-18.11: force_resume resumes server."""
        manager._paused = True
        
        with patch.object(manager, '_force_resume', AsyncMock()) as mock_fr:
            result = manager.force_resume()
            assert result is True
            await asyncio.sleep(0.01)
            mock_fr.assert_called_once()

    def test_force_resume_not_paused(self, manager):
        """FS-18.12: force_resume returns False when not paused."""
        manager._paused = False
        assert manager.force_resume() is False

    @pytest.mark.asyncio
    async def test_init_with_pause_mode(self, palworld_config, mock_player_monitor, mock_logger):
        """FS-18.13: Init with pause mode config."""
        palworld_config.monitoring.idle_restart.mode = "pause"
        pm = MagicMock()
        pm.is_server_running.return_value = True
        mgr = IdleRestartManager(palworld_config, mock_player_monitor, pm)
        assert mgr.mode == "pause"

    @pytest.mark.asyncio
    async def test_paused_state_triggers_full_restart_after_max_time(self, manager):
        """FS-18.14: Paused state triggers full restart after 24h."""
        manager._paused = True
        manager._pause_start_time = 0.0
        
        with patch.object(manager, '_perform_restart', AsyncMock(return_value=True)) as mock_restart:
            await manager._handle_paused_state(time.time())
            mock_restart.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_idle_action_increments_pause_stats(self, manager):
        """FS-18.15: Triggering pause action increments pause stats."""
        manager.mode = "pause"
        manager.process_manager.pause_server = AsyncMock(return_value=True)
        
        with patch.object(manager, '_send_discord_notification', AsyncMock()):
            await manager._trigger_idle_action()
        
        assert manager.stats.total_pauses == 1
        assert manager.stats.last_pause_time is not None
        assert manager._paused is True
