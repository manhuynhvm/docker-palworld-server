#!/usr/bin/env python3
"""
Idle restart configuration classes
"""

from dataclasses import dataclass


@dataclass
class IdleRestartConfig:
    """Idle restart configuration"""
    enabled: bool = True
    idle_minutes: int = 30