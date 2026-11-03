"""Utkast i användarens brevlåda (SPEC 6.6 steg 4). ÖPPEN FRÅGA 3: Outlook/Microsoft 365 eller Gmail.

Båda adaptrarna skapar bara **utkast** – det finns ingen metod som skickar. De är stubbar tills användaren
gett
behörighet (Microsoft Graph `Mail.ReadWrite`, Gmail `gmail.compose`); fram till dess sparas utkastet som .eml.
"""

from __future__ import annotations

from typing import Protocol


class MailboxNotConfigured(RuntimeError):
    pass


class DraftCreator(Protocol):
    name: str

    def create_draft(self, eml: bytes) -> str:
        """Lägger utkastet i användarens brevlåda och returnerar utkastets id. Skickar aldrig."""
        ...


class GraphDraftCreator:
    """Microsoft 365 via Graph: POST /me/messages (skapar ett utkast). Kräver Mail.ReadWrite."""

    name = "outlook"

    def create_draft(self, eml: bytes) -> str:
        raise MailboxNotConfigured(
            "Utkast i Outlook är inte påslaget: behörighet för Microsoft Graph (Mail.ReadWrite) saknas "
            "(SPEC 14, "
            "fråga 3). Ladda ned .eml-filen och öppna den i Outlook i stället."
        )


class GmailDraftCreator:
    """Gmail via users.drafts.create (skapar ett utkast). Kräver gmail.compose."""

    name = "gmail"

    def create_draft(self, eml: bytes) -> str:
        raise MailboxNotConfigured(
            "Utkast i Gmail är inte påslaget: behörighet (gmail.compose) saknas (SPEC 14, fråga 3). "
            "Ladda ned "
            ".eml-filen och öppna den i stället."
        )
