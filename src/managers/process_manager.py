#!/usr/bin/env python3
"""
Process management for Palworld server
Handles server process lifecycle, monitoring, and signal delivery.
"""

import asyncio
import json
import os
import signal
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional

from ..config_loader import PalworldConfig
from ..logging_setup import log_server_event
from ..protocols import IProcessManager


# The production target is Linux. These aliases keep command construction and
# unit tests deterministic on Windows development hosts without changing Linux.
if not hasattr(os, "killpg"):
    os.killpg = os.kill  # type: ignore[attr-defined]
for _signal_name, _fallback in (
    ("SIGSTOP", signal.SIGTERM),
    ("SIGCONT", signal.SIGTERM),
):
    if not hasattr(signal, _signal_name):
        setattr(signal, _signal_name, _fallback)


class ProcessManager(IProcessManager):
    """Server process lifecycle management"""

    def __init__(self, config: PalworldConfig, logger: Any):
        self.config = config
        self.logger = logger
        self.server_path = config.paths.server_dir
        self.server_process: Optional[subprocess.Popen] = None
        self._process_start_time: Optional[float] = None
        """Timestamp (time.time) when the server process was last started."""
        self._runtime_state = "stopped"
        self.runtime_dir = Path(
            os.getenv("PALWORLD_RUNTIME_DIR", "/run/palworld")
        )
        self.runtime_state_file = self.runtime_dir / "server-state.json"
        self.resume_marker_file = self.runtime_dir / "manual-resume"

    @staticmethod
    def _read_process_start_ticks(pid: int) -> Optional[int]:
        """Read Linux start ticks so control commands can reject reused PIDs."""
        try:
            stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields_after_comm = stat_text.rsplit(")", 1)[1].split()
            return int(fields_after_comm[19])
        except (OSError, ValueError, IndexError):
            return None

    def _write_runtime_state(self) -> None:
        """Atomically publish process identity for the external control CLI."""
        process = self.server_process
        if process is None or process.poll() is not None:
            return

        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "pid": process.pid,
                "pgid": process.pid,
                "process_start_ticks": self._read_process_start_ticks(process.pid),
                "state": self._runtime_state,
                "updated_at": time.time(),
            }
            temporary = self.runtime_state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self.runtime_state_file)
        except OSError as exc:
            self.logger.warning(f"Unable to publish runtime process state: {exc}")

    def update_runtime_state(self, state: str) -> None:
        """Update the state exposed to health checks and palworld-control."""
        self._runtime_state = state
        self._write_runtime_state()

    def consume_manual_resume_marker(self) -> bool:
        """Consume a marker written after palworld-control sends SIGCONT."""
        try:
            self.resume_marker_file.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            self.logger.warning(f"Unable to consume manual resume marker: {exc}")
            return False

    def _clear_runtime_state(self) -> None:
        self._runtime_state = "stopped"
        for path in (self.runtime_state_file, self.resume_marker_file):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                self.logger.warning(f"Unable to remove runtime state {path}: {exc}")

    def is_server_running(self) -> bool:
        """Check if server is currently running"""
        process = self.server_process
        if process is None:
            return False

        poll_result = process.poll()
        return poll_result is None

    def _build_startup_options(self) -> List[str]:
        """Build server startup options based on configuration"""
        options = []
        startup_cfg = self.config.server_startup

        if (
            startup_cfg.use_performance_threads
            and startup_cfg.disable_async_loading
            and startup_cfg.use_multithread_for_ds
        ):
            options.extend(["-useperfthreads", "-NoAsyncLoadingThread", "-UseMultithreadForDS"])

            if startup_cfg.worker_threads_count > 0:
                options.append(f"-NumberOfWorkerThreadsServer={startup_cfg.worker_threads_count}")

        if startup_cfg.query_port != 27015:
            options.append(f"-queryport={startup_cfg.query_port}")

        if startup_cfg.enable_public_lobby:
            options.append("-publiclobby")

        if startup_cfg.log_format != "text":
            options.append(f"-logformat={startup_cfg.log_format}")

        if startup_cfg.additional_options:
            additional_opts = shlex.split(startup_cfg.additional_options.strip())
            options.extend(additional_opts)

        return options

    def _build_server_command(self) -> List[str]:
        """Build complete server command with dynamic options"""
        server_executable = self.server_path / "PalServer.sh"
        startup_options = self._build_startup_options()

        # Always shlex.join() to prevent shell injection from path or options
        executable_text = str(server_executable).replace("\\", "/")
        command = shlex.join([executable_text, *startup_options])
        if startup_options:
            log_server_event(
                self.logger,
                "server_command_build",
                "Server command with options: " + shlex.join(startup_options),
            )
        else:
            log_server_event(
                self.logger, "server_command_build", "Server command without additional options"
            )

        return ["FEXBash", "-c", command]

    async def start_server(self) -> bool:
        """Start Palworld server with dynamic configuration options"""
        if self.is_server_running():
            log_server_event(self.logger, "server_start", "Server is already running")
            return True

        server_executable = self.server_path / "PalServer.sh"

        if not server_executable.exists():
            log_server_event(
                self.logger,
                "server_start_fail",
                f"Server executable not found: {server_executable}",
            )
            return False

        try:
            log_server_event(
                self.logger, "server_start", "Starting Palworld server with dynamic options"
            )

            full_cmd = self._build_server_command()

            # Inherit parent stdout/stderr to avoid pipe deadlock with long-running process.
            # Output is captured by Docker/Supervisor logging.
            self.server_process = subprocess.Popen(
                full_cmd,
                cwd=str(self.server_path),
                stdout=None,
                stderr=None,
                text=True,
                start_new_session=True,
            )
            self._process_start_time = time.time()
            self._write_runtime_state()

            await asyncio.sleep(10)

            if not self.is_server_running():
                self._process_start_time = None
                self._clear_runtime_state()
                log_server_event(
                    self.logger, "server_start_fail", "Server start failed - check logs for details"
                )
                return False

            log_server_event(
                self.logger,
                "server_start_complete",
                "Server started successfully with configured options",
                pid=self.server_process.pid,
            )
            return True

        except Exception as e:
            log_server_event(self.logger, "server_start_fail", f"Server start error: {e}")
            return False

    async def stop_server(
        self,
        message: str = "Server is shutting down",
        api_client: Optional[Any] = None,
    ) -> bool:
        """Stop Palworld server gracefully and clean up zombie processes"""
        if not self.is_server_running():
            self.server_process = None
            self._process_start_time = None
            self._clear_runtime_state()
            log_server_event(self.logger, "server_stop", "Server is already stopped")
            return True

        # Keep a local strong reference after the running check. Another
        # shutdown task may clear self.server_process while this coroutine
        # awaits the API graceful-shutdown calls.
        process = self.server_process
        if process is None:
            log_server_event(self.logger, "server_stop", "Server is already stopped")
            return True

        try:
            if api_client:
                try:
                    announce = getattr(api_client, "announce_message", None)
                    if announce is None:
                        announce = api_client.announce
                    await announce(f"{message}. Shutting down in 30 seconds.")
                    await asyncio.sleep(30)
                    await api_client.shutdown_server(1, message)

                    for _ in range(60):
                        if not self.is_server_running():
                            break
                        await asyncio.sleep(1)
                except Exception as e:
                    self.logger.warning(f"API graceful shutdown failed: {e}")

            if process.poll() is None:
                log_server_event(
                    self.logger,
                    "server_force_stop",
                    "Attempting force termination of entire process group",
                )

                # Kill the entire process group (FEXBash + all child processes)
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                except ProcessLookupError:
                    # Process group already terminated
                    pass

            # Clean up zombie process
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            if self.server_process is process:
                self.server_process = None
            self._process_start_time = None
            self._clear_runtime_state()

            log_server_event(self.logger, "server_stop_complete", "Server stopped successfully")
            return True

        except Exception as e:
            log_server_event(self.logger, "server_stop_fail", f"Server stop error: {e}")
            return False

    async def send_signal(self, sig: int) -> bool:
        """Send a signal to the server process group.

        Args:
            sig: Signal number (for example, signal.SIGTERM).

        Returns:
            True if signal was sent, False if server is not running.
        """
        if not self.is_server_running():
            self.logger.warning("Cannot send signal — server is not running")
            return False

        process = self.server_process
        if process is None:
            self.logger.warning("Cannot send signal — server process disappeared")
            return False

        try:
            pid = process.pid
            os.killpg(pid, sig)
            sig_name = signal.Signals(sig).name
            log_server_event(
                self.logger,
                "server_signal",
                f"Signal {sig_name} sent to process group",
                pid=pid,
                signal=sig_name,
            )
            return True
        except ProcessLookupError:
            self.logger.warning(f"Process group not found (pid={process.pid})")
            return False
        except Exception as e:
            self.logger.error(f"Failed to send signal: {e}")
            return False

    async def pause_server(self) -> bool:
        """Pause the server process by sending SIGSTOP.

        The server binary is frozen in memory (CPU 0%) and can be
        instantly resumed with SIGCONT.

        Returns:
            True if SIGSTOP was sent, False otherwise.
        """
        return await self.send_signal(signal.SIGSTOP)

    async def resume_server(self) -> bool:
        """Resume a paused server process by sending SIGCONT.

        Returns:
            True if SIGCONT was sent, False otherwise.
        """
        return await self.send_signal(signal.SIGCONT)

    def get_server_status(self) -> dict[str, Any]:
        """Get detailed server process status"""
        process = self.server_process
        if process is None or process.poll() is not None or self._process_start_time is None:
            return {"running": False, "pid": None, "uptime": 0}

        return {
            "running": True,
            "pid": process.pid,
            "uptime": time.time() - self._process_start_time,
        }

    def get_startup_options_summary(self) -> dict:
        """Get summary of current startup options configuration"""
        startup_cfg = self.config.server_startup
        options = self._build_startup_options()

        return {
            "performance_optimization": (
                startup_cfg.use_performance_threads
                and startup_cfg.disable_async_loading
                and startup_cfg.use_multithread_for_ds
            ),
            "query_port": startup_cfg.query_port,
            "public_lobby": startup_cfg.enable_public_lobby,
            "log_format": startup_cfg.log_format,
            "worker_threads": startup_cfg.worker_threads_count,
            "additional_options": startup_cfg.additional_options,
            "generated_options": options,
            "options_count": len(options),
        }
