import os
import re
import json
import random
import logging
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# =========================================================
# ALPHA AI ROAST BOT - UPGRADE VERSION
# Dynamic AI roast, no fixed reply, sharp sarcastic Bangla roast.
# Works with local fallback if OpenAI fails.
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()

# Supports both variable names
_ADMIN_RAW = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_USER_IDS") or ""
ADMIN_IDS = {int(x.strip()) for x in _ADMIN_RAW.replace(";", ",").split(",") if x.strip().isdigit()}

DATA_FILE = Path(os.getenv("DATA_FILE", "alpha_roast_memory.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alpha-ai-roast")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

DEFAULT_DATA = {
    "repair": False,
    "normal_reply": True,
    "group_lock": False,
    "allowed_groups": [],
    "memory_by_name": {},
    "users": {},
}

def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("Memory file load failed, using default")
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))

DATA = load_data()

def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def clean_name(s: str) -> str:
    s = clean_text(s).lower()
    s = re.sub(r"^@", "", s)
    s = re.sub(r"[^a-zA-Z0-9অ-হঀ-৿_\s.-]", "", s)
    return clean_text(s)

def display_name(user) -> str:
    if not user:
        return "কেউ একজন"
    name = " ".join([x for x in [user.first_name, user.last_name] if x]).strip()
    return name or ("@" + user.username if user.username else str(user.id))

def remember_user(update: Update):
    u = update.effective_user
    if not u:
        return
    DATA["users"][str(u.id)] = {
        "id": u.id,
        "name": display_name(u),
        "username": u.username or "",
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_data()

def arg_text(message_text: str) -> str:
    parts = (message_text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""

def group_blocked(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return True
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if DATA.get("group_lock"):
            return True
        allowed = [str(x) for x in DATA.get("allowed_groups", [])]
        if allowed and str(chat.id) not in allowed:
            return True
    return False

FILLER_WORDS = {
    "ke", "k", "re", "রে", "রে।", "রে?", "রে!", "niye", "নিয়ে", "নিয়া", "নিয়া", "kisu", "kichu",
    "bolo", "bol", "বল", "বলো", "kor", "koro", "কর", "করো", "rost", "roast", "পচাও", "পচা",
    "এই", "ওই", "akta", "একটা", "ekta", "তো", "ta", "টা"
}

FAMILY_WORDS = {"kaka", "ভাই", "vai", "bhai", "mama", "মামা", "চাচা", "চাচু", "apu", "আপু", "দাদা"}

POINT_HINTS = [
    "fapor", "fafor", "faporbaj", "faforbaj", "ফাপর", "ফাপরবাজ", "ফাপরাবাজ",
    "bokachoda", "boka", "বোকা", "গাধা", "gadha", "faltu", "ফালতু", "ভুয়া", "vua",
    "baje", "বাজে", "লোভী", "লাজুক", "চুপ", "লেট", "ঘুম", "কাজ", "খায়", "খায়", "চলে"
]

def extract_target_reason(text: str):
    """Detect target and point from normal group text."""
    text = clean_text(text)
    if not text or text.startswith("/"):
        return None, None

    # VS auto pattern
    if re.search(r"\bvs\b|\bversus\b| বনাম ", text, re.I):
        return None, None

    # Known memory name longest match
    low = clean_name(text)
    for name in sorted(DATA.get("memory_by_name", {}).keys(), key=len, reverse=True):
        if low == name or low.startswith(name + " "):
            rest = text[len(name):].strip() if len(text) >= len(name) else ""
            return name, rest

    words = text.split()
    if len(words) < 2:
        return clean_name(words[0]) if words else None, ""

    # If second word is family relation, target = first 2 words
    if clean_name(words[1]) in FAMILY_WORDS:
        target = " ".join(words[:2])
        reason = " ".join(words[2:])
    else:
        target = words[0]
        reason = " ".join(words[1:])

    target = clean_name(target)
    reason = clean_text(reason)

    # Remove filler from reason beginning
    rw = reason.split()
    while rw and clean_name(rw[0]) in FILLER_WORDS:
        rw.pop(0)
    reason = " ".join(rw).strip()

    return target, reason

def should_roast_text(text: str, reason: str) -> bool:
    if not reason:
        return False
    low = clean_name(text + " " + reason)
    # Direct name + anything is allowed, but avoid very generic greetings
    greetings = {"hi", "hello", "হাই", "হ্যালো", "kemon aso", "কেমন আছো"}
    if low in greetings:
        return False
    if any(h in low for h in POINT_HINTS):
        return True
    # For phrase like "joni kaka ekdom ..." still roast if enough words
    return len(reason.split()) >= 1 and len(text.split()) >= 2

async def dynamic_ai_roast(target: str, point: str, context_memory: str = "") -> str:
    """Generate dynamic, non-fixed savage sarcastic roast."""
    if OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            prompt = f"""
তুমি একটি বাংলা গ্রুপের রোস্ট বট। তোমার কাজ হলো target-কে point ধরে ছোট, তীক্ষ্ণ, বিদ্রুপাত্মক roast করা।

কঠোর নিয়ম:
- কোনো নির্দিষ্ট/হার্ডকোডেড reply না; প্রতিবার নতুনভাবে বানাবে।
- ১ থেকে ২ লাইনের বেশি হবে না।
- বাংলা প্রধান ভাষা হবে; group, performance, network, CEO টাইপ কথাগুলো দরকার হলে ব্যবহার করা যাবে।
- অশ্লীল গালি, হুমকি, জাতি/ধর্ম/শরীর/পরিবার/রোগ নিয়ে আক্রমণ করবে না।
- explanation, bullet, memory dump, "কারণ" এসব লিখবে না।
- punchline ধারালো হবে।
- Target নাম অবশ্যই থাকবে।
- Point থেকে ছোট ছোট ব্যঙ্গাত্মক angle ধরবে।

Target: {target}
Point: {point or 'ফাপর/আওয়াজ বেশি'}
Previous context: {context_memory or 'নেই'}

এখন শুধু roast লিখো:
""".strip()
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You write sharp short Bangla sarcastic roasts only. No explanations."},
                    {"role": "user", "content": prompt},
                ],
                temperature=1.15,
                max_tokens=120,
            )
            out = (resp.choices[0].message.content or "").strip()
            out = re.sub(r"^[\"'“”]+|[\"'“”]+$", "", out).strip()
            if len(out) >= 10:
                return out
        except Exception:
            log.exception("OpenAI failed, using fallback")

    # local dynamic fallback, not one fixed reply
    punch = [
        "কথায় VIP, কাজে low battery mode।",
        "আওয়াজটা মাইকের মতো, কিন্তু কাজের বেলায় silent mode।",
        "নিজেকে main character ভাবে, বাস্তবে group-এর loading screen।",
        "confidence দেখে CEO লাগে, কাজ দেখলে intern-ও resign করে।",
        "ফাপর এমন level-এর, calculator দিয়েও হিসাব মেলে না।",
        "কথায় আগুন, কাজে শুধু ধোঁয়া।",
        "নিজের hype নিজেই দেয়, group শুধু evidence দেখে হাসে।",
        "performance এমন দুর্বল, screenshot নিলেও লজ্জা পায়।",
    ]
    starters = [
        f"{target} এমন {point or 'ফাপরবাজ'}, {random.choice(punch)}",
        f"{target}-এর {point or 'ফাপর'} দেখে মনে হয় বড় কিছু, কিন্তু {random.choice(punch)}",
        f"ওহে {target}, {point or 'ফাপর'} কমাও—{random.choice(punch)}",
        f"{target} আবার {point or 'ফাপর'} নিয়ে হাজির; {random.choice(punch)}",
    ]
    return random.choice(starters)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        "🔥 Alpha AI Roast Bot active.\n\n"
        "Test:\n"
        "/ping\n/status\n"
        "joni kaka faforbarj\n"
        "reply দিয়ে: ফাপরবাজ\n\n"
        "Group normal message ধরতে BotFather privacy Disable থাকতে হবে।"
    )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    await update.message.reply_text(
        "📌 Status\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"OpenAI: {'ON' if OPENAI_API_KEY else 'OFF fallback'}\n"
        f"Admins: {sorted(list(ADMIN_IDS)) or 'none'}\n"
        f"Chat ID: {chat.id if chat else 'unknown'}"
    )

async def set_bool(update: Update, key: str, value: bool, label: str):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে।")
        return
    DATA[key] = value
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if value else 'OFF'}")

async def repair_on(update, context): await set_bool(update, "repair", True, "Repair")
async def repair_off(update, context): await set_bool(update, "repair", False, "Repair")
async def normal_on(update, context): await set_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await set_bool(update, "normal_reply", False, "Normal reply")
async def lock_on(update, context): await set_bool(update, "group_lock", True, "Group lock")
async def lock_off(update, context): await set_bool(update, "group_lock", False, "Group lock")

async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    txt = arg_text(update.message.text)
    if len(txt.split()) < 2:
        await update.message.reply_text("Use: /mem name info")
        return
    parts = txt.split(maxsplit=1)
    name = clean_name(parts[0])
    info = parts[1].strip()
    DATA["memory_by_name"].setdefault(name, [])
    DATA["memory_by_name"][name].append(info)
    DATA["memory_by_name"][name] = DATA["memory_by_name"][name][-30:]
    save_data()
    await update.message.reply_text(f"✅ Memory saved for {name}")

async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে।")
        return
    name = clean_name(arg_text(update.message.text))
    if name in DATA["memory_by_name"]:
        del DATA["memory_by_name"][name]
        save_data()
        await update.message.reply_text(f"✅ {name} memory deleted")
    else:
        await update.message.reply_text("Memory পাওয়া যায়নি।")

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    txt = arg_text(update.message.text)
    target, reason = extract_target_reason(txt)
    if not target:
        await update.message.reply_text("Use: /roast name point")
        return
    mem = " | ".join(DATA["memory_by_name"].get(target, [])[-3:])
    await update.message.reply_text(await dynamic_ai_roast(target, reason, mem))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = clean_text(msg.text)
    log.info("MSG chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply") or group_blocked(update):
        return

    # protect bot mention direct attack with dynamic reply to sender
    if BOT_USERNAME and f"@{BOT_USERNAME}" in text.lower():
        target = display_name(update.effective_user)
        roast = await dynamic_ai_roast(target, "বটকে খোঁচাতে এসেছে", "")
        await msg.reply_text(roast)
        return

    # Reply targeting: target is replied user, point is current text
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target = clean_name(display_name(msg.reply_to_message.from_user))
        point = text
        DATA["memory_by_name"].setdefault(target, [])
        DATA["memory_by_name"][target].append(point)
        DATA["memory_by_name"][target] = DATA["memory_by_name"][target][-30:]
        save_data()
        mem = " | ".join(DATA["memory_by_name"].get(target, [])[-3:])
        await msg.reply_text(await dynamic_ai_roast(target, point, mem))
        return

    # VS detection
    if re.search(r"\bvs\b|\bversus\b| বনাম ", text, re.I):
        parts = re.split(r"\s+vs\s+|\s+versus\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            a, b = clean_name(parts[0]), clean_name(parts[1])
            await msg.reply_text(await dynamic_ai_roast(f"{a} বনাম {b}", "দুইজনের তুলনা করে savage roast", ""))
            return

    target, reason = extract_target_reason(text)
    if not target:
        return

    # Single name only: use memory only
    if not reason:
        mems = DATA["memory_by_name"].get(target, [])
        if not mems:
            return
        await msg.reply_text(await dynamic_ai_roast(target, "", " | ".join(mems[-3:])))
        return

    if not should_roast_text(text, reason):
        return

    DATA["memory_by_name"].setdefault(target, [])
    DATA["memory_by_name"][target].append(reason)
    DATA["memory_by_name"][target] = DATA["memory_by_name"][target][-30:]
    save_data()
    mem = " | ".join(DATA["memory_by_name"].get(target, [])[-3:])
    await msg.reply_text(await dynamic_ai_roast(target, reason, mem))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("BOT ERROR: %s", context.error)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("normal_on", normal_on))
    app.add_handler(CommandHandler("normal_off", normal_off))
    app.add_handler(CommandHandler("lock_on", lock_on))
    app.add_handler(CommandHandler("lock_off", lock_off))
    app.add_handler(CommandHandler("mem", mem_cmd))
    app.add_handler(CommandHandler("save", mem_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))
    app.add_handler(CommandHandler("delete", forget_cmd))
    app.add_handler(CommandHandler("roast", roast_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("Bot starting | OpenAI=%s | Admins=%s", bool(OPENAI_API_KEY), ADMIN_IDS)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
