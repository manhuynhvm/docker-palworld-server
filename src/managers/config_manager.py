#!/usr/bin/env python3
"""
Configuration file management for Palworld server
Handles file writing for PalWorldSettings.ini and Engine.ini.
All content generation is delegated to SettingsGenerator.
"""

from pathlib import Path
from typing import Optional

from ..config_loader import PalworldConfig
from ..logging_setup import log_server_event
from .settings_generator import SettingsGenerator


class ConfigManager:
    """Server configuration file management
    
    Delegates all INI content generation to SettingsGenerator.
    Only handles directory creation and file writing.
    """
    
    def __init__(self, config: PalworldConfig, logger, generator: Optional[SettingsGenerator] = None):
        self.config = config
        self.logger = logger
        self.generator = generator or SettingsGenerator(config, logger)
        self.server_path = config.paths.server_dir
        self.config_dir = self.server_path / "Pal" / "Saved" / "Config" / "LinuxServer"
    
    def generate_server_settings(self) -> bool:
        """Generate and write Palworld server settings file"""
        try:
            settings_file = self.config_dir / "PalWorldSettings.ini"
            self.config_dir.mkdir(parents=True, exist_ok=True)
            settings_content = self.generator.generate_server_settings()
            settings_file.write_text(settings_content, encoding='utf-8')
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
            log_server_event(self.logger, "config_generate",
                           "Engine settings file generated successfully",
                           engine_file=str(engine_file))
            return True
        except Exception as e:
            log_server_event(self.logger, "config_generate_fail",
                           f"Failed to generate engine settings file: {e}")
            return False
