from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .db import Database
from .matcher import Rule, find_matches


@dataclass
class Decision:
    action: str
    reason: str = ""
    rule: Rule | None = None
    keyword: str = ""
    reply_text: str = ""
    log: bool = False


def _local_day_start(now: float) -> float:
    local = datetime.fromtimestamp(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return midnight.timestamp()
    except (OSError, OverflowError, ValueError):
        # Windows cannot convert dates before 1970; fall back to local midnight.
        return now - (local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1_000_000)


def render_reply(template: str, *, keyword: str, user_name: str, chat_title: str) -> str:
    try:
        rendered = template.format(keyword=keyword, user=user_name, chat=chat_title)
    except (KeyError, IndexError, ValueError):
        rendered = template
    if len(rendered) > 4096:
        rendered = rendered[:4090] + "..."
    return rendered


class ReplyService:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db = db
        self.clock = clock

    def handle_group_message(
        self,
        *,
        chat_id: int,
        chat_title: str,
        message_id: int,
        user_id: int,
        user_name: str,
        text: str,
        is_bot: bool = False,
    ) -> Decision:
        if self.db.setting_bool("paused"):
            return Decision(action="ignore", reason="全局已暂停")
        if not self.db.is_monitored(chat_id):
            return Decision(action="ignore", reason="群未启用")
        if is_bot and self.db.setting_bool("ignore_bots", True):
            return Decision(action="ignore", reason="机器人消息")
        if not text or not text.strip():
            return Decision(action="ignore", reason="空消息")

        rules = [Rule.from_row(row) for row in self.db.rules_for_chat(chat_id)]
        matched = find_matches(text, rules)
        if not matched:
            return Decision(action="ignore", reason="未命中关键词")

        rule = matched[0]
        if not self.db.mark_handled(chat_id, message_id):
            return Decision(
                action="ignore",
                reason="重复消息",
                rule=rule,
                keyword=rule.pattern,
                log=True,
            )

        now = self.clock()
        limit_reason = self._limit_reason(now, chat_id, rule, user_id)
        if limit_reason:
            return Decision(
                action="ignore",
                reason=limit_reason,
                rule=rule,
                keyword=rule.pattern,
                log=True,
            )

        return Decision(
            action="reply",
            rule=rule,
            keyword=rule.pattern,
            reply_text=render_reply(
                rule.reply,
                keyword=rule.pattern,
                user_name=user_name,
                chat_title=chat_title,
            ),
            log=True,
        )

    def _limit_reason(self, now: float, chat_id: int, rule: Rule, user_id: int) -> str:
        min_gap = self.db.setting_int("min_seconds_between_replies_in_chat", 15)
        last_chat = self.db.last_sent(chat_id=chat_id)
        if min_gap > 0 and last_chat is not None and now - last_chat < min_gap:
            return f"群内冷却中（{min_gap} 秒）"

        if rule.cooldown_seconds > 0:
            last_rule = self.db.last_sent(chat_id=chat_id, rule_id=rule.id)
            if last_rule is not None and now - last_rule < rule.cooldown_seconds:
                return f"关键词冷却中（{rule.cooldown_seconds} 秒）"

        if user_id and rule.per_user_cooldown_seconds > 0:
            last_user = self.db.last_sent(rule_id=rule.id, user_id=user_id)
            if last_user is not None and now - last_user < rule.per_user_cooldown_seconds:
                return f"该用户冷却中（{rule.per_user_cooldown_seconds} 秒）"

        per_minute = self.db.setting_int("max_replies_per_chat_per_minute", 3)
        if per_minute > 0 and self.db.count_sent_since(now - 60, chat_id=chat_id) >= per_minute:
            return "本群每分钟上限"

        per_day = self.db.setting_int("max_replies_per_chat_per_day", 50)
        if per_day > 0 and self.db.count_sent_since(
            _local_day_start(now), chat_id=chat_id
        ) >= per_day:
            return "本群每日上限"

        global_per_minute = self.db.setting_int("max_replies_global_per_minute", 5)
        if global_per_minute > 0 and self.db.count_sent_since(now - 60) >= global_per_minute:
            return "全局每分钟上限"

        return ""
