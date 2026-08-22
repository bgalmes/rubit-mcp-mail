"""A minimal in-memory stand-in for IMAPClient.

Records every command issued so tests can assert the backend never mutates the
mailbox and always peeks rather than fetches bodies.
"""

from __future__ import annotations


class FakeIMAPClient:
    def __init__(self, folders, messages, uidvalidity=1000):
        # folders: list of (flags, delimiter, name)
        self._folders = folders
        # messages: {folder_name: {uid: {fetch-key: value}}}
        self._messages = messages
        self._uidvalidity = uidvalidity
        self.selected = None
        self.calls: list[tuple] = []

    # -- recorded API ----------------------------------------------------
    def capabilities(self):
        return [b"IMAP4REV1", b"AUTH=XOAUTH2", b"SPECIAL-USE"]

    def list_folders(self, directory="", pattern="*"):
        self.calls.append(("list_folders",))
        return self._folders

    def folder_status(self, folder, what=None):
        msgs = self._messages.get(folder, {})
        return {b"MESSAGES": len(msgs), b"UNSEEN": 0}

    def select_folder(self, folder, readonly=False):
        self.calls.append(("select_folder", folder, readonly))
        if not readonly:
            raise AssertionError("select_folder must always be read-only (EXAMINE)")
        self.selected = folder
        return {b"UIDVALIDITY": self._uidvalidity, b"EXISTS": len(self._messages.get(folder, {}))}

    def search(self, criteria="ALL", charset=None):
        self.calls.append(("search", tuple(criteria), charset))
        return sorted(self._messages.get(self.selected, {}))

    def fetch(self, messages, data, modifiers=None):
        keys = [d.decode() if isinstance(d, bytes) else d for d in data]
        self.calls.append(("fetch", tuple(messages), tuple(keys)))
        for key in keys:
            if key.startswith("BODY[") and not key.startswith("BODY.PEEK["):
                raise AssertionError(f"{key} would set \\Seen; must use BODY.PEEK")
        out = {}
        store = self._messages.get(self.selected, {})
        for uid in messages:
            if uid not in store:
                continue
            entry = {}
            for key in keys:
                # The server answers a PEEK with the non-peek key.
                response_key = key.replace("BODY.PEEK[", "BODY[").encode()
                lookup = key.encode()
                if lookup in store[uid]:
                    entry[response_key] = store[uid][lookup]
                elif response_key in store[uid]:
                    entry[response_key] = store[uid][response_key]
            out[uid] = entry
        return out

    def logout(self):
        self.calls.append(("logout",))

    # -- guards ----------------------------------------------------------
    def _forbidden(self, *args, **kwargs):
        raise AssertionError("mutating IMAP command called in a read-only backend")

    add_flags = remove_flags = set_flags = _forbidden
    delete_messages = expunge = copy = move = append = _forbidden
