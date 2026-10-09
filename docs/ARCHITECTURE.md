# Architecture

## Overview

The project is a single Python process that combines:

- a **Telethon** client for the Telegram user account;
- a **Starlette** web application for configuration and monitoring;
- a **SQLite** database for settings, rules, chats and logs.

The web application and the Telegram listener share the same asyncio event loop. The process is designed to run as a long-lived systemd service.

## Components

| Component | File | Responsibility |
| --- | --- | --- |
| Settings | `app/settings.py` | Reads `.env` values and builds paths |
| Database | `app/db.py` | SQLite schema and queries |
| Matcher | `app/matcher.py` | Contains / regex / word matching and CJK fallback |
| Reply service | `app/service.py` | Rule selection, cooldowns, rate limits, reply rendering |
| Telegram manager | `app/telegram_manager.py` | Telethon client, login wizard, group list, listener |
| Web app | `app/web.py` | Starlette routes, sessions, CSRF, forms, templates |
| Entry point | `main.py` | Loads settings, creates the app and runs Uvicorn |

## Message flow

```text
Telegram group message
        |
        v
Is the group in the monitored allowlist?
        | no -> ignore
        v yes
Is the sender a bot and bots ignored?
        | yes -> ignore
        v no
Find matching enabled rules for this group
        | none -> ignore
        v match
Has this message already been handled?
        | yes -> ignore
        v no
Check per-chat, per-rule, per-user and global limits
        | blocked -> log "skipped"
        v allowed
Reply to the triggering message with the configured text
        |
        v
Log the result in SQLite
```

## Data model

| Table | Purpose |
| --- | --- |
| `settings` | Key/value settings, including Telegram credentials, proxy settings and limits |
| `chats` | Monitored group allowlist and titles |
| `rules` | Keyword rules, match type, reply text and cooldowns |
| `rule_chats` | Optional per-rule group scoping |
| `handled` | Deduplication of already-processed messages |
| `events` | Sent, skipped and error log entries |

SQLite is opened with WAL mode. All database access goes through a lock, so the web routes and the Telegram listener can share one connection safely.

## Matching semantics

- `contains`: substring search.
- `regex`: Python regular expression search.
- `word`: Latin word-boundary search.

If the pattern contains CJK characters, Japanese kana or Hangul, `word` mode automatically uses substring matching. Python treats those characters as `\w`, so a strict `(?<!\w)pattern(?!\w)` check would fail inside normal Chinese, Japanese or Korean text.

The first matching rule (in rule ID order) is used for a message. Additional matches are not replied to, which keeps one reply per message.

## Rate limiting

The following checks are applied before sending:

- minimum seconds between replies in the same group;
- per-keyword cooldown in the same group;
- per-user and per-rule cooldown;
- maximum replies per group per minute;
- maximum replies per group per day;
- maximum replies globally per minute.

Skipped replies are logged with a reason, so the web panel can explain why a message did not receive a reply.

## Login and session

The web panel contains a Telegram login wizard:

1. Save `api_id` and `api_hash`.
2. Send a login code to the phone number.
3. Submit the code.
4. Submit the two-step password if required.

The Telethon session is stored in `TGKR_SESSION_PATH`. The session file must be protected and backed up. Restarting the service does not require a new login.

## Safety boundaries

The code has no function that sends a direct message to a group member. The only outbound message path is `event.reply()` for a monitored group. The group allowlist, bot-message filter and rate limits are enforced before any reply.

This design intentionally keeps the project on the "reply inside an allowed group" side of Telegram automation. It is still a userbot and still carries account risk; see [SECURITY.md](../SECURITY.md).
