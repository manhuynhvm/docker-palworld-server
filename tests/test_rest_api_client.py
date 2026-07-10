"""Tests for the REST API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from src.clients.rest_api_client import RestAPIClient


class TestRestAPIClient:
    """FS-5.x: REST API client behavior."""

    @pytest.fixture
    def client(self, palworld_config, mock_logger):
        return RestAPIClient(palworld_config, mock_logger)

    def _make_async_context_manager(self, mock_response):
        """Create an async context manager mock from a response mock."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    def _setup_mock_session(self, client, mock_response):
        """Configure client session to return mock_response via request()."""
        cm = self._make_async_context_manager(mock_response)
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=cm)
        client.session = mock_session
        return mock_session

    @pytest.mark.asyncio
    async def test_enter_exit(self, client):
        """FS-5.7: Context manager lifecycle."""
        with patch('aiohttp.ClientSession') as mock_session:
            mock_instance = MagicMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.close = AsyncMock(return_value=None)
            mock_session.return_value = mock_instance

            async with client as c:
                assert c.session is not None

    @pytest.mark.asyncio
    async def test_make_request_success(self, client):
        """FS-5.4: Successful GET request."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"name": "Test"})
        mock_response.text = AsyncMock(return_value='{"name": "Test"}')

        self._setup_mock_session(client, mock_response)

        result = await client._make_request("/info")
        assert result == {"name": "Test"}

    @pytest.mark.asyncio
    async def test_make_request_with_retry_success(self, client):
        """FS-5.3: Retry logic succeeds on first attempt."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"name": "Test"})
        mock_response.text = AsyncMock(return_value='{"name": "Test"}')

        self._setup_mock_session(client, mock_response)

        result = await client._make_request_with_retry("/info")
        assert result == {"name": "Test"}

    @pytest.mark.asyncio
    async def test_make_request_with_retry_failure(self, client):
        """FS-5.3: Retry exhausts and returns None."""
        def raise_error(*args, **kwargs):
            raise Exception("Connection error")

        cm = self._make_async_context_manager(MagicMock())
        cm.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=cm)
        client.session = mock_session

        result = await client._make_request_with_retry("/info", retry_count=2)
        assert result is None
        assert mock_session.request.call_count == 3

    @pytest.mark.asyncio
    async def test_get_server_info(self, client):
        """FS-5.4: GET /info."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"name": "Test"})
        mock_response.text = AsyncMock(return_value='{"name": "Test"}')

        self._setup_mock_session(client, mock_response)

        result = await client.get_server_info()
        assert result == {"name": "Test"}

    @pytest.mark.asyncio
    async def test_get_players(self, client):
        """FS-5.4: GET /players returns player list."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"players": [{"name": "P1"}]})
        mock_response.text = AsyncMock(return_value='{"players": [{"name": "P1"}]}')

        self._setup_mock_session(client, mock_response)

        result = await client.get_players()
        assert result == [{"name": "P1"}]

    @pytest.mark.asyncio
    async def test_post_endpoints(self, client):
        """FS-5.4: POST endpoints work."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={})
        mock_response.text = AsyncMock(return_value="{}")

        self._setup_mock_session(client, mock_response)

        assert await client.announce_message("Hello") is True
        assert await client.kick_player("uid1") is True
        assert await client.ban_player("uid1") is True
        assert await client.unban_player("uid1") is True
        assert await client.save_world() is True
        assert await client.shutdown_server(1, "Shutdown") is True

    @pytest.mark.asyncio
    async def test_no_session_returns_none(self, client):
        """FS-5.4: Request without session returns None."""
        client.session = None
        result = await client._make_request("/info")
        assert result is None
