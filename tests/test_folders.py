from datetime import date

import pytest

from rubit_mcp_mail.backends.imap import build_search_criteria, folder_role


@pytest.mark.parametrize(
    "flags,name,expected",
    [
        # Servers that advertise SPECIAL-USE win outright, whatever the name.
        ([rb"\HasNoChildren", rb"\Junk"], "Weird Name", "junk"),
        ([rb"\Sent"], "Enviados", "sent"),
        ([rb"\Trash"], "Papelera", "trash"),
        ([rb"\Archive"], "Whatever", "archive"),
        ([rb"\Drafts"], "Borradores", "drafts"),
        # Name fallback, Outlook style.
        ([], "INBOX", "inbox"),
        ([], "Sent Items", "sent"),
        ([], "Junk Email", "junk"),
        ([], "Deleted Items", "trash"),
        ([], "Drafts", "drafts"),
        # Name fallback, Gmail style.
        ([], "[Gmail]/Sent Mail", "sent"),
        ([], "[Gmail]/Spam", "junk"),
        ([], "[Gmail]/All Mail", "archive"),
        ([], "[Gmail]/Bin", "trash"),  # Gmail's en-GB name for Trash
        # Ordinary user folders stay 'other'.
        ([], "Projects/Client", "other"),
        ([], "Receipts", "other"),
    ],
)
def test_folder_role(flags, name, expected):
    assert folder_role(flags, name) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        # Outlook.com does not advertise SPECIAL-USE, so localized mailboxes
        # depend entirely on name matching.
        ("Elementos enviados", "sent"),  # es
        ("Correo no deseado", "junk"),
        ("Elementos eliminados", "trash"),
        ("Borradores", "drafts"),
        ("Archivo", "archive"),
        ("Elements enviats", "sent"),  # ca
        ("Correu brossa", "junk"),
        ("Elements suprimits", "trash"),
        ("Esborranys", "drafts"),
        ("Arxiu", "archive"),
        ("\u00c9l\u00e9ments envoy\u00e9s", "sent"),  # fr, accented
        ("Courrier ind\u00e9sirable", "junk"),
        ("\u00c9l\u00e9ments supprim\u00e9s", "trash"),
        ("Gesendete Elemente", "sent"),  # de
        ("Gel\u00f6schte Elemente", "trash"),
        ("Entw\u00fcrfe", "drafts"),
        ("Posta inviata", "sent"),  # it
        ("Posta indesiderata", "junk"),
        ("Posta eliminata", "trash"),
        ("Itens Enviados", "sent"),  # pt
        ("Lixo Eletr\u00f4nico", "junk"),
        ("Itens Exclu\u00eddos", "trash"),
    ],
)
def test_localized_folder_names(name, expected):
    assert folder_role([], name) == expected


def test_special_use_beats_name():
    """A folder literally called Inbox but flagged Archive is an archive."""
    assert folder_role([rb"\Archive"], "Inbox") == "archive"


class TestSearchCriteria:
    def test_defaults_to_all(self):
        assert build_search_criteria() == ["ALL"]

    def test_combines_criteria(self):
        assert build_search_criteria(
            from_="bob@example.com", unread_only=True, since=date(2026, 1, 1)
        ) == ["UNSEEN", "FROM", "bob@example.com", "SINCE", date(2026, 1, 1)]

    def test_values_stay_separate_list_items(self):
        """Values must never be concatenated into the criteria string, or a
        crafted subject could inject extra IMAP commands."""
        nasty = 'x" DELETED "'
        criteria = build_search_criteria(subject=nasty)
        assert criteria == ["SUBJECT", nasty]
        assert criteria[1] is nasty
