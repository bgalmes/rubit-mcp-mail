"""Local web GUI for viewing and editing config.toml.

Binds to 127.0.0.1 only and is meant for the one person sitting at the machine.
Because app passwords and sign-in now pass through it, "local" is not left to
mean "unprotected": the server mints a random token at startup, the browser is
opened on a URL carrying it, and the token is exchanged for a SameSite=Strict
cookie. Requests without it are refused, as are requests whose Host is not
loopback (DNS rebinding) or whose Origin is another site (CSRF).

Pure stdlib, no web framework: the GUI is forms and redirects. Rendering lives
in webui_pages.py, and every write goes through config_editor.py so the file
keeps its comments and is never left in a state the CLI would refuse to load.
"""

from __future__ import annotations

import secrets as secrets_mod
import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import webui_pages as pages
from .auth import MicrosoftDeviceCodeAuth, PasswordAuth
from .auth.oauth_microsoft import DeviceFlow
from .config import Config, config_path, load_config
from .config_editor import (
    apply_toggles,
    apply_write_toggles,
    load_document,
    remove_account,
    remove_provider_override,
    save_document,
    set_download_dir,
    upsert_account,
    upsert_provider_override,
    validate_account_form,
    write_disabled_tools,
    write_write_permissions,
)
from .diagnostics import run_doctor
from .secrets import SecretStore
from .session import Session

COOKIE_NAME = "rubit_gui"

#: Device-code sign-ins in progress, keyed by a random id handed to the browser.
#: The flow outlives the request that started it - MSAL blocks until the user
#: finishes in another tab - so it waits here on a background thread.
_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()


class Redirect(Exception):
    """Answer this request with a 303 to `location`."""

    def __init__(self, location: str) -> None:
        self.location = location
        super().__init__(location)


def _banner(path: str, message: str) -> str:
    return f"{path}?msg={quote(message)}"


def _first(posted: dict[str, list[str]], key: str, default: str = "") -> str:
    values = posted.get(key)
    return values[0] if values else default


def raw_accounts(doc: Any) -> dict[str, dict]:
    """Account tables straight from the TOML, bypassing validation.

    The forms are built from these rather than from `Config` so that an account
    which fails validation - the exact case a user needs help with - can still
    be opened and repaired in the GUI.
    """
    accounts = doc.get("accounts") or {}
    return {name: dict(body) for name, body in accounts.items()}


class Handler(BaseHTTPRequestHandler):
    server: ConfigServer  # type: ignore[assignment]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # keep stdout clean; this isn't a diagnostic tool

    # -- request plumbing ------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def _handle(self, method: str) -> None:
        split = urlsplit(self.path)
        query = parse_qs(split.query)
        if not self._authorised(method, query, split.path):
            return
        parts = [part for part in split.path.split("/") if part]
        posted = self._read_form() if method == "POST" else {}
        try:
            page = self._route(method, parts, query, posted)
        except Redirect as redirect:
            self._redirect(redirect.location)
            return
        except Exception as exc:  # noqa: BLE001 - show the user, never a traceback
            page = pages.layout("Error", "<h1>Something went wrong</h1>", error=str(exc))
        self._respond(page)

    def _authorised(self, method: str, query: dict[str, list[str]], path: str) -> bool:
        """Enforce the loopback/token/origin rules. Answers the request if not."""
        token = self.server.token
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "::1", "[::1]", ""):
            self._deny("This page only answers to 127.0.0.1.")
            return False

        origin = self.headers.get("Origin")
        if method == "POST" and origin:
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if origin not in (expected, f"http://localhost:{self.server.server_port}"):
                self._deny("Cross-site request refused.")
                return False

        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        if COOKIE_NAME in cookie and secrets_mod.compare_digest(cookie[COOKIE_NAME].value, token):
            return True

        supplied = (query.get("t") or [""])[0]
        if supplied and secrets_mod.compare_digest(supplied, token):
            # Swap the one-time URL token for a cookie so no later link, form
            # action or redirect has to carry the secret around.
            self.send_response(303)
            self.send_header("Location", path or "/")
            self.send_header(
                "Set-Cookie", f"{COOKIE_NAME}={token}; Path=/; SameSite=Strict; HttpOnly"
            )
            self.end_headers()
            return False

        self._deny(
            "Missing or invalid access token. Open the URL printed by "
            "`rubit-mcp-mail gui` in full - it carries a one-time token."
        )
        return False

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body)

    def _deny(self, message: str) -> None:
        encoded = pages.layout("Refused", f"<h1>Refused</h1><p>{pages.esc(message)}</p>").encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _respond(self, page: str) -> None:
        encoded = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    # -- routing ---------------------------------------------------------
    def _route(
        self,
        method: str,
        parts: list[str],
        query: dict[str, list[str]],
        posted: dict[str, list[str]],
    ) -> str:
        path = config_path()
        message = _first(query, "msg")

        if not parts:
            if not path.exists():
                raise Redirect("/setup")
            return self._overview(path, message)
        if parts == ["setup"]:
            return self._setup(method, path)
        if parts == ["download-dir"] and method == "POST":
            return self._download_dir(path, posted)
        if parts == ["accounts", "new"]:
            return self._account_form(method, path, None, posted)
        if len(parts) == 2 and parts[0] == "accounts":
            return self._account_form(method, path, parts[1], posted)
        if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "delete":
            return self._delete_account(method, path, parts[1], posted)
        if parts == ["permissions"]:
            return self._permissions(method, path, query, posted)
        if parts == ["providers"]:
            return self._providers(method, path, posted, message)
        if len(parts) == 2 and parts[0] == "auth":
            return self._auth(method, parts[1], query, posted)
        if parts[0] == "doctor":
            return self._doctor(parts[1] if len(parts) > 1 else None)

        return pages.layout("Not found", "<h1>No such page</h1><p><a href='/'>Accounts</a></p>")

    # -- pages -----------------------------------------------------------
    def _overview(self, path: Path, message: str) -> str:
        # connect=False: the overview must stay instant, so it checks
        # credentials only. The doctor page is where the network gets touched.
        report = run_doctor(connect=False)
        return pages.render_overview(report, raw_accounts(load_document(path)), banner=message)

    def _setup(self, method: str, path: Path) -> str:
        if method == "GET":
            if path.exists():
                raise Redirect("/")
            return pages.render_setup(path)
        doc = load_document(path)
        set_download_dir(doc, str(Path.home() / "Downloads" / "rubit-mcp-mail"))
        save_document(path, doc)
        raise Redirect("/accounts/new")

    def _download_dir(self, path: Path, posted: dict[str, list[str]]) -> str:
        doc = load_document(path)
        set_download_dir(doc, _first(posted, "download_dir"))
        save_document(path, doc)
        raise Redirect(_banner("/", "Download directory saved."))

    def _account_form(
        self, method: str, path: Path, name: str | None, posted: dict[str, list[str]]
    ) -> str:
        doc = load_document(path)
        existing = raw_accounts(doc)
        is_new = name is None

        if method == "GET":
            if not is_new and name not in existing:
                raise Redirect(_banner("/", f"No account named {name}."))
            fields = dict(existing.get(name or "", {})) if not is_new else {"provider": "outlook"}
            disabled = list(fields.get("disabled_tools") or []) if not is_new else None
            return pages.render_account_form(
                name or "", fields, is_new=is_new, disabled_tools=disabled
            )

        submitted = {
            "provider": _first(posted, "provider"),
            "email": _first(posted, "email"),
            "client_id": _first(posted, "client_id"),
            "host": _first(posted, "host"),
            "port": _first(posted, "port"),
            "ssl": _first(posted, "ssl"),
        }
        account_name = _first(posted, "name") if is_new else (name or "")
        try:
            if is_new and account_name in existing:
                raise ValueError(f"An account named {account_name!r} already exists.")
            cleaned = validate_account_form(account_name, submitted)
            upsert_account(doc, account_name, cleaned)
            if not is_new:
                disabled = apply_toggles([account_name], posted)[account_name]
                accounts = doc["accounts"][account_name]
                if disabled:
                    accounts["disabled_tools"] = disabled
                else:
                    accounts.pop("disabled_tools", None)
            save_document(path, doc)
        except ValueError as exc:
            disabled_now = (
                None if is_new else list(existing.get(account_name, {}).get("disabled_tools") or [])
            )
            return pages.render_account_form(
                account_name,
                submitted,
                is_new=is_new,
                error=str(exc),
                disabled_tools=disabled_now,
            )
        raise Redirect(_banner("/", f"Saved {account_name}."))

    def _delete_account(
        self, method: str, path: Path, name: str, posted: dict[str, list[str]]
    ) -> str:
        doc = load_document(path)
        if name not in raw_accounts(doc):
            raise Redirect(_banner("/", f"No account named {name}."))
        store = SecretStore()
        keys = [f"password:{name}", f"msal-cache:{name}"]

        if method == "GET":
            has_secret = any(store.get(key) for key in keys)
            return pages.render_delete(name, has_secret)

        remove_account(doc, name)
        save_document(path, doc)
        if "drop_secret" in posted:
            for key in keys:
                store.delete(key)
        raise Redirect(_banner("/", f"Removed {name}."))

    def _permissions(
        self, method: str, path: Path, query: dict[str, list[str]], posted: dict[str, list[str]]
    ) -> str:
        config: Config = load_config()
        if method == "GET":
            return pages.render_permissions(config, saved=query.get("saved") == ["1"])
        names = list(config.accounts)
        write_disabled_tools(path, apply_toggles(names, posted))
        write_write_permissions(path, apply_write_toggles(names, posted))
        raise Redirect("/permissions?saved=1")

    def _providers(
        self, method: str, path: Path, posted: dict[str, list[str]], message: str
    ) -> str:
        doc = load_document(path)
        current = {name: dict(body) for name, body in (doc.get("providers") or {}).items()}
        if method == "GET":
            return pages.render_providers(current, banner=message)

        for provider in list(current) + list(pages.PROFILES):
            fields = {
                "host": _first(posted, f"{provider}__host").strip(),
                "port": _first(posted, f"{provider}__port").strip(),
                "ssl": _first(posted, f"{provider}__ssl").strip().lower(),
                "authority": _first(posted, f"{provider}__authority").strip(),
                "scopes": [
                    line.strip()
                    for line in _first(posted, f"{provider}__scopes").splitlines()
                    if line.strip()
                ],
            }
            try:
                if fields["port"]:
                    fields["port"] = int(fields["port"])
                if fields["ssl"]:
                    if fields["ssl"] not in ("true", "false"):
                        raise ValueError(f"SSL for {provider} must be 'true' or 'false'.")
                    fields["ssl"] = fields["ssl"] == "true"
            except ValueError as exc:
                return pages.render_providers(current, error=str(exc))
            if any(fields.values()):
                upsert_provider_override(doc, provider, fields)
            else:
                # Also reached for a [providers.x] table this form does not
                # render - i.e. one naming an unknown provider, which is
                # exactly the table load_config refuses to read.
                remove_provider_override(doc, provider)

        try:
            save_document(path, doc)
        except ValueError as exc:
            return pages.render_providers(current, error=str(exc))
        raise Redirect(_banner("/providers", "Provider overrides saved."))

    def _auth(self, method: str, name: str, query: dict[str, list[str]], posted: dict) -> str:
        session = Session()
        account = session.account(name)
        strategy = session.auth_for(account)

        flow_id = _first(query, "flow")
        if flow_id:
            with _PENDING_LOCK:
                pending = dict(_PENDING.get(flow_id, {}))
            if not pending:
                raise Redirect(_banner("/", "That sign-in has expired; start it again."))
            return pages.render_device_flow(name, pending)

        server = f"{account.profile.host}:{account.profile.port}"
        if isinstance(strategy, PasswordAuth):
            if method == "GET":
                return pages.render_password_signin(name, account.email, server)
            try:
                result = strategy.store_password(_first(posted, "password"))
            except ValueError as exc:
                return pages.render_password_signin(name, account.email, server, error=str(exc))
            raise Redirect(_banner("/", result))

        if not isinstance(strategy, MicrosoftDeviceCodeAuth):
            raise ValueError(f"No GUI sign-in for the {account.provider!r} provider yet.")

        if method == "GET":
            return pages.render_device_start(name, account.email)
        try:
            started = strategy.begin_device_flow()
        except Exception as exc:  # noqa: BLE001 - MSAL's message is the useful part
            return pages.render_device_start(name, account.email, error=str(exc))

        flow_id = secrets_mod.token_urlsafe(8)
        with _PENDING_LOCK:
            _PENDING[flow_id] = {
                "state": "waiting",
                "code": started.user_code,
                "uri": started.verification_uri,
                "message": started.message,
            }
        threading.Thread(
            target=_await_device_flow, args=(strategy, started, flow_id), daemon=True
        ).start()
        raise Redirect(f"/auth/{name}?flow={flow_id}")

    def _doctor(self, name: str | None) -> str:
        report = run_doctor([name] if name else None, connect=True)
        return pages.render_doctor(report, connected=True)


def _await_device_flow(
    strategy: MicrosoftDeviceCodeAuth, started: DeviceFlow, flow_id: str
) -> None:
    """Block on MSAL off the request thread, recording the outcome for the page."""
    try:
        detail, state = strategy.complete_device_flow(started), "done"
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim on the page
        detail, state = str(exc), "error"
    with _PENDING_LOCK:
        pending = _PENDING.get(flow_id)
        if pending is not None:
            pending["state"] = state
            pending["detail"] = detail


class ConfigServer(ThreadingHTTPServer):
    """HTTP server carrying the per-run access token."""

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.token = secrets_mod.token_urlsafe(32)


def make_server(port: int = 0) -> ConfigServer:
    """Build the (not yet running) server, bound to 127.0.0.1:`port`.

    Split out from `serve()` so tests can bind to an ephemeral port, read
    `server.server_port` and `server.token`, and drive `serve_forever()` /
    `shutdown()` themselves.
    """
    return ConfigServer(("127.0.0.1", port), Handler)


def serve(port: int = 0, open_browser: bool = True, path: str = "/") -> None:
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_port}{path}?t={server.token}"
    print(f"Listening on {url}  (Ctrl+C to stop)")
    print("The token in that URL is what keeps other pages in your browser out.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
