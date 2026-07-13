#!/usr/bin/env python3
"""
Configuration file management for Palworld server
Handles file writing for PalWorldSettings.ini and Engine.ini.
All content generation is delegated to SettingsGenerator.
Supports validated configuration staging and controlled container recycling.
"""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Dict

from ..config_loader import ConfigLoader, PalworldConfig
from ..logging_setup import log_server_event
from .settings_generator import SettingsGenerator


@dataclass(frozen=True)
class StagedConfig:
    """Validated configuration and generated files awaiting installation."""

    config: PalworldConfig
    server_settings: str
    engine_settings: str


class ConfigManager:
    """Server configuration file management
    
    Delegates all INI content generation to SettingsGenerator.
    Only handles directory creation and file writing.
    Supports safe reload staging via polling-based file change detection.
    """
    
    def __init__(self, config: PalworldConfig, logger, generator: Optional[SettingsGenerator] = None):
        self.config = config
        self.logger = logger
        self.generator = generator or SettingsGenerator(config, logger)
        self.server_path = config.paths.server_dir
        self.config_dir = self.server_path / "Pal" / "Saved" / "Config" / "LinuxServer"
        self.config_path = Path("config/default.yaml")
        
        # Hot-reload state
        self._checksums: Dict[str, str] = {}
        self._watch_task: Optional[asyncio.Task] = None
        self._on_config_change: Optional[Callable] = None
    
    def generate_server_settings(self) -> bool:
        """Generate and write Palworld server settings file"""
        try:
            settings_file = self.config_dir / "PalWorldSettings.ini"
            self.config_dir.mkdir(parents=True, exist_ok=True)
            settings_content = self.generator.generate_server_settings()
            settings_file.write_text(settings_content, encoding='utf-8')
            self._update_checksum("server_settings", settings_content)
            log_server_event(self.logger, "config_generate",
                           "Server settings file generated successfully",
                           settings_file=str(settings_file))
            return True
        except Exception as e:
            log_server_event(self.logger, "config_generate_fail",
                           f"Failed to generate settings file: {e}")
            return False
    
    def generate_engine_settings(self) -> bool:
        """Generate and write Palworld engine settings file"""
        try:
            engine_file = self.config_dir / "Engine.ini"
            self.config_dir.mkdir(parents=True, exist_ok=True)
            engine_content = self.generator.generate_engine_settings()
            engine_file.write_text(engine_content, encoding='utf-8')
            self._update_checksum("engine_settings", engine_content)
            log_server_event(self.logger, "config_generate",
                           "Engine settings file generated successfully",
                           engine_file=str(engine_file))
            return True
        except Exception as e:
            log_server_event(self.logger, "config_generate_fail",
                           f"Failed to generate engine settings file: {e}")
            return False
    
    # ------------------------------------------------------------------
    # Hot-reload support
    # ------------------------------------------------------------------
    
    def _update_checksum(self, key: str, content: str) -> None:
        """Update internal checksum for change detection"""
        self._checksums[key] = hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _compute_checksums(self) -> Dict[str, str]:
        """Compute current checksums of managed config files"""
        result = {}
        for key, path in [("server_settings", self.config_dir / "PalWorldSettings.ini"),
                          ("engine_settings", self.config_dir / "Engine.ini")]:
            try:
                if path.exists():
                    content = path.read_text(encoding='utf-8')
                    result[key] = hashlib.sha256(content.encode('utf-8')).hexdigest()
                else:
                    result[key] = ""
            except Exception:
                result[key] = ""
        return result
    
    def _check_yaml_changed(self) -> bool:
        """Check if the source YAML config has changed since last generation"""
        config_path = self.config_path
        if not config_path.exists():
            return False
        try:
            content = config_path.read_text(encoding='utf-8')
            current_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            key = "yaml_config"
            if key not in self._checksums:
                self._checksums[key] = current_hash
                return False
            if self._checksums[key] != current_hash:
                self._checksums[key] = current_hash
                return True
        except Exception:
            pass
        return False
    
    def reload_and_apply(self) -> bool:
        """Compatibility helper: validate, stage, then atomically install."""
        try:
            staged = self.stage_reload()
            self.install_staged(staged)
            return True
        except Exception as e:
            log_server_event(self.logger, "config_reload_fail",
                           f"Configuration reload error: {e}")
            return False

    def stage_reload(self) -> StagedConfig:
        """Load fresh YAML, validate it, and generate content without live writes."""
        loader = ConfigLoader(self.config_path)
        config = loader.load_config()
        loader.validate_config(config)
        generator = SettingsGenerator(config, self.logger)
        return StagedConfig(
            config=config,
            server_settings=generator.generate_server_settings(),
            engine_settings=generator.generate_engine_settings(),
        )

    def install_staged(self, staged: StagedConfig) -> None:
        """Atomically install staged INI files after Palworld has stopped."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        targets = (
            (self.config_dir / "PalWorldSettings.ini", staged.server_settings),
            (self.config_dir / "Engine.ini", staged.engine_settings),
        )
        temporary_paths = []
        backup_paths = []
        installed_targets = []
        try:
            for target, content in targets:
                temporary = target.with_suffix(target.suffix + ".new")
                temporary.write_text(content, encoding="utf-8")
                temporary_paths.append((temporary, target))

            for _, target in temporary_paths:
                backup = target.with_suffix(target.suffix + ".previous")
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass
                if target.exists():
                    os.replace(target, backup)
                    backup_paths.append((backup, target))

            for temporary, target in temporary_paths:
                os.replace(temporary, target)
                installed_targets.append(target)
        except Exception:
            for target in installed_targets:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            for backup, target in reversed(backup_paths):
                os.replace(backup, target)
            raise
        finally:
            for temporary, _ in temporary_paths:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            for backup, _ in backup_paths:
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass
    
    async def watch_config(self, 
                           check_interval: int = 30,
                           on_change: Optional[Callable] = None) -> None:
        """Poll YAML config for changes and regenerate INI files on change.
        
        A changed file is validated and staged before the callback coordinates
        a graceful container recycle.
        
        Args:
            check_interval: Polling interval in seconds.
            on_change: Async callback receiving a :class:`StagedConfig`.
        """
        self._on_config_change = on_change
        
        log_server_event(self.logger, "config_watch_start",
                        f"Config file watching started (interval={check_interval}s)")
        
        while True:
            try:
                changed = self._check_yaml_changed()
                
                if changed:
                    self.logger.info("Configuration source changed; validating")
                    try:
                        staged = self.stage_reload()
                    except Exception as exc:
                        self.logger.error(
                            "Configuration change rejected", error=str(exc)
                        )
                    else:
                        if self._on_config_change:
                            await self._on_config_change(staged)
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Config watch error", error=str(e))
                await asyncio.sleep(5)
    
    async def start_watching(self, 
                              check_interval: int = 30,
                              on_change: Optional[Callable] = None) -> None:
        """Start the config watcher as a background task"""
        if self._watch_task is not None:
            self.logger.warning("Config watcher already running")
            return
        
        self._watch_task = asyncio.create_task(
            self.watch_config(check_interval, on_change)
        )
        log_server_event(self.logger, "config_watch", 
                        f"Config file watcher started (interval={check_interval}s)")
    
    async def stop_watching(self) -> None:
        """Stop the config watcher background task"""
        if self._watch_task is None:
            return
        
        self._watch_task.cancel()
        try:
            await self._watch_task
        except asyncio.CancelledError:
            pass
        self._watch_task = None
        log_server_event(self.logger, "config_watch_stop",
                        "Config file watcher stopped")
    
    def is_watching(self) -> bool:
        """Check if config watcher is active"""
        return self._watch_task is not None and not self._watch_task.done()
