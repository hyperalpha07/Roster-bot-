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
DAY_SHIFT_START = os.getenv("DAY_SHIFT_START", "05:00").strip()
DAY_SHIFT_END = os.getenv("DAY_SHIFT_END", "17:20").strip()

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


def parse_hhmm(value):
    try:
        h, m = value.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 300


def is_day_shift_now():
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    start = parse_hhmm(DAY_SHIFT_START)
    end = parse_hhmm(DAY_SHIFT_END)
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end


def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"[@:।,!?]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value[:50].strip()


def raw_name(user):
    if user.username:
        return user.username.upper()
    return (user.full_name or str(user.id)).upper()


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

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
    CREATE TABLE IF NOT EXISTS roast_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        attacker TEXT,
        target TEXT,
        topic TEXT,
        message TEXT,
        reply TEXT,
        created_at TEXT
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
        UPDATE user_profiles SET username=?, full_name=?, last_seen=? WHERE user_id=?
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
        UPDATE user_profiles SET day_name=?, night_name=?, role=?, last_seen=? WHERE user_id=?
        """, (day_name.upper(), night_name.upper(), role.upper(), now_str(), str(user_id)))
    else:
        cur.execute("""
        INSERT INTO user_profiles(user_id,username,full_name,day_name,night_name,role,last_seen)
        VALUES(?,?,?,?,?,?,?)
        """, (str(user_id), "", "", day_name.upper(), night_name.upper(), role.upper(), now_str()))

    con.commit()
    con.close()


def get_profile_by_id(user_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT user_id,username,full_name,day_name,night_name,role,last_seen
    FROM user_profiles WHERE user_id=?
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


def active_name_by_id(user_id, fallback_user=None):
    profile = get_profile_by_id(user_id)

    if profile:
        if is_day_shift_now():
            name = profile["day_name"] or profile["full_name"] or profile["username"] or str(user_id)
        else:
            name = profile["night_name"] or profile["day_name"] or profile["full_name"] or profile["username"] or str(user_id)
        return clean_name(name).upper()

    if fallback_user:
        return raw_name(fallback_user)

    return str(user_id)


def is_protected_user(user_id):
    profile = get_profile_by_id(user_id)
    if is_admin(user_id):
        return True
    if profile and profile.get("role", "").upper() in ["ADMIN", "OWNER", "ALPHA"]:
        return True
    return False


def find_user_by_name_or_username(name):
    q = clean_name(name).lower()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT user_id, username, full_name, day_name, night_name, role
    FROM user_profiles
    """)
    rows = cur.fetchall()
    con.close()

    for uid, username, full_name, day_name, night_name, role in rows:
        candidates = [username, full_name, day_name, night_name]
        for c in candidates:
            if c and clean_name(c).lower() == q:
                return active_name_by_id(uid), str(uid), role or "MEMBER"

    return clean_name(name).upper(), None, "MEMBER"


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


def get_target_memory(target):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT note FROM person_memory
    WHERE target=?
    ORDER BY id DESC
    LIMIT 8
    """, (target.upper(),))
    rows = cur.fetchall()
    con.close()

    if not rows:
        return "এখনো কোনো পুরনো তথ্য নেই।"

    return " | ".join([r[0] for r in rows])


def save_roast(chat_id, attacker, target, topic, message, reply):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO roast_log(chat_id,attacker,target,topic,message,reply,created_at)
    VALUES(?,?,?,?,?,?,?)
    """, (str(chat_id), attacker, target, topic, message, reply, now_str()))
    con.commit()
    con.close()


def get_recent_roasts(target):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    SELECT topic,message,reply FROM roast_log
    WHERE target=?
    ORDER BY id DESC
    LIMIT 5
    """, (target.upper(),))
    rows = cur.fetchall()
    con.close()

    if not rows:
        return "আগের roast history নেই।"

    return " | ".join([f"{r[0]}: {r[1]}" for r in rows])


def detect_reply_target(update: Update):
    if not update.message or not update.message.reply_to_message:
        return None, None, "MEMBER"

    replied = update.message.reply_to_message.from_user
    if not replied:
        return None, None, "MEMBER"

    register_user(replied)

    if replied.is_bot:
        return "BOT", str(replied.id), "BOT"

    profile = get_profile_by_id(replied.id)
    role = profile["role"] if profile else "MEMBER"
    return active_name_by_id(replied.id, replied), str(replied.id), role


def detect_mention_target(text):
    mention = re.findall(r"@([A-Za-z0-9_]+)", text)
    if mention:
        return find_user_by_name_or_username(mention[0])
    return None, None, "MEMBER"


def detect_text_target(text):
    raw = text.strip()

    patterns = [
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:always|sob somoy|সবসময়|সব সময়)\s+(.+)$",
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:ke|কে)\s+(.+)$",
        r"^@?([A-Za-z0-9_\u0980-\u09FF\s]+?)\s+(?:chittar|chitar|cheater|চিটার|faforbaj|fapore|fapor|ফাপরবাজ|ফাপরে|lazy|লেজি|drama|নাটক|boka|বোকা|hutase|হুটাসে|hero|হিরো|attitude|faltu|ফালতু|bot|বট).*$",
    ]

    for p in patterns:
        m = re.search(p, raw, flags=re.IGNORECASE)
        if m:
            name = clean_name(m.group(1))
            if name:
                return find_user_by_name_or_username(name)

    words = raw.split()
    if len(words) >= 2:
        return find_user_by_name_or_username(words[0])

    return None, None, "MEMBER"


def text_attacks_bot(text):
    low = text.lower()
    bot_words = ["bot", "বট", "robot", "roster bot", "roast bot"]
    attack_words = ["faltu", "ফালতু", "bad", "baje", "বাজে", "vul", "ভুল", "bokachoda", "useless", "bekar", "বেকার"]
    return any(b in low for b in bot_words) and any(a in low for a in attack_words)


def detect_target(update: Update, text: str):
    attacker_id = str(update.effective_user.id)

    if text_attacks_bot(text):
        return active_name_by_id(attacker_id, update.effective_user), attacker_id, "SELF_ATTACK"

    reply_target, reply_uid, reply_role = detect_reply_target(update)
    if reply_target:
        if reply_role in ["BOT", "ADMIN", "OWNER", "ALPHA"] or (reply_uid and is_protected_user(reply_uid)):
            return active_name_by_id(attacker_id, update.effective_user), attacker_id, "SELF_ATTACK"
        return reply_target, reply_uid, reply_role

    mention_target, mention_uid, mention_role = detect_mention_target(text)
    if mention_target:
        if mention_role in ["ADMIN", "OWNER", "ALPHA"] or (mention_uid and is_protected_user(mention_uid)):
            return active_name_by_id(attacker_id, update.effective_user), attacker_id, "SELF_ATTACK"
        return mention_target, mention_uid, mention_role

    target, uid, role = detect_text_target(text)
    if target:
        if role in ["ADMIN", "OWNER", "ALPHA"] or (uid and is_protected_user(uid)):
            return active_name_by_id(attacker_id, update.effective_user), attacker_id, "SELF_ATTACK"
        return target, uid, role

    return None, None, "MEMBER"


def extract_memory_note(text, target):
    low = text.lower()
    note = text.strip()

    memory_words = [
        "always", "sob somoy", "সবসময়", "সব সময়",
        "faforbaj", "fapore", "fapor", "ফাপরবাজ", "ফাপরে",
        "chittar", "chitar", "cheater", "চিটার",
        "lazy", "লেজি", "drama", "নাটক",
        "boka", "বোকা", "hero", "হিরো", "attitude",
        "dhoka", "ধোঁকা", "faltu", "ফালতু"
    ]

    if any(w in low for w in memory_words):
        return note[:220]

    return None


def detect_topic_fallback(text):
    low = text.lower()
    if any(w in low for w in ["chittar", "chitar", "cheater", "চিটার", "dhoka", "ধোঁকা"]):
        return "চিটার/ধোঁকাবাজ"
    if any(w in low for w in ["faforbaj", "fapore", "fapor", "ফাপরবাজ", "ফাপরে"]):
        return "ফাপরবাজ"
    if any(w in low for w in ["lazy", "ghum", "ঘুম", "লেজি", "অলস"]):
        return "অলস"
    if any(w in low for w in ["drama", "natok", "নাটক"]):
        return "নাটকবাজ"
    if any(w in low for w in ["boka", "বোকা", "gada", "গাধা"]):
        return "বোকামি"
    if any(w in low for w in ["hero", "হিরো", "attitude", "smart"]):
        return "বেশি ভাব"
    if text_attacks_bot(text):
        return "বটকে খোঁচা দেওয়া"
    return "সাধারণ roast"


def detect_topic_ai(text):
    if not client:
        return detect_topic_fallback(text)

    prompt = f"""
এই কথাটায় target-কে কোন কারণে roast করা হচ্ছে?
কথা: {text}

শুধু ১-৪ শব্দের পরিষ্কার বাংলা topic লিখো।
যেমন: চিটার, ফাপরবাজ, অলস, নাটকবাজ, বেশি ভাব, বোকামি, বটকে খোঁচা।
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=20,
        )
        topic = res.choices[0].message.content.strip()
        topic = re.sub(r"[^\u0980-\u09FF\s]", "", topic).strip()
        return topic or detect_topic_fallback(text)
    except Exception:
        return detect_topic_fallback(text)


def is_clean_bangla(text):
    low = text.lower()
    banned_fragments = [
        "apni", "aap", "nahi", "jaisa", "maje", "bahut", "kya", "kaise",
        "circus", "joker", "reply:", "analysis", "json", "memory", "as an ai"
    ]
    if any(x in low for x in banned_fragments):
        return False
    latin_count = len(re.findall(r"[A-Za-z]", text))
    bangla_count = len(re.findall(r"[\u0980-\u09FF]", text))
    if bangla_count < 8:
        return False
    if latin_count > 20:
        return False
    return True


def fallback_roast(target, topic, attacker):
    base = [
        f"{target} আজ এমনভাবে ধরা খাইছে, গ্রুপের বিনোদন নিজে থেকেই চালু হয়ে গেছে 😭😂",
        f"{target}, তোমার আত্মবিশ্বাস দেখে ভালো লাগে, কিন্তু যুক্তি দেখে মনে হয় নেটওয়ার্ক নেই 🤣",
        f"{target} কে roast করতে আলাদা কষ্ট লাগে না, ও নিজেই কনটেন্ট দিয়ে দেয় 😭😂",
        f"{target} আবার হিরো মোডে? আগে নিজের সফটওয়্যারটা আপডেট দাও ভাই 🤣",
    ]

    if "চিটার" in topic or "ধোঁকা" in topic:
        base += [
            f"{target} এমন চিটার, নিজের ছায়াও ওকে বিশ্বাস করার আগে দুইবার ভাবে 😭😂",
            f"{target} এর সততা খুঁজতে গেলে মানচিত্রও পথ হারিয়ে ফেলে 🤣",
        ]

    if "ফাপর" in topic or "ভাব" in topic:
        base += [
            f"{target} এমন ফাপর মারে, বাতাসও ওর কাছ থেকে attitude শিখে 😭😂",
            f"{target} এর ফাপর দেখে গ্রুপের WiFi signal-ও লজ্জা পায় 🤣",
        ]

    if "অলস" in topic:
        base += [
            f"{target} এত অলস, ঘুম থেকেও বিরতি নিতে চায় 😭😂",
            f"{target} কাজ শুরু করার আগেই ক্লান্ত হয়ে যায়, pure talent 🤣",
        ]

    if "নাটক" in topic:
        base += [
            f"{target} নাটক করলে সিরিয়ালের director-রাও খাতা বের করে 😭😂",
            f"{target} এর জীবন না, পুরো season with bonus episode 🤣",
        ]

    if "বট" in topic:
        base += [
            f"{target} বটকে ফালতু বলার আগে নিজের কথাগুলো update দাও, reply-তেই lag ধরেছে 🤣",
            f"{target} বটকে roast করতে এসে নিজেই demo version হয়ে গেল 😭😂",
        ]

    return random.choice(base)


def ai_roast(target, topic, attacker, original_text):
    memory_note = get_target_memory(target)
    history = get_recent_roasts(target)

    if not client:
        return fallback_roast(target, topic, attacker)

    prompt = f"""
তুমি Telegram বন্ধুর গ্রুপের বাংলা roast bot।

Target: {target}
যে roast শুরু করেছে: {attacker}
Roast topic: {topic}
User message: {original_text}
Target সম্পর্কে পুরনো তথ্য: {memory_note}
আগের roast history: {history}

কাজ:
Target-কে topic অনুযায়ী খুব savage, sharp, funny ভাবে roast করো।

কঠোর নিয়ম:
১. শুধু বাংলা ভাষায় উত্তর দিবে।
২. Hindi, Urdu, English sentence, Banglish sentence ব্যবহার করবে না।
৩. ১-২ লাইনের বেশি না।
৪. Reply শুধু roast হবে, অন্য কোনো ব্যাখ্যা না।
৫. “আমি”, “AI”, “memory”, “rules”, “analysis” এসব লিখবে না।
৬. ধর্ম, জাতি, শরীর, পরিবার, অসুস্থতা, মৃত্যু, যৌন বিষয় নিয়ে আক্রমণ করবে না।
৭. অশ্লীল গালি ব্যবহার করবে না।
৮. Target নাম অবশ্যই reply-তে থাকবে।
৯. Bot/admin কে কেউ খোঁচা দিলে target হলো সেই খোঁচা দেওয়া লোক।

শুধু final roast reply লিখো।
"""

    for _ in range(2):
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "তুমি শুধু পরিষ্কার বাংলা ভাষায় মজার savage roast লিখবে। Hindi/English/Banglish নিষিদ্ধ।",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1.05,
                max_tokens=170,
            )

            text = res.choices[0].message.content.strip()
            text = text.replace("```", "").strip()
            text = re.sub(r"\s+", " ", text).strip()

            if is_clean_bangla(text):
                return text[:420]

        except Exception:
            print(traceback.format_exc())

    return fallback_roast(target, topic, attacker)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "🔥 Ultra Savage Roast Bot active.\n\n"
        f"তোমার Telegram ID: {update.effective_user.id}\n"
        f"Detected name: {active_name_by_id(update.effective_user.id, update.effective_user)}\n\n"
        "Example:\n"
        "joni always faforbaj\n"
        "surjo sobar taka khai\n"
        "কারো message reply দিয়ে: chittar\n\n"
        "Admin:\n"
        "/status\n/users\n/setuser USER_ID DAY_NAME NIGHT_NAME ROLE\n/memory\n/forget NAME"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🔥 ROAST BOT STATUS\n\n"
        f"Repair Mode: {'ON 🔧' if repair_mode else 'OFF ✅'}\n"
        f"OpenAI: {'ON 🤖' if OPENAI_API_KEY else 'OFF'}\n"
        f"Group Lock: {ROAST_GROUP_ID or 'OFF'}\n"
        f"Mode: ULTRA SAVAGE BANGLA ONLY\n"
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
    LIMIT 40
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
            "Usage:\n/setuser USER_ID DAY_NAME NIGHT_NAME ROLE\n\n"
            "Example:\n/setuser 123456789 MONIR MEHEDI MEMBER"
        )
        return

    user_id = context.args[0]
    day_name = context.args[1]
    night_name = context.args[2]
    role = context.args[3]

    set_user_profile(user_id, day_name, night_name, role)

    await update.message.reply_text(
        f"✅ Saved\nID: {user_id}\nDay: {day_name.upper()}\nNight: {night_name.upper()}\nRole: {role.upper()}"
    )


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    SELECT target,note,created_by,created_at FROM person_memory
    ORDER BY id DESC LIMIT 20
    """)
    mem = cur.fetchall()

    cur.execute("""
    SELECT attacker,target,topic,message,reply,created_at FROM roast_log
    ORDER BY id DESC LIMIT 10
    """)
    logs = cur.fetchall()

    con.close()

    msg = "🧠 ROAST MEMORY\n\n"

    if mem:
        msg += "📌 Person Memory:\n"
        for target, note, by, at in mem:
            msg += f"• {target}: {note}\n  by {by} | {at}\n"

    if logs:
        msg += "\n🔥 Recent Roasts:\n"
        for attacker, target, topic, message, reply, at in logs:
            msg += f"• {attacker} → {target} | {topic}\n  {message}\n  {reply}\n  {at}\n"

    if not mem and not logs:
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
    cur.execute("DELETE FROM roast_log WHERE target=?", (target,))
    con.commit()
    con.close()

    await update.message.reply_text(f"🗑 {target} এর memory delete করা হয়েছে।")


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

    attacker = active_name_by_id(user.id, user)

    if repair_mode and not is_admin(user.id):
        return

    target, target_uid, role = detect_target(update, text)

    if not target:
        return

    topic = detect_topic_ai(text)
    memory_note = extract_memory_note(text, target)

    if memory_note:
        save_person_memory(target, memory_note, attacker)

    reply = ai_roast(target, topic, attacker, text)
    save_roast(chat.id, attacker, target, topic, text, reply)

    await update.message.reply_text(reply)


async def post_init(application: Application):
    commands = [
        BotCommand("start", "Start roast bot"),
        BotCommand("status", "Admin status"),
        BotCommand("repair_on", "Admin repair ON"),
        BotCommand("repair_off", "Admin repair OFF"),
        BotCommand("users", "Admin users"),
        BotCommand("setuser", "Admin set user"),
        BotCommand("memory", "Admin memory"),
        BotCommand("forget", "Admin forget memory"),
    ]
    await application.bot.set_my_commands(commands)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    init_db()

    print("Ultra Savage Bangla Roast Bot running...")
    print("OpenAI:", "ON" if OPENAI_API_KEY else "OFF")
    print("Group Lock:", ROAST_GROUP_ID or "OFF")

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
