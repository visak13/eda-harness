"""M0 probe MCP server: reports which EDP_* env vars reach an MCP stdio child."""
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("edp-probe")

@mcp.tool()
def env_probe() -> dict:
    """Return every EDP_* environment variable visible to this MCP server process."""
    return {k: v for k, v in os.environ.items() if k.startswith("EDP_")}

if __name__ == "__main__":
    mcp.run()
