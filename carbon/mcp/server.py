# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP server exposing CARBON tools, session state and the journal."""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from carbon.core.session import Session


def build_mcp_server(session: Session) -> MCPServer:
    # `sess` is the closed-over Session; uds_session has a param named `session`.
    sess = session
    server = MCPServer("carbon")

    @server.tool()
    def can_sniff(count: int | None = None, timeout: float = 1.0) -> dict[str, Any]:
        """Passively capture CAN frames."""
        return sess.run_tool("can_sniff", count=count, timeout=timeout).to_dict()

    @server.tool()
    def can_dump(path: str, count: int | None = None, timeout: float = 1.0) -> dict[str, Any]:
        """Capture CAN frames to a candump -l file."""
        return sess.run_tool("can_dump", path=path, count=count, timeout=timeout).to_dict()

    @server.tool()
    def can_replay(path: str) -> dict[str, Any]:
        """Replay a candump capture onto the bus. DESTRUCTIVE: requires approval."""
        return sess.run_tool("can_replay", path=path).to_dict()

    @server.tool()
    def can_inject(arb_id: int, data_hex: str = "", extended: bool = False) -> dict[str, Any]:
        """Inject one CAN frame (data as hex string). DESTRUCTIVE: requires approval."""
        # Hex decoding happens in the adapter so a malformed payload is a journaled failure.
        return sess.run_tool(
            "can_inject", arb_id=arb_id, data=data_hex, extended=extended
        ).to_dict()

    @server.tool()
    def uds_scan() -> dict[str, Any]:
        """Discover supported UDS services (non-destructive probes only)."""
        return sess.run_tool("uds_scan").to_dict()

    @server.tool()
    def uds_session(session: str = "extended") -> dict[str, Any]:
        """Switch the UDS diagnostic session."""
        return sess.run_tool("uds_session", session=session).to_dict()

    @server.tool()
    def uds_security_access(level: int = 1) -> dict[str, Any]:
        """Perform UDS SecurityAccess seed/key at the given level."""
        return sess.run_tool("uds_security_access", level=level).to_dict()

    @server.tool()
    def uds_read_did(did: int = 0xF190) -> dict[str, Any]:
        """Read a UDS data identifier (default 0xF190, VIN)."""
        return sess.run_tool("uds_read_did", did=did).to_dict()

    @server.tool()
    def uds_read_dtc(status_mask: int = 0xFF) -> dict[str, Any]:
        """Read DTCs by status mask."""
        return sess.run_tool("uds_read_dtc", status_mask=status_mask).to_dict()

    @server.tool()
    def uds_clear_dtc(group: int = 0xFFFFFF) -> dict[str, Any]:
        """Clear DTCs for a group. DESTRUCTIVE: requires approval."""
        return sess.run_tool("uds_clear_dtc", group=group).to_dict()

    @server.tool()
    def session_state() -> dict[str, Any]:
        """Return tools, methodology mode, recent history, channel and interface."""
        return sess.state()

    # Methodology tools: thin delegates to the Session (the engine lives there).
    # Bad input (unknown mode, non-candidate step, nothing loaded) raises in the
    # Session and surfaces as an MCP tool error (isError), not an error dict.
    @server.tool()
    def methodology_load(path: str) -> dict[str, Any]:
        """Load a methodology tree (YAML path) and return the session state."""
        sess.load_methodology(path)
        return sess.state()

    @server.tool()
    def mode_set(mode: str) -> dict[str, Any]:
        """Set the methodology mode ('guided' or 'libre') and return the state."""
        sess.set_mode(mode)
        return sess.state()

    @server.tool()
    def step_ack() -> dict[str, Any]:
        """Acknowledge the current (tool-less) step and return the state."""
        sess.step_ack()
        return sess.state()

    @server.tool()
    def step_choose(step_id: str) -> dict[str, Any]:
        """Choose among candidate next steps by id and return the state."""
        sess.step_choose(step_id)
        return sess.state()

    @server.resource("carbon://journal")
    def journal() -> str:
        """Raw JSONL journal of every tool call."""
        return sess.journal_text()

    return server
