from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, events, errors

from .db import Database
from .service import Decision, ReplyService


class TelegramNotConfigured(RuntimeError):
    pass


class PasswordRequired(RuntimeError):
    pass


@dataclass
class ManagerStatus:
    configured: bool = False
    connected: bool = False
    authorized: bool = False
    me_id: int | None = None
    me_name: str = ""
    me_username: str = ""
    phone: str = ""
    pending_code: bool = False
    pending_password: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "connected": self.connected,
            "authorized": self.authorized,
            "me_id": self.me_id,
            "me_name": self.me_name,
            "me_username": self.me_username,
            "phone": self.phone,
            "pending_code": self.pending_code,
            "pending_password": self.pending_password,
            "error": self.error,
        }


def _display_name(entity: Any) -> str:
    if entity is None:
        return ""
    if getattr(entity, "title", None):
        return str(entity.title)
    parts = [getattr(entity, "first_name", "") or "", getattr(entity, "last_name", "") or ""]
    name = " ".join(part for part in parts if part).strip()
    return name or (getattr(entity, "username", "") or "")


class TelegramManager:
    def __init__(
        self,
        db: Database,
        session_path: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self.db = db
        self.session_path = str(session_path)
        self.log = logger or logging.getLogger("tgkr.telegram")
        self.service = ReplyService(db)
        self.status = ManagerStatus()
        self._client: TelegramClient | None = None
        self._listener_task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._phone = ""
        self._phone_code_hash: str | None = None

    # ------------------------------------------------------------------
    # client lifecycle
    # ------------------------------------------------------------------
    def _proxy(self) -> dict[str, Any] | None:
        if not self.db.setting_bool("proxy_enabled"):
            return None
        host = (self.db.setting("proxy_host", "") or "").strip()
        port = self.db.setting_int("proxy_port", 0)
        if not host or not port:
            return None
        return {
            "proxy_type": (self.db.setting("proxy_kind", "socks5") or "socks5").lower(),
            "addr": host,
            "port": port,
            "rdns": True,
            "username": (self.db.setting("proxy_username", "") or "") or None,
            "password": (self.db.setting("proxy_password", "") or "") or None,
        }

    def _build_client(self) -> TelegramClient | None:
        api_id = self.db.setting_int("telegram_api_id", 0)
        api_hash = self.db.setting("telegram_api_hash", "") or ""
        if not api_id or not api_hash:
            self._client = None
            return None
        client = TelegramClient(
            self.session_path,
            api_id,
            api_hash,
            proxy=self._proxy(),
            connection_retries=None,
            retry_delay=5,
            auto_reconnect=True,
            request_retries=5,
            flood_sleep_threshold=120,
        )
        client.add_event_handler(self._on_event, events.NewMessage(incoming=True))
        self._client = client
        return client

    async def bootstrap(self) -> None:
        async with self._lock:
            await self._bootstrap_locked()

    async def _bootstrap_locked(self) -> None:
        api_id = self.db.setting_int("telegram_api_id", 0)
        api_hash = self.db.setting("telegram_api_hash", "") or ""
        self.status.configured = bool(api_id and api_hash)
        self.status.phone = self.db.setting("telegram_phone", "") or ""
        if not self.status.configured:
            return
        if self._client is None:
            self._build_client()
        if self._client is None:
            return
        try:
            await self._client.connect()
            self.status.connected = True
            self.status.error = ""
            if await self._client.is_user_authorized():
                await self._after_login()
            else:
                self.status.authorized = False
        except Exception as exc:  # noqa: BLE001 - surface errors in the web UI
            self._set_error(exc)

    def _set_error(self, exc: BaseException) -> None:
        self.status.error = f"{type(exc).__name__}: {exc}"
        self.log.warning("telegram error: %s", self.status.error)

    async def _after_login(self) -> None:
        if self._client is None:
            return
        me = await self._client.get_me()
        self.status.authorized = True
        self.status.pending_code = False
        self.status.pending_password = False
        self.status.me_id = int(me.id)
        self.status.me_name = _display_name(me)
        self.status.me_username = me.username or ""
        self.status.phone = me.phone or self.status.phone
        self.status.error = ""
        if self.status.phone:
            self.db.update_settings({"telegram_phone": self.status.phone})
        self._start_listener()

    def _start_listener(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return
        if self._client is None:
            return
        self._listener_task = asyncio.create_task(
            self._client.run_until_disconnected(),
            name="tgkr-telegram-listener",
        )

    async def disconnect(self) -> None:
        async with self._lock:
            await self._disconnect_locked()

    async def _disconnect_locked(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as exc:  # noqa: BLE001
                self.log.debug("disconnect failed: %s", exc)
        self.status.connected = False
        self.status.authorized = False

    async def restart(self) -> None:
        async with self._lock:
            await self._disconnect_locked()
            self._client = None
            await self._bootstrap_locked()

    # ------------------------------------------------------------------
    # login wizard
    # ------------------------------------------------------------------
    async def save_api_credentials(self, api_id: str, api_hash: str) -> None:
        try:
            parsed_id = int(str(api_id).strip())
        except ValueError as exc:
            raise TelegramNotConfigured("api_id 必须是数字") from exc
        api_hash = str(api_hash).strip()
        if not parsed_id or not api_hash:
            raise TelegramNotConfigured("api_id 和 api_hash 都不能为空")
        async with self._lock:
            self.db.update_settings(
                {"telegram_api_id": str(parsed_id), "telegram_api_hash": api_hash}
            )
            await self._disconnect_locked()
            self._client = None
            await self._bootstrap_locked()

    async def send_code(self, phone: str) -> None:
        phone = str(phone).strip().replace(" ", "")
        if not phone:
            raise TelegramNotConfigured("手机号不能为空")
        if self._client is None:
            raise TelegramNotConfigured("请先保存 api_id 和 api_hash")
        async with self._lock:
            await self._client.connect()
            sent = await self._client.send_code_request(phone)
            self._phone = phone
            self._phone_code_hash = sent.phone_code_hash
            self.status.phone = phone
            self.status.pending_code = True
            self.status.pending_password = False
            self.status.error = ""
            self.db.update_settings({"telegram_phone": phone})

    async def sign_in_code(self, code: str) -> None:
        code = str(code).strip()
        if not code:
            raise TelegramNotConfigured("验证码不能为空")
        if self._client is None or not self._phone_code_hash:
            raise TelegramNotConfigured("登录状态已过期，请重新发送验证码")
        async with self._lock:
            try:
                await self._client.sign_in(
                    phone=self._phone,
                    code=code,
                    phone_code_hash=self._phone_code_hash,
                )
            except errors.SessionPasswordNeededError as exc:
                self.status.pending_code = False
                self.status.pending_password = True
                raise PasswordRequired("该账号启用了两步验证") from exc
            await self._after_login()

    async def sign_in_password(self, password: str) -> None:
        if self._client is None:
            raise TelegramNotConfigured("请先完成验证码步骤")
        if not password:
            raise TelegramNotConfigured("两步验证密码不能为空")
        async with self._lock:
            await self._client.sign_in(password=str(password))
            await self._after_login()

    async def logout(self) -> None:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.log_out()
                except Exception as exc:  # noqa: BLE001 - still clear local state
                    self.log.warning("log_out failed: %s", exc)
            await self._disconnect_locked()
            self._client = None
            self.status.authorized = False
            self.status.connected = False
            self.status.me_id = None
            self.status.me_name = ""
            self.status.me_username = ""
            self.status.pending_code = False
            self.status.pending_password = False
            self.status.error = ""

    # ------------------------------------------------------------------
    # data for the web UI
    # ------------------------------------------------------------------
    async def list_groups(self, limit: int = 500) -> list[dict[str, Any]]:
        if self._client is None or not self.status.authorized:
            return []
        dialogs = await self._client.get_dialogs(limit=limit)
        groups: list[dict[str, Any]] = []
        for dialog in dialogs:
            if not dialog.is_group:
                continue
            entity = dialog.entity
            groups.append(
                {
                    "chat_id": int(dialog.id),
                    "title": dialog.name or str(dialog.id),
                    "username": getattr(entity, "username", "") or "",
                    "kind": "超级群" if getattr(entity, "megagroup", False) else "群组",
                    "monitored": self.db.is_monitored(int(dialog.id)),
                }
            )
        groups.sort(key=lambda item: item["title"].lower())
        return groups

    # ------------------------------------------------------------------
    # message handling
    # ------------------------------------------------------------------
    async def _on_event(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle_event(event)
        except Exception as exc:  # noqa: BLE001 - never kill the listener
            self.log.exception("message handler failed: %s", exc)

    async def _handle_event(self, event: events.NewMessage.Event) -> None:
        if not event.is_group:
            return
        chat_id = int(event.chat_id)
        if not self.db.is_monitored(chat_id):
            return
        message = event.message
        if message is None or message.out:
            return
        text = event.raw_text or ""
        sender = await event.get_sender()
        is_bot = bool(getattr(sender, "bot", False))
        user_id = int(getattr(sender, "id", 0) or 0)
        user_name = _display_name(sender)
        chat_title = _display_name(event.chat) or str(chat_id)

        decision = self.service.handle_group_message(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=int(event.id),
            user_id=user_id,
            user_name=user_name,
            text=text,
            is_bot=is_bot,
        )
        if decision.action != "reply":
            if decision.log:
                self._log_decision(
                    chat_id,
                    chat_title,
                    user_id,
                    user_name,
                    event.id,
                    decision,
                    status="skipped",
                )
            return
        try:
            await event.reply(decision.reply_text, parse_mode=None, link_preview=False)
            self._log_decision(
                chat_id,
                chat_title,
                user_id,
                user_name,
                event.id,
                decision,
                status="sent",
            )
        except errors.FloodWaitError as exc:
            self._log_decision(
                chat_id,
                chat_title,
                user_id,
                user_name,
                event.id,
                decision,
                status="skipped",
                reason=f"Telegram 限速，等待 {exc.seconds} 秒",
            )
            await asyncio.sleep(exc.seconds)
        except Exception as exc:  # noqa: BLE001
            self._log_decision(
                chat_id,
                chat_title,
                user_id,
                user_name,
                event.id,
                decision,
                status="error",
                reason=str(exc),
            )

    def _log_decision(
        self,
        chat_id: int,
        chat_title: str,
        user_id: int,
        user_name: str,
        message_id: int,
        decision: Decision,
        *,
        status: str,
        reason: str = "",
    ) -> None:
        rule = decision.rule
        self.db.add_event(
            chat_id=chat_id,
            chat_title=chat_title,
            user_id=user_id,
            user_name=user_name,
            message_id=int(message_id),
            rule_id=rule.id if rule else None,
            rule_name=rule.name if rule else "",
            keyword=decision.keyword,
            status=status,
            reason=reason or decision.reason,
            reply_text=decision.reply_text if status == "sent" else "",
        )
