#!/usr/bin/env python3
"""
SteamCMD client for Palworld server management
Handles server file downloads and updates via SteamCMD
"""

import os
import threading
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

    def _run_and_stream(self, cmd: list, env: dict, cwd: str, timeout: int,
                        label: str = "SteamCMD") -> tuple[int, list[str]]:
        """Run a process and stream stdout/stderr line by line in real-time.

        Returns (returncode, all_output_lines). Raises on timeout.
        """
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=cwd,
        )

        output_lines: list[str] = []
        lock = threading.Lock()

        def _reader(stream, label_prefix: str):
            for line in iter(stream.readline, ''):
                line = line.rstrip('\n\r')
                if line:
                    with lock:
                        output_lines.append(line)
                    self.logger.info(f"[{label}][{label_prefix}] {line}")
            stream.close()

        stdout_t = threading.Thread(target=_reader, args=(process.stdout, "out"))
        stderr_t = threading.Thread(target=_reader, args=(process.stderr, "err"))
        stdout_t.daemon = True
        stderr_t.daemon = True
        stdout_t.start()
        stderr_t.start()

        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            stdout_t.join(timeout=5)
            stderr_t.join(timeout=5)
            process.stdout.close()
            process.stderr.close()
            raise

        stdout_t.join()
        stderr_t.join()
        process.stdout.close()
        process.stderr.close()

        return returncode, output_lines

    def _ensure_updated(self) -> bool:
        """Lightweight warm-up to trigger any pending self-update."""
        if not self.validate_steamcmd():
            return False

        steamcmd_args = "+login anonymous +quit"
        full_cmd = ["FEXBash", "-c", f"{self.steamcmd_script} {steamcmd_args}"]

        env = {
            **dict(os.environ),
            "STEAM_COMPAT_DATA_PATH": str(self.steamcmd_path / "steam_compat"),
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.steamcmd_path),
        }
        (self.steamcmd_path / "steam_compat").mkdir(parents=True, exist_ok=True)

        self.logger.info("Running SteamCMD warm-up to trigger any pending self-update",
                         event_type="steamcmd_warmup")
        try:
            rc, lines = self._run_and_stream(
                full_cmd, env, str(self.steamcmd_path), timeout=120, label="warmup"
            )
            if rc == 0:
                self.logger.info("SteamCMD warm-up completed (no update needed or update applied)")
            else:
                self.logger.warning(
                    "SteamCMD warm-up finished with non-zero exit (may be normal)",
                    event_type="steamcmd_warmup",
                    return_code=rc,
                    last_lines=lines[-50:],
                )
            return True
        except subprocess.TimeoutExpired:
            self.logger.warning("SteamCMD warm-up timed out, proceeding anyway")
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

            rc, lines = self._run_and_stream(
                full_cmd, env, str(self.steamcmd_path), timeout=timeout, label="SteamCMD"
            )

            if rc == 0:
                log_server_event(self.logger, "steamcmd_complete",
                                 "SteamCMD commands completed successfully")
                return True
            else:
                fex_env_vars = {k: v for k, v in env.items()
                                if 'FEX' in k or 'STEAM_COMPAT' in k}
                self.logger.error(
                    "SteamCMD commands failed",
                    event_type="steamcmd_fail",
                    return_code=rc,
                    last_lines=lines[-100:],
                    env_vars=fex_env_vars,
                )
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"SteamCMD timeout after {timeout} seconds", event_type="steamcmd_fail")
            return False
        except Exception as e:
            self.logger.error(f"SteamCMD execution error: {e}", event_type="steamcmd_fail")
            return False
