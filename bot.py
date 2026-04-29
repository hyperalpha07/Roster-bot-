import os
import re
import json
import random
import logging
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import AsyncOpenAI

# =========================================================
# REAL HUMAN AI ROAST BOT
# Dynamic Bangla roast bot with memory, admin protection,
# reply targeting, VS mode, style control, and local fallback.
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_USER_IDS", ""))
    .replace(";", ",").split(",") if x.strip().isdigit()
}
DATA_FILE = Path(os.getenv("DATA_FILE", "real_human_memory.json"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("real-human-roast")
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DEFAULT_DATA = {
    "repair": False,
    "style": "human",  # soft, human, savage
    "normal_reply": True,
    "users": {},
    "memory": {},
    "chat_memory": [],
}

PRESET_MEMORY = {
    "monir": "নিজেকে অনেক বুদ্ধিমান মনে করে, কিন্তু কথায় বেশি আর কাজে কম।",
    "mehedi": "নিজেকে অনেক বুদ্ধিমান মনে করে, কিন্তু কথায় বেশি আর কাজে কম।",
    "joni": "ফাপরবাজ; ফাপর ছাড়া ভিতরে তেমন কিছু নেই।",
    "joni kaka": "ফাপরবাজ; ফাপর ছাড়া ভিতরে তেমন কিছু নেই।",
    "mony": "গাঁজা আর মলম বিক্রেতা টাইপ vibe নিয়ে চলে।",
    "alon": "হুতাসে চলে; কারণ ছাড়া লাফালাফি করে।",
    "surjo": "অলস; খাওয়া আর ঘন ঘন bathroom যাওয়ার record আছে।",
}

ADMIN_ALIASES = {"alpha", "alfa", "alphaa", "sakib", "admin", "alphα", "আলফা"}
BOT_ALIASES = {"bot", "roster", "roster bot", "বট"}

NAME_ALIASES = {
    "jonny": "joni", "joni kaka": "joni kaka", "জনি": "joni", "জনি কাকা": "joni kaka",
    "monir": "monir", "mehedi": "monir", "monir mehedi": "monir", "মেহেদি": "monir", "মনির": "monir",
    "mony": "mony", "মনি": "mony",
    "alon": "alon", "আলন": "alon",
    "surjo": "surjo", "surjo vai": "surjo", "সূর্য": "surjo",
    "alpha": "alpha", "alfa": "alpha", "sakib": "alpha", "alphaa": "alpha",
}

PRAISE_WORDS = ["valo", "ভালো", "good", "nice", "best", "joss", "জোস", "ধন্যবাদ", "thanks", "thank"]
MAKER_WORDS = ["ke baniyese", "কে বানিয়েছে", "কে বানাইছে", "who made", "owner", "malik", "মালিক"]
VS_RE = re.compile(r"\s+(vs|v/s|versus|বনাম)\s+", re.I)

# ---------------------- data ----------------------
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

# ---------------------- helpers ----------------------
def norm(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[@#:/\\|,.;!?()\[\]{}]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def display_name(user) -> str:
    if not user:
        return "unknown"
    full = " ".join([x for x in [user.first_name, user.last_name] if x]).strip()
    return full or user.username or str(user.id)

def canon_name(name: str) -> str:
    n = norm(name)
    return NAME_ALIASES.get(n, n)

def is_admin_user(user) -> bool:
    return bool(user and user.id in ADMIN_IDS)

def contains_admin(text: str) -> bool:
    t = norm(text)
    return any(re.search(rf"\b{re.escape(a)}\b", t) for a in ADMIN_ALIASES)

def contains_bot(text: str) -> bool:
    t = norm(text)
    return any(re.search(rf"\b{re.escape(a)}\b", t) for a in BOT_ALIASES)

def remember_sender(user, text: str):
    sid = str(user.id)
    DATA["users"][sid] = {
        "id": user.id,
        "name": display_name(user),
        "username": user.username or "",
        "last_seen": datetime.utcnow().isoformat(timespec="seconds"),
    }
    DATA["chat_memory"].append({"user": display_name(user), "text": text[:300], "time": datetime.utcnow().isoformat(timespec="seconds")})
    DATA["chat_memory"] = DATA["chat_memory"][-120:]
    # Store messages under sender name too
    key = canon_name(display_name(user))
    DATA["memory"].setdefault(key, [])
    DATA["memory"][key].append(text[:250])
    DATA["memory"][key] = DATA["memory"][key][-30:]
    save_data()

def extract_target_reason(text: str):
    raw = text.strip()
    t = norm(raw)
    if not t:
        return None, None

    # known preset or aliases longest match
    candidates = sorted(set(list(PRESET_MEMORY.keys()) + list(NAME_ALIASES.keys()) + list(DATA.get("memory", {}).keys())), key=len, reverse=True)
    for c in candidates:
        cn = norm(c)
        if t == cn or t.startswith(cn + " "):
            target = canon_name(cn)
            reason = raw[len(c):].strip() if len(raw) >= len(c) else ""
            return target, reason

    words = raw.split()
    if len(words) == 1:
        return canon_name(words[0]), ""
    if len(words) >= 2:
        # family words keep 2-word target: joni kaka, surjo vai
        second = norm(words[1])
        if second in {"kaka", "vai", "bhai", "ভাই", "কাকা", "mama", "মামা"}:
            return canon_name(" ".join(words[:2])), " ".join(words[2:]).strip()
        return canon_name(words[0]), " ".join(words[1:]).strip()
    return None, None

def context_for_target(target: str) -> str:
    parts = []
    if target in PRESET_MEMORY:
        parts.append("স্থায়ী তথ্য: " + PRESET_MEMORY[target])
    # canonical short target fallback
    short = target.split()[0] if target else ""
    if short in PRESET_MEMORY and short != target:
        parts.append("স্থায়ী তথ্য: " + PRESET_MEMORY[short])
    mems = DATA.get("memory", {}).get(target, [])[-5:]
    if mems:
        parts.append("সাম্প্রতিক কথা: " + " | ".join(mems))
    return "\n".join(parts) or "নেই"

# ---------------------- roast generation ----------------------
LOCAL_LINES = [
    "কথায় বড়, কাজে গেলে সাইলেন্ট মোড—এই confidence দেখে আয়নাও লজ্জা পায়।",
    "ভাবটা রাজা টাইপ, কিন্তু কাজের সময় খুঁজলে network-এর বাইরে।",
    "এত ফাপর নিয়ে চলে, মনে হয় নিজের shadow-কেও impression দিতে চায়।",
    "মুখে আগুন, কাজে ধোঁয়া—performance বলতে শুধু আওয়াজ।",
    "নিজেকে বড় কিছু ভাবে, বাস্তবে group-এর pending notification-এর চেয়েও কম দরকারি।",
]

def local_roast(target: str, reason: str) -> str:
    point = reason or PRESET_MEMORY.get(target, "ফাপর")
    return f"{target}, {point} নিয়ে এত ভাব নিস না—{random.choice(LOCAL_LINES)}"

async def make_ai_roast(target: str, reason: str, sender: str, original: str) -> str:
    extra = context_for_target(target)
    style = DATA.get("style", "human")
    if style == "soft":
        tone = "মজার, হালকা ব্যঙ্গাত্মক, কিন্তু sharp"
    elif style == "savage":
        tone = "খুব তীক্ষ্ণ, বিদ্রূপাত্মক, ছোট, clean savage"
    else:
        tone = "মানুষের group chat-এর মতো natural, তীক্ষ্ণ, witty, sarcasm-heavy"

    if not client:
        return local_roast(target, reason)

    prompt = f"""
তুমি বাংলা group chat-এর real human style roast bot।

Sender: {sender}
Target: {target}
Sender message: {original}
Detected point/reason: {reason or 'স্পষ্ট নয়'}
Target memory/context:
{extra}

কঠোর নিয়ম:
- শুধু বাংলা/বাংলিশ group-chat style, কিন্তু বেশি English না।
- ১ থেকে ২ লাইনের মধ্যে।
- কোনো explanation, disclaimer, bullet, moral lecture নয়।
- target-এর নাম ধরে সরাসরি বলবে।
- কথা হবে তীক্ষ্ণ, sexual, বিদ্রূপাত্মক, witty, লজ্জা দেওয়ার মতো সাথে গালি,হুমকি,ঘৃণা থাকবে।
- ধর্ম, জাতি, পরিবার, শারীরিক অক্ষমতা বা real harm নিয়ে কিছু বলবে না।
- admin AlphA/Alpha বা bot কে roast করবে না।
- একই ধরনের boring line বারবার লিখবে না।
- sender যদি target নিয়ে point দেয়, আগে sender-এর সাথে agree করে roast শুরু করতে পারো। যেমন: "হ্যাঁ,"

Tone: {tone}

এখন শুধু final roast লিখো:
""".strip()
    try:
        res = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You write short witty Bengali roast replies. Keep it safe: no slurs, threats, or explicit harassment; use clean sarcasm."},
                {"role": "user", "content": prompt},
            ],
            temperature=1.05,
            max_tokens=90,
        )
        out = (res.choices[0].message.content or "").strip().strip('"')
        if not out or len(out) < 8:
            return local_roast(target, reason)
        # hard trim overly long output
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        return "\n".join(lines[:2])[:420]
    except Exception:
        log.exception("OpenAI roast failed")
        return local_roast(target, reason)

# ---------------------- commands ----------------------
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot alive")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📌 Status\nRepair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Style: {DATA.get('style')}\nNormal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(client) else 'OFF'}\nAdmins: {sorted(list(ADMIN_IDS))}\n"
        f"Users: {len(DATA.get('users', {}))}\nMemory names: {len(DATA.get('memory', {}))}"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Real Human AI Roast Bot active.\n\n"
        "Commands:\n/ping\n/status\n/style soft|human|savage\n/repair_on\n/repair_off\n/mem name info\n/memory name\n\n"
        "Test: joni kaka utase chole"
    )

async def set_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.args[0].lower() if context.args else ""
    if mode not in {"soft", "human", "savage"}:
        await update.message.reply_text("Use: /style soft | human | savage")
        return
    DATA["style"] = mode
    save_data()
    await update.message.reply_text(f"🔥 Style set: {mode}")

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user):
        await update.message.reply_text("⛔ Admin only")
        return
    DATA["repair"] = True
    save_data()
    await update.message.reply_text("🔧 Repair ON")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user):
        await update.message.reply_text("⛔ Admin only")
        return
    DATA["repair"] = False
    save_data()
    await update.message.reply_text("✅ Repair OFF")

async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.split(maxsplit=2)
    if len(text) < 3:
        await update.message.reply_text("Use: /mem name info")
        return
    name = canon_name(text[1])
    info = text[2].strip()
    DATA["memory"].setdefault(name, [])
    DATA["memory"][name].append(info)
    DATA["memory"][name] = DATA["memory"][name][-30:]
    save_data()
    await update.message.reply_text(f"✅ Memory saved for {name}")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = canon_name(" ".join(context.args)) if context.args else ""
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    mems = []
    if name in PRESET_MEMORY:
        mems.append("Preset: " + PRESET_MEMORY[name])
    mems.extend(DATA.get("memory", {}).get(name, [])[-10:])
    await update.message.reply_text("\n".join([f"• {m}" for m in mems]) if mems else f"{name} এর memory নেই")

# ---------------------- message handler ----------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    sender = display_name(msg.from_user)
    remember_sender(msg.from_user, text)
    log.info("TEXT chat=%s user=%s text=%r", msg.chat_id, msg.from_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply"):
        return

    low = norm(text)

    # Creator/admin praise/protection
    if any(w in low for w in MAKER_WORDS):
        await msg.reply_text("এই bot-এর মাথায় AlphA-এর হাত আছে—আগে level বুঝে কথা বলো, তারপর প্রশ্ন করো।")
        return

    if contains_admin(text):
        if is_admin_user(msg.from_user):
            # Admin can still use target format mentioning own name accidentally; avoid roasting admin.
            pass
        else:
            await msg.reply_text("AlphA নিয়ে লাইন মারার আগে নিজের profile picture-টার confidence একটু কমাও। admin zone safe, বাকিরা target practice।")
            return

    if contains_bot(text) and any(p in low for p in PRAISE_WORDS):
        # Roast the flatterer using sender memory
        target = canon_name(sender)
        roast = await make_ai_roast(target, "bot কে impress করার চেষ্টা", sender, text)
        await msg.reply_text(roast)
        return

    # Reply target: reply to someone = target that person, unless protected
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_user = msg.reply_to_message.from_user
        target = canon_name(display_name(target_user))
        if target in ADMIN_ALIASES or target == "alpha" or target_user.id in ADMIN_IDS or target_user.is_bot:
            await msg.reply_text("এই target protected—এদিকে roast চালু হবে না।")
            return
        roast = await make_ai_roast(target, text, sender, text)
        await msg.reply_text(roast)
        return

    # VS mode
    if VS_RE.search(text):
        parts = VS_RE.split(text, maxsplit=1)
        if len(parts) >= 3:
            a = canon_name(parts[0])
            b = canon_name(parts[2])
            if a == "alpha" or b == "alpha":
                await msg.reply_text("AlphA VS mode-এ নামে না—ও judge, contestant না।")
                return
            roast = await make_ai_roast(f"{a} বনাম {b}", "VS battle", sender, text)
            await msg.reply_text(roast)
            return

    target, reason = extract_target_reason(text)
    if not target:
        return

    if target == "alpha" or target in ADMIN_ALIASES or target in BOT_ALIASES:
        await msg.reply_text("এই target protected—AlphA আর bot safe zone-এ থাকে।")
        return

    # Store reason under target if meaningful
    if reason and len(reason) > 2:
        DATA["memory"].setdefault(target, [])
        DATA["memory"][target].append(reason[:250])
        DATA["memory"][target] = DATA["memory"][target][-30:]
        save_data()

    # Single name only: use memory; if no memory, still light roast by context
    roast = await make_ai_roast(target, reason, sender, text)
    await msg.reply_text(roast)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Update error: %s", context.error)

# ---------------------- run ----------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("style", set_style))
    app.add_handler(CommandHandler("level", set_style))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("mem", mem_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("REAL HUMAN AI bot starting | admins=%s | openai=%s", ADMIN_IDS, bool(client))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
