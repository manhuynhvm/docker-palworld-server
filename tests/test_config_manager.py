"""Tests for the config file manager (including hot-reload)."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from src.managers.config_manager import ConfigManager


class TestConfigManager:
    """FS-11.x: Config manager behavior."""

    @pytest.fixture
    def manager(self, palworld_config, mock_logger):
        return ConfigManager(palworld_config, mock_logger)

    def test_init_creates_default_generator(self, palworld_config, mock_logger):
        """FS-11.1: Default SettingsGenerator created when none provided."""
        mgr = ConfigManager(palworld_config, mock_logger)
        assert mgr.generator is not None

    def test_generate_server_settings_success(self, manager, tmp_path):
        """FS-11.1+11.2: Generates PalWorldSettings.ini."""
        manager.config_dir = tmp_path
        manager.generator.generate_server_settings = MagicMock(return_value="content")
        result = manager.generate_server_settings()
        assert result is True
        assert (tmp_path / "PalWorldSettings.ini").exists()
        assert (tmp_path / "PalWorldSettings.ini").read_text() == "content"

    def test_generate_server_settings_creates_dir(self, manager, tmp_path):
        """FS-11.2: Creates directory if missing."""
        config_dir = tmp_path / "new" / "dir"
        manager.config_dir = config_dir
        manager.generator.generate_server_settings = MagicMock(return_value="content")
        result = manager.generate_server_settings()
        assert result is True
        assert config_dir.exists()

    def test_generate_server_settings_failure(self, manager):
        """FS-11.3: Returns False on failure."""
        manager.generator.generate_server_settings = MagicMock(side_effect=Exception("fail"))
        result = manager.generate_server_settings()
        assert result is False

    def test_generate_engine_settings_success(self, manager, tmp_path):
        """FS-11.1: Generates Engine.ini."""
        manager.config_dir = tmp_path
        manager.generator.generate_engine_settings = MagicMock(return_value="engine")
        result = manager.generate_engine_settings()
        assert result is True
        assert (tmp_path / "Engine.ini").read_text() == "engine"

    def test_generate_engine_settings_failure(self, manager):
        """FS-11.3: Returns False on failure."""
        manager.generator.generate_engine_settings = MagicMock(side_effect=Exception("fail"))
        result = manager.generate_engine_settings()
        assert result is False

    # ---- Hot-reload tests ----

    def test_reload_and_apply_calls_both_generators(self, manager):
        """FS-11.4: reload_and_apply regenerates both config files."""
        with patch.object(manager, 'generate_server_settings', return_value=True) as mock_srv, \
             patch.object(manager, 'generate_engine_settings', return_value=True) as mock_eng:
            result = manager.reload_and_apply()
            assert result is True
            mock_srv.assert_called_once()
            mock_eng.assert_called_once()

    def test_reload_and_apply_failure_returns_false(self, manager):
        """FS-11.5: reload_and_apply returns False when both fail."""
        with patch.object(manager, 'generate_server_settings', return_value=False) as mock_srv, \
             patch.object(manager, 'generate_engine_settings', return_value=False) as mock_eng:
            result = manager.reload_and_apply()
            assert result is False

    def test_reload_and_apply_partial_ok(self, manager):
        """FS-11.6: reload_and_apply returns True if at least one succeeds."""
        with patch.object(manager, 'generate_server_settings', return_value=True) as mock_srv, \
             patch.object(manager, 'generate_engine_settings', return_value=False) as mock_eng:
            result = manager.reload_and_apply()
            assert result is True

    @pytest.mark.asyncio
    async def test_watch_config_detects_change(self, manager, tmp_path):
        """FS-11.7: watch_config detects YAML changes and triggers callback."""
        # Make config path point to temp
        config_path = tmp_path / "config" / "default.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("initial: value\n")
        
        # Monkey-patch _check_yaml_changed to simulate change
        manager._check_yaml_changed = MagicMock(side_effect=[False, True])
        
        callback = AsyncMock()
        
        # Run watch for a limited time
        import asyncio
        task = asyncio.create_task(manager.watch_config(
            check_interval=0.1,
            on_change=callback
        ))
        
        # Let it run a couple cycles
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Callback should have been invoked when _check_yaml_changed returned True
        assert callback.called

    def test_is_watching_initially_false(self, manager):
        """FS-11.8: is_watching returns False initially."""
        assert manager.is_watching() is False

    @pytest.mark.asyncio
    async def test_start_stop_watching(self, manager):
        """FS-11.9: start_watching and stop_watching lifecycle."""
        import asyncio
        with patch.object(manager, 'watch_config', return_value=asyncio.sleep(0)):
            await manager.start_watching()
            # Task was created and cancelled immediately
            await manager.stop_watching()

    @pytest.mark.asyncio
    async def test_start_watching_twice_warns(self, manager):
        """FS-11.10: Starting watcher twice logs warning."""
        import asyncio
        with patch.object(manager, 'watch_config', return_value=asyncio.sleep(0)):
            await manager.start_watching()
            with patch.object(manager.logger, 'warning') as mock_warn:
                await manager.start_watching()
                mock_warn.assert_called_once()
            await manager.stop_watching()
