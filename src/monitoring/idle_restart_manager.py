#!/usr/bin/env python3
"""
Idle-based server auto-restart/pause manager
Restarts or pauses (SIGSTOP/SIGCONT) the server if no players
are online for a configurable duration.
"""

import asyncio
import time
from typing import Optional
from dataclasses import dataclass

from ..config_loader import PalworldConfig
from ..logging_setup import get_logger, log_server_event
from ..notifications import get_discord_notifier
from ..managers.lifecycle_manager import ServerLifecycleManager
from .wake_detector import ConnectionWakeDetector


@dataclass
class IdleRestartStats:
    """Idle restart statistics"""
    total_restarts: int = 0
    total_pauses: int = 0
    total_resumes: int = 0
    last_restart_time: Optional[float] = None
    last_pause_time: Optional[float] = None
    current_idle_duration: float = 0.0
    longest_idle_duration: float = 0.0


class IdleRestartManager:
    """
    Monitors player activity and automatically restarts or pauses
    the server when idle. Integrates with Discord notifications.
    
    Two modes:
    - 'restart': Full server restart (stop + start, ~120s)
    - 'pause':   SIGSTOP freeze; inbound game traffic automatically resumes it
    """
    
    def __init__(self, config: PalworldConfig, player_monitor,
                 lifecycle_manager, api_manager=None, wake_detector=None):
        """Initialize idle restart manager with configuration"""
        self.config = config
        self.player_monitor = player_monitor
        self.lifecycle_manager = (
            lifecycle_manager
            if isinstance(lifecycle_manager, ServerLifecycleManager)
            else None
        )
        self.process_manager = (
            lifecycle_manager.process_manager
            if self.lifecycle_manager is not None
            else lifecycle_manager
        )
        self.api_manager = api_manager
        self.logger = get_logger("palworld.idle_restart")
        self.wake_detector = wake_detector or ConnectionWakeDetector(
            config.server.port, self.logger
        )
        
        idle_config = getattr(config.monitoring, 'idle_restart', None)
        if idle_config:
            self.enabled = idle_config.enabled
            try:
                self.idle_minutes = int(idle_config.idle_minutes) if hasattr(idle_config, 'idle_minutes') else 30
            except (TypeError, ValueError):
                self.idle_minutes = 30
            self.mode = getattr(idle_config, 'mode', 'restart')
        else:
            self.enabled = True
            self.idle_minutes = 30
            self.mode = 'restart'
        
        self.discord_notify = config.discord.events.get('idle_restart', True)
        self.idle_seconds = self.idle_minutes * 60
        self.check_interval = 30
        
        self._idle_start: Optional[float] = None
        self._running = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._paused = False
        self._pause_start_time: Optional[float] = None
        self._last_resume_reason: Optional[str] = None
        self.stats = IdleRestartStats()
        
        if self.enabled:
            log_server_event(
                self.logger, "idle_restart_init",
                f"Idle restart manager initialized",
                idle_minutes=self.idle_minutes,
                mode=self.mode,
                discord_enabled=self.discord_notify
            )
        else:
            self.logger.info("Idle restart manager disabled by configuration")
    
    async def start_monitoring(self) -> None:
        """Start idle monitoring loop"""
        if not self.enabled:
            self.logger.warning("Idle restart monitoring is disabled")
            return
        
        if self._running:
            self.logger.warning("Idle restart monitoring already running")
            return
        
        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        log_server_event(
            self.logger, "idle_monitoring_start",
            f"Idle monitoring started (threshold: {self.idle_minutes} min, mode: {self.mode})"
        )
    
    async def stop_monitoring(self) -> None:
        """Stop idle monitoring loop"""
        if not self._running and not self._paused:
            await self.wake_detector.stop()
            return
        
        self._running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        if self._paused:
            await self._force_resume("monitoring shutdown")
        await self.wake_detector.stop()
        
        log_server_event(
            self.logger, "idle_monitoring_stop",
            "Idle monitoring stopped"
        )
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop for idle detection"""
        while self._running:
            try:
                if self._paused:
                    await self._check_paused_status()
                    await asyncio.sleep(1)
                    continue
                await self._check_idle_status()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Idle monitoring loop error", error=str(e))
                await asyncio.sleep(10)
    
    async def _check_idle_status(self) -> None:
        """Check current idle status and trigger action if needed"""
        if not self.process_manager.is_server_running():
            if self._idle_start is not None:
                self.logger.debug("Server not running, resetting idle timer")
                self._idle_start = None
            return
        
        current_player_count = await self.player_monitor.get_current_player_count()
        if current_player_count is None:
            self.logger.warning(
                "Unable to determine current player count; skipping idle check"
            )
            return

        current_time = time.time()
        
        if current_player_count == 0:
            await self._handle_zero_players(current_time)
        else:
            await self._handle_active_players(current_player_count)

    async def _check_paused_status(self) -> None:
        """Handle packet/manual resume and safety without calling frozen REST."""
        if self.process_manager.consume_manual_resume_marker():
            if self.lifecycle_manager is not None:
                self.lifecycle_manager.acknowledge_external_resume()
            await self._complete_resume("manual operator request")
            return

        if self.process_manager.consume_connection_wake_marker():
            if self.lifecycle_manager is not None:
                resumed = await self.lifecycle_manager.resume()
            else:
                resumed = await self.process_manager.resume_server()
            if not resumed:
                self.logger.error("Client connection detected but resume failed")
                return
            await self._complete_resume("client connection")
            return

        await self._handle_paused_state(time.time())

    async def _complete_resume(self, reason: str) -> None:
        await self.wake_detector.stop()
        self.process_manager.consume_connection_wake_marker()
        self._paused = False
        self._pause_start_time = None
        self._idle_start = None
        self._last_resume_reason = reason
        self.stats.total_resumes += 1
        self.logger.info(f"Server resumed after {reason}; player polling restored")
        await self._send_discord_notification(
            "resume", f"Server resumed after {reason}"
        )
    
    async def _handle_zero_players(self, current_time: float) -> None:
        """Handle server state when no players are online"""
        # If currently paused, check if it's time to do a full restart
        if self._paused:
            await self._handle_paused_state(current_time)
            return
        
        if self._idle_start is None:
            self._idle_start = current_time
            self.logger.info("No players online - idle timer started")
            return
        
        idle_duration = current_time - self._idle_start
        self.stats.current_idle_duration = idle_duration
        
        if idle_duration > self.stats.longest_idle_duration:
            self.stats.longest_idle_duration = idle_duration
        
        minutes_elapsed = int(idle_duration // 60)
        
        if minutes_elapsed > 0 and minutes_elapsed % 5 == 0:
            remaining_minutes = self.idle_minutes - minutes_elapsed
            if remaining_minutes > 0:
                self.logger.debug(
                    f"Server idle for {minutes_elapsed}m "
                    f"({remaining_minutes}m until action)"
                )
        
        if idle_duration >= self.idle_seconds:
            await self._trigger_idle_action()
    
    async def _handle_paused_state(self, current_time: float) -> None:
        """Handle server state when already paused (idle action already taken)"""
        if self._pause_start_time is None:
            self._pause_start_time = current_time
        
        paused_duration = current_time - self._pause_start_time
        max_pause_hours = 24  # Full restart after 24h of pause (memory leak safety)
        max_pause_seconds = max_pause_hours * 3600
        
        if paused_duration >= max_pause_seconds:
            self.logger.warning(
                f"Server paused for {max_pause_hours}h — performing full restart"
            )
            if await self._perform_restart():
                self._paused = False
                self._pause_start_time = None
                self.stats.total_restarts += 1
                self.stats.last_restart_time = time.time()
            else:
                self.logger.error(
                    "24-hour safety restart failed; retaining paused state"
                )
                await self.wake_detector.start()
    
    async def _handle_active_players(self, player_count: int) -> None:
        """Handle server state when players are online"""
        # The packet detector, rather than frozen REST, owns pause wakeups.
        if self._paused:
            return
        
        # Normal active state — reset idle timer
        if self._idle_start is not None:
            idle_duration = time.time() - self._idle_start
            minutes_idle = int(idle_duration // 60)
            self.logger.info(
                f"Players online ({player_count}) — idle timer reset "
                f"(was idle for {minutes_idle}m)"
            )
            self._idle_start = None
            self.stats.current_idle_duration = 0.0
    
    async def _trigger_idle_action(self) -> None:
        """Trigger idle action (restart or pause) depending on mode"""
        self.logger.warning(
            f"Server idle for {self.idle_minutes}m — triggering {self.mode}"
        )
        
        await self._send_discord_notification(
            self.mode,
            f"Server idle for {self.idle_minutes}m — triggering {self.mode}"
        )
        
        try:
            if self.mode == "pause":
                success = await self._perform_pause()
            else:
                success = await self._perform_restart()
            
            if success:
                if self.mode == "pause":
                    self.stats.total_pauses += 1
                    self.stats.last_pause_time = time.time()
                else:
                    self.stats.total_restarts += 1
                    self.stats.last_restart_time = time.time()
                
                log_server_event(
                    self.logger, "idle_action_success",
                    f"Idle action ({self.mode}) completed successfully",
                    total_pauses=self.stats.total_pauses,
                    total_restarts=self.stats.total_restarts
                )
            else:
                log_server_event(
                    self.logger, "idle_action_fail",
                    f"Idle action ({self.mode}) failed"
                )
            
        except Exception as e:
            self.logger.error(f"Idle action failed: {e}")
        finally:
            self._idle_start = None
            self.stats.current_idle_duration = 0.0
    
    async def _perform_pause(self) -> bool:
        """Pause the server via SIGSTOP"""
        save_world = getattr(self.api_manager, "save_world", None)
        if save_world is None or not await save_world():
            self.logger.error("Save-world failed; refusing to pause server")
            return False
        await asyncio.sleep(2)

        if not await self.wake_detector.start():
            self.logger.error("Auto-pause aborted because wake detector failed")
            return False

        self.logger.info("Pausing server (SIGSTOP)...")
        if self.lifecycle_manager is not None:
            success = await self.lifecycle_manager.pause()
        else:
            success = await self.process_manager.pause_server()
        if success:
            self._paused = True
            self._pause_start_time = time.time()
            self.logger.info("Server paused — CPU usage will be 0%")
        if not success:
            await self.wake_detector.stop()
        return success
    
    async def _perform_restart(self) -> bool:
        """Perform the actual server restart"""
        try:
            if self._paused:
                await self.wake_detector.stop()
            message = f"Automatic restart after {self.idle_minutes}m of inactivity"
            if self.lifecycle_manager is not None:
                return await self.lifecycle_manager.restart(
                    message, self.api_manager
                )

            stop_success = await self.process_manager.stop_server(message)
            if not stop_success:
                self.logger.error("Failed to stop server gracefully")
                return False
            
            await asyncio.sleep(5)
            start_success = await self.process_manager.start_server()
            if not start_success:
                self.logger.error("Failed to start server after idle restart")
                return False
            
            return True
        except Exception as e:
            self.logger.error("Error during server restart", error=str(e))
            return False
    
    async def _send_discord_notification(self, action: str, message: str) -> None:
        """Send Discord notification about idle action"""
        if not self.config.discord.enabled:
            return
        
        try:
            notifier = get_discord_notifier(self.config)
            async with notifier:
                await notifier._send_notification(
                    f"idle_{action}",
                    f"idle.{action}",
                    level=notifier.NotificationLevel.WARNING,
                    language=self.config.language,
                    minutes=self.idle_minutes,
                    server=self.config.server.name
                )
                self.logger.info(f"Discord notification sent for idle {action}")
        except Exception as e:
            self.logger.error(f"Failed to send Discord notification: {e}")
    
    def get_idle_status(self) -> dict:
        """Get current idle status information"""
        current_time = time.time()
        
        if self._idle_start is None:
            idle_duration = 0.0
            remaining_time = self.idle_seconds
        else:
            idle_duration = current_time - self._idle_start
            remaining_time = max(0, self.idle_seconds - idle_duration)
        
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "monitoring_active": self._running,
            "is_paused": self._paused,
            "auto_resume_on_connection": self.mode == "pause",
            "wake_detector_active": self.wake_detector.active,
            "last_resume_reason": self._last_resume_reason,
            "idle_threshold_minutes": self.idle_minutes,
            "current_idle_seconds": idle_duration,
            "remaining_seconds_until_action": remaining_time,
            "is_currently_idle": self._idle_start is not None,
            "discord_notifications": self.discord_notify,
            "statistics": {
                "total_restarts": self.stats.total_restarts,
                "total_pauses": self.stats.total_pauses,
                "total_resumes": self.stats.total_resumes,
                "last_restart_time": self.stats.last_restart_time,
                "last_pause_time": self.stats.last_pause_time,
                "longest_idle_duration": self.stats.longest_idle_duration
            }
        }
    
    def is_monitoring_active(self) -> bool:
        """Check if idle monitoring is currently active"""
        return self._running
    
    def force_resume(self) -> bool:
        """Forcefully resume a paused server from external call"""
        if not self._paused:
            return False
        
        import asyncio
        try:
            asyncio.create_task(self._force_resume())
            return True
        except Exception:
            return False
    
    async def _force_resume(self, reason: str = "forced request") -> None:
        """Internal force resume implementation"""
        if self.lifecycle_manager is not None:
            success = await self.lifecycle_manager.resume()
        else:
            success = await self.process_manager.resume_server()
        if success:
            await self._complete_resume(reason)
        else:
            self.logger.error("Unable to forcefully resume server")
