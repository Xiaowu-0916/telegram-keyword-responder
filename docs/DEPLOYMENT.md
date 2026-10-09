# Deployment

The recommended production setup is Linux + systemd + a reverse proxy with HTTPS.

## 1. Create a dedicated user and directory

```bash
sudo useradd --system --create-home --home-dir /srv/tg-keyword-responder tgkr
sudo mkdir -p /srv/tg-keyword-responder
sudo chown -R tgkr:tgkr /srv/tg-keyword-responder
```

Copy the project into `/srv/tg-keyword-responder`.

## 2. Create the virtual environment

```bash
cd /srv/tg-keyword-responder
sudo -u tgkr python3 -m venv .venv
sudo -u tgkr .venv/bin/pip install -r requirements.txt
```

## 3. Create `.env`

```bash
cd /srv/tg-keyword-responder
sudo -u tgkr cp .env.example .env
sudo -u tgkr chmod 600 .env
```

Set at least:

```dotenv
TGKR_BASE_DIR=/srv/tg-keyword-responder
TGKR_DATA_DIR=/srv/tg-keyword-responder/data
TGKR_DB_PATH=/srv/tg-keyword-responder/data/state.db
TGKR_SESSION_PATH=/srv/tg-keyword-responder/data/account
TGKR_ADMIN_USER=admin
TGKR_INITIAL_PASSWORD=<strong-password>
TGKR_SESSION_SECRET=<openssl rand -hex 32>
TGKR_HTTPS_ONLY=1
TGKR_HOST=127.0.0.1
TGKR_PORT=8100
```

Create the data directory:

```bash
sudo -u tgkr mkdir -p /srv/tg-keyword-responder/data
sudo -u tgkr chmod 700 /srv/tg-keyword-responder/data
```

## 4. Install the systemd unit

```bash
sudo cp deploy/tg-keyword-responder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tg-keyword-responder
sudo systemctl status tg-keyword-responder --no-pager
```

The unit assumes the directory `/srv/tg-keyword-responder` and the user `tgkr`. Adjust the paths if you use a different location.

## 5. Reverse proxy and HTTPS

Use `deploy/nginx-tg.conf` as a starting point:

1. Replace `<YOUR_DOMAIN>` with your domain.
2. Point the domain at the server.
3. Obtain a certificate (for example with certbot).
4. Reload nginx.

The app binds to `127.0.0.1:8100`, so it is not directly exposed to the internet.

`TGKR_HTTPS_ONLY=1` makes the panel session cookie HTTPS-only.

## 6. Telegram connectivity

If the server can reach Telegram directly, no proxy is needed.

If it cannot:

1. Open **Settings → Network proxy** in the web panel.
2. Choose SOCKS5, SOCKS4 or HTTP.
3. Enter the proxy host, port and credentials.
4. Save and wait for the Telegram manager to reconnect.

An optional SSH dynamic SOCKS example is provided in `deploy/tg-keyword-responder-socks.service`. It uses an SSH key and a placeholder `<PROXY_USER>@<PROXY_HOST>`. This is only one way to obtain a proxy; a normal SOCKS5 or HTTP proxy works too.

## 7. First login

1. Open the panel.
2. Go to **Account**.
3. Enter `api_id` and `api_hash` from <https://my.telegram.org>.
4. Enter the phone number and the Telegram code.
5. Enter the two-step password if required.
6. Go to **Groups** and enable the groups to watch.
7. Go to **Keywords** and create rules.

## 8. Updating

Code updates do not require a new Telegram login:

```bash
cd /srv/tg-keyword-responder
# replace code files
sudo -u tgkr .venv/bin/pip install -r requirements.txt
sudo systemctl restart tg-keyword-responder
sudo systemctl status tg-keyword-responder --no-pager
```

Do not delete or replace:

- `data/state.db` (rules, settings, logs);
- `data/account.session` (Telegram login session).

## 9. Backup

Back up:

```text
.env
data/
```

The session file is the most sensitive item. Store backups with mode `600` and do not commit them to Git.

## 10. Docker alternative

The repository includes `Dockerfile` and `docker-compose.example.yml`.

The example uses host networking so the app can bind to `127.0.0.1` and sit behind a local reverse proxy:

```bash
cp .env.example .env
# use container paths:
# TGKR_BASE_DIR=/app
# TGKR_DATA_DIR=/app/data
# TGKR_DB_PATH=/app/data/state.db
# TGKR_SESSION_PATH=/app/data/account
docker compose -f docker-compose.example.yml up -d --build
```

The `data` directory is bind-mounted to `/app/data`.

## 11. Troubleshooting

| Symptom | Check |
| --- | --- |
| Panel does not open | `systemctl status tg-keyword-responder`, `curl http://127.0.0.1:8100/healthz` |
| Login code never arrives | The code is sent inside Telegram, not by SMS; check the correct account |
| Telegram connection error | Check the proxy in **Settings → Network proxy** |
| No replies | Check the group allowlist, rule enabled state, cooldowns and the **Logs** page |
| Rate limited by Telegram | Increase cooldowns, reduce limits, or pause the bot |
| Session lost | Restore `data/account.session` from a backup; otherwise log in again |
