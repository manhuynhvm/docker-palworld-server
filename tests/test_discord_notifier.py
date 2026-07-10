"""Tests for the Discord notifier."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.notifications.discord_notifier import DiscordNotifier, NotificationLevel


class TestDiscordNotifier:
    """FS-19.x: Discord notifier behavior."""

    @pytest.fixture
    def notifier(self, palworld_config):
        n = DiscordNotifier(palworld_config)
        n.session = MagicMock()
        n.enabled = True
        n.webhook_url = "https://discord.com/api/webhooks/test"
        return n

    def test_init_disabled_without_url(self, palworld_config):
        """FS-19.1: Disabled when no webhook URL."""
        palworld_config.discord.webhook_url = ""
        n = DiscordNotifier(palworld_config)
        assert n.enabled is False

    def test_notification_level_colors(self, palworld_config):
        """FS-19.1: Level colors defined."""
        n = DiscordNotifier(palworld_config)
        colors = n.level_colors
        assert colors[NotificationLevel.INFO] == 0x00FF7F
        assert colors[NotificationLevel.WARNING] == 0xFFD700
        assert colors[NotificationLevel.ERROR] == 0xFF6B6B
        assert colors[NotificationLevel.CRITICAL] == 0x8B0000

    def _make_async_context_manager(self, mock_response):
        """Create an async context manager mock from a response mock."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    @pytest.mark.asyncio
    async def test_send_webhook_success(self, notifier):
        """FS-19.1: Successful webhook send."""
        mock_response = MagicMock()
        mock_response.status = 204

        cm = self._make_async_context_manager(mock_response)
        notifier.session.post = MagicMock(return_value=cm)

        result = await notifier._send_webhook(
            "Test notification",
            NotificationLevel.INFO
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_send_webhook_failure(self, notifier):
        """FS-19.1: Failed webhook returns False."""
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        cm = self._make_async_context_manager(mock_response)
        notifier.session.post = MagicMock(return_value=cm)

        result = await notifier._send_webhook(
            "Test",
            NotificationLevel.INFO
        )
        assert result is False

    def test_init_enabled(self, palworld_config):
        """FS-19.1: Enabled when webhook URL provided."""
        palworld_config.discord.webhook_url = "https://discord.com/api/webhooks/test"
        palworld_config.discord.enabled = True
        n = DiscordNotifier(palworld_config)
        assert n.enabled is True

    def test_mention_role_config(self, palworld_config):
        palworld_config.discord.mention_role = "123456"
        n = DiscordNotifier(palworld_config)
        assert n.mention_role == "123456"
