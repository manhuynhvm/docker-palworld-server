"""Tests for utility helper functions."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.utils.helpers import (
    ensure_directory, get_file_size_mb, format_bytes,
    format_duration, retry_async
)


class TestHelpers:
    """FS-22.x: Helper functions."""

    def test_ensure_directory_creates(self, tmp_path):
        """FS-22: Creates directory."""
        new_dir = tmp_path / "new" / "nested" / "dir"
        result = ensure_directory(new_dir)
        assert result == new_dir
        assert new_dir.exists()

    def test_ensure_directory_exists(self, tmp_path):
        """FS-22: Existing directory works."""
        result = ensure_directory(tmp_path)
        assert result == tmp_path

    def test_get_file_size_mb(self, tmp_path):
        """FS-22: Returns size in MB."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"x" * 1024 * 1024)
        size = get_file_size_mb(test_file)
        assert 0.99 < size < 1.01

    def test_get_file_size_mb_not_found(self):
        """FS-22: Returns 0 for missing file."""
        assert get_file_size_mb("/nonexistent/file") == 0.0

    def test_format_bytes(self):
        """FS-22: Human-readable byte sizes."""
        assert format_bytes(500) == "500.0 B"
        assert format_bytes(2048) == "2.0 KB"
        assert format_bytes(3 * 1024 * 1024) == "3.0 MB"
        assert format_bytes(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_format_duration(self):
        """FS-22: Human-readable durations."""
        assert format_duration(30) == "30.0s"
        assert format_duration(150) == "2m 30s"
        assert format_duration(7500) == "2h 5m 0s"

    @pytest.mark.asyncio
    async def test_retry_async_success_first(self):
        """FS-22: Retry succeeds on first try."""
        mock_fn = AsyncMock(return_value="success")
        decorated = retry_async(max_retries=3, delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "success"
        assert mock_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_async_succeeds_after_retry(self):
        """FS-22: Retry succeeds after failures."""
        mock_fn = AsyncMock(side_effect=[ValueError("fail"), "success"])
        decorated = retry_async(max_retries=3, delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "success"
        assert mock_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_async_exhausted(self):
        """FS-22: Retry exhausts and raises."""
        mock_fn = AsyncMock(side_effect=ValueError("always fail"))
        decorated = retry_async(max_retries=2, delay=0.01)(mock_fn)
        with pytest.raises(ValueError):
            await decorated()
        assert mock_fn.call_count == 3  # max_retries + 1


from unittest.mock import AsyncMock
