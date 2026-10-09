from __future__ import annotations

from app.db import Database


def test_default_settings_exist() -> None:
    db = Database(":memory:")
    assert db.setting_bool("ignore_bots") is True
    assert db.setting_int("max_replies_per_chat_per_minute") == 3
    db.close()


def test_monitored_chats_round_trip() -> None:
    db = Database(":memory:")
    db.upsert_chat(-1001, "测试群一", True)
    db.upsert_chat(-1002, "测试群二", False)
    assert db.monitored_chat_ids() == {-1001}
    db.set_monitored_chats([(-1002, "测试群二")])
    assert db.monitored_chat_ids() == {-1002}
    db.close()


def test_rules_are_scoped_to_chats() -> None:
    db = Database(":memory:")
    global_rule = db.create_rule(
        name="全局",
        pattern="全局",
        match_type="contains",
        case_sensitive=False,
        reply="全局回复",
        cooldown_seconds=0,
        per_user_cooldown_seconds=0,
        enabled=True,
    )
    scoped_rule = db.create_rule(
        name="单群",
        pattern="单群",
        match_type="contains",
        case_sensitive=False,
        reply="单群回复",
        cooldown_seconds=0,
        per_user_cooldown_seconds=0,
        enabled=True,
    )
    db.set_rule_chats(scoped_rule, [-1001])
    first_chat_rules = {int(row["id"]) for row in db.rules_for_chat(-1001)}
    second_chat_rules = {int(row["id"]) for row in db.rules_for_chat(-1002)}
    assert first_chat_rules == {global_rule, scoped_rule}
    assert second_chat_rules == {global_rule}
    db.close()


def test_handled_messages_are_deduplicated() -> None:
    db = Database(":memory:")
    assert db.mark_handled(-1001, 10) is True
    assert db.mark_handled(-1001, 10) is False
    assert db.mark_handled(-1001, 11) is True
    db.close()
