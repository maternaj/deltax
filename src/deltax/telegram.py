"""Telegram delivery (sharpener-style group map)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramGroupConfig:
    token: str
    chat_id: str


def parse_telegram_groups(raw: str) -> dict[str, TelegramGroupConfig]:
    """Parse DELTAX_TELEGRAM_GROUPS: GROUP:TOKEN:CHAT (comma-separated)."""
    groups: dict[str, TelegramGroupConfig] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if len(entry) < 4 or entry[1] != ":":
            continue
        group_id = entry[0]
        rest = entry[2:]
        if ":" not in rest:
            continue
        parts = rest.split(":")
        if len(parts) < 2:
            continue
        chat_id = parts[-1].strip()
        token = ":".join(parts[:-1]).strip()
        if group_id and token and chat_id:
            groups[group_id] = TelegramGroupConfig(token=token, chat_id=chat_id)
    return groups


def resolve_alert_groups(raw: str, group_map: dict[str, TelegramGroupConfig]) -> list[tuple[str, TelegramGroupConfig]]:
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    out: list[tuple[str, TelegramGroupConfig]] = []
    for group_id in ids:
        group = group_map.get(group_id)
        if group is None:
            logger.warning("Unknown alert group %r (not in DELTAX_TELEGRAM_GROUPS)", group_id)
            continue
        out.append((group_id, group))
    return out


def telegram_enabled(env: dict[str, str] | None = None) -> bool:
    env = env or dict(os.environ)
    raw = (env.get("DELTAX_TELEGRAM_GROUPS") or "").strip()
    return bool(raw)


class TelegramSender:
    """Reuse one HTTP client for all Telegram sends in a monitor process."""

    def __init__(self, *, timeout_s: float = 15.0):
        self._timeout_s = timeout_s
        self._client: httpx.Client | None = None

    def _client_or_create(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout_s)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def send_html(self, token: str, chat_id: str, text: str) -> bool:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = self._client_or_create().post(url, json=payload)
            response.raise_for_status()
            body = response.json()
            return bool(body.get("ok"))
        except Exception:
            logger.exception("Telegram send failed for chat_id=%s", chat_id)
            return False

    def broadcast(
        self,
        text: str,
        *,
        alert_groups: list[tuple[str, TelegramGroupConfig]],
    ) -> tuple[bool, str]:
        if not alert_groups:
            return False, ""

        sent_groups: list[str] = []
        all_ok = True
        for group_id, group in alert_groups:
            ok = self.send_html(group.token, group.chat_id, text)
            if ok:
                sent_groups.append(group_id)
            else:
                all_ok = False
        return all_ok, ",".join(sent_groups)
