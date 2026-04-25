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

DAY_SHIFT_START = os.getenv("DAY_SHIFT_START", "05:00").strip()
DAY_SHIFT_END = os.getenv("DAY_SHIFT_END", "17:20").strip()

DB_PATH = "roast_memory.db"
repair_mode = False

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================================================
# BASIC
# =========================================================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_minutes():
    now = datetime.now()
    return now.hour * 60 + now.minute


def parse_hhmm(value: str):
    try:
        h, m = value.strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 5 * 60


def is_day_shift_now():
    start = parse_hhmm(DAY_SHIFT_START)
    end = parse_hhmm(DAY_SHIFT_END)
    cur = today_minutes()

    if start <= end:
        return start <= cur <= end

    return cur >= start or cur <= end


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
    return value[:50].strip()


def raw_display_name(user):
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        day_name TEXT,
        night_name TEXT,
        role TEXT,
        last_seen TEXT
    )
    """)

    con.commit()
    con.close()


def register_user(user):
    if not user:
        return

    uid = str(user.id)
    username = user.username or ""
    full_name = user.full_name or ""

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT user_id FROM user_profiles WHERE user_id=?", (uid,))
    exists = cur.fetchone()

    if exists:
        cur.execute("""
        UPDATE user_profiles
        SET username=?, full_name=?, last_seen=?
        WHERE user_id=?
        """, (username, full_name, now_str(), uid))
    else:
        cur.execute("""
        INSERT INTO user_profiles(user_id,username,full_name,day_name,night_name,role,last_seen)
        VALUES(?,?,?,?,?,?,?)
        """, (uid, username, full_name, full_name or username or uid, "", "MEMBER", now_str()))

    con.commit()
    con.close()


def set_user_profile(user_id, day_name, night_name, role="MEMBER"):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT user_id FROM user_profiles WHERE user_id=?", (str(user_id),))
    exists = cur.fetchone()

    if exists:
        cur.execute("""
        UPDATE user_profiles
        SET day_name=?, night_name=?, role=?, last_seen=?
        WHERE user_id=?
        """, (day_name, night_name, role.upper(), now_str(), str(user_id)))
    else:
        cur.execute("""
        INSERT INTO user_profiles(user_id,username,full_name,day_name,night_name,role,last_seen)
        VALUES(?,?,?,?,?,?,?)
        """, (str(user_id), "", "", day_name, night_name, role.upper(), now_str()))

    con.commit()
    con.close()


def get_profile_by_id(user_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT user_id,username,full_name,day_name,night_name,role,last_seen
    FROM user_profiles
    WHERE user_id=?
    """, (str(user_id),))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return {
        "user_id": row[0],
        "username": row[1] or "",
        "full_name": row[2] or "",
        "day_name": row[3] or "",
        "night_name": row[4] or "",
        "role": row[5] or "MEMBER",
        "last_seen": row[6] or "",
    }


def get_active_name_by_id(user_id, fallback_user=None):
    profile = get_profile_by_id(user_id)

    if profile:
        if is_day_shift_now():
            name = profile["day_name"] or profile["full_name"] or profile["username"] or str(user_id)
        else:
            name = profile["night_name"] or profile["day_name"] or profile["full_name"] or profile["username"] or str(user_id)
        return clean_name(name).upper()

    if fallback_user:
        return raw_display_name(fallback_user)

    return str(user_id)


def find_user_by_name_or_username(name):
    q = clean_name(name).lower()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT user_id,username,full_name,day_name,night_name,role,last_seen
    FROM user_profiles
    """)
    rows = cur.fetchall()
    con.close()

    for row in rows:
        user_id, username, full_name, day_name, night_name, role, last_seen = row
        candidates = [username, full_name, day_name, night_name]
        for c in candidates:
            if c and clean_name(c).lower() == q:
                return get_active_name_by_id(user_id)

    return clean_name(name).upper()


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
    """, (target.upper(), note[:220], created_by, now_str()))
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


# =========================================================
# TARGET DETECTION
# =========================================================
def detect_reply_target(update: Update):
    if not update.message or not update.message.reply_to_message:
        return None

    replied_user = update.message.reply_to_message.from_user
    if not replied_user:
        return None

    register_user(replied_user)
    return get_active_name_by_id(replied_user.id, replied_user)


def detect_mention_target(text):
    mention = re.findall(r"@([A-Za-z0-9_]+)", text)
    if mention:
        return find_user_by_name_or_username(mention[0])
    return None


def detect_text_target(text):
    raw = text.strip()

    patterns = [
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:always|sob somoy|সবসময়|সব সময়)\s+(.+)$",
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:ke|কে)\s+(.+)$",
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:chittar|chitar|cheater|চিটার|faforbaj|fapore|fapor|ফাপরবাজ|ফাপরে|lazy|লেজি|drama|নাটক|boka|বোকা|hutase|হুটাসে|hero|হিরো|attitude).*$",
    ]

    for p in patterns:
        m = re.search(p, raw, flags=re.IGNORECASE)
        if m:
            target = clean_name(m.group(1))
            if target:
                return find_user_by_name_or_username(target)

    words = raw.split()
    if len(words) >= 2:
        first = clean_name(words[0])
        if first:
            return find_user_by_name_or_username(first)

    return None


def detect_target(update: Update, text: str):
    # 1) Reply target is highest priority
    reply_target = detect_reply_target(update)
    if reply_target:
        return reply_target

    # 2) @username target
    mention_target = detect_mention_target(text)
    if mention_target:
        return mention_target

    # 3) Normal text target
    return detect_text_target(text)


def extract_memory_note(text, target):
    if not target:
        return None

    raw = text.strip()
    low = raw.lower()
    note = raw

    note = re.sub(rf"^{re.escape(target.lower())}\s+", "", note, flags=re.IGNORECASE).strip()

    memory_words = [
        "always", "sob somoy", "সবসময়", "সব সময়",
        "faforbaj", "fapore", "fapor", "ফাপরবাজ", "ফাপরে",
        "chittar", "chitar", "cheater", "চিটার",
        "lazy", "লেজি", "drama", "নাটক",
        "boka", "বোকা", "hutase", "হুটাসে",
        "hero", "হিরো", "over", "attitude",
        "dhoka", "ঠকায়", "ধোঁকা", "miche", "মিথ্যা"
    ]

    if any(w in low for w in memory_words):
        return note[:220]

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
    register_user(update.effective_user)

    text = (
        "🔥 Ultra Savage Roast Bot active.\n\n"
        f"তোমার Telegram ID: {update.effective_user.id}\n"
        f"Detected name: {get_active_name_by_id(update.effective_user.id, update.effective_user)}\n\n"
        "Example:\n"
        "joni always faforbaj\n"
        "surjo sobar taka khai\n"
        "alon beshi hero hoy\n"
        "অথবা কারো message-এ reply দিয়ে লিখো: chittar\n\n"
        "Admin:\n"
        "/status\n"
        "/users\n"
        "/setuser USER_ID DAY_NAME NIGHT_NAME ROLE\n"
        "/memory\n"
        "/forget NAME"
    )

    await update.message.reply_text(text)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "🔥 ROAST BOT STATUS\n\n"
        f"Repair Mode: {'ON 🔧' if repair_mode else 'OFF ✅'}\n"
        f"OpenAI: {'ON 🤖' if OPENAI_API_KEY else 'OFF'}\n"
        f"Group Lock: {ROAST_GROUP_ID or 'OFF'}\n"
        f"Mode: ULTRA SAVAGE\n"
        f"Current Shift: {'DAY' if is_day_shift_now() else 'NIGHT'}\n"
        f"Day Shift: {DAY_SHIFT_START} - {DAY_SHIFT_END}"
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


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT user_id, username, full_name, day_name, night_name, role, last_seen
    FROM user_profiles
    ORDER BY last_seen DESC
    LIMIT 30
    """)
    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("No users saved yet.")
        return

    msg = "👥 SAVED USERS\n\n"

    for uid, username, full_name, day_name, night_name, role, last_seen in rows:
        msg += (
            f"ID: {uid}\n"
            f"Username: @{username if username else '-'}\n"
            f"TG Name: {full_name or '-'}\n"
            f"Day: {day_name or '-'}\n"
            f"Night: {night_name or '-'}\n"
            f"Role: {role or 'MEMBER'}\n"
            f"Seen: {last_seen or '-'}\n\n"
        )

    await update.message.reply_text(msg[:4000])


async def setuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage:\n"
            "/setuser USER_ID DAY_NAME NIGHT_NAME ROLE\n\n"
            "Example:\n"
            "/setuser 123456789 MONIR MEHEDI MEMBER\n\n"
            "যদি same person day/night হয়:\n"
            "/setuser 123456789 MONIR MONIR MEMBER"
        )
        return

    user_id = context.args[0]
    day_name = context.args[1]
    night_name = context.args[2]
    role = context.args[3]

    set_user_profile(user_id, day_name, night_name, role)

    await update.message.reply_text(
        f"✅ User profile saved\n\n"
        f"ID: {user_id}\n"
        f"Day: {day_name.upper()}\n"
        f"Night: {night_name.upper()}\n"
        f"Role: {role.upper()}"
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

    register_user(user)

    attacker = get_active_name_by_id(user.id, user)
    save_chat(chat.id, user.id, attacker, text)

    if repair_mode and not is_admin(user.id):
        return

    target = detect_target(update, text)

    if not target:
        return

    # If user replies only "chittar", target comes from replied message.
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
        BotCommand("users", "Admin only saved users"),
        BotCommand("setuser", "Admin set day/night user"),
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
    print("Shift:", DAY_SHIFT_START, "-", DAY_SHIFT_END)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on_cmd))
    app.add_handler(CommandHandler("repair_off", repair_off_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("setuser", setuser_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
