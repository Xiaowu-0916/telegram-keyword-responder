# Configuration

## `.env`

| Variable | Default | Description |
| --- | --- | --- |
| `TGKR_BASE_DIR` | project root | Application directory |
| `TGKR_DATA_DIR` | `data` | Data directory |
| `TGKR_DB_PATH` | `data/state.db` | SQLite database path |
| `TGKR_SESSION_PATH` | `data/account` | Telethon session path (without the `.session` suffix) |
| `TGKR_ADMIN_USER` | `admin` | Web panel username |
| `TGKR_INITIAL_PASSWORD` | random | Initial web panel password; used only when the database has no password hash |
| `TGKR_SESSION_SECRET` | random per run | Session cookie signing secret; set a fixed value in production |
| `TGKR_HTTPS_ONLY` | `0` | `1` when the panel is served over HTTPS |
| `TGKR_HOST` | `127.0.0.1` | Listen address |
| `TGKR_PORT` | `8100` | Listen port |

## Web panel settings

Open **Settings** in the panel.

### Runtime

| Setting | Meaning |
| --- | --- |
| Pause all auto replies | Stops every reply without stopping the process |
| Ignore bot messages | Bot messages do not trigger rules |
| Minimum seconds between replies in a chat | Per-group cooldown |
| Maximum replies per chat per minute | Per-group minute limit |
| Maximum replies per chat per day | Per-group daily limit |
| Maximum replies globally per minute | Global minute limit |

### Network proxy

| Setting | Meaning |
| --- | --- |
| Proxy enabled | Use a proxy for Telegram connections |
| Type | SOCKS5, SOCKS4 or HTTP |
| Host / port | Proxy address |
| Username / password | Optional proxy authentication |

After changing proxy settings, the Telegram manager reconnects.

## Keyword rules

Each rule has:

| Field | Description |
| --- | --- |
| Name | Human-readable rule name |
| Pattern | Keyword or regular expression |
| Match type | `contains`, `regex` or `word` |
| Case sensitive | Whether matching is case-sensitive |
| Reply | Reply text |
| Cooldown seconds | Minimum interval for the same keyword in the same group |
| Per-user cooldown seconds | Minimum interval for the same user and rule |
| Enabled | Whether the rule is active |
| Chat scope | Optional group selection; empty means all monitored groups |

### Matching modes

- `contains`: substring search.
- `regex`: Python regular expression search.
- `word`: Latin word-boundary search; CJK/kana/Hangul patterns fall back to substring matching.

### Reply placeholders

| Placeholder | Value |
| --- | --- |
| `{keyword}` | The rule pattern that matched |
| `{user}` | Sender display name |
| `{chat}` | Group title |

## Groups

Only groups explicitly enabled in **Groups** are monitored. The Telegram account must already be a member of the group.

## Telegram API credentials

Create an application at <https://my.telegram.org>:

| Field | Suggested value |
| --- | --- |
| App title | `Telegram Keyword Responder` |
| Short name | `tgkeywordresp` (letters and digits, 5–32 characters) |
| URL | Your project or panel URL |
| Platform | Desktop |

Copy `api_id` and `api_hash` into the panel's **Account** page.

## Data files

| File | Purpose |
| --- | --- |
| `data/state.db` | Settings, rules, chats, logs |
| `data/account.session` | Telegram login session |
| `.env` | Process-level configuration |

Keep `.env`, `data/state.db` and `data/account.session` at mode `600`.
