from __future__ import annotations

from app.matcher import Rule, find_matches, validate_pattern


def make_rule(
    pattern: str,
    match_type: str = "contains",
    case_sensitive: bool = False,
) -> Rule:
    return Rule(
        id=1,
        name="test",
        pattern=pattern,
        match_type=match_type,
        case_sensitive=case_sensitive,
        reply="reply",
        cooldown_seconds=0,
        per_user_cooldown_seconds=0,
    )


def test_contains_matches_substring() -> None:
    assert find_matches("这里怎么收费？", [make_rule("收费")])


def test_regex_matches_multiple_forms() -> None:
    rule = make_rule(r"价格|多少钱|怎么收费", "regex")
    assert find_matches("这个多少钱", [rule])
    assert not find_matches("今天天气不错", [rule])


def test_case_insensitive_by_default() -> None:
    rule = make_rule("Telegram")
    assert find_matches("telegram bot", [rule])


def test_case_sensitive_can_be_enabled() -> None:
    rule = make_rule("Telegram", case_sensitive=True)
    assert not find_matches("telegram bot", [rule])


def test_word_match_requires_word_boundaries() -> None:
    rule = make_rule("price", "word")
    assert find_matches("what is the price?", [rule])
    assert not find_matches("priceless", [rule])


def test_word_match_chinese_falls_back_to_substring() -> None:
    rule = make_rule("国庆", "word")
    assert find_matches("国庆", [rule])
    assert find_matches("欢度国庆", [rule])
    assert find_matches("国庆节快乐", [rule])


def test_invalid_regex_is_reported() -> None:
    assert validate_pattern("([", "regex")
    assert validate_pattern("ok", "regex") is None


def test_find_matches_returns_rules_in_order() -> None:
    first = make_rule("价格")
    second = make_rule("价格|优惠", "regex")
    matched = find_matches("价格和优惠", [first, second])
    assert [rule.id for rule in matched] == [1, 1]
