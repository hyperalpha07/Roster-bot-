import os
import re
import random
import sqlite3
import traceback
from datetime import datetime

from openai import OpenAI
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "").strip()
ROAST_GROUP_ID = os.getenv("ROAST_GROUP_ID", "").strip()

DB_PATH = "roast_memory.db"
repair_mode = False

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_admin_ids():
    return [x.strip() for x in ADMIN_USER_IDS.split(",") if x.strip()]


def is_admin(user_id):
    return str(user_id).strip() in get_admin_ids()


def allowed_group(update: Update):
    if not ROAST_GROUP_ID:
        return True
    return update.effective_chat and str(update.effective_chat.id) == str(ROAST_GROUP_ID)


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        user_id TEXT,
        name TEXT,
        message TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS target_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        attacker TEXT,
        target TEXT,
        topic TEXT,
        message TEXT,
        created_at TEXT
    )
    """)

    con.commit()
    con.close()


def save_chat(chat_id, user_id, name, message):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO chat_memory(chat_id,user_id,name,message,created_at)
    VALUES(?,?,?,?,?)
    """, (str(chat_id), str(user_id), name, message, now_str()))
    con.commit()
    con.close()


def save_target(chat_id, attacker, target, topic, message):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO target_memory(chat_id,attacker,target,topic,message,created_at)
    VALUES(?,?,?,?,?,?)
    """, (str(chat_id), attacker, target, topic, message, now_str()))
    con.commit()
    con.close()


def get_recent_target(chat_id, attacker):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT target, topic, message
    FROM target_memory
    WHERE chat_id=? AND attacker=?
    ORDER BY id DESC
    LIMIT 1
    """, (str(chat_id), attacker))
    row = cur.fetchone()
    con.close()
    return row


def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"[@:।,!?]", "", value)
    return value[:40].strip()


def user_display_name(user):
    if user.username:
        return user.username.upper()
    return (user.full_name or str(user.id)).upper()


def detect_topic_ai(text):
    if not client:
        return "general"

    prompt = f"""
User message: {text}

এই message অনুযায়ী target কে কোন কারণে roast করা হচ্ছে সেটা এক কথায় বলো।

Rules:
- 1 word only
- english word
- example: cheating, lazy, drama, fake, stupid, attention, annoying, overconfident

Answer শুধু word হবে।
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=10,
        )
        topic = res.choices[0].message.content.strip().lower()
        return topic if topic else "general"
    except:
        return "general"


def detect_target(text):
    raw = text.strip()

    patterns = [
        r"^(.+?)\s+(?:ke|কে)\s+(?:chittar|chitar|cheater|চিটার)",
        r"^(.+?)\s+(?:chittar|chitar|cheater|চিটার)",
        r"^(.+?)\s+(?:fapore chole|fapor e chole|ফাপরে চলে|ফাপর চলে)",
        r"^(.+?)\s+(?:lazy|লেজি|অলস)",
        r"^(.+?)\s+(?:drama|নাটক)",
        r"^(.+?)\s+(?:boka|বোকা)",
        r"^(.+?)\s+(?:hutase|hutashe|হুটাসে)",
    ]

    for p in patterns:
        m = re.search(p, raw, flags=re.IGNORECASE)
        if m:
            target = clean_name(m.group(1))
            if target:
                return target.upper()

    return None


def fallback_roast(target, topic, attacker):
    if topic == "cheater":
        lines = [
            f"{target} চিটার না, ও তো চিটিং-এর brand ambassador মনে হয় 😭😂",
            f"{target} এমন চিটার যে calculator-ও ওর হিসাব দেখে সন্দেহ করে বসে 🤣",
            f"{target} এর honesty খুঁজতে গেলে Google Maps-ও রাস্তা হারায় 😭",
        ]
    elif topic == "fapore":
        lines = [
            f"{target} ফাপরে এমনভাবে চলে, মনে হয় নিজের shadow-কেও impress করতে চায় 😭😂",
            f"{target} এর ফাপর দেখে বাতাসও বলে, ভাই একটু কমাও 🤣",
            f"{target} ফাপরে চলে ঠিকই, কিন্তু result আসে loading screen-এর মতো 😭",
        ]
    elif topic == "lazy":
        lines = [
            f"{target} এত lazy যে ঘুম থেকেও ছুটি নিতে চায় 😭😂",
            f"{target} কাজ শুরু করার আগে ক্লান্ত হয়ে যায়, pure talent 🤣",
        ]
    elif topic == "drama":
        lines = [
            f"{target} drama করলে serial director-রাও note নেয় 😭😂",
            f"{target} এর life না, full episode with commercial break 🤣",
        ]
    elif topic == "boka":
        lines = [
            f"{target} এর logic দেখে calculator silent mode-এ চলে যায় 😭😂",
            f"{target} কথা বললে brain cell meeting ডাকতে হয় 🤣",
        ]
    else:
        lines = [
            f"{target} আজকে ধরা খাইছে 😭 এখন group officially entertainment mode-এ 🤣",
            f"{target}, তোমার confidence ভালো, কিন্তু backup নাই 😭😂",
            f"{target} কে roast করতে বেশি effort লাগে না, ও নিজেই content দিয়ে দেয় 🤣",
        ]

    return random.choice(lines)


def ai_roast(target, topic, attacker, original_text):
    if not client:
        return fallback_roast(target, topic, attacker)

    prompt = f"""
তুমি একটি বন্ধুবান্ধবের Telegram group-এর Bangla/Banglish roast bot।

Target: {target}
Attacker: {attacker}
Topic: {topic}
Original message: {original_text}

কাজ:
- Target কে topic অনুযায়ী savage কিন্তু funny ভাবে roast করো।
- বাংলা spelling যতটা সম্ভব শুদ্ধ রাখো।
- Banglish থাকলে natural রাখো।
- ১-৩ লাইনের মধ্যে reply।
- fixed template না।
- খুব অশ্লীল গালি না।
- ধর্ম, জাতি, শরীর, পরিবার, অসুস্থতা, মৃত্যু, sexual insult — এসব নিয়ে roast করবে না।
- reply যেন বন্ধুরা পড়ে হাসে।
- কোনো explanation, JSON, list, analysis দিবে না।
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a Bengali/Banglish funny Telegram roast bot. Keep spelling clean and tone playful-savage.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=1.1,
            max_tokens=180,
        )
        text = res.choices[0].message.content.strip()
        text = text.replace("```", "").strip()
        return text[:500] if text else fallback_roast(target, topic, attacker)
    except Exception:
        print(traceback.format_exc())
        return fallback_roast(target, topic, attacker)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Roast Bot active.\n\n"
        "Example:\n"
        "joni chittar\n"
        "surjo fapore chole\n"
        "alon lazy\n\n"
        "Admin:\n"
        "/repair_on\n"
        "/repair_off\n"
        "/status"
    )


async def repair_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global repair_mode
    if not is_admin(update.effective_user.id):
        return
    repair_mode = True
    await update.message.reply_text("🔧 Repair mode ON")


async def repair_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global repair_mode
    if not is_admin(update.effective_user.id):
        return
    repair_mode = False
    await update.message.reply_text("✅ Repair mode OFF")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        f"🔥 Roast Bot Status\n\n"
        f"Repair Mode: {'ON' if repair_mode else 'OFF'}\n"
        f"OpenAI: {'ON' if OPENAI_API_KEY else 'OFF'}\n"
        f"Group Lock: {ROAST_GROUP_ID or 'OFF'}"
    )


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT attacker,target,topic,message,created_at
    FROM target_memory
    ORDER BY id DESC
    LIMIT 10
    """)
    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("Memory empty.")
        return

    msg = "🧠 Last roast memory:\n\n"
    for attacker, target, topic, message, created_at in rows:
        msg += f"• {attacker} → {target} | {topic}\n{message}\n{created_at}\n\n"

    await update.message.reply_text(msg[:4000])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global repair_mode

    if not update.message or not update.message.text:
        return

    if not allowed_group(update):
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text.strip()
    attacker = user_display_name(user)

    save_chat(chat.id, user.id, attacker, text)

    if repair_mode and not is_admin(user.id):
        return

    target = detect_target(text)
   # SMART
topic = detect_topic_ai(text)

    if target:
        save_target(chat.id, attacker, target, topic, text)
        reply = ai_roast(target, topic, attacker, text)
        await update.message.reply_text(reply)
        return

    old = get_recent_target(chat.id, attacker)

    trigger_words = ["roast", "পচা", "পচাও", "fapore", "chittar", "চিটার", "ফাপরে"]
    if old and any(w in text.lower() for w in trigger_words):
        old_target, old_topic, old_msg = old
        reply = (
            f"{attacker}, তুমি তো আগে {old_target} কে নিয়ে কথা বলছিলা 😏\n"
            f"আগে ওই case clear করো, তারপর নতুন roast court বসুক 😂"
        )
        await update.message.reply_text(reply)
        return

    # Normal random chat ignored silently.


async def post_init(application: Application):
    commands = [
        BotCommand("start", "Start roast bot"),
        BotCommand("status", "Bot status"),
        BotCommand("repair_on", "Admin only repair ON"),
        BotCommand("repair_off", "Admin only repair OFF"),
        BotCommand("memory", "Admin only last memory"),
    ]
    await application.bot.set_my_commands(commands)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    init_db()

    print("Roast Bot running...")
    print("OpenAI:", "ON" if OPENAI_API_KEY else "OFF")
    print("Group:", ROAST_GROUP_ID or "No group lock")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on_cmd))
    app.add_handler(CommandHandler("repair_off", repair_off_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
