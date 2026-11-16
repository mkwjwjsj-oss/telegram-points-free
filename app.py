import os
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, abort
import telebot

TOKEN = os.environ["BOT_TOKEN"].strip()
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATABASE_URL = os.environ["DATABASE_URL"].strip()
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()
RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def db():
    return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=20)

def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    points BIGINT NOT NULL DEFAULT 0 CHECK (points >= 0),
                    last_daily DATE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    actor_id BIGINT NOT NULL,
                    target_id BIGINT NOT NULL,
                    amount BIGINT NOT NULL CHECK (amount > 0),
                    kind TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

def ensure_user(cur, user):
    cur.execute("""
        INSERT INTO users(user_id, username)
        VALUES (%s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET username = EXCLUDED.username
    """, (user.id, user.username or user.first_name or ""))

@bot.message_handler(commands=["start", "help"])
def start(message):
    with db() as conn:
        with conn.cursor() as cur:
            ensure_user(cur, message.from_user)
    bot.reply_to(
        message,
        "أهلاً بك في نظام النقاط 💎\n\n"
        "/balance — عرض رصيدك\n"
        "/daily — مكافأة يومية (100 نقطة)\n"
        "/transfer USER_ID AMOUNT — تحويل نقاط\n"
        "/top — أعلى 10 أرصدة"
    )

@bot.message_handler(commands=["balance"])
def balance(message):
    with db() as conn:
        with conn.cursor() as cur:
            ensure_user(cur, message.from_user)
            cur.execute("SELECT points FROM users WHERE user_id=%s",
                        (message.from_user.id,))
            points = cur.fetchone()[0]
    bot.reply_to(message, f"💎 رصيدك الحالي: {points} نقطة")

@bot.message_handler(commands=["daily"])
def daily(message):
    today = date.today()
    uid = message.from_user.id
    with db() as conn:
        with conn.cursor() as cur:
            ensure_user(cur, message.from_user)
            cur.execute("""
                UPDATE users
                SET points = points + 100, last_daily = %s
                WHERE user_id = %s AND last_daily IS DISTINCT FROM %s
                RETURNING points
            """, (today, uid, today))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    INSERT INTO transactions(actor_id,target_id,amount,kind)
                    VALUES (%s,%s,100,'daily')
                """, (uid, uid))
    if row:
        bot.reply_to(message, "🎁 مبروك! حصلت على 100 نقطة.")
    else:
        bot.reply_to(message, "⏳ أخذت مكافأتك اليومية بالفعل. ارجع بكرا!")

@bot.message_handler(commands=["transfer"])
def transfer(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "طريقة الاستخدام:\n/transfer USER_ID AMOUNT")
        return
    try:
        target_id, amount = int(parts[1]), int(parts[2])
    except ValueError:
        bot.reply_to(message, "أدخل رقم مستخدم ومبلغ صحيحين.")
        return

    sender_id = message.from_user.id
    if target_id == sender_id or amount <= 0:
        bot.reply_to(message, "❌ التحويل غير صالح.")
        return

    result = None
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id=%s FOR UPDATE",
                        (sender_id,))
            sender = cur.fetchone()
            cur.execute("SELECT user_id FROM users WHERE user_id=%s",
                        (target_id,))
            target = cur.fetchone()
            if not target:
                result = "❌ المستخدم لازم يفتح البوت ويرسل /start أولاً."
            elif not sender or sender[0] < amount:
                result = "❌ رصيدك لا يكفي."
            else:
                cur.execute("UPDATE users SET points=points-%s WHERE user_id=%s",
                            (amount, sender_id))
                cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s",
                            (amount, target_id))
                cur.execute("""
                    INSERT INTO transactions(actor_id,target_id,amount,kind)
                    VALUES (%s,%s,%s,'transfer')
                """, (sender_id, target_id, amount))
                result = f"✅ تم تحويل {amount} نقطة إلى المستخدم {target_id}."
    bot.reply_to(message, result)

@bot.message_handler(commands=["top"])
def top(message):
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT user_id, username, points FROM users
                ORDER BY points DESC, user_id ASC LIMIT 10
            """)
            rows = cur.fetchall()
    if not rows:
        bot.reply_to(message, "لا يوجد مستخدمون في القائمة بعد.")
        return
    lines = ["🏆 أعلى 10 أرصدة:\n"]
    for i, row in enumerate(rows, 1):
        name = "@" + row["username"] if row["username"] else str(row["user_id"])
        lines.append(f'{i}. {name} — {row["points"]} نقطة')
    bot.reply_to(message, "\n".join(lines))

def admin_change(message, sign):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "هذا الأمر مخصص للمشرف.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "الاستخدام: /addpoints USER_ID AMOUNT")
        return
    try:
        target_id, amount = int(parts[1]), int(parts[2])
    except ValueError:
        bot.reply_to(message, "أدخل أرقاماً صحيحة.")
        return
    if amount <= 0:
        bot.reply_to(message, "المبلغ يجب أن يكون أكبر من صفر.")
        return

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id=%s FOR UPDATE",
                        (target_id,))
            row = cur.fetchone()
            if not row:
                bot.reply_to(message, "المستخدم غير مسجل. اطلب منه إرسال /start.")
                return
            if sign < 0 and row[0] < amount:
                bot.reply_to(message, "رصيد المستخدم أقل من المبلغ المطلوب.")
                return
            cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s",
                        (sign * amount, target_id))
            cur.execute("""
                INSERT INTO transactions(actor_id,target_id,amount,kind)
                VALUES (%s,%s,%s,%s)
            """, (message.from_user.id, target_id, amount,
                  "admin_add" if sign > 0 else "admin_remove"))
    verb = "إضافة" if sign > 0 else "خصم"
    bot.reply_to(message, f"✅ تم {verb} {amount} نقطة للمستخدم {target_id}.")

@bot.message_handler(commands=["addpoints"])
def addpoints(message):
    admin_change(message, 1)

@bot.message_handler(commands=["removepoints"])
def removepoints(message):
    admin_change(message, -1)

@app.get("/")
@app.get("/healthz")
def health():
    return "Telegram points bot is running", 200

@app.post("/telegram")
def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return "ok", 200

def setup():
    init_db()
    bot.remove_webhook()
    bot.set_webhook(
        url=f"{RENDER_EXTERNAL_URL}/telegram",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message"]
    )

setup()
