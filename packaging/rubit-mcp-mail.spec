# PyInstaller spec building both executables into one shared onedir bundle.
#
# The two executables used to be built as independent `--onefile` binaries,
# which meant the installer embedded a *complete second copy* of the server
# binary's own Python runtime, cryptography, and OpenSSL as a data blob on top
# of its own copy of the same things - roughly doubling the download for no
# reason. MERGE() below gives both executables one shared copy of everything
# they have in common, and COLLECT() lays them out side by side so the setup
# wizard can find the server executable as a plain sibling file at runtime
# (see installer.py's bundled_server_binary()).
#
# An earlier version of this spec also tried to `excludes=` the ASGI
# server/HTTP-client stack (uvicorn, starlette, sse_starlette, httpx, h11,
# h2), on the theory that server.py:338's `mcp.run(transport="stdio")` never
# needs them. That theory was wrong, and only actually running the frozen
# `serve` command (not just grepping imports) caught it:
# `mcp/__init__.py` unconditionally imports `mcp.client.session_group`
# (needs httpx, vendored as `httpx2`), and `mcp/server/lowlevel/server.py` -
# the exact module this app imports - unconditionally imports `starlette`,
# `sse_starlette`, and `uvicorn` at module scope, regardless of which
# transport is actually selected at runtime. None of it is excludable through
# a plain `excludes=` list without vendoring/patching the `mcp` package
# itself, which is out of scope here. This spec's only real saving is
# de-duplicating the shared runtime between the two executables - not
# trimming dead code, because there turned out to be none reachable this way.
#
# Run from the repo root: pyinstaller packaging/rubit-mcp-mail.spec

block_cipher = None

cli_analysis = Analysis(
    ["cli_entry.py"],
    pathex=[],
    noarchive=False,
)

setup_analysis = Analysis(
    ["setup_entry.py"],
    pathex=[],
    noarchive=False,
)

MERGE(
    (cli_analysis, "rubit-mcp-mail", "rubit-mcp-mail"),
    (setup_analysis, "rubit-mcp-mail-setup", "rubit-mcp-mail-setup"),
)

cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data, cipher=block_cipher)
setup_pyz = PYZ(setup_analysis.pure, setup_analysis.zipped_data, cipher=block_cipher)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="rubit-mcp-mail",
    console=True,
    version="packaging/version_info.txt",
)

setup_exe = EXE(
    setup_pyz,
    setup_analysis.scripts,
    [],
    exclude_binaries=True,
    name="rubit-mcp-mail-setup",
    console=False,
    version="packaging/version_info.txt",
)

COLLECT(
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    setup_exe,
    setup_analysis.binaries,
    setup_analysis.datas,
    name="rubit-mcp-mail",
)
