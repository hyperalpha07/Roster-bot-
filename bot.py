import os
import re
import random
import sqlite3
import traceback
from datetime import datetime

from openai import OpenAI
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# =========================================================
# ENV
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "").strip()
ROAST_GROUP_ID = os.getenv("ROAST_GROUP_ID", "").strip()

DB_PATH = "roast_memory.db"
repair_mode = False

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================================================
# BASIC
# =========================================================
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


def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"[@:।,!?]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value[:40].strip()


def user_display_name(user):
    if user.username:
        return user.username.upper()
    return (user.full_name or str(user.id)).upper()


# =========================================================
# DATABASE
# =========================================================
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS person_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT,
        note TEXT,
        created_by TEXT,
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


def save_person_memory(target, note, created_by):
    if not target or not note:
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO person_memory(target,note,created_by,created_at)
    VALUES(?,?,?,?)
    """, (target.upper(), note[:200], created_by, now_str()))
    con.commit()
    con.close()


def get_target_memory_note(target):
    target = target.upper()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    SELECT note
    FROM person_memory
    WHERE target=?
    ORDER BY id DESC
    LIMIT 8
    """, (target,))
    rows1 = cur.fetchall()

    cur.execute("""
    SELECT topic, message
    FROM target_memory
    WHERE target=?
    ORDER BY id DESC
    LIMIT 5
    """, (target,))
    rows2 = cur.fetchall()

    con.close()

    notes = []

    for row in rows1:
        notes.append(row[0])

    for topic, message in rows2:
        notes.append(f"{topic}: {message}")

    if not notes:
        return "No memory yet."

    return " | ".join(notes[:10])


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


# =========================================================
# TARGET + MEMORY DETECTION
# =========================================================
def detect_target(text):
    raw = text.strip()

    patterns = [
        r"^(.+?)\s+(?:always|sob somoy|সবসময়|সব সময়)\s+(.+)$",
        r"^(.+?)\s+(?:ke|কে)\s+(.+)$",
        r"^(.+?)\s+(?:chittar|chitar|cheater|চিটার|faforbaj|fapore|fapor|ফাপরবাজ|ফাপরে|lazy|লেজি|drama|নাটক|boka|বোকা|hutase|হুটাসে).*$",
    ]

    for p in patterns:
        m = re.search(p, raw, flags=re.IGNORECASE)
        if m:
            target = clean_name(m.group(1))
            if target:
                return target.upper()

    words = raw.split()
    if len(words) >= 2:
        first = clean_name(words[0])
        if first:
            return first.upper()

    return None


def extract_memory_note(text, target):
    if not target:
        return None

    raw = text.strip()
    low = raw.lower()

    target_low = target.lower()
    note = raw

    note = re.sub(rf"^{re.escape(target_low)}\s+", "", note, flags=re.IGNORECASE).strip()

    if any(x in low for x in ["always", "sob somoy", "সবসময়", "সব সময়", "hobe", "হবে", "bole", "বলে"]):
        return note[:200]

    memory_words = [
        "faforbaj", "fapore", "fapor", "ফাপরবাজ", "ফাপরে",
        "chittar", "chitar", "cheater", "চিটার",
        "lazy", "লেজি", "drama", "নাটক",
        "boka", "বোকা", "hutase", "হুটাসে",
        "hero", "হিরো", "over", "attitude",
    ]

    if any(w in low for w in memory_words):
        return note[:200]

    return None


def detect_topic_ai(text):
    if not client:
        return "general"

    prompt = f"""
User message: {text}

এই message অনুযায়ী target কে কোন কারণে roast করা হচ্ছে সেটা 1-3 word-এ বলো।

Rules:
- English only
- No sentence
- Example: cheating, fake showoff, lazy, drama, annoying, overconfident, liar, useless logic

Only answer topic.
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=12,
        )
        topic = res.choices[0].message.content.strip().lower()
        topic = re.sub(r"[^a-zA-Z\s_-]", "", topic).strip()
        return topic if topic else "general"
    except Exception:
        return "general"


def detect_topic_fallback(text):
    low = text.lower()

    if any(w in low for w in ["chittar", "chitar", "cheater", "চিটার", "dhoka", "ঠকায়", "ধোঁকা"]):
        return "cheating"
    if any(w in low for w in ["faforbaj", "fapore", "fapor", "ফাপরবাজ", "ফাপরে"]):
        return "fake showoff"
    if any(w in low for w in ["lazy", "ghum", "ঘুম", "লেজি", "অলস"]):
        return "lazy"
    if any(w in low for w in ["drama", "natok", "নাটক"]):
        return "drama"
    if any(w in low for w in ["boka", "বোকা", "gada", "গাধা"]):
        return "stupid"
    if any(w in low for w in ["hero", "হিরো", "attitude", "smart"]):
        return "overconfident"

    return "general"


def detect_topic(text):
    ai_topic = detect_topic_ai(text)
    if ai_topic and ai_topic != "general":
        return ai_topic
    return detect_topic_fallback(text)


# =========================================================
# ROAST ENGINE
# =========================================================
def fallback_roast(target, topic, attacker):
    lines = [
        f"{target} আজকে এমনভাবে ধরা খাইছে, group-এর entertainment নিজে থেকেই চালু হয়ে গেছে 😭😂",
        f"{target}, তোমার confidence দেখে ভালো লাগে, কিন্তু backup দেখে মনে হয় network নেই 🤣",
        f"{target} এর logic এমন premium যে calculator-ও বুঝতে গিয়ে hang করে 😭",
        f"{target} আবার hero mode on করছে? আগে নিজের software update দাও ভাই 🤣",
        f"{target}, তোমাকে roast করতে আলাদা script লাগে না, তুমি নিজেই content দিয়ে দাও 😭😂",
    ]

    if "cheat" in topic or "liar" in topic:
        lines += [
            f"{target} এমন চিটার যে নিজের shadow-কেও trust করতে ভয় লাগে 😭😂",
            f"{target} এর honesty খুঁজতে গেলে Google Maps-ও রাস্তা হারায় 🤣",
        ]

    if "fake" in topic or "show" in topic or "over" in topic:
        lines += [
            f"{target} ফাপর এমন মারে, মনে হয় বাতাসও ওর কাছ থেকে attitude শিখে 😭😂",
            f"{target} এর ফাপর দেখে group-এর WiFi signal-ও লজ্জা পায় 🤣",
        ]

    if "lazy" in topic:
        lines += [
            f"{target} এত lazy যে ঘুম থেকেও break নিতে চায় 😭😂",
            f"{target} কাজ শুরু করার আগেই ক্লান্ত হয়ে যায়, pure talent 🤣",
        ]

    if "drama" in topic:
        lines += [
            f"{target} নাটক করলে serial director-রাও notebook বের করে 😭😂",
            f"{target} এর life না, full season with bonus episode 🤣",
        ]

    return random.choice(lines)


def ai_roast(target, topic, attacker, original_text):
    memory_note = get_target_memory_note(target)

    if not client:
        return fallback_roast(target, topic, attacker)

    prompt = f"""
তুমি Telegram friend group-এর ULTRA SAVAGE Bangla/Banglish roast bot।

Target: {target}
Attacker: {attacker}
Detected topic: {topic}
Original message: {original_text}
Memory about target: {memory_note}

Rules:
- Target কে topic + memory অনুযায়ী খুব মজা করে পচাবে।
- Tone: ultra savage, sharp, humiliating-funny, friend-group style.
- বাংলা spelling যতটা সম্ভব শুদ্ধ রাখবে।
- Banglish natural রাখবে।
- ১-৩ লাইনের মধ্যে reply।
- fixed template না।
- খুব অশ্লীল গালি না।
- ধর্ম, জাতি, শরীর, পরিবার, অসুস্থতা, মৃত্যু, sexual insult — এসব নিয়ে attack করবে না।
- Memory থাকলে naturally use করবে, কিন্তু “memory says” বা “memory” শব্দ লিখবে না।
- কোনো explanation, JSON, list, analysis দিবে না।
- Reply only.
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an ultra savage Bengali/Banglish friend-group roast bot. Keep it funny, sharp, and safe. Bengali spelling must be clean.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=1.25,
            max_tokens=220,
        )

        text = res.choices[0].message.content.strip()
        text = text.replace("```", "").strip()
        text = re.sub(r"\s+", " ", text).strip()

        bad = ["json", "analysis", "memory says", "as an ai", "আমি পারি না"]
        if not text or any(b in text.lower() for b in bad):
            return fallback_roast(target, topic, attacker)

        return text[:600]

    except Exception:
        print(traceback.format_exc())
        return fallback_roast(target, topic, attacker)


# =========================================================
# COMMANDS
# =========================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Ultra Savage Roast Bot active.\n\n"
        "Example:\n"
        "joni always faforbaj\n"
        "surjo sobar taka khai\n"
        "alon beshi hero hoy\n"
        "mony natok kore\n\n"
        "Admin:\n"
        "/status\n"
        "/repair_on\n"
        "/repair_off\n"
        "/memory"
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
        "🔥 ROAST BOT STATUS\n\n"
        f"Repair Mode: {'ON 🔧' if repair_mode else 'OFF ✅'}\n"
        f"OpenAI: {'ON 🤖' if OPENAI_API_KEY else 'OFF'}\n"
        f"Group Lock: {ROAST_GROUP_ID or 'OFF'}\n"
        f"Mode: ULTRA SAVAGE"
    )


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    SELECT target,note,created_by,created_at
    FROM person_memory
    ORDER BY id DESC
    LIMIT 15
    """)
    rows1 = cur.fetchall()

    cur.execute("""
    SELECT attacker,target,topic,message,created_at
    FROM target_memory
    ORDER BY id DESC
    LIMIT 10
    """)
    rows2 = cur.fetchall()

    con.close()

    msg = "🧠 ROAST MEMORY\n\n"

    if rows1:
        msg += "📌 Person Memory:\n"
        for target, note, created_by, created_at in rows1:
            msg += f"• {target}: {note}\n  by {created_by} | {created_at}\n"

    if rows2:
        msg += "\n🎯 Recent Targets:\n"
        for attacker, target, topic, message, created_at in rows2:
            msg += f"• {attacker} → {target} | {topic}\n  {message}\n  {created_at}\n"

    if not rows1 and not rows2:
        msg += "Memory empty."

    await update.message.reply_text(msg[:4000])


async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /forget JONI")
        return

    target = clean_name(" ".join(context.args)).upper()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM person_memory WHERE target=?", (target,))
    cur.execute("DELETE FROM target_memory WHERE target=?", (target,))
    con.commit()
    con.close()

    await update.message.reply_text(f"🗑 {target} এর memory delete করা হয়েছে।")


# =========================================================
# MESSAGE HANDLER
# =========================================================
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

    if not target:
        return

    topic = detect_topic(text)
    memory_note = extract_memory_note(text, target)

    if memory_note:
        save_person_memory(target, memory_note, attacker)

    save_target(chat.id, attacker, target, topic, text)

    reply = ai_roast(target, topic, attacker, text)
    await update.message.reply_text(reply)


# =========================================================
# BOT SETUP
# =========================================================
async def post_init(application: Application):
    commands = [
        BotCommand("start", "Start roast bot"),
        BotCommand("status", "Admin only bot status"),
        BotCommand("repair_on", "Admin only repair ON"),
        BotCommand("repair_off", "Admin only repair OFF"),
        BotCommand("memory", "Admin only show memory"),
        BotCommand("forget", "Admin only forget target memory"),
    ]
    await application.bot.set_my_commands(commands)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    init_db()

    print("Ultra Savage Roast Bot running...")
    print("OpenAI:", "ON" if OPENAI_API_KEY else "OFF")
    print("Group Lock:", ROAST_GROUP_ID or "OFF")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on_cmd))
    app.add_handler(CommandHandler("repair_off", repair_off_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
