#!/usr/bin/env python3
"""
SteamCMD client for Palworld server management
Handles server file downloads and updates via SteamCMD
"""

import os
import subprocess
from pathlib import Path
from typing import List

from ..logging_setup import log_server_event


class SteamCMDManager:
    """Manages SteamCMD operations for Palworld server"""

    def __init__(self, steamcmd_path: Path, logger):
        self.steamcmd_path = steamcmd_path
        self.logger = logger
        self.steamcmd_script = steamcmd_path / "steamcmd.sh"

    def validate_steamcmd(self) -> bool:
        """Check if SteamCMD executable exists and is executable"""
        if not self.steamcmd_script.exists():
            self.logger.error("SteamCMD executable not found", script_path=str(self.steamcmd_script))
            return False

        if not self.steamcmd_script.is_file():
            self.logger.error("SteamCMD path is not a file", script_path=str(self.steamcmd_script))
            return False

        import stat
        mode = self.steamcmd_script.stat().st_mode
        if not (mode & stat.S_IEXEC):
            self.logger.warning("SteamCMD executable lacks execute permission, attempting to set it")
            try:
                self.steamcmd_script.chmod(mode | stat.S_IEXEC)
            except PermissionError:
                self.logger.error("Failed to set execute permission for SteamCMD")
                return False

        return True


    def _ensure_updated(self) -> bool:
        """Run a lightweight steamcmd session to trigger any pending self-update.

        Under FEX emulation, steamcmd.sh often fails with "Missing configuration"
        on the first real command because the Steam runtime has not been fully
        initialized. Running +login anonymous +quit here forces SteamCMD to:
        1. Detect and apply any pending self-update
        2. Fully initialize the Steam client library and create config files
        3. Complete the Steam authentication handshake
        """
        if not self.validate_steamcmd():
            return False

        warmup_cmd = [
            str(self.steamcmd_script),
            "+login", "anonymous",
            "+quit"
        ]
        full_cmd = ["FEXBash", "-c", " ".join(warmup_cmd)]

        env = {
            **dict(os.environ),
            "STEAM_COMPAT_DATA_PATH": str(self.steamcmd_path / "steam_compat"),
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.steamcmd_path),
        }
        (self.steamcmd_path / "steam_compat").mkdir(parents=True, exist_ok=True)

        self.logger.info("Running SteamCMD warm-up to trigger any pending self-update",
                        event_type="steamcmd_warmup")
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                cwd=str(self.steamcmd_path),
            )
            if result.returncode == 0:
                self.logger.info("SteamCMD warm-up completed (no update needed or update applied)")
            else:
                self.logger.warning(
                    "SteamCMD warm-up finished with non-zero exit (may be normal)",
                    event_type="steamcmd_warmup",
                    return_code=result.returncode,
                    stdout=result.stdout[-500:],
                    stderr=result.stderr[-500:],
                )
            return True
        except subprocess.TimeoutExpired:
            self.logger.warning("SteamCMD warm-up timed out, proceeding anyway")
            return True
        except Exception as e:
            self.logger.warning(f"SteamCMD warm-up failed: {e}, proceeding anyway")
            return True


    def run_command(self, commands: List[str], timeout: int = 600) -> bool:
        """Run SteamCMD commands with timeout"""
        if not self.validate_steamcmd():
            return False

        # Warm up steamcmd first to handle any pending self-update
        # before running the real command.
        self._ensure_updated()

        steamcmd_command = " ".join([str(self.steamcmd_script)] + commands)

        full_cmd = ["FEXBash", "-c", steamcmd_command]

        log_server_event(self.logger, "steamcmd_start", f"Executing: FEXBash -c '{steamcmd_command}'")

        try:
             env = {
                 **dict(os.environ),
                 "STEAM_COMPAT_DATA_PATH": str(self.steamcmd_path / "steam_compat"),
                 "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.steamcmd_path),
             }
 
             result = subprocess.run(
                 full_cmd,
                 capture_output=True,
                 text=True,
                 timeout=timeout,
                 env=env,
                 cwd=str(self.steamcmd_path)
             )
 
             if result.returncode == 0:
                 log_server_event(self.logger, "steamcmd_complete", "SteamCMD commands completed successfully", duration_seconds=timeout)
                 return True
             else:
                 # FEX 관련 환경 변수 추출
                 fex_env_vars = {k: v for k, v in env.items() if 'FEX' in k or 'STEAM_COMPAT' in k}
                 
                 # Log error with ERROR level instead of INFO
                 self.logger.error(
                     "SteamCMD commands failed",
                     event_type="steamcmd_fail",
                     return_code=result.returncode,
                     stdout=result.stdout,
                     stderr=result.stderr,
                     env_vars=fex_env_vars
                 )
                 return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"SteamCMD timeout after {timeout} seconds", event_type="steamcmd_fail")
            return False
        except Exception as e:
            self.logger.error(f"SteamCMD execution error: {e}", event_type="steamcmd_fail")
            return False
