#!/usr/bin/env python3
"""
SteamCMD configuration classes
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SteamCMDConfig:
    """SteamCMD configuration data class"""
    app_id: int = 2394010
    depot_id: int = 2394012
    target_manifest_id: Optional[int] = None
    validate: bool = True
    auto_update: bool = True
    update_on_start: bool = True
