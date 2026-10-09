from __future__ import annotations

from app.db import Database
from app.service import ReplyService


def make_db() -> Database:
    db = Database(":memory:")
    db.upsert_chat(-1001, "测试群", True)
    return db


def add_rule(db: Database, **overrides: object) -> int:
    values: dict[str, object] = {
        "name": "价格",
        "pattern": "价格",
        "match_type": "contains",
        "case_sensitive": False,
        "reply": "价格是 10 元",
        "cooldown_seconds": 0,
        "per_user_cooldown_seconds": 0,
        "enabled": True,
    }
    values.update(overrides)
    return db.create_rule(**values)  # type: ignore[arg-type]


def record_sent(
    db: Database,
    *,
    chat_id: int = -1001,
    user_id: int = 100,
    rule_id: int,
    ts: float,
    keyword: str = "价格",
) -> None:
    db.add_event(
        chat_id=chat_id,
        chat_title="测试群",
        user_id=user_id,
        user_name="用户",
        message_id=1,
        rule_id=rule_id,
        rule_name="价格",
        keyword=keyword,
        status="sent",
        reply_text="价格是 10 元",
        ts=ts,
    )


def test_reply_is_returned_for_matching_message() -> None:
    db = make_db()
    add_rule(db, cooldown_seconds=0, per_user_cooldown_seconds=0)
    service = ReplyService(db, clock=lambda: 1_700_000_000.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=10,
        user_id=100,
        user_name="小明",
        text="请问价格是多少",
    )
    assert decision.action == "reply"
    assert decision.reply_text == "价格是 10 元"
    db.close()


def test_unmonitored_chat_is_ignored() -> None:
    db = make_db()
    add_rule(db)
    service = ReplyService(db, clock=lambda: 1_700_000_000.0)
    decision = service.handle_group_message(
        chat_id=-2002,
        chat_title="其他群",
        message_id=11,
        user_id=100,
        user_name="小明",
        text="价格",
    )
    assert decision.action == "ignore"
    assert "未启用" in decision.reason
    db.close()


def test_duplicate_message_is_ignored() -> None:
    db = make_db()
    add_rule(db)
    service = ReplyService(db, clock=lambda: 1_700_000_000.0)
    first = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=12,
        user_id=100,
        user_name="小明",
        text="价格",
    )
    second = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=12,
        user_id=100,
        user_name="小明",
        text="价格",
    )
    assert first.action == "reply"
    assert second.action == "ignore"
    assert second.reason == "重复消息"
    db.close()


def test_per_user_cooldown_blocks_second_reply() -> None:
    db = make_db()
    rule_id = add_rule(db, per_user_cooldown_seconds=3600)
    record_sent(db, rule_id=rule_id, ts=1_700_000_000.0)
    service = ReplyService(db, clock=lambda: 1_700_000_100.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=13,
        user_id=100,
        user_name="小明",
        text="价格",
    )
    assert decision.action == "ignore"
    assert "该用户冷却中" in decision.reason
    db.close()


def test_chat_min_gap_blocks_second_reply() -> None:
    db = make_db()
    rule_id = add_rule(db)
    db.update_settings({"min_seconds_between_replies_in_chat": "60"})
    record_sent(db, rule_id=rule_id, ts=1_700_000_000.0)
    service = ReplyService(db, clock=lambda: 1_700_000_010.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=14,
        user_id=100,
        user_name="小明",
        text="价格",
    )
    assert decision.action == "ignore"
    assert "群内冷却中" in decision.reason
    db.close()


def test_keyword_cooldown_blocks_second_reply() -> None:
    db = make_db()
    rule_id = add_rule(db, cooldown_seconds=600)
    db.update_settings({"min_seconds_between_replies_in_chat": "0"})
    record_sent(db, rule_id=rule_id, ts=1_700_000_000.0)
    service = ReplyService(db, clock=lambda: 1_700_000_100.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=15,
        user_id=200,
        user_name="小红",
        text="价格",
    )
    assert decision.action == "ignore"
    assert "关键词冷却中" in decision.reason
    db.close()


def test_per_chat_per_minute_limit_blocks_reply() -> None:
    db = make_db()
    rule_id = add_rule(db)
    db.update_settings(
        {
            "min_seconds_between_replies_in_chat": "0",
            "max_replies_per_chat_per_minute": "1",
        }
    )
    record_sent(db, rule_id=rule_id, ts=1_700_000_000.0)
    service = ReplyService(db, clock=lambda: 1_700_000_010.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=16,
        user_id=200,
        user_name="小红",
        text="价格",
    )
    assert decision.action == "ignore"
    assert "每分钟上限" in decision.reason
    db.close()


def test_bot_messages_can_be_ignored() -> None:
    db = make_db()
    add_rule(db)
    service = ReplyService(db, clock=lambda: 1_700_000_000.0)
    decision = service.handle_group_message(
        chat_id=-1001,
        chat_title="测试群",
        message_id=17,
        user_id=999,
        user_name="bot",
        text="价格",
        is_bot=True,
    )
    assert decision.action == "ignore"
    assert decision.reason == "机器人消息"
    db.close()
