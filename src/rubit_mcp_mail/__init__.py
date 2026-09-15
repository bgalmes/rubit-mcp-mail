"""Provider-agnostic, read-only MCP server for reading mail over IMAP."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rubit-mcp-mail")
except PackageNotFoundError:
    # Running from a source checkout that was never `pip install`-ed.
    __version__ = "0.0.0-dev"
