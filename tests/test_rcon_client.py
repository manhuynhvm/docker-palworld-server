"""Tests for the RCON client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from src.clients.rcon_client import RconClient


class TestRconClient:
    """FS-6.x: RCON client behavior."""

    @pytest.fixture
    def client(self, palworld_config, mock_logger):
        return RconClient(palworld_config, mock_logger)

    @pytest.mark.asyncio
    async def test_enter_checks_rcon_cli(self, client):
        """FS-6.5: Context manager tests rcon-cli availability."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"help", b""))

        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=mock_process)):
            async with client as c:
                assert c._is_connected is True

    @pytest.mark.asyncio
    async def test_enter_rcon_cli_not_found(self, client):
        """FS-6.5: rcon-cli not found handles gracefully."""
        with patch('asyncio.create_subprocess_exec',
                   AsyncMock(side_effect=FileNotFoundError)):
            async with client as c:
                assert c._is_connected is False

    @pytest.mark.asyncio
    async def test_execute_command_not_connected(self, client):
        """FS-6.1: Command fails when not connected."""
        client._is_connected = False
        result = await client._execute_command_with_retry("Info")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_command_success(self, client):
        """FS-6.3: Successful RCON command."""
        client._is_connected = True
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"Server Info", b""))

        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=mock_process)):
            result = await client._execute_command_with_retry("Info")
            assert result == "Server Info"

    @pytest.mark.asyncio
    async def test_execute_command_failure_then_success(self, client):
        """FS-6.2: Retry logic works."""
        client._is_connected = True
        fail_process = MagicMock()
        fail_process.returncode = 1
        fail_process.communicate = AsyncMock(return_value=(b"", b"error"))

        success_process = MagicMock()
        success_process.returncode = 0
        success_process.communicate = AsyncMock(return_value=(b"OK", b""))

        mock_exec = AsyncMock()
        mock_exec.side_effect = [fail_process, success_process]

        with patch('asyncio.create_subprocess_exec', mock_exec):
            result = await client._execute_command_with_retry("Info", retry_count=2)
            assert result == "OK"

    @pytest.mark.asyncio
    async def test_uses_env_var_for_password(self, client):
        """FS-6.1: Password passed via env var, not CLI."""
        client._is_connected = True
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"OK", b""))

        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=mock_process)) as mock_exec:
            await client._execute_command_with_retry("Info")
            # Verify env was passed with RCON_PASSWORD
            call_kwargs = mock_exec.call_args[1]
            assert 'env' in call_kwargs
            assert call_kwargs['env']['RCON_PASSWORD'] == client.password
            # Verify --password is NOT in the command args
            cmd_args = mock_exec.call_args[0]
            assert '--password' not in cmd_args

    @pytest.mark.asyncio
    async def test_convenience_methods(self, client):
        """FS-6.3: All RCON methods work."""
        client._is_connected = True
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"OK", b""))

        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=mock_process)):
            assert await client.get_server_info() == "OK"
            assert await client.get_players() == "OK"
            assert await client.announce_message("Hello") is True
            assert await client.kick_player("Player1") is True
            assert await client.ban_player("Player1") is True
            assert await client.save_world() is True
            assert await client.shutdown_server(1, "bye") is True
            assert await client.get_server_settings() == "OK"
            assert await client.execute_custom_command("CustomCmd") == "OK"
