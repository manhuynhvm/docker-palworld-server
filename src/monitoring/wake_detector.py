#!/usr/bin/env python3
"""Packet-based client connection detector used while Palworld is paused."""

import asyncio
import os
from pathlib import Path
from typing import Optional


class ConnectionWakeDetector:
    """Run knockd outside PalServer and mark inbound game-port traffic."""

    def __init__(self, server_port: int, logger):
        self.server_port = int(server_port)
        self.logger = logger
        self.runtime_dir = Path(
            os.getenv("PALWORLD_RUNTIME_DIR", "/run/palworld")
        )
        self.interface = os.getenv("IDLE_PAUSE_INTERFACE", "eth0")
        self.config_file = self.runtime_dir / "knockd.conf"
        self.wake_marker = self.runtime_dir / "client-wake"
        self._process: Optional[asyncio.subprocess.Process] = None

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _write_config(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.wake_marker.unlink(missing_ok=True)
        self.config_file.write_text(
            "\n".join((
                "[options]",
                " logfile = /dev/null",
                "[resume-by-player]",
                f" sequence = {self.server_port}:udp",
                " seq_cooldown = 5",
                " command = /usr/local/bin/palworld-control wake",
                "",
            )),
            encoding="utf-8",
        )

    async def start(self) -> bool:
        """Start a foreground knockd listener on the container interface."""
        if self.active:
            return True

        await self.stop()
        try:
            self._write_config()
            self._process = await asyncio.create_subprocess_exec(
                "knockd",
                "-c",
                str(self.config_file),
                "-i",
                self.interface,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(0.2)
            if self._process.returncode is not None:
                await self._process.wait()
                self.logger.error(
                    "Connection wake detector exited during startup; "
                    "verify NET_RAW capability"
                )
                self._process = None
                return False
            self.logger.info(
                f"Connection wake detector listening on "
                f"{self.interface}:{self.server_port}/udp"
            )
            return True
        except (OSError, ValueError) as exc:
            self._process = None
            self.logger.error(f"Unable to start connection wake detector: {exc}")
            return False

    async def stop(self) -> None:
        """Stop the packet listener and remove its transient configuration."""
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            else:
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

        self.config_file.unlink(missing_ok=True)
