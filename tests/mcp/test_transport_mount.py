# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from click.testing import CliRunner

from carbon.cli import build_cli
from carbon.mcp.transport import build_http_app, build_mcp_sub_app


def test_sub_app_helper_exported():
    assert callable(build_mcp_sub_app) and callable(build_http_app)


def test_web_command_registered_and_rejects_non_loopback(tmp_path):
    r = CliRunner().invoke(build_cli(), ["--journal", str(tmp_path / "j"),
                                         "web", "--host", "0.0.0.0"])
    assert r.exit_code != 0 and "127.0.0.1" in r.output
