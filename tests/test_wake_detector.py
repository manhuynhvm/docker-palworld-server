"""Tests for packet-based pause wake detection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.monitoring.wake_detector import ConnectionWakeDetector


@pytest.mark.asyncio
async def test_detector_writes_game_udp_only_config(tmp_path):
    logger = MagicMock()
    detector = ConnectionWakeDetector(8211, logger)
    detector.runtime_dir = tmp_path
    detector.config_file = tmp_path / "knockd.conf"
    detector.wake_marker = tmp_path / "client-wake"
    process = MagicMock()
    process.returncode = None

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)
    ), patch("asyncio.sleep", new=AsyncMock()):
        assert await detector.start() is True

    content = detector.config_file.read_text(encoding="utf-8")
    assert "sequence = 8211:udp" in content
    assert "palworld-control wake" in content
    assert "8212" not in content


@pytest.mark.asyncio
async def test_detector_start_failure_is_reported(tmp_path):
    logger = MagicMock()
    detector = ConnectionWakeDetector(8211, logger)
    detector.runtime_dir = tmp_path
    detector.config_file = tmp_path / "knockd.conf"
    detector.wake_marker = tmp_path / "client-wake"

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError("knockd")),
    ):
        assert await detector.start() is False

    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_detector_stop_terminates_process(tmp_path):
    detector = ConnectionWakeDetector(8211, MagicMock())
    detector.runtime_dir = tmp_path
    detector.config_file = tmp_path / "knockd.conf"
    detector.config_file.write_text("config", encoding="utf-8")
    process = MagicMock()
    process.returncode = None
    process.wait = AsyncMock(return_value=0)
    detector._process = process

    await detector.stop()

    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()
    assert not detector.config_file.exists()

