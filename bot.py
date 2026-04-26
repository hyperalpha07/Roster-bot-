import os
import re
import json
import random
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import AsyncOpenAI

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_USER_IDS", ""))
    .replace(";", ",").split(",") if x.strip().isdigit()
}
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "insane_roast_memory.json"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY missing. Local fallback will be used.")

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("insane-roast-bot")

# ================== DEFAULT DATA ==================
DEFAULT_DATA = {
    "repair": False,
    "normal_reply": True,
    "group_lock": False,
    "style": "brutal",       # normal | savage | brutal | insane
    "auto_roast": True,
    "memory": {},
    "users": {},
}

PRESET_MEMORY = {
    "monir": "নিজেকে অনেক বুদ্ধিমান ভাবে, কিন্তু বাস্তবে কথার ভেতর ফাঁকা আওয়াজ বেশি।",
    "mehedi": "নিজেকে অনেক বুদ্ধিমান ভাবে, কিন্তু বাস্তবে কথার ভেতর ফাঁকা আওয়াজ বেশি।",
    "joni": "ফাপরবাজ; ফাপর ছাড়া ভেতরে বিশেষ কিছু নেই।",
    "joni kaka": "ফাপরবাজ; ফাপর ছাড়া ভেতরে বিশেষ কিছু নেই।",
    "mony": "গাঁজা আর মলম বিক্রেতা টাইপ চরিত্র।",
    "alon": "হুতাসে চলে, কারণ ছাড়া লাফালাফি করে।",
    "surjo": "অলস, খাওয়া আর ঘন ঘন বাথরুমে যাওয়ার কম্বো।",
}

PROTECTED_NAMES = {"alpha", "alfa", "alphaa", "sakib", "admin", "owner", "bot", "roster", "roster bot"}
ADMIN_PRAISE_TRIGGERS = ["ke baniyese", "কে বানিয়েছে", "কে বানাইছে", "creator", "owner", "admin ke", "alpha ke"]
PRAISE_TRIGGERS = ["valo", "ভালো", "good", "joss", "জোস", "nice", "best", "thanks", "thank you", "ধন্যবাদ"]
VS_RE = re.compile(r"\s+(vs|বনাম)\s+", re.I)

# ================== STORAGE ==================
def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("Memory load failed; using default")
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))

DATA = load_data()

def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")

# ================== HELPERS ==================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def clean_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[@#:/\\|_,.!?]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def display_name(user) -> str:
    if not user:
        return "unknown"
    name = " ".join([x for x in [user.first_name, user.last_name] if x]).strip()
    return name or user.username or str(user.id)

def remember_user(update: Update):
    u = update.effective_user
    if not u:
        return
    DATA["users"][str(u.id)] = {
        "id": u.id,
        "name": display_name(u),
        "username": u.username or "",
        "last_seen": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_data()

def command_args(text: str) -> str:
    p = text.split(maxsplit=1)
    return p[1].strip() if len(p) > 1 else ""

def protected(text_or_name: str) -> bool:
    t = clean_text(text_or_name)
    return any(x == t or x in t.split() for x in PROTECTED_NAMES)

def memory_for(name: str) -> str:
    n = clean_text(name)
    parts = []
    if n in PRESET_MEMORY:
        parts.append(PRESET_MEMORY[n])
    if n in DATA["memory"]:
        parts.extend(DATA["memory"][n][-5:])
    return " | ".join(parts)

def save_point(name: str, point: str):
    n = clean_text(name)
    point = (point or "").strip()
    if not n or not point or protected(n):
        return
    DATA["memory"].setdefault(n, [])
    if point not in DATA["memory"][n]:
        DATA["memory"][n].append(point)
    DATA["memory"][n] = DATA["memory"][n][-30:]
    save_data()

def detect_target_reason(text: str, reply_user=None):
    raw = text.strip()
    low = clean_text(raw)

    if reply_user:
        target = display_name(reply_user)
        return clean_text(target), raw

    # VS handled separately
    if VS_RE.search(raw):
        return None, None

    # Known longest memory/preset name first
    names = sorted(set(list(PRESET_MEMORY.keys()) + list(DATA["memory"].keys())), key=len, reverse=True)
    for name in names:
        if low == name or low.startswith(name + " "):
            rest = raw[len(name):].strip()
            return clean_text(name), rest

    words = raw.split()
    if not words:
        return None, None

    if len(words) == 1:
        return clean_text(words[0]), ""

    family = {"kaka", "ভাই", "vai", "bhai", "mama", "মামা", "apu", "আপু", "ভাইয়া"}
    if len(words) >= 2 and clean_text(words[1]) in family:
        target = " ".join(words[:2])
        reason = " ".join(words[2:])
    else:
        target = words[0]
        reason = " ".join(words[1:])
    return clean_text(target), reason.strip()

# ================== ROAST ENGINE ==================
FALLBACKS = [
    "{target} এমন {point}, কথা শুনলে নেতা লাগে—কাজের সময় খুঁজলে সিগন্যালও পায় না।",
    "{target}-এর {point} এমন লেভেলের, নিজের ছায়াও পাশে দাঁড়াতে লজ্জা পায়।",
    "{target} শুধু আওয়াজে বড়; কাজে গেলে পুরো সিস্টেম ‘পরে আসুন’ দেখায়।",
    "{target} নিজেকে ঝড় ভাবে, বাস্তবে ফ্যানের হাওয়াও না—শুধু শব্দ বেশি।",
    "{target} কথা বলে রাজা হয়ে, কিন্তু কাজে নামলে পাসওয়ার্ড ভুলে যাওয়া ইউজারের মতো।",
]

def local_roast(target: str, point: str) -> str:
    p = point or memory_for(target) or "ফাপর"
    return random.choice(FALLBACKS).format(target=target, point=p)

def tone_text(style: str) -> str:
    return {
        "normal": "হালকা খোঁচা, মজার ব্যঙ্গ",
        "savage": "তীক্ষ্ণ, আত্মবিশ্বাসী, কাটিং ব্যঙ্গ",
        "brutal": "খুব ধারালো, লজ্জায় চুপ করিয়ে দেওয়ার মতো, গালি/হুমকি/ঘৃণা থাকবে",
        "insane": "অতি তীক্ষ্ণ, স্মার্ট অপমানের মতো শোনাবে, কিন্তু গালি, হুমকি, ঘৃণ নিয়ে আক্রমণ হবে",
    }.get(style, "তীক্ষ্ণ ব্যঙ্গ")

async def ai_roast(target: str, message: str, extra: str, style: str = None) -> str:
    style = style or DATA.get("style", "brutal")
    if not client:
        return local_roast(target, message)

    prompt = f"""
তুমি বাংলা গ্রুপের witty roast bot।

Target: {target}
Current message/point: {message or 'নেই'}
Known memory: {extra or 'নেই'}
Style: {tone_text(style)}

কঠোর নিয়ম:
- সর্বোচ্চ ১-২ লাইন।
- pure বাংলা লিখবে; English শব্দ ব্যবহার করবে না, যদি না user message-এ থাকা নাম/শব্দ লাগে।
- কোনো ব্যাখ্যা, disclaimer, bullet, quote mark নয়।
- গালি, যৌন কথা, হুমকি, নিয়েও আক্রমণ হবে।
- আঘাত হবে আচরণ, ফাপর, অলসতা, overconfidence, কাজের অক্ষমতা—এই ধরনের বিষয়ে।
- target-এর memory/point ধরবে, random কথা বলবে না।
- শেষে শক্ত punchline থাকবে।
- Admin/AlphA/Bot সম্পর্কে খারাপ কিছু বলবে না।

এখন target কে উদ্দেশ্য করে roast দাও।
""".strip()
    try:
        res = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.05,
            max_tokens=85,
        )
        out = (res.choices[0].message.content or "").strip()
        if not out or len(out) < 10:
            return local_roast(target, message)
        return out
    except Exception:
        log.exception("OpenAI failed")
        return local_roast(target, message)

async def ai_vs(a: str, b: str) -> str:
    if not client:
        return f"{a} আর {b}—দুজনের ফাপর মিলে গ্রুপে শব্দ হয়, ফলাফল হয় শূন্য।"
    prompt = f"""
বাংলায় ১-২ লাইনের witty VS roast দাও।
নাম: {a} বনাম {b}
Memory A: {memory_for(a)}
Memory B: {memory_for(b)}
গালি/হুমকি/ঘৃণা নয়। ছোট, ধারালো, punchline সহ।
""".strip()
    try:
        res = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.1,
            max_tokens=90,
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return f"{a} আর {b}—একজন ফাপর চালায়, আরেকজন সেটাকে achievement ভাবে। গ্রুপের শান্তির আসল শত্রু দুজনই।"

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        "🔥 INSANE Roast Bot active\n"
        "Commands: /ping /status /style normal|savage|brutal|insane /repair_on /repair_off /mem name text /memory name /forget name /users"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        f"📌 Status\nRepair: {'ON' if DATA['repair'] else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA['normal_reply'] else 'OFF'}\n"
        f"Group lock: {'ON' if DATA['group_lock'] else 'OFF'}\n"
        f"Style: {DATA['style']}\n"
        f"OpenAI: {'ON' if bool(OPENAI_API_KEY) else 'OFF'}\n"
        f"Admins: {sorted(list(ADMIN_IDS)) or 'not set'}\n"
        f"Chat ID: {update.effective_chat.id}"
    )

async def style_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin style change করতে পারবে।")
        return
    arg = (context.args[0].lower() if context.args else "").strip()
    if arg not in {"normal", "savage", "brutal", "insane"}:
        await update.message.reply_text("Use: /style normal | savage | brutal | insane")
        return
    DATA["style"] = arg
    save_data()
    await update.message.reply_text(f"🔥 Style set: {arg.upper()}")

async def repair_on(update, context):
    remember_user(update)
    if is_admin(update.effective_user.id):
        DATA["repair"] = True; save_data(); await update.message.reply_text("🔧 Repair ON")

async def repair_off(update, context):
    remember_user(update)
    if is_admin(update.effective_user.id):
        DATA["repair"] = False; save_data(); await update.message.reply_text("✅ Repair OFF")

async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_args(update.message.text)
    if len(arg.split()) < 2:
        await update.message.reply_text("Use: /mem name text")
        return
    name, point = arg.split(maxsplit=1)
    save_point(name, point)
    await update.message.reply_text(f"✅ Memory saved for {clean_text(name)}")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    name = clean_text(command_args(update.message.text))
    txt = memory_for(name)
    await update.message.reply_text(txt if txt else f"{name} এর memory নেই।")

async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin delete করতে পারবে।")
        return
    name = clean_text(command_args(update.message.text))
    DATA["memory"].pop(name, None)
    save_data()
    await update.message.reply_text(f"✅ Deleted: {name}")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    lines = ["👥 Users"]
    for u in list(DATA["users"].values())[-40:]:
        lines.append(f"• {u['name']} | {u['id']} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))

# ================== MESSAGE HANDLER ==================
def should_ignore(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return True
    if DATA["repair"] or not DATA["normal_reply"]:
        return True
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and DATA["group_lock"]:
        return True
    return False

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    low = clean_text(text)
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if should_ignore(update):
        return

    # Creator/admin questions
    if any(t in low for t in ADMIN_PRAISE_TRIGGERS):
        await msg.reply_text("AlphA এই বটের মালিক—ওর সেটআপে কথা কম, কাজ বেশি। আগে লেভেল বুঝে কথা বলো।")
        return

    # Protect admin/bot
    if protected(low):
        await msg.reply_text("Admin আর bot নিয়ে ফাপর দিও না—এখানে target বদলাও, নইলে নিজের কথাতেই নিজে ধরা খাবে।")
        return

    # Praise / impress attempt => roast sender using memory
    if any(t in low for t in PRAISE_TRIGGERS):
        sender = clean_text(display_name(update.effective_user))
        extra = memory_for(sender)
        roast = await ai_roast(sender, "bot কে impress করার চেষ্টা করছে", extra, DATA["style"])
        await msg.reply_text(roast)
        return

    # VS mode
    if VS_RE.search(text):
        parts = VS_RE.split(text, maxsplit=1)
        if len(parts) >= 3:
            a, b = clean_text(parts[0]), clean_text(parts[2])
            if protected(a) or protected(b):
                await msg.reply_text("Admin/Bot VS হবে না—ওদের বাদ দিয়ে target দাও।")
                return
            await msg.reply_text(await ai_vs(a, b))
            return

    reply_user = None
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        reply_user = msg.reply_to_message.from_user

    target, reason = detect_target_reason(text, reply_user)
    if not target:
        return

    if protected(target):
        await msg.reply_text("Admin safe zone-এ আছে—নিজের লেভেলের কাউকে target করো।")
        return

    if reason:
        save_point(target, reason)

    extra = memory_for(target)
    if not reason and not extra:
        reason = "নিজেকে বেশি চালাক দেখানোর চেষ্টা"

    roast = await ai_roast(target, reason or text, extra, DATA["style"])
    await msg.reply_text(roast)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Update error: %s", context.error)

# ================== RUN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("style", style_cmd))
    app.add_handler(CommandHandler("level", style_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("mem", mem_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("INSANE bot starting | admins=%s | openai=%s", ADMIN_IDS, bool(OPENAI_API_KEY))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
