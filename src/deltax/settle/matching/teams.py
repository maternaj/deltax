"""Fuzzy team-name normalization and similarity (from morex/morex/inspire/teams.py)."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

_STOPWORDS = frozenset(
    {
        "fc",
        "sc",
        "cf",
        "ac",
        "ca",
        "fk",
        "club",
        "the",
        "clube",
    }
)


def fold_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_team(name: str, *, aliases: Mapping[str, str] | None = None) -> str:
    aliases = aliases or {}
    s = fold_accents(str(name)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [token for token in s.split() if token and token not in _STOPWORDS]
    key = " ".join(tokens)
    return aliases.get(key, key)


def _is_strict_token_subset(left: str, right: str) -> bool:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return False
    return left_tokens < right_tokens or right_tokens < left_tokens


def name_similarity(left: str, right: str, *, aliases: Mapping[str, str] | None = None) -> float:
    lk = normalize_team(left, aliases=aliases)
    rk = normalize_team(right, aliases=aliases)
    if not lk or not rk:
        return 0.0

    try:
        from rapidfuzz import fuzz
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, lk, rk).ratio() * 100.0

    wratio = float(fuzz.WRatio(lk, rk))
    if _is_strict_token_subset(lk, rk):
        return wratio
    token = float(fuzz.token_set_ratio(lk, rk))
    return max(wratio, token)
