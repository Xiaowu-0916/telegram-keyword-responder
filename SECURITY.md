# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability. Use GitHub's
private vulnerability reporting for this repository, or contact the maintainer
through the GitHub profile.

## Security model

This project is a **Telegram userbot**: it signs in with a real Telegram
account through MTProto. Treat it with the same care as the account itself.

Important assets:

| Asset | Where it lives | Why it matters |
| --- | --- | --- |
| Telegram session | `data/account.session` | Full control of the signed-in Telegram account |
| `api_id` / `api_hash` | SQLite settings | Telegram application credentials |
| Web panel password hash | SQLite settings | Access to the control panel |
| Session signing secret | `.env` (`TGKR_SESSION_SECRET`) | Protects panel session cookies |
| Proxy credentials | SQLite settings / `.env` | May allow access to your proxy |

## Telegram terms of service

Account automation can violate Telegram's terms of service. The project is
deliberately limited to **replies inside explicitly allowed groups**. It does
not contain a private-message sending path and it does not implement bulk
messaging.

Even with these limits:

- use a dedicated account rather than your primary account;
- keep reply frequency low;
- only enable groups you own or administer;
- stop the bot immediately if Telegram sends a warning or rate limit.

## Hardening checklist

- [ ] Set a strong `TGKR_INITIAL_PASSWORD` and change it after the first login.
- [ ] Set a fixed, random `TGKR_SESSION_SECRET` (for example `openssl rand -hex 32`).
- [ ] Serve the panel over HTTPS and set `TGKR_HTTPS_ONLY=1`.
- [ ] Bind the app to `127.0.0.1` and put it behind a reverse proxy.
- [ ] Restrict the server firewall to the ports you actually need.
- [ ] Keep `.env`, `data/state.db` and `data/account.session` at mode `600`.
- [ ] Back up the data directory; never commit it to Git.
- [ ] Rotate proxy credentials and the Telegram session if they leak.
- [ ] Review the logs page regularly for unexpected activity.

## Out of scope

The project does not provide:

- private-message sending to group members;
- bulk messaging or member scraping;
- bypassing Telegram spam controls;
- anonymity or protection from Telegram account restrictions.
