# Telegram points bot — free Web Service version

Use Render **Web Service** (not Background Worker).

Build command:
`pip install -r requirements.txt`

Start command:
`gunicorn app:app`

Environment variables:
- `BOT_TOKEN`: BotFather token (keep secret)
- `ADMIN_ID`: your numeric Telegram user ID
- `DATABASE_URL`: Neon Postgres connection string
- `WEBHOOK_SECRET`: random letters/numbers, 20-50 characters
- `RENDER_EXTERNAL_URL`: Render sets this automatically for web services

This version uses Telegram webhooks and PostgreSQL. It avoids SQLite on Render's ephemeral filesystem.
Free hosting has limits: Render free web services sleep after 15 minutes without inbound traffic and may take about a minute to wake. Neon Free compute scales to zero after inactivity and has monthly usage limits. This is suitable for a hobby/test bot, not guaranteed 24/7 production uptime.
