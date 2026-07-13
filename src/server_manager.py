#!/usr/bin/env python3
"""
Palworld server manager - Main orchestrator with API readiness verification
Waits for REST API to be ready before starting monitoring systems 
"""

import asyncio
import shutil
import signal
import time
import aiohttp
from typing import Optional, Any

from .config_loader import PalworldConfig, get_config
from .logging_setup import get_logger, log_server_event, setup_logging

from .clients import SteamCMDManager
from .managers import ProcessManager, ConfigManager
from .monitoring import MonitoringManager
from .managers.lifecycle_manager import ServerLifecycleManager, ServerState
from .managers.api_facade import ServerAPIFacade
from .managers.settings_generator import SettingsGenerator
from .container import ServiceContainer


async def wait_for_api_ready(manager, max_wait_time: int = 60, check_interval: int = 2) -> bool:
    """Wait for REST API to become available before starting monitoring"""
    logger = get_logger("palworld.api_readiness")
    
    api_host = manager.config.rest_api.host
    api_port = manager.config.rest_api.port
    admin_password = manager.config.server.admin_password
    
    logger.info(f"Checking REST API readiness at {api_host}:{api_port}")
    logger.info(f"Maximum wait time: {max_wait_time} seconds")
    
    start_time = time.time()
    attempt = 0
    
    _auth_header = aiohttp.encode_basic_auth("admin", admin_password)
    _headers = {"Authorization": _auth_header} if _auth_header else {}
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(headers=_headers, timeout=timeout) as session:
        while (time.time() - start_time) < max_wait_time:
            attempt += 1
            elapsed = int(time.time() - start_time)
            
            try:
                test_url = f"http://{api_host}:{api_port}/v1/api/info"
                
                async with session.get(test_url) as response:
                    if response.status == 200:
                        logger.info(f"REST API is ready and responding (attempt {attempt}, {elapsed}s elapsed)")
                        return True
                    elif response.status == 401:
                        logger.error(
                            "REST API authentication failed; verify ADMIN_PASSWORD"
                        )
                        disable_rest = getattr(manager.api_facade, "disable_rest", None)
                        if disable_rest is not None:
                            disable_rest("authentication failed (HTTP 401)")
                        return False
                    else:
                        logger.debug(f"API responding with status {response.status} (attempt {attempt})")
                            
            except aiohttp.ClientConnectorError as e:
                logger.debug(f"API not ready - connection failed (attempt {attempt}, {elapsed}s): {str(e)[:50]}...")
                
            except asyncio.TimeoutError:
                logger.debug(f"API not ready - timeout (attempt {attempt}, {elapsed}s)")
                
            except Exception as e:
                logger.debug(f"API check error (attempt {attempt}, {elapsed}s): {str(e)[:50]}...")
            
            log_every = max(1, 10 // max(1, check_interval))
            if attempt % log_every == 0:
                remaining = max_wait_time - elapsed
                logger.info(f"Still waiting for API... ({elapsed}s elapsed, {remaining}s remaining)")
            
            await asyncio.sleep(check_interval)
    
    total_elapsed = int(time.time() - start_time)
    logger.error(f"REST API did not become ready within {max_wait_time} seconds (total attempts: {attempt})")
    return False


class PalworldServerManager:
    """Main Palworld server orchestrator with enhanced startup verification"""
    
    def __init__(self, 
                 config: Optional[PalworldConfig] = None,
                 container: Optional[ServiceContainer] = None):
        """Initialize server manager with dependency injection container"""
        self.config = config or get_config()
        self.logger = get_logger("palworld.server")
        
        # Use provided container or create a new one
        self.container = container or ServiceContainer()
        
        # Register services if not already registered
        self._setup_container_services()
        
        # Resolve dependencies from container
        self.lifecycle_manager = self.container.resolve(ServerLifecycleManager)
        self.api_facade = self.container.resolve(ServerAPIFacade)
        self.settings_generator = self.container.resolve(SettingsGenerator)
        
        # Get process manager from lifecycle manager if available, otherwise resolve from container
        if hasattr(self.lifecycle_manager, 'process_manager'):
            self.process_manager = self.lifecycle_manager.process_manager
        else:
            self.process_manager = self.container.resolve(ProcessManager)
        
        # Initialize remaining components
        self.steamcmd_manager = SteamCMDManager(
            self.config.paths.steamcmd_dir, 
            self.logger
        )
        self.config_manager = ConfigManager(self.config, self.logger)
        
        # Use api_facade as the single API integration point
        self.monitoring_manager = MonitoringManager(
            self.config, 
            self.process_manager, 
            self.api_facade,
            self.lifecycle_manager,
        )
        
        self._backup_manager: Optional[Any] = None
        self._startup_completed = False
        self._shutdown_event = asyncio.Event()
        self._exit_code = 0
        self._shutdown_reason = ""
        self._process_watch_task: Optional[asyncio.Task] = None
        self._cleanup_started = False
    
    def _setup_container_services(self):
        """Setup default services in the container if not already registered"""
        if self.container.has_service(ServerLifecycleManager):
            lifecycle_manager = self.container.resolve(ServerLifecycleManager)
            self.container.register(
                ProcessManager, lifecycle_manager.process_manager
            )
        else:
            if self.container.has_service(ProcessManager):
                process_manager = self.container.resolve(ProcessManager)
            else:
                process_manager = ProcessManager(self.config, self.logger)
                self.container.register(ProcessManager, process_manager)
            lifecycle_manager = ServerLifecycleManager(
                self.config, self.logger, process_manager=process_manager
            )
            self.container.register(ServerLifecycleManager, lifecycle_manager)
        
        if not self.container.has_service(ServerAPIFacade):
            api_facade = ServerAPIFacade(
                self.config, self.logger
            )
            self.container.register(ServerAPIFacade, api_facade)
        
        if not self.container.has_service(SettingsGenerator):
            settings_generator = SettingsGenerator(
                self.config, self.logger
            )
            self.container.register(SettingsGenerator, settings_generator)
    
    async def __aenter__(self):
        """Initialize all components"""
        await self.api_facade.initialize_clients()
        
        self._ensure_directories()
        
        if self.config.backup.enabled:
            from .backup.backup_manager import get_backup_manager
            self._backup_manager = get_backup_manager(self.config)
            self._backup_manager.configure_runtime(
                self.api_facade.save_world,
                self.process_manager.is_server_running,
            )
            await self._backup_manager.start_backup_scheduler()
            
            if hasattr(self._backup_manager, 'add_completion_callback'):
                self._backup_manager.add_completion_callback(
                    self.monitoring_manager.handle_backup_completion
                )
            
            self.logger.info(f"Backup system started with {self.config.backup.interval_seconds}s interval")
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup all components"""
        if self._cleanup_started:
            return
        self._cleanup_started = True

        await self.config_manager.stop_watching()

        if hasattr(self, 'monitoring_manager'):
            await self.monitoring_manager.stop_monitoring()

        if self._backup_manager:
            await self._backup_manager.stop_backup_scheduler()

        if self.process_manager.is_server_running():
            await self.lifecycle_manager.shutdown(
                "System shutdown", self.api_facade
            )

        await self.api_facade.cleanup_clients()

        if self._process_watch_task:
            self._process_watch_task.cancel()
            await asyncio.gather(self._process_watch_task, return_exceptions=True)
            self._process_watch_task = None
    
    def _ensure_directories(self) -> None:
        """Create necessary directories for server operation"""
        directories = [
            self.config.paths.server_dir,
            self.config.paths.backup_dir,
            self.config.paths.log_dir,
            self.config.paths.server_dir / "Pal" / "Saved" / "Config" / "LinuxServer"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug("Directory check/create", path=str(directory))
    
    async def start_server_with_verification(self) -> bool:
        """Start Palworld server and wait for full readiness"""
        success = await self.lifecycle_manager.start()
        if not success:
            self.logger.error("Failed to start server process")
            await self.monitoring_manager.handle_error("Failed to start Palworld server")
            return False
        
        if self.config.rest_api.enabled:
            self.logger.info("Waiting for REST API to become ready...")
            api_ready = await wait_for_api_ready(self, max_wait_time=60, check_interval=2)
            
            if api_ready:
                self.logger.info("REST API is ready")
            else:
                self.logger.warning("REST API not ready within timeout, starting with limited monitoring")
                await self.monitoring_manager.handle_error("REST API failed to become ready within timeout")
        
        self.logger.info("Starting monitoring systems...")
        try:
            await self.monitoring_manager.start_monitoring()
            self.logger.info("Monitoring systems started successfully")
        except Exception as e:
            self.logger.error(f"Failed to start monitoring systems: {e}")
            await self.monitoring_manager.handle_error(f"Failed to start monitoring: {str(e)}")
        
        self._startup_completed = True
        return True

    def start_process_watch(self) -> None:
        if self._process_watch_task is None:
            self._process_watch_task = asyncio.create_task(
                self._watch_process_liveness()
            )

    async def _watch_process_liveness(self) -> None:
        """Request container shutdown only for an unexpected process exit."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(5)
            if self.has_unexpected_process_exit():
                self.logger.error("Palworld process exited unexpectedly")
                self.request_shutdown(1, "Palworld process exited unexpectedly")
                return

    def has_unexpected_process_exit(self) -> bool:
        """Intentional restart downtime is not a terminal process exit."""
        return (
            self.lifecycle_manager.state == ServerState.RUNNING
            and not self.process_manager.is_server_running()
        )

    def request_shutdown(self, exit_code: int = 0, reason: str = "") -> None:
        self._exit_code = exit_code
        self._shutdown_reason = reason
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> int:
        await self._shutdown_event.wait()
        return self._exit_code

    async def apply_config_and_recycle(self, staged_config) -> bool:
        """Gracefully stop, install validated settings, and recycle container."""
        if self._shutdown_event.is_set():
            return False

        self.logger.warning("Applying validated configuration via container restart")
        await self.monitoring_manager.stop_monitoring()
        if self._backup_manager:
            await self._backup_manager.stop_backup_scheduler()

        if self.process_manager.is_server_running():
            save_ok = await self.api_facade.save_world()
            if not save_ok:
                self.logger.warning("Save-world failed before configuration restart")

        stopped = await self.lifecycle_manager.recycle_config(
            lambda: self.config_manager.install_staged(staged_config),
            "Configuration changed; server restarting",
            self.api_facade,
        )
        if not stopped:
            self.logger.error("Configuration restart aborted: server did not stop")
            return False

        self.request_shutdown(75, "Validated configuration installed")
        return True
    
    async def download_server_files(self) -> bool:
        """Download/update Palworld server files via SteamCMD"""
        log_server_event(self.logger, "server_download_start", 
                        "Starting Palworld server file download")
        
        manifest_id = self.config.steamcmd.target_manifest_id
        if manifest_id is not None:
            commands = [
                "+login", "anonymous",
                "+download_depot", str(self.config.steamcmd.app_id),
                str(self.config.steamcmd.depot_id), str(manifest_id),
            ]
        else:
            commands = [
                "+force_install_dir", str(self.config.paths.server_dir),
                "+login", "anonymous",
                "+app_update", str(self.config.steamcmd.app_id),
            ]

            if self.config.steamcmd.validate:
                commands.append("validate")
        commands.append("+quit")
        success = self.steamcmd_manager.run_command(commands, timeout=1800)

        if success and manifest_id is not None:
            depot_dir = (
                self.config.paths.steamcmd_dir
                / "steamapps" / "content"
                / f"app_{self.config.steamcmd.app_id}"
                / f"depot_{self.config.steamcmd.depot_id}"
            )
            if not depot_dir.is_dir():
                self.logger.error(
                    "SteamCMD completed but the downloaded manifest was not found",
                    manifest_id=manifest_id,
                    depot_dir=str(depot_dir),
                )
                success = False
            else:
                try:
                    self.config.paths.server_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(
                        depot_dir,
                        self.config.paths.server_dir,
                        dirs_exist_ok=True,
                    )
                    self.logger.info(
                        "Installed pinned Palworld server manifest",
                        manifest_id=manifest_id,
                        depot_id=self.config.steamcmd.depot_id,
                    )
                except OSError as exc:
                    self.logger.error(
                        "Failed to install downloaded manifest",
                        manifest_id=manifest_id,
                        error=str(exc),
                    )
                    success = False
        
        if success:
            log_server_event(self.logger, "server_download_complete", 
                           "Server file download completed")
        else:
            log_server_event(self.logger, "server_download_fail", 
                           "Server file download failed")
            await self.monitoring_manager.handle_error("Server file download failed")
        
        return success
    
    def is_server_running(self) -> bool:
        """Check if server is currently running"""
        return self.process_manager.is_server_running()
    
    async def start_server(self) -> bool:
        """Start Palworld server"""
        success = await self.lifecycle_manager.start()
        
        if not success:
            asyncio.create_task(
                self.monitoring_manager.handle_error("Failed to start Palworld server")
            )
        
        return success
    
    async def stop_server(self, message: str = "Server is shutting down") -> bool:
        """Stop Palworld server gracefully"""
        return await self.lifecycle_manager.shutdown(message, self.api_facade)
    
    def get_server_status(self) -> dict:
        """Get detailed server process status"""
        return self.lifecycle_manager.get_server_status()
    
    def generate_server_settings(self) -> bool:
        """Generate server settings file"""
        try:
            settings_content = self.settings_generator.generate_server_settings()
            success = self.settings_generator.write_server_settings()
            return success
        except Exception as e:
            self.logger.error(f"Failed to generate server settings: {e}")
            return False
    
    def generate_engine_settings(self) -> bool:
        """Generate engine settings file"""
        try:
            engine_content = self.settings_generator.generate_engine_settings()
            success = self.settings_generator.write_engine_settings()
            return success
        except Exception as e:
            self.logger.error(f"Failed to generate engine settings: {e}")
            return False
    
    async def get_server_info_any(self):
        """Get server info using available API"""
        return await self.api_facade.get_server_info()
    
    async def announce_message_any(self, message: str) -> bool:
        """Announce message using available API"""
        return await self.api_facade.announce(message)
    
    async def save_world_any(self) -> bool:
        """Save world using available API"""
        return await self.api_facade.save_world()
    
    async def api_get_server_info(self):
        """Get server information via REST API"""
        return await self.api_facade.get_server_info()
    
    async def api_get_players(self):
        """Get online player list via REST API"""
        return await self.api_facade.get_players()
    
    async def api_get_server_settings(self):
        """Get server settings via REST API"""
        return await self.api_facade.get_server_settings()
    
    async def api_get_server_metrics(self):
        """Get server metrics via REST API"""
        return await self.api_facade.api_get_server_metrics()
    
    async def api_announce_message(self, message: str) -> bool:
        """Announce message to all players via REST API"""
        return await self.api_facade.announce(message)
    
    async def api_kick_player(self, player_uid: str, message: str = "") -> bool:
        """Kick player from server via REST API"""
        return await self.api_facade.kick_player(player_uid, message)
    
    async def api_ban_player(self, player_uid: str, message: str = "") -> bool:
        """Ban player from server via REST API"""
        return await self.api_facade.ban_player(player_uid, message)
    
    async def api_unban_player(self, player_uid: str) -> bool:
        """Unban player from server via REST API"""
        return await self.api_facade.unban_player(player_uid)
    
    async def api_save_world(self) -> bool:
        """Save world data via REST API"""
        return await self.api_facade.save_world()
    
    async def api_shutdown_server(self, waittime: int = 1, message: str = "Server shutdown") -> bool:
        """Shutdown server gracefully via REST API"""
        return await self.api_facade.shutdown_server(waittime, message)
    
    def get_api_manager(self) -> ServerAPIFacade:
        """Get API facade for direct API access"""
        return self.api_facade
    
    def get_process_manager(self) -> ProcessManager:
        """Get process manager for direct process control"""
        return self.process_manager
    
    def get_config_manager(self) -> ConfigManager:
        """Get config manager for direct configuration control"""
        return self.config_manager
    
    def get_steamcmd_manager(self) -> SteamCMDManager:
        """Get SteamCMD manager for direct SteamCMD operations"""
        return self.steamcmd_manager
    
    def get_monitoring_manager(self) -> MonitoringManager:
        """Get monitoring manager for direct monitoring control"""
        return self.monitoring_manager
    
    def get_overall_status(self) -> dict:
        """Get comprehensive server status including startup state"""
        server_status = self.get_server_status()
        monitoring_status = self.monitoring_manager.get_monitoring_status()
        
        status = {
            "server": server_status,
            "monitoring": monitoring_status,
            "startup_completed": self._startup_completed,
            "backup_enabled": self.config.backup.enabled,
            "api_enabled": self.config.rest_api.enabled,
            "rcon_enabled": self.config.rcon.enabled,
            "discord_enabled": self.config.discord.enabled,
            "server_name": self.config.server.name,
            "max_players": self.config.server.max_players,
            "language": self.config.language
        }
        
        if self._backup_manager:
            try:
                backup_stats = self._backup_manager.get_backup_statistics()
                status["backup_stats"] = backup_stats
            except Exception as e:
                status["backup_error"] = str(e)
        
        return status
    
    def is_startup_completed(self) -> bool:
        """Check if full server startup process is completed"""
        return self._startup_completed


async def main():
    """Main production server function with API readiness verification"""
    manager_exit_code = 0
    config = get_config()
    setup_logging(
        log_level=config.monitoring.log_level,
        log_format_style=config.monitoring.log_format_style,
        log_dir=config.paths.log_dir,
        enable_console=True,
        enable_file=True
    )
    print("Starting Palworld Dedicated Server")
    print(f"   Server: {config.server.name}")
    print(f"   Port: {config.server.port}")
    print(f"   Max Players: {config.server.max_players}")
    
    async with PalworldServerManager(config) as manager:
        loop = asyncio.get_running_loop()
        for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(
                    shutdown_signal,
                    manager.request_shutdown,
                    0,
                    f"Received {shutdown_signal.name}",
                )
            except (NotImplementedError, RuntimeError):
                # Windows development loops do not implement POSIX handlers.
                pass

        if config.steamcmd.update_on_start:
            print("Downloading/updating server files...")
            download_success = await manager.download_server_files()
            if not download_success:
                print("Server file download failed")
                return 1
        
        print("Generating server settings...")
        manager.generate_server_settings()
        manager.generate_engine_settings()
        
        print("Starting Palworld server...")
        startup_success = await manager.start_server_with_verification()
        
        if startup_success:
            print("Palworld server started successfully!")
            
            status = manager.get_overall_status()
            print(f"Monitoring active: {status['monitoring']['monitoring_active']}")
            print(f"Startup completed: {status['startup_completed']}")

            # Apply file changes through a validated, graceful container recycle.
            config_restart_watch_enabled = manager.config.monitoring.mode in (
                "logs", "prometheus", "both"
            )
            if config_restart_watch_enabled:
                async def on_config_change(staged_config):
                    await manager.apply_config_and_recycle(staged_config)

                await manager.config_manager.start_watching(
                    check_interval=30,
                    on_change=on_config_change
                )
                print("Validated config restart watcher started (30s polling)")
            
            try:
                print("Server operational. Monitoring in progress...")
                manager.start_process_watch()
                manager_exit_code = await manager.wait_for_shutdown()
                    
            except KeyboardInterrupt:
                print("Received shutdown signal...")
                await manager.stop_server("Server shutdown requested")
        else:
            print("Failed to start Palworld server")
            return 1
    
    print("Palworld server manager stopped")
    if manager_exit_code == 75:
        print("Requesting Supervisor shutdown for container recreation")
        try:
            supervisorctl = await asyncio.create_subprocess_exec(
                "supervisorctl", "shutdown"
            )
            await asyncio.wait_for(supervisorctl.wait(), timeout=10)
        except (OSError, asyncio.TimeoutError) as exc:
            print(f"Unable to request Supervisor shutdown: {exc}")
    return manager_exit_code


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
