"""Integration tests for the main server manager."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.server_manager import (
    PalworldServerManager, wait_for_api_ready
)
from src.container import ServiceContainer
from src.managers.lifecycle_manager import ServerLifecycleManager, ServerState
from src.managers.api_facade import ServerAPIFacade
from src.managers.settings_generator import SettingsGenerator
from src.managers.process_manager import ProcessManager


class TestPalworldServerManager:
    """FS-13.x: Server manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config):
        container = ServiceContainer()

        lifecycle = MagicMock(spec=ServerLifecycleManager)
        lifecycle.start = AsyncMock(return_value=True)
        lifecycle.stop = AsyncMock(return_value=True)
        lifecycle.shutdown = AsyncMock(return_value=True)
        lifecycle.recycle_config = AsyncMock(return_value=True)
        lifecycle.state = MagicMock()
        lifecycle.verify_startup = AsyncMock(return_value=True)
        lifecycle.get_server_status = MagicMock(return_value={
            'running': True, 'pid': 12345, 'uptime': 3600
        })
        lifecycle.process_manager = MagicMock(spec=ProcessManager)
        lifecycle.process_manager.is_server_running = MagicMock(return_value=True)
        lifecycle.process_manager.stop_server = AsyncMock(return_value=True)
        lifecycle.process_manager.start_server = AsyncMock(return_value=True)
        lifecycle.process_manager.get_server_status = MagicMock(return_value={
            'running': True, 'pid': 12345, 'uptime': 3600
        })
        container.register(ServerLifecycleManager, lifecycle)

        api_facade = MagicMock(spec=ServerAPIFacade)
        api_facade.initialize_clients = AsyncMock()
        api_facade.cleanup_clients = AsyncMock()
        api_facade.disable_rest = MagicMock()
        api_facade.get_api_client = MagicMock(return_value=MagicMock())
        api_facade.get_server_info = AsyncMock(return_value=MagicMock())
        api_facade.get_players = AsyncMock(return_value=[])
        api_facade.announce = AsyncMock(return_value=True)
        api_facade.save_world = AsyncMock(return_value=True)
        api_facade.api_get_server_metrics = AsyncMock(return_value={"cpu": 45})
        container.register(ServerAPIFacade, api_facade)

        settings_gen = MagicMock(spec=SettingsGenerator)
        settings_gen.generate_server_settings = MagicMock(return_value="content")
        settings_gen.write_server_settings = MagicMock(return_value=True)
        settings_gen.generate_engine_settings = MagicMock(return_value="engine")
        settings_gen.write_engine_settings = MagicMock(return_value=True)
        container.register(SettingsGenerator, settings_gen)

        m = PalworldServerManager(config=palworld_config, container=container)

        # Mock monitoring manager
        m.monitoring_manager = MagicMock()
        m.monitoring_manager.start_monitoring = AsyncMock()
        m.monitoring_manager.stop_monitoring = AsyncMock()
        m.monitoring_manager.handle_error = AsyncMock()
        m.monitoring_manager.get_monitoring_status = MagicMock(return_value={
            'monitoring_active': True, 'player_count': 0
        })

        # Mock steamcmd
        m.steamcmd_manager = MagicMock()
        m.steamcmd_manager.run_command = MagicMock(return_value=True)

        return m

    @pytest.mark.asyncio
    async def test_server_startup_success(self, manager):
        """FS-13.1.4: Full startup succeeds (wait_for_api_ready mocked)."""
        mock_readiness = AsyncMock(return_value=True)
        with patch('src.server_manager.wait_for_api_ready', new=mock_readiness):
            result = await manager.start_server_with_verification()
        assert result is True
        assert manager._startup_completed is True
        mock_readiness.assert_awaited_once_with(manager, max_wait_time=60, check_interval=2)

    @pytest.mark.asyncio
    async def test_server_startup_rest_api_disabled(self, manager):
        """FS-13.1.4: REST API disabled skips readiness check."""
        manager.config.rest_api.enabled = False
        mock_readiness = AsyncMock(return_value=True)
        with patch('src.server_manager.wait_for_api_ready', new=mock_readiness):
            result = await manager.start_server_with_verification()
        assert result is True
        assert manager._startup_completed is True
        mock_readiness.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_server_startup_lifecycle_fails(self, manager):
        """FS-13.1.4: Startup fails when lifecycle fails."""
        manager.lifecycle_manager.start = AsyncMock(return_value=False)
        result = await manager.start_server_with_verification()
        assert result is False
        assert manager._startup_completed is False

    @pytest.mark.asyncio
    async def test_server_startup_stability_fails(self, manager):
        """Lifecycle start owns stability verification; it is not repeated."""
        with patch('src.server_manager.wait_for_api_ready', new=AsyncMock(return_value=True)):
            result = await manager.start_server_with_verification()
        assert result is True
        manager.lifecycle_manager.verify_startup.assert_not_awaited()

    def test_is_server_running(self, manager):
        """FS-13: Running status."""
        assert manager.is_server_running() is True

    def test_intentional_restart_downtime_is_not_terminal(self, manager):
        manager.lifecycle_manager.state = ServerState.RESTARTING
        manager.process_manager.is_server_running.return_value = False
        assert manager.has_unexpected_process_exit() is False

    def test_running_process_exit_is_terminal(self, manager):
        manager.lifecycle_manager.state = ServerState.RUNNING
        manager.process_manager.is_server_running.return_value = False
        assert manager.has_unexpected_process_exit() is True

    @pytest.mark.asyncio
    async def test_start_server_delegates(self, manager):
        """FS-13.1.4: Start delegates."""
        result = await manager.start_server()
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_server(self, manager):
        """FS-13.3.1: Stop delegates."""
        result = await manager.stop_server()
        assert result is True

    @pytest.mark.asyncio
    async def test_cleanup_closes_api_after_graceful_stop(self, manager):
        order = []
        manager.config_manager.stop_watching = AsyncMock()
        manager.monitoring_manager.stop_monitoring = AsyncMock()
        manager.lifecycle_manager.shutdown = AsyncMock(
            side_effect=lambda *args: order.append("stop") or True
        )
        manager.api_facade.cleanup_clients = AsyncMock(
            side_effect=lambda: order.append("cleanup")
        )

        await manager.__aexit__(None, None, None)

        assert order == ["stop", "cleanup"]

    @pytest.mark.asyncio
    async def test_validated_config_stops_then_installs_and_recycles(self, manager):
        staged = MagicMock()
        order = []
        manager.monitoring_manager.stop_monitoring = AsyncMock()
        async def recycle(installer, *args):
            order.append("stop")
            installer()
            return True

        manager.lifecycle_manager.recycle_config = AsyncMock(
            side_effect=recycle
        )
        manager.config_manager.install_staged = MagicMock(
            side_effect=lambda value: order.append("install")
        )

        assert await manager.apply_config_and_recycle(staged) is True

        assert order == ["stop", "install"]
        assert manager._shutdown_event.is_set()
        assert manager._exit_code == 75

    def test_generate_server_settings(self, manager):
        """FS-13.1.3: Settings generation."""
        assert manager.generate_server_settings() is True

    def test_generate_engine_settings(self, manager):
        """FS-13.1.3: Engine settings."""
        assert manager.generate_engine_settings() is True

    def test_get_overall_status(self, manager):
        """FS-13.4: Comprehensive status."""
        status = manager.get_overall_status()
        assert "server" in status
        assert "monitoring" in status
        assert "startup_completed" in status
        assert "backup_enabled" in status

    def test_is_startup_completed(self, manager):
        """FS-13.4: Startup state."""
        assert manager.is_startup_completed() is False
        manager._startup_completed = True
        assert manager.is_startup_completed() is True

    def test_get_api_manager(self, manager):
        """FS-13.4: Accessor returns facade."""
        api = manager.get_api_manager()
        assert api is manager.api_facade

    def test_get_process_manager(self, manager):
        """FS-13.4: Process manager accessor."""
        pm = manager.get_process_manager()
        assert pm is manager.process_manager
        assert manager.container.resolve(ProcessManager) is pm

    @pytest.mark.asyncio
    async def test_api_get_players(self, manager):
        """FS-13.4: API delegation methods."""
        result = await manager.api_get_players()
        manager.api_facade.get_players.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_server_files(self, manager):
        """FS-13.1.2: SteamCMD download."""
        result = await manager.download_server_files()
        assert result is True

        manager.steamcmd_manager.run_command.assert_called_once_with([
            "+force_install_dir", str(manager.config.paths.server_dir),
            "+login", "anonymous",
            "+app_update", "2394010", "validate", "+quit",
        ], timeout=1800)

    @pytest.mark.asyncio
    async def test_download_server_files_at_target_manifest(self, manager, tmp_path):
        """A target manifest downloads and installs the Linux depot."""
        manager.config.paths.steamcmd_dir = tmp_path / "steamcmd"
        manager.config.paths.server_dir = tmp_path / "server"
        manager.config.steamcmd.target_manifest_id = 5125159522749666228
        depot_dir = (
            manager.config.paths.steamcmd_dir
            / "steamapps/content/app_2394010/depot_2394012"
        )
        depot_dir.mkdir(parents=True)
        (depot_dir / "PalServer.sh").write_text("pinned", encoding="utf-8")

        result = await manager.download_server_files()

        assert result is True
        manager.steamcmd_manager.run_command.assert_called_once_with([
            "+login", "anonymous",
            "+download_depot", "2394010", "2394012", "5125159522749666228",
            "+quit",
        ], timeout=1800)
        assert (manager.config.paths.server_dir / "PalServer.sh").read_text() == "pinned"

    @pytest.mark.asyncio
    async def test_target_manifest_fails_when_depot_is_missing(self, manager, tmp_path):
        manager.config.paths.steamcmd_dir = tmp_path / "steamcmd"
        manager.config.paths.server_dir = tmp_path / "server"
        manager.config.steamcmd.target_manifest_id = 5125159522749666228

        result = await manager.download_server_files()

        assert result is False
        manager.monitoring_manager.handle_error.assert_awaited_once_with(
            "Server file download failed"
        )


class TestWaitForApiReady:
    """FS-13.1.5: API readiness check."""

    def _make_async_context_manager(self, mock_obj):
        """Create an async context manager wrapper."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_obj)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    @pytest.mark.asyncio
    async def test_api_ready_returns_true(self):
        """FS-13.1.5: Returns True when API responds 200."""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._make_async_context_manager(mock_response))

        manager = MagicMock()
        manager.config.rest_api.host = "localhost"
        manager.config.rest_api.port = 8212
        manager.config.server.admin_password = "admin"

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await wait_for_api_ready(manager, max_wait_time=1, check_interval=1)
            assert result is True

    @pytest.mark.asyncio
    async def test_api_unauthorized_is_not_ready(self):
        """FS-13.1.5: 401 is a credential failure, not readiness."""
        mock_response = MagicMock()
        mock_response.status = 401

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._make_async_context_manager(mock_response))

        manager = MagicMock()
        manager.config.rest_api.host = "localhost"
        manager.config.rest_api.port = 8212
        manager.config.server.admin_password = "admin"

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await wait_for_api_ready(manager, max_wait_time=1, check_interval=1)
            assert result is False
            manager.api_facade.disable_rest.assert_called_once_with(
                "authentication failed (HTTP 401)"
            )

    @pytest.mark.asyncio
    async def test_api_timeout_returns_false(self):
        """FS-13.1.5: Returns False when API never responds."""
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=ConnectionError("refused"))

        manager = MagicMock()
        manager.config.rest_api.host = "localhost"
        manager.config.rest_api.port = 8212
        manager.config.server.admin_password = "admin"

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await wait_for_api_ready(manager, max_wait_time=1, check_interval=1)
            assert result is False
