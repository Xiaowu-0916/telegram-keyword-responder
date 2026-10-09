from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence


MATCH_TYPES = ("contains", "regex", "word")


def _has_cjk(value: str) -> bool:
    """Return True when the text contains CJK, kana or Hangul characters.

    Python's ``\\w`` treats these characters as word characters, so the usual
    word-boundary check would reject a keyword such as "国庆" inside
    "欢度国庆".  For these languages a substring match is the useful
    behaviour; plain English keeps the strict word-boundary rule.
    """
    for char in value:
        code = ord(char)
        if (
            0x3400 <= code <= 0x4DBF      # CJK Extension A
            or 0x4E00 <= code <= 0x9FFF   # CJK Unified Ideographs
            or 0xF900 <= code <= 0xFAFF   # CJK Compatibility Ideographs
            or 0x3040 <= code <= 0x309F   # Hiragana
            or 0x30A0 <= code <= 0x30FF   # Katakana
            or 0xAC00 <= code <= 0xD7AF   # Hangul syllables
        ):
            return True
    return False


@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    pattern: str
    match_type: str
    case_sensitive: bool
    reply: str
    cooldown_seconds: int
    per_user_cooldown_seconds: int

    @classmethod
    def from_row(cls, row: Any) -> "Rule":
        return cls(
            id=int(row["id"]),
            name=str(row["name"] or ""),
            pattern=str(row["pattern"] or ""),
            match_type=str(row["match_type"] or "contains"),
            case_sensitive=bool(row["case_sensitive"]),
            reply=str(row["reply"] or ""),
            cooldown_seconds=int(row["cooldown_seconds"] or 0),
            per_user_cooldown_seconds=int(row["per_user_cooldown_seconds"] or 0),
        )


@lru_cache(maxsize=512)
def _compiled(pattern: str, match_type: str, case_sensitive: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    if match_type == "regex":
        return re.compile(pattern, flags)
    escaped = re.escape(pattern)
    if match_type == "word":
        if _has_cjk(pattern):
            return re.compile(escaped, flags)
        return re.compile(rf"(?<!\w){escaped}(?!\w)", flags)
    return re.compile(escaped, flags)


def validate_pattern(pattern: str, match_type: str) -> str | None:
    if not pattern:
        return "关键词不能为空"
    if match_type not in MATCH_TYPES:
        return "匹配方式无效"
    try:
        _compiled(pattern, match_type, False)
    except re.error as exc:
        return f"正则表达式无效：{exc}"
    return None


def matches_rule(text: str, rule: Rule) -> bool:
    if not text or not rule.pattern:
        return False
    if rule.match_type not in MATCH_TYPES:
        return False
    try:
        return _compiled(rule.pattern, rule.match_type, rule.case_sensitive).search(text) is not None
    except re.error:
        return False


def find_matches(text: str, rules: Sequence[Rule]) -> list[Rule]:
    return [rule for rule in rules if matches_rule(text, rule)]
