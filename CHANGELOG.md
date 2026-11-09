# Changelog

## 2.0.1 (2026-11-09)

### Broadcast

- Each person gets a broadcast at most once every 7 days. New setting `BROADCAST_GAP_DAYS`, default `7`, lowest `1` (every day).
- No forecast file (`FORECAST_URL` empty): the mock forecast has no rain, so the bot sends a friendly hello, not a rain message.
- Friendly hello reason: "ขอให้วันนี้เป็นวันที่ดี เจออะไรแถวบ้านก็มาเล่าให้ฟังได้นะ".

### Chat prompt

- When the bot messages first, it says a short hello and does not introduce itself: no name, no team, no UCR. It introduces itself only if they ask who it is.
- Buttons follow the story item the bot asks about: where → location button, photo → camera and camera roll, when or how often → 2 to 4 answer buttons. Asking what happened, how it affects them, or to go on → no buttons.
- The new prompt goes in only when the database is new. An old database keeps its old prompt in table `ai_configs`.

### Settings

- Removed 18 settings that no code read: `CORS_ORIGINS`, `DEV_ROUTES_ENABLED`, `REASONING_EFFORT` and 15 `QUOTA_*` keys.

## 2.0.0 (2026-11-04)

First release of UCR Chatbot 2.0. See the [2.0.0 release notes](https://github.com/tonkitcstu/ucr-smartcity_chatbot/releases/tag/v2.0.0).
