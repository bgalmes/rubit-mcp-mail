"""PyInstaller entry point for the MCP server executable.

Lives outside the package on purpose: PyInstaller runs its entry script as a
top-level `__main__` with no package context, so freezing
`src/rubit_mcp_mail/__main__.py` directly would break its relative imports.
Importing through the installed package keeps them working.
"""

from rubit_mcp_mail.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
