# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client
from mcp.server.mcpserver import MCPServer


def test_in_memory_client_drives_a_trivial_tool():
    server = MCPServer("contract")

    @server.tool()
    def ping() -> dict[str, Any]:
        return {"pong": True}

    @server.resource("carbon://contract/hello")
    def hello() -> str:
        return "hello"

    async def run():
        async with Client(server) as client:
            tools = await client.list_tools()
            assert "ping" in [t.name for t in tools.tools]
            result = await client.call_tool("ping", {})
            assert result.structured_content == {"pong": True}
            res = await client.read_resource("carbon://contract/hello")
            assert res.contents[0].text == "hello"

    asyncio.run(run())
