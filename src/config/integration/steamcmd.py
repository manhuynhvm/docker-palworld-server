#!/usr/bin/env python3
"""
SteamCMD configuration classes
"""

from dataclasses import dataclass


@dataclass
class SteamCMDConfig:
    """SteamCMD configuration data class"""
    app_id: int = 2394010
    validate: bool = True
    auto_update: bool = True
    update_on_start: bool = True