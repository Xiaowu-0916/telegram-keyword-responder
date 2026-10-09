# Deployment templates

These files are generic starting points. Replace every `<PLACEHOLDER>` before use.

| File | Purpose |
| --- | --- |
| `tg-keyword-responder.service` | systemd unit for the app |
| `tg-keyword-responder-socks.service` | optional SSH dynamic SOCKS tunnel |
| `nginx-tg.conf` | nginx reverse proxy with HTTPS |

The full deployment guide is in [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

Typical layout:

```text
/srv/tg-keyword-responder/
├── .env
├── .venv/
├── app/
├── data/
└── main.py
```

The app should bind to `127.0.0.1:8100` and sit behind a reverse proxy. Set
`TGKR_HTTPS_ONLY=1` when HTTPS is enabled.
