from __future__ import annotations

import hmac
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .db import Database
from .matcher import MATCH_TYPES, validate_pattern
from .security import hash_password, new_token, verify_password
from .settings import Settings, load_settings
from .telegram_manager import (
    PasswordRequired,
    TelegramManager,
    TelegramNotConfigured,
)


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["dt"] = lambda value: datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M:%S")

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_WINDOW_SECONDS = 600
LOGIN_MAX_ATTEMPTS = 10


def _client_ip(request: Any) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _login_locked(ip: str) -> bool:
    now = time.time()
    attempts = [item for item in LOGIN_ATTEMPTS.get(ip, []) if now - item < LOGIN_WINDOW_SECONDS]
    LOGIN_ATTEMPTS[ip] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(ip: str) -> None:
    LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def _csrf_token(request: Any) -> str:
    token = request.session.get("csrf")
    if not token:
        token = new_token()
        request.session["csrf"] = token
    return str(token)


def _check_csrf(request: Any, provided: Any) -> bool:
    expected = request.session.get("csrf")
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(expected), str(provided))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _checkbox(value: Any) -> bool:
    return str(value).strip().lower() in {"on", "1", "true", "yes"}


def _day_start(now: float) -> float:
    local = datetime.fromtimestamp(now)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    log = logging.getLogger("tgkr.web")

    if not db.setting("admin_password_hash"):
        initial_password = settings.initial_password or new_token()[:12]
        db.update_settings(
            {
                "admin_user": settings.admin_user,
                "admin_password_hash": hash_password(initial_password),
            }
        )
        password_file = settings.data_dir / "initial_admin_password.txt"
        password_file.write_text(
            f"username: {settings.admin_user}\npassword: {initial_password}\n",
            encoding="utf-8",
        )
        try:
            password_file.chmod(0o600)
        except OSError:
            pass
        log.warning("initial admin password written to %s", password_file)

    manager = TelegramManager(db, str(settings.session_path), logging.getLogger("tgkr.telegram"))

    @asynccontextmanager
    async def lifespan(_: Starlette):
        db.cleanup_handled(time.time() - 14 * 24 * 3600)
        await manager.bootstrap()
        try:
            yield
        finally:
            await manager.disconnect()
            db.close()

    def render(request: Any, name: str, **context: Any) -> HTMLResponse:
        base: dict[str, Any] = {
            "request": request,
            "username": request.session.get("user"),
            "csrf_token": _csrf_token(request),
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        }
        base.update(context)
        return HTMLResponse(templates.get_template(name).render(**base))

    def require_login(request: Any) -> RedirectResponse | None:
        if not request.session.get("user"):
            return RedirectResponse("/login", status_code=303)
        return None

    async def healthz(request: Any) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "tg-keyword-responder"})

    async def login_get(request: Any) -> Any:
        if request.session.get("user"):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html")

    async def login_post(request: Any) -> Any:
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败，请刷新页面重试", status_code=400)
        ip = _client_ip(request)
        if _login_locked(ip):
            return render(request, "login.html", error="登录失败次数过多，请 10 分钟后再试")
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        stored_user = db.setting("admin_user", "admin") or "admin"
        stored_hash = db.setting("admin_password_hash", "") or ""
        if username == stored_user and verify_password(password, stored_hash):
            LOGIN_ATTEMPTS.pop(ip, None)
            request.session.clear()
            request.session["user"] = username
            request.session["csrf"] = new_token()
            return RedirectResponse("/", status_code=303)
        _record_login_failure(ip)
        return render(request, "login.html", error="用户名或密码错误")

    async def logout(request: Any) -> Any:
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    async def dashboard(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        now = time.time()
        day = _day_start(now)
        stats = {
            "monitored": len(db.monitored_chats()),
            "rules": len(db.rules(enabled_only=True)),
            "sent_today": db.count_sent_since(day),
            "skipped_today": db.count_events_since("skipped", day),
            "errors_today": db.count_events_since("error", day),
        }
        return render(
            request,
            "dashboard.html",
            stats=stats,
            events=db.recent_events(limit=12),
            status=manager.status.as_dict(),
        )

    async def telegram_page(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        return render(request, "telegram.html", status=manager.status.as_dict())

    async def telegram_save_api(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        try:
            await manager.save_api_credentials(
                str(form.get("api_id", "")),
                str(form.get("api_hash", "")),
            )
        except Exception as exc:  # noqa: BLE001
            return render(
                request,
                "telegram.html",
                status=manager.status.as_dict(),
                error=f"{type(exc).__name__}: {exc}",
            )
        return RedirectResponse("/telegram?msg=API 凭据已保存", status_code=303)

    async def telegram_send_code(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        try:
            await manager.send_code(str(form.get("phone", "")))
        except Exception as exc:  # noqa: BLE001
            return render(
                request,
                "telegram.html",
                status=manager.status.as_dict(),
                error=f"{type(exc).__name__}: {exc}",
            )
        return RedirectResponse("/telegram?msg=验证码已发送", status_code=303)

    async def telegram_sign_in(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        try:
            await manager.sign_in_code(str(form.get("code", "")))
        except PasswordRequired:
            return render(
                request,
                "telegram.html",
                status=manager.status.as_dict(),
                info="该账号启用了两步验证，请输入密码",
            )
        except Exception as exc:  # noqa: BLE001
            return render(
                request,
                "telegram.html",
                status=manager.status.as_dict(),
                error=f"{type(exc).__name__}: {exc}",
            )
        return RedirectResponse("/telegram?msg=登录成功", status_code=303)

    async def telegram_password(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        try:
            await manager.sign_in_password(str(form.get("password", "")))
        except Exception as exc:  # noqa: BLE001
            return render(
                request,
                "telegram.html",
                status=manager.status.as_dict(),
                error=f"{type(exc).__name__}: {exc}",
            )
        return RedirectResponse("/telegram?msg=登录成功", status_code=303)

    async def telegram_logout(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        await manager.logout()
        return RedirectResponse("/telegram?msg=已退出 Telegram 账号", status_code=303)

    async def groups_page(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        if not manager.status.authorized:
            return RedirectResponse("/telegram?err=请先登录 Telegram 账号", status_code=303)
        try:
            groups = await manager.list_groups()
        except Exception as exc:  # noqa: BLE001
            return render(request, "groups.html", groups=[], error=f"读取群列表失败：{exc}")
        return render(request, "groups.html", groups=groups)

    async def groups_save(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        if not manager.status.authorized:
            return RedirectResponse("/telegram?err=请先登录 Telegram 账号", status_code=303)
        selected: set[int] = set()
        for raw in form.getlist("selected"):
            value = _as_int(raw, default=0)
            if value:
                selected.add(value)
        groups = await manager.list_groups()
        for group in groups:
            db.upsert_chat(group["chat_id"], group["title"], enabled=group["chat_id"] in selected)
        return RedirectResponse("/groups?msg=群监听设置已保存", status_code=303)

    def parse_rule_form(form: Any) -> tuple[dict[str, Any] | None, str | None]:
        name = str(form.get("name", "")).strip()
        pattern = str(form.get("pattern", "")).strip()
        match_type = str(form.get("match_type", "contains")).strip()
        if match_type not in MATCH_TYPES:
            match_type = "contains"
        reply = str(form.get("reply", "")).strip()
        error = validate_pattern(pattern, match_type)
        if error:
            return None, error
        if not reply:
            return None, "回复内容不能为空"
        case_sensitive = _checkbox(form.get("case_sensitive"))
        return (
            {
                "name": name or pattern,
                "pattern": pattern,
                "match_type": match_type,
                "case_sensitive": case_sensitive,
                "reply": reply,
                "cooldown_seconds": max(0, _as_int(form.get("cooldown_seconds"), 300)),
                "per_user_cooldown_seconds": max(
                    0, _as_int(form.get("per_user_cooldown_seconds"), 3600)
                ),
                "enabled": _checkbox(form.get("enabled")),
            },
            None,
        )

    def selected_chat_ids(form: Any) -> list[int]:
        result: list[int] = []
        for raw in form.getlist("chat_ids"):
            value = _as_int(raw, default=0)
            if value:
                result.append(value)
        return result

    def rules_context(request: Any, **extra: Any) -> dict[str, Any]:
        rules = db.rules()
        assignments = {int(rule["id"]): db.rule_chat_ids(int(rule["id"])) for rule in rules}
        context = {
            "rules": rules,
            "assignments": assignments,
            "chats": db.monitored_chats(),
        }
        context.update(extra)
        return context

    async def rules_page(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        return render(request, "rules.html", **rules_context(request))

    async def rule_new(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        data, error = parse_rule_form(form)
        if data is None:
            return render(request, "rules.html", **rules_context(request, error=error))
        rule_id = db.create_rule(**data)
        db.set_rule_chats(rule_id, selected_chat_ids(form))
        return RedirectResponse("/rules?msg=关键词已新增", status_code=303)

    async def rule_detail(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        rule_id = int(request.path_params["rule_id"])
        rule = db.rule(rule_id)
        if rule is None:
            return RedirectResponse("/rules?err=规则不存在", status_code=303)
        return render(
            request,
            "rule_edit.html",
            rule=rule,
            rule_chats=db.rule_chat_ids(rule_id),
            chats=db.monitored_chats(),
        )

    async def rule_update(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        rule_id = int(request.path_params["rule_id"])
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        rule = db.rule(rule_id)
        if rule is None:
            return RedirectResponse("/rules?err=规则不存在", status_code=303)
        data, error = parse_rule_form(form)
        if data is None:
            return render(
                request,
                "rule_edit.html",
                rule=rule,
                rule_chats=db.rule_chat_ids(rule_id),
                chats=db.monitored_chats(),
                error=error,
            )
        db.update_rule(rule_id, **data)
        db.set_rule_chats(rule_id, selected_chat_ids(form))
        return RedirectResponse("/rules?msg=关键词已保存", status_code=303)

    async def rule_delete(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        rule_id = int(request.path_params["rule_id"])
        db.delete_rule(rule_id)
        return RedirectResponse("/rules?msg=关键词已删除", status_code=303)

    async def logs_page(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        limit = max(10, min(500, _as_int(request.query_params.get("limit"), 100)))
        raw_chat = request.query_params.get("chat_id", "")
        chat_id = _as_int(raw_chat, default=0) if raw_chat else None
        status_filter = request.query_params.get("status", "")
        events = db.recent_events(limit=500, chat_id=chat_id)
        if status_filter:
            events = [event for event in events if event["status"] == status_filter]
        return render(
            request,
            "logs.html",
            events=events[:limit],
            chats=db.monitored_chats(),
            selected_chat=chat_id,
            selected_status=status_filter,
            limit=limit,
        )

    async def settings_page(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        return render(request, "settings.html", settings=db.settings())

    async def settings_save(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        proxy_kind = str(form.get("proxy_kind", "socks5")).strip().lower()
        if proxy_kind not in {"socks5", "socks4", "http"}:
            proxy_kind = "socks5"
        updates = {
            "paused": "true" if _checkbox(form.get("paused")) else "false",
            "ignore_bots": "true" if _checkbox(form.get("ignore_bots")) else "false",
            "min_seconds_between_replies_in_chat": str(
                max(0, _as_int(form.get("min_seconds_between_replies_in_chat"), 15))
            ),
            "max_replies_per_chat_per_minute": str(
                max(0, _as_int(form.get("max_replies_per_chat_per_minute"), 3))
            ),
            "max_replies_per_chat_per_day": str(
                max(0, _as_int(form.get("max_replies_per_chat_per_day"), 50))
            ),
            "max_replies_global_per_minute": str(
                max(0, _as_int(form.get("max_replies_global_per_minute"), 5))
            ),
            "proxy_enabled": "true" if _checkbox(form.get("proxy_enabled")) else "false",
            "proxy_kind": proxy_kind,
            "proxy_host": str(form.get("proxy_host", "")).strip(),
            "proxy_port": str(max(0, _as_int(form.get("proxy_port"), 1080))),
            "proxy_username": str(form.get("proxy_username", "")).strip(),
            "proxy_password": str(form.get("proxy_password", "")),
        }
        old = db.settings()
        db.update_settings(updates)
        proxy_changed = any(
            old.get(key) != value for key, value in updates.items() if key.startswith("proxy_")
        )
        if proxy_changed and manager.status.configured:
            await manager.restart()
        return RedirectResponse("/settings?msg=设置已保存", status_code=303)

    async def password_change(request: Any) -> Any:
        redirect = require_login(request)
        if redirect:
            return redirect
        form = await request.form()
        if not _check_csrf(request, form.get("csrf_token")):
            return HTMLResponse("CSRF 校验失败", status_code=400)
        current = str(form.get("current_password", ""))
        new_password = str(form.get("new_password", ""))
        confirm = str(form.get("confirm_password", ""))
        stored_hash = db.setting("admin_password_hash", "") or ""
        if not verify_password(current, stored_hash):
            return render(
                request,
                "settings.html",
                settings=db.settings(),
                error="当前密码不正确",
            )
        if len(new_password) < 8:
            return render(
                request,
                "settings.html",
                settings=db.settings(),
                error="新密码至少 8 位",
            )
        if new_password != confirm:
            return render(
                request,
                "settings.html",
                settings=db.settings(),
                error="两次输入的新密码不一致",
            )
        db.update_settings({"admin_password_hash": hash_password(new_password)})
        return RedirectResponse("/settings?msg=管理密码已更新", status_code=303)

    async def api_status(request: Any) -> JSONResponse:
        redirect = require_login(request)
        if redirect:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        now = time.time()
        day = _day_start(now)
        return JSONResponse(
            {
                "telegram": manager.status.as_dict(),
                "monitored_chats": len(db.monitored_chats()),
                "active_rules": len(db.rules(enabled_only=True)),
                "sent_today": db.count_sent_since(day),
                "paused": db.setting_bool("paused"),
            }
        )

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/login", login_get, methods=["GET"]),
        Route("/login", login_post, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/", dashboard, methods=["GET"]),
        Route("/telegram", telegram_page, methods=["GET"]),
        Route("/telegram/api", telegram_save_api, methods=["POST"]),
        Route("/telegram/send-code", telegram_send_code, methods=["POST"]),
        Route("/telegram/sign-in", telegram_sign_in, methods=["POST"]),
        Route("/telegram/password", telegram_password, methods=["POST"]),
        Route("/telegram/logout", telegram_logout, methods=["POST"]),
        Route("/groups", groups_page, methods=["GET"]),
        Route("/groups/save", groups_save, methods=["POST"]),
        Route("/rules", rules_page, methods=["GET"]),
        Route("/rules/new", rule_new, methods=["POST"]),
        Route("/rules/{rule_id:int}", rule_detail, methods=["GET"]),
        Route("/rules/{rule_id:int}/update", rule_update, methods=["POST"]),
        Route("/rules/{rule_id:int}/delete", rule_delete, methods=["POST"]),
        Route("/logs", logs_page, methods=["GET"]),
        Route("/settings", settings_page, methods=["GET"]),
        Route("/settings/save", settings_save, methods=["POST"]),
        Route("/settings/password", password_change, methods=["POST"]),
        Route("/api/status", api_status, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=str(BASE_DIR / "static")), name="static"),
    ]

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key=settings.session_secret,
                session_cookie="tgkr_session",
                max_age=settings.session_max_age,
                same_site="lax",
                https_only=settings.https_only,
            )
        ],
    )
    app.state.db = db
    app.state.manager = manager
    app.state.settings = settings
    return app
