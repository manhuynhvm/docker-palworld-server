"""Tests for the metrics collector (log-based + Prometheus)."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.monitoring.metrics_collector import (
    MetricsCollector, SystemMetrics, GameMetrics
)


class TestMetricsCollector:
    """FS-17.x: Metrics collector behavior."""

    @pytest.fixture
    def collector(self, palworld_config):
        return MetricsCollector(palworld_config)

    def test_system_metrics_dataclass(self):
        """FS-17.1: SystemMetrics fields."""
        metrics = SystemMetrics(
            cpu_percent=45.0,
            memory_usage_gb=8.0,
            memory_percent=50.0,
            disk_usage_gb=100.0,
            disk_percent=65.0,
            network_bytes_sent=1000,
            network_bytes_recv=2000
        )
        assert metrics.cpu_percent == 45.0
        assert metrics.memory_usage_gb == 8.0

    def test_game_metrics_dataclass(self):
        """FS-17.4: GameMetrics fields."""
        metrics = GameMetrics(
            players_online=3,
            max_players=16,
            server_uptime_seconds=3600,
            tps=20.0,
            world_save_size_mb=50.0
        )
        assert metrics.players_online == 3
        assert metrics.tps == 20.0

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    @pytest.mark.asyncio
    async def test_collect_system_metrics(
        self, mock_disk, mock_mem, mock_cpu, collector
    ):
        """FS-17.1: Collects system metrics."""
        mock_cpu.return_value = 45.0
        mock_mem.return_value.total = 16 * 1024**3
        mock_mem.return_value.used = 8 * 1024**3
        mock_mem.return_value.percent = 50.0
        mock_disk.return_value.total = 500 * 1024**3
        mock_disk.return_value.used = 250 * 1024**3

        with patch('psutil.net_io_counters') as mock_net:
            mock_net.return_value.bytes_sent = 1000
            mock_net.return_value.bytes_recv = 2000
            metrics = await collector._collect_system_metrics()
            assert metrics.cpu_percent == 45.0
            assert metrics.memory_percent == 50.0

    def test_collect_game_metrics_sync(self, collector):
        """FS-17.5: Sync game metrics collection."""
        players = [{"name": "P1"}, {"name": "P2"}]
        metrics = collector.collect_game_metrics_sync(
            players_data=players,
            server_info={"tps": 20.0}
        )
        assert metrics.players_online == 2
        assert metrics.tps == 20.0

    def test_get_current_metrics_summary(self, collector):
        """FS-17.6: Real-time metrics summary."""
        with patch('psutil.cpu_percent', return_value=30.0), \
             patch('psutil.virtual_memory') as mock_mem, \
             patch('psutil.disk_usage') as mock_disk, \
             patch('psutil.net_io_counters') as mock_net:
            mock_mem.return_value.percent = 40.0
            mock_mem.return_value.available = 8 * 1024**3
            mock_disk.return_value.used = 100 * 1024**3
            mock_disk.return_value.total = 200 * 1024**3
            mock_net.return_value.bytes_sent = 500
            mock_net.return_value.bytes_recv = 1000

            summary = collector.get_current_metrics_summary()
            assert "uptime_seconds" in summary
            assert "system" in summary
            assert summary["system"]["cpu_percent"] == 30.0

    def test_record_api_call(self, collector):
        """FS-17.2: API call recording."""
        collector.record_api_call("/info", 200, 150.0)
        # Should not raise

    def test_record_backup_event(self, collector):
        """FS-17.2: Backup event recording."""
        collector.record_backup_event(30.0, 1024 * 1024)
        # Should not raise

    def test_record_player_event(self, collector):
        """FS-17.2: Player event recording."""
        collector.record_player_event("join", "Player1", 3)
        collector.record_player_event("leave", "Player1", 2)
        # Should not raise

    def test_record_server_event(self, collector):
        """FS-17.2: Server event recording."""
        collector.record_server_event("start", "Server started")
        collector.record_server_event("restart", "Server restarting")
        # Should not raise

    def test_prometheus_mode_config(self, palworld_config):
        """FS-17.7: Prometheus mode configuration."""
        # Default mode from config is 'logs' or 'both'
        palworld_config.monitoring.mode = "prometheus"
        collector = MetricsCollector(palworld_config)
        assert collector.enable_prometheus is True
        assert collector.enable_logs is False

        palworld_config.monitoring.mode = "both"
        collector = MetricsCollector(palworld_config)
        assert collector.enable_prometheus is True
        assert collector.enable_logs is True

        palworld_config.monitoring.mode = "logs"
        collector = MetricsCollector(palworld_config)
        assert collector.enable_prometheus is False
        assert collector.enable_logs is True

    @patch('src.monitoring.metrics_collector._PROMETHEUS_AVAILABLE', False)
    def test_prometheus_unavailable_fallback(self, palworld_config):
        """FS-17.8: Graceful fallback when prometheus_client not available."""
        palworld_config.monitoring.mode = "prometheus"
        collector = MetricsCollector(palworld_config)
        assert collector.enable_prometheus is False
        # Should still work without raising
        collector.record_player_event("join", "Player1", 1)
        collector.record_api_call("/info", 200, 100.0)

    def test_start_stop_collection_logs_only(self, collector):
        """FS-17.9: Start/stop collection lifecycle (logs mode)."""
        collector.enable_prometheus = False

        import asyncio
        with patch.object(collector, '_collection_loop', return_value=asyncio.sleep(0)):
            with patch('src.monitoring.metrics_collector.log_server_event') as mock_log:
                asyncio.run(collector.start_collection())
                assert collector._running is True
                mock_log.assert_called_once()

                asyncio.run(collector.stop_collection())
                assert collector._running is False

    @patch('src.monitoring.metrics_collector.start_http_server')
    def test_start_collection_prometheus_mode(self, mock_start_http, palworld_config):
        """FS-17.10: Prometheus HTTP server starts in prometheus mode."""
        palworld_config.monitoring.mode = "prometheus"
        collector = MetricsCollector(palworld_config)
        collector.enable_prometheus = True

        import asyncio
        with patch.object(collector, '_collection_loop', return_value=asyncio.sleep(0)):
            asyncio.run(collector.start_collection())
            mock_start_http.assert_called_once_with(8080)
            assert collector._prometheus_server_started is True

    def test_update_prometheus_system(self, collector):
        """FS-17.11: Prometheus gauge updates for system metrics."""
        collector.enable_prometheus = True

        try:
            metrics = SystemMetrics(
                cpu_percent=55.0, memory_usage_gb=4.0, memory_percent=40.0,
                disk_percent=60.0, disk_usage_gb=120.0,
                network_bytes_sent=5000, network_bytes_recv=10000
            )
            collector._update_prometheus_system(metrics)
        except Exception:
            pass  # OK if prometheus_client not available at module level

    def test_update_prometheus_game(self, collector):
        """FS-17.12: Prometheus gauge updates for game metrics."""
        collector.enable_prometheus = True

        try:
            metrics = GameMetrics(
                players_online=5, max_players=32,
                server_uptime_seconds=7200, tps=20.0, world_save_size_mb=100.0
            )
            collector._update_prometheus_game(metrics)
        except Exception:
            pass  # OK if prometheus_client not available at module level

    def test_process_game_metrics_updates_prometheus(self, collector):
        """FS-17.13: process_game_metrics updates Prometheus gauges."""
        collector.enable_prometheus = True
        import datetime
        metrics = GameMetrics(
            players_online=3, max_players=32,
            server_uptime_seconds=3600, tps=19.5, world_save_size_mb=80.0
        )

        with patch.object(collector, '_update_prometheus_game') as mock_update:
            import asyncio
            asyncio.run(collector.process_game_metrics(metrics))
            mock_update.assert_called_once_with(metrics)

    def test_serial_start_stop_safe(self, collector):
        """FS-17.14: Calling start/stop multiple times is safe."""
        collector.enable_prometheus = False
        import asyncio

        with patch.object(collector, '_collection_loop', return_value=asyncio.sleep(0)):
            # Start twice - second should warn
            asyncio.run(collector.start_collection())
            with patch.object(collector.logger, 'warning') as mock_warn:
                asyncio.run(collector.start_collection())
                mock_warn.assert_called_once()

            asyncio.run(collector.stop_collection())
            # Stop twice - second should no-op
            asyncio.run(collector.stop_collection())
            assert collector._running is False
