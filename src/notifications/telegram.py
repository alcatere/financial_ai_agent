import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

API_BASE = "https://api.telegram.org/bot{token}/{method}"
CONFIRM_RE = re.compile(r"^/confirm[_ ](\d+)$", re.IGNORECASE)
REJECT_RE = re.compile(r"^/reject[_ ](\d+)$", re.IGNORECASE)


def escape_markdown(text: str) -> str:
    """Escapes Telegram legacy-Markdown special characters (_ * ` [) in
    free-form text - notably LLM-generated rationale - before it's
    interpolated into a message that also uses literal Markdown (*bold*).
    Without this, a stray '_' or '*' in the model's own wording breaks
    Telegram's parser and the whole message fails to send.
    """
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def notify_safely(notifier: "TelegramNotifier", text: str) -> None:
    """send_message that never raises.

    A Telegram outage or a Markdown-breaking character in LLM-generated text
    must never crash the caller or land in an `except` block that then
    reclassifies an order's already-correct status (e.g. EXECUTED) as
    failed just because the *notification about it* failed.
    """
    try:
        notifier.send_message(text)
    except Exception as e:
        print(f"[!] Failed to send Telegram notification: {e}\n    Message was: {text}")


@dataclass
class ConfirmationReply:
    order_id: int
    approved: bool
    update_id: int


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, offset_path: str = "data/telegram_offset.txt"):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.offset_path = offset_path

    def _url(self, method: str) -> str:
        return API_BASE.format(token=self.bot_token, method=method)

    def send_message(self, text: str) -> None:
        resp = requests.post(
            self._url("sendMessage"),
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()

    def _load_offset(self) -> int:
        try:
            with open(self.offset_path) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _save_offset(self, offset: int) -> None:
        import os
        os.makedirs(os.path.dirname(self.offset_path) or ".", exist_ok=True)
        with open(self.offset_path, "w") as f:
            f.write(str(offset))

    def get_updates(self) -> List[dict]:
        """Fetch new raw Telegram updates without advancing the stored offset.

        Callers must call `ack(update_id)` once an update has actually been
        handled, so a crash mid-batch only loses progress on the update being
        processed - not on every update fetched in the same poll.
        """
        offset = self._load_offset()
        resp = requests.get(
            self._url("getUpdates"),
            params={"offset": offset, "timeout": 0},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])

    def ack(self, update_id: int) -> None:
        """Mark this update (and everything before it) as processed."""
        if update_id + 1 > self._load_offset():
            self._save_offset(update_id + 1)

    def parse_confirmation(self, update: dict) -> Optional[ConfirmationReply]:
        """Parse a single update into a ConfirmationReply, or None if it isn't one."""
        message = update.get("message", {})
        if str(message.get("chat", {}).get("id")) != str(self.chat_id):
            return None
        text = (message.get("text") or "").strip()
        parsed = self._parse(text)
        if not parsed:
            return None
        order_id, approved = parsed
        return ConfirmationReply(order_id=order_id, approved=approved, update_id=update["update_id"])

    @staticmethod
    def _parse(text: str) -> Optional[Tuple[int, bool]]:
        m = CONFIRM_RE.match(text)
        if m:
            return int(m.group(1)), True
        m = REJECT_RE.match(text)
        if m:
            return int(m.group(1)), False
        return None
