# Changelog

## 0.2.0 - 2026-10-04

- Fixed Chinese/CJK keyword matching in `word` mode. Keywords containing CJK,
  kana or Hangul now fall back to substring matching, so `国庆` matches
  `欢度国庆`.
- Added a hint in the keyword UI: word mode is for Latin words; CJK keywords
  are matched as substrings.
- Added the public documentation set: English/Chinese README, architecture,
  deployment and configuration docs, security policy and Docker examples.

## 0.1.0 - 2026-10-03

- Initial release.
- Telethon userbot with a group allowlist.
- Web panel for Telegram login, group selection, keyword rules, logs and limits.
- Contains / regex / word matching, cooldowns and per-group/per-user/global
  rate limits.
- SQLite storage and mobile-friendly server-rendered UI.
