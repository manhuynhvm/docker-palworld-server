"""Tests for the lifecycle manager."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.managers.lifecycle_manager import (
    ServerLifecycleManager, ServerState, verify_server_startup
)


class TestLifecycleManager:
    """FS-9.x: Lifecycle manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_logger):
        pm = MagicMock()
        pm.start_server = AsyncMock(return_value=True)
        pm.stop_server = AsyncMock(return_value=True)
        pm.is_server_running = MagicMock(return_value=True)
        pm.get_server_status = MagicMock(return_value={
            'running': True, 'pid': 12345, 'uptime': 3600
        })
        pm.server_process = MagicMock()
        pm.server_process.pid = 12345
        return ServerLifecycleManager(palworld_config, mock_logger, process_manager=pm)

    @pytest.mark.asyncio
    async def test_start_success(self, manager):
        """FS-9.1: Start delegates to process manager."""
        result = await manager.start()
        assert result is True
        manager.process_manager.start_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_failure(self, manager):
        """FS-9.1: Start failure returns False."""
        manager.process_manager.start_server = AsyncMock(return_value=False)
        result = await manager.start()
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_graceful(self, manager):
        """FS-9.2: Graceful stop delegates."""
        result = await manager.stop(graceful=True)
        assert result is True
        manager.process_manager.stop_server.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restart_success(self, manager):
        """FS-9.4: Successful restart."""
        result = await manager.restart()
        assert result is True
        manager.process_manager.stop_server.assert_awaited()
        assert manager.process_manager.start_server.await_count >= 1

    @pytest.mark.asyncio
    async def test_restart_stop_fails(self, manager):
        """FS-9.4: Restart fails if stop fails."""
        manager.process_manager.stop_server = AsyncMock(return_value=False)
        result = await manager.restart()
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_startup(self, manager):
        """FS-9.5: Verify delegates to helper."""
        result = await manager.verify_startup()
        assert result is True

    def test_get_server_status(self, manager):
        """FS-9: Status delegation."""
        status = manager.get_server_status()
        assert status["running"] is True



    @pytest.mark.asyncio
    async def test_stop_already_stopped(self, manager):
        """FS-9.3: Stop returns True when already stopped."""
        manager.process_manager.is_server_running = MagicMock(return_value=False)
        result = await manager.stop(graceful=True)
        assert result is True

    @pytest.mark.asyncio
    async def test_restart_start_fails(self, manager):
        """FS-9.4: Restart fails if start fails after stop."""
        manager.process_manager.stop_server = AsyncMock(return_value=True)
        manager.process_manager.start_server = AsyncMock(return_value=False)
        result = await manager.restart()
        assert result is False

class TestVerifyServerStartup:
    """FS-9.5: verify_server_startup function."""

    @pytest.mark.asyncio
    async def test_not_running(self):
        pm = MagicMock()
        pm.is_server_running = MagicMock(return_value=False)
        result = await verify_server_startup(pm, max_wait_time=5)
        assert result is False


class TestSerializedLifecycle:
    @pytest.mark.asyncio
    async def test_config_recycle_is_terminal_and_installs_while_locked(
        self, palworld_config, mock_logger
    ):
        pm = MagicMock()
        pm.update_runtime_state = MagicMock()
        pm.stop_server = AsyncMock(return_value=True)
        pm.is_server_running.return_value = True
        manager = ServerLifecycleManager(
            palworld_config, mock_logger, process_manager=pm
        )
        manager._state = ServerState.RUNNING
        installed = MagicMock()

        assert await manager.recycle_config(installed, "config change") is True
        installed.assert_called_once_with()
        assert manager.state == ServerState.STOPPED
        assert await manager.start() is False

    @pytest.mark.asyncio
    async def test_config_install_failure_recovers_server(
        self, palworld_config, mock_logger
    ):
        pm = MagicMock()
        pm.update_runtime_state = MagicMock()
        pm.stop_server = AsyncMock(return_value=True)
        pm.start_server = AsyncMock(return_value=True)
        pm.is_server_running.return_value = True
        manager = ServerLifecycleManager(
            palworld_config, mock_logger, process_manager=pm
        )
        manager._state = ServerState.RUNNING

        def fail_install():
            raise OSError("disk error")

        with patch(
            "src.managers.lifecycle_manager.verify_server_startup",
            new=AsyncMock(return_value=True),
        ):
            assert await manager.recycle_config(fail_install, "config change") is False

        pm.start_server.assert_awaited_once()
        assert manager.state == ServerState.RUNNING

    @pytest.mark.asyncio
    async def test_restart_resumes_paused_process_before_stop(
        self, palworld_config, mock_logger
    ):
        pm = MagicMock()
        pm.update_runtime_state = MagicMock()
        pm.resume_server = AsyncMock(return_value=True)
        pm.stop_server = AsyncMock(return_value=True)
        pm.start_server = AsyncMock(return_value=True)
        pm.is_server_running.return_value = True
        manager = ServerLifecycleManager(
            palworld_config, mock_logger, process_manager=pm
        )
        manager._state = ServerState.PAUSED

        with patch(
            "src.managers.lifecycle_manager.verify_server_startup",
            new=AsyncMock(return_value=True),
        ), patch("asyncio.sleep", new=AsyncMock()):
            assert await manager.restart() is True

        pm.resume_server.assert_awaited_once()
        pm.stop_server.assert_awaited_once()
        assert manager.state == ServerState.RUNNING

    @pytest.mark.asyncio
    async def test_lifecycle_lock_serializes_restart_and_pause(
        self, palworld_config, mock_logger
    ):
        stop_entered = asyncio.Event()
        allow_stop = asyncio.Event()

        async def slow_stop(*args):
            stop_entered.set()
            await allow_stop.wait()
            return True

        pm = MagicMock()
        pm.update_runtime_state = MagicMock()
        pm.stop_server = AsyncMock(side_effect=slow_stop)
        pm.start_server = AsyncMock(return_value=True)
        pm.pause_server = AsyncMock(return_value=True)
        pm.is_server_running.return_value = True
        manager = ServerLifecycleManager(
            palworld_config, mock_logger, process_manager=pm
        )
        manager._state = ServerState.RUNNING
        real_sleep = asyncio.sleep

        with patch(
            "src.managers.lifecycle_manager.verify_server_startup",
            new=AsyncMock(return_value=True),
        ), patch("asyncio.sleep", new=AsyncMock()):
            restart_task = asyncio.create_task(manager.restart())
            await stop_entered.wait()
            pause_task = asyncio.create_task(manager.pause())
            await real_sleep(0)
            pm.pause_server.assert_not_awaited()
            allow_stop.set()
            assert await restart_task is True
            assert await pause_task is True

        pm.pause_server.assert_awaited_once()
        assert manager.state == ServerState.PAUSED

    @pytest.mark.asyncio
    async def test_running_and_stable(self):
        pm = MagicMock()
        pm.is_server_running = MagicMock(return_value=True)
        result = await verify_server_startup(pm, max_wait_time=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_crashes_during_check(self):
        pm = MagicMock()
        pm.is_server_running = MagicMock(side_effect=[True, True, False])
        result = await verify_server_startup(pm, max_wait_time=5)
        assert result is False
