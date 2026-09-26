"""Pain p-13393743: a default_factory tool arg (record_decision replaces/domains) must be optional in
the MCP tool signature and schema, not required."""
import inspect

from edp8 import bundles
from edp8.mcp_server import _wrap, build_role_server


def _tool(name):
    return bundles.ALL_TOOLS[name]


def test_default_factory_args_are_optional_in_the_signature():
    call = _wrap(_tool("record_decision"), board_url="http://127.0.0.1:1", admin_token=None)
    params = inspect.signature(call).parameters
    for name in ("replaces", "domains"):
        assert params[name].default == [], name


def test_default_factory_args_are_not_required_in_the_tool_schema():
    import anyio
    server = build_role_server("architect", board_url="http://127.0.0.1:1", admin_token=None)
    tools = anyio.run(server.list_tools)
    schema = next(t for t in tools if t.name == "record_decision").input_schema
    assert "replaces" not in schema.get("required", [])
    assert "domains" not in schema.get("required", [])
