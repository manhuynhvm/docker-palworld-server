#!/usr/bin/env python3
"""Serialized lifecycle management for the Palworld server process."""

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Optional

from ..config_loader import PalworldConfig
from ..logging_setup import get_logger
from .process_manager import ProcessManager


class ServerState(str, Enum):
    """Observable lifecycle states for the managed Palworld process."""

    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    RESTARTING = "restarting"
    STOPPING = "stopping"
    STOPPED = "stopped"


async def verify_server_startup(process_manager, max_wait_time: int = 30) -> bool:
    """Verify that the Palworld server process is running and stable."""
    logger = get_logger("palworld.startup_verification")

    logger.info("Verifying server process startup...")
    if not process_manager.is_server_running():
        logger.error("Server process is not running")
        return False

    stability_check_duration = min(10, max_wait_time)
    logger.info(f"Checking process stability for {stability_check_duration} seconds...")

    start_time = time.time()
    while (time.time() - start_time) < stability_check_duration:
        if not process_manager.is_server_running():
            logger.error("Server process crashed during stability check")
            return False
        await asyncio.sleep(1)

    logger.info("Server process is running and stable")
    return True


class ServerLifecycleManager:
    """Single serialized owner of all process lifecycle mutations."""

    def __init__(
        self,
        config: PalworldConfig,
        logger=None,
        process_manager: Optional[ProcessManager] = None,
    ):
        self.config = config
        self.logger = logger or get_logger("palworld.lifecycle")
        self.process_manager = process_manager or ProcessManager(config, self.logger)
        self._state = ServerState.STOPPED
        self._lifecycle_lock = asyncio.Lock()
        self._terminal_stop = False

    @property
    def state(self) -> ServerState:
        return self._state

    def _set_state(self, state: ServerState) -> None:
        self._state = state
        self.process_manager.update_runtime_state(state.value)

    async def _start_locked(self) -> bool:
        self._set_state(ServerState.STARTING)
        success = await self.process_manager.start_server()
        if not success:
            self._set_state(ServerState.STOPPED)
            self.logger.error("Failed to start server process")
            return False

        process_stable = await verify_server_startup(
            self.process_manager, max_wait_time=30
        )
        if not process_stable:
            await self.process_manager.stop_server()
            self._set_state(ServerState.STOPPED)
            self.logger.error("Server process is not stable")
            return False

        self._set_state(ServerState.RUNNING)
        self.logger.info("Server started successfully and is stable")
        return True

    async def start(self) -> bool:
        """Start and verify the server under the lifecycle lock."""
        async with self._lifecycle_lock:
            if self._terminal_stop:
                self.logger.warning("Start rejected during terminal shutdown")
                return False
            if self._state in (ServerState.RUNNING, ServerState.PAUSED):
                return True
            return await self._start_locked()

    async def _stop_locked(
        self,
        message: str,
        api_client: Optional[Any],
    ) -> bool:
        if not self.process_manager.is_server_running():
            self._set_state(ServerState.STOPPED)
            self.logger.info("Server is already stopped")
            return True

        # A stopped process must be continued before graceful API shutdown or
        # signal escalation can make progress.
        if self._state == ServerState.PAUSED:
            if not await self.process_manager.resume_server():
                self.logger.error("Unable to resume paused server for shutdown")
                return False

        self._set_state(ServerState.STOPPING)
        success = await self.process_manager.stop_server(message, api_client)
        self._set_state(
            ServerState.STOPPED if success else ServerState.RUNNING
        )
        return success

    async def stop(
        self,
        graceful: bool = True,
        message: str = "Server is shutting down",
        api_client: Optional[Any] = None,
    ) -> bool:
        """Stop the server, serializing against restart, pause, and resume."""
        async with self._lifecycle_lock:
            return await self._stop_locked(
                message,
                api_client if graceful else None,
            )

    async def restart(
        self,
        message: str = "Server restarting",
        api_client: Optional[Any] = None,
    ) -> bool:
        """Restart without exposing transient downtime as terminal state."""
        async with self._lifecycle_lock:
            if self._terminal_stop:
                self.logger.warning("Restart rejected during terminal shutdown")
                return False
            if self._state == ServerState.PAUSED:
                if not await self.process_manager.resume_server():
                    self.logger.error("Unable to resume paused server for restart")
                    return False
            self._set_state(ServerState.RESTARTING)
            stop_success = await self.process_manager.stop_server(message, api_client)
            if not stop_success:
                self._set_state(ServerState.RUNNING)
                self.logger.error("Failed to stop server for restart")
                return False

            await asyncio.sleep(5)
            start_success = await self._start_locked()
            if not start_success:
                self._set_state(ServerState.STOPPED)
                self.logger.error("Failed to start server after restart")
                return False

            self.logger.info("Server restarted successfully")
            return True

    async def shutdown(
        self,
        message: str = "Server is shutting down",
        api_client: Optional[Any] = None,
    ) -> bool:
        """Permanently stop this lifecycle instance and reject later starts."""
        self._terminal_stop = True
        async with self._lifecycle_lock:
            return await self._stop_locked(message, api_client)

    async def recycle_config(
        self,
        installer: Callable[[], None],
        message: str,
        api_client: Optional[Any] = None,
    ) -> bool:
        """Stop and install staged configuration as one lifecycle transaction.

        Successful installation leaves the process terminally stopped for the
        container runtime to recreate. If installation fails, the old files
        have already been restored by the installer and the server is started
        again before releasing the lock.
        """
        self._terminal_stop = True
        async with self._lifecycle_lock:
            stopped = await self._stop_locked(message, api_client)
            if not stopped:
                self._terminal_stop = False
                return False

            try:
                installer()
            except Exception as exc:
                self.logger.error(f"Configuration installation failed: {exc}")
                self._terminal_stop = False
                recovered = await self._start_locked()
                if not recovered:
                    self.logger.error(
                        "Server recovery failed after configuration installation error"
                    )
                return False

            self._set_state(ServerState.STOPPED)
            return True

    async def pause(self) -> bool:
        """Pause the process group under the lifecycle lock."""
        async with self._lifecycle_lock:
            if self._terminal_stop:
                return False
            if self._state == ServerState.PAUSED:
                return True
            if self._state != ServerState.RUNNING:
                return False
            success = await self.process_manager.pause_server()
            if success:
                self._set_state(ServerState.PAUSED)
            return success

    async def resume(self) -> bool:
        """Resume the process group under the lifecycle lock."""
        async with self._lifecycle_lock:
            if self._terminal_stop:
                return False
            if self._state == ServerState.RUNNING:
                return True
            if self._state != ServerState.PAUSED:
                return False
            success = await self.process_manager.resume_server()
            if success:
                self._set_state(ServerState.RUNNING)
            return success

    def acknowledge_external_resume(self) -> None:
        """Reconcile state after the external control CLI sends SIGCONT."""
        if self._state == ServerState.PAUSED:
            self._set_state(ServerState.RUNNING)

    async def verify_startup(self) -> bool:
        return await verify_server_startup(self.process_manager, max_wait_time=30)

    def get_server_status(self) -> dict:
        status = self.process_manager.get_server_status()
        status["state"] = self._state.value
        return status
