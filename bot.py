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

# =========================================================
# ALPHA ROAST BOT - AUTO FIX VERSION
# - Accepts ADMIN_IDS or ADMIN_USER_IDS
# - Accepts /repair_on, /repair_off, /repair on, /repair off
# - Works without OpenAI using savage local fallback
# - Group normal messages need BotFather privacy DISABLED
# =========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alpha-roast")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "alpha_roast_data.json"))

# Auto-detect admin env name
_admin_raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_USER_IDS") or os.getenv("ADMIN_ID") or ""
ADMIN_IDS = {int(x.strip()) for x in re.split(r"[,;\s]+", _admin_raw) if x.strip().isdigit()}

# Optional initial values from Railway variables
ENV_REPAIR = os.getenv("REPAIR_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
ENV_GROUP_LOCK = os.getenv("GROUP_LOCK", "").strip().lower() in {"1", "true", "yes", "on"}
ENV_NORMAL_REPLY = os.getenv("NORMAL_REPLY", "on").strip().lower() not in {"0", "false", "no", "off"}
ROAST_GROUP_ID = os.getenv("ROAST_GROUP_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

DEFAULT_DATA = {
    "repair": ENV_REPAIR,
    "group_lock": ENV_GROUP_LOCK,
    "normal_reply": ENV_NORMAL_REPLY,
    "allowed_groups": [ROAST_GROUP_ID] if ROAST_GROUP_ID else [],
    "memory": {},
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
            log.exception("Data load failed, using defaults")
    return json.loads(json.dumps(DEFAULT_DATA))

DATA = load_data()

def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")

def is_admin(user_id: int) -> bool:
    # If ADMIN_IDS missing, commands still reply with clear warning instead of silent fail
    return user_id in ADMIN_IDS

def display_name(user) -> str:
    if not user:
        return "unknown"
    name = " ".join([p for p in [user.first_name, user.last_name] if p]).strip()
    return name or user.username or str(user.id)

def clean_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[@#:/\\|]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def arg_text(text: str) -> str:
    return text.split(maxsplit=1)[1].strip() if text and len(text.split(maxsplit=1)) > 1 else ""

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

def parse_target_reason(text: str):
    raw = (text or "").strip()
    if not raw:
        return None, None
    low = clean_name(raw)

    # known memory longest match
    names = sorted(DATA.get("memory", {}).keys(), key=len, reverse=True)
    for name in names:
        if low == name or low.startswith(name + " "):
            reason = raw[len(name):].strip() if low.startswith(name + " ") else ""
            return name, reason

    words = raw.split()
    if len(words) == 1:
        return clean_name(words[0]), ""

    family_words = {"kaka", "ভাই", "vai", "bhai", "mama", "মামা", "চাচা", "apu", "আপু", "dada", "দাদা"}
    if len(words) >= 2 and clean_name(words[1]) in family_words:
        target = " ".join(words[:2])
        reason = " ".join(words[2:])
    else:
        target = words[0]
        reason = " ".join(words[1:])
    return clean_name(target), reason.strip()

SAVAGE_BITS = [
    "কথা শুনলে মনে হয় গ্রুপের মালিক, কাজে গেলে নিজের নামটাই pending থাকে।",
    "আওয়াজে VIP, কাজে free trial—দুই মিনিটেই মেয়াদ শেষ।",
    "এত ফাপর মারে, মনে হয় নিজের ছায়াকেও impress করতে চায়।",
    "confidence ফুল ভলিউমে, performance silent mode-এ।",
    "কথার আগুনে গ্রুপ গরম, কিন্তু কাজে গেলে নিজেরাই ধোঁয়া খুঁজে পায় না।",
    "ভাব এমন, যেন সবাই ওর update-এর জন্য notification on করে বসে আছে।",
    "ফাপর কমিয়ে আগে নিজের system reboot করুক, না হলে lag নিয়েই legend হবে।",
    "মুখে rocket speed, কাজে কচ্ছপও ওকে overtake করে।",
    "নিজেকে boss ভাবে, কিন্তু result দেখলে intern-ও resign দিয়ে পালায়।",
]

def local_roast(target: str, reason: str, memory: str = "") -> str:
    t = target.strip() or "এইজন"
    point = (reason or memory or "ফাপর").strip()
    point = re.sub(r"\s+", " ", point)
    templates = [
        f"{t} এমন {point}, {random.choice(SAVAGE_BITS)}",
        f"{t}-এর {point} level এত বেশি, {random.choice(SAVAGE_BITS)}",
        f"{t} আবার {point} mood নিয়ে হাজির—{random.choice(SAVAGE_BITS)}",
        f"{t} {point} দেখাতে গিয়ে নিজেই meme material হয়ে গেছে; {random.choice(SAVAGE_BITS)}",
        f"{t} আগে {point} কমাক, তারপর group-এ hero entry দিক—{random.choice(SAVAGE_BITS)}",
    ]
    return random.choice(templates)

async def ai_roast(target: str, reason: str, memory: str = "") -> str:
    if not OPENAI_API_KEY:
        return local_roast(target, reason, memory)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""
তুমি বাংলা savage roast bot।
নিয়ম:
- শুধু বাংলা ভাষা।
- ১-২ লাইনের punchy reply।
- explanation, bullet, memory dump না।
- clean কিন্তু ধারালো savage roast।
- হুমকি/ঘৃণা/অশ্লীলতা না।
- group/CEO/performance/network type modern slang ব্যবহার করতে পারো।
- আগের example থেকেও বেশি savage হবে।

Target: {target}
Point: {reason or 'নেই'}
Memory: {memory or 'নেই'}
""".strip()
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.05,
            max_tokens=100,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or local_roast(target, reason, memory)
    except Exception:
        log.exception("OpenAI failed, fallback used")
        return local_roast(target, reason, memory)

def group_allowed(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if DATA.get("group_lock"):
            return False
        allowed = [str(x) for x in DATA.get("allowed_groups", []) if str(x).strip()]
        if allowed and str(chat.id) not in allowed:
            return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    u = update.effective_user
    await update.message.reply_text(
        "🔥 Alpha Roast Bot active.\n\n"
        f"Your ID: {u.id}\n"
        f"Admin: {'YES' if is_admin(u.id) else 'NO'}\n"
        "Test: /ping /status\n"
        "Roast: joni kaka faforbarj\n"
        "VS: joni vs mony"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive. এই reply এলে code running আছে।")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(
        "📌 STATUS\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(OPENAI_API_KEY) else 'OFF / local savage fallback'}\n"
        f"Admin IDs found: {len(ADMIN_IDS)}\n"
        f"You are admin: {'YES' if is_admin(user.id) else 'NO'}\n"
        f"Your ID: {user.id}\n"
        f"Chat ID: {chat.id}\n"
        f"Allowed groups: {DATA.get('allowed_groups') or 'ALL'}"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/ping\n/status\n/help\n"
        "/repair_on /repair_off\n"
        "/repair on /repair off\n"
        "/normal_on /normal_off\n"
        "/lockgroup /unlockgroup\n"
        "/setgroup\n"
        "/mem name text\n/memory name\n/forget name\n"
        "/roast name reason\n/vs name1 name2"
    )

async def set_bool(update: Update, key: str, val: bool, label: str):
    remember_user(update)
    if not ADMIN_IDS:
        await update.message.reply_text("⚠️ ADMIN_IDS/ADMIN_USER_IDS Railway variable missing. আগে তোমার Telegram ID add করো।")
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(f"⛔ Admin only. তোমার ID: {update.effective_user.id}")
        return
    DATA[key] = val
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if val else 'OFF'}")

async def repair_on(update, context): await set_bool(update, "repair", True, "Repair mode")
async def repair_off(update, context): await set_bool(update, "repair", False, "Repair mode")
async def normal_on(update, context): await set_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await set_bool(update, "normal_reply", False, "Normal reply")
async def lockgroup(update, context): await set_bool(update, "group_lock", True, "Group lock")
async def unlockgroup(update, context): await set_bool(update, "group_lock", False, "Group lock")

async def repair_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = arg_text(update.message.text).lower()
    if "on" in a:
        await repair_on(update, context)
    elif "off" in a:
        await repair_off(update, context)
    else:
        await update.message.reply_text("Use: /repair on or /repair off")

async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = arg_text(update.message.text).lower()
    if "on" in a:
        await lockgroup(update, context)
    elif "off" in a:
        await unlockgroup(update, context)
    else:
        await update.message.reply_text("Use: /lock on or /lock off")

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not ADMIN_IDS:
        await update.message.reply_text("⚠️ ADMIN_IDS/ADMIN_USER_IDS missing.")
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(f"⛔ Admin only. তোমার ID: {update.effective_user.id}")
        return
    gid = str(update.effective_chat.id)
    if gid not in DATA["allowed_groups"]:
        DATA["allowed_groups"].append(gid)
    save_data()
    await update.message.reply_text(f"✅ Group allowed: {gid}")

async def mem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = arg_text(update.message.text)
    if len(arg.split()) < 2:
        await update.message.reply_text("Use: /mem name text")
        return
    name, info = arg.split(maxsplit=1)
    name = clean_name(name)
    DATA["memory"].setdefault(name, [])
    DATA["memory"][name].append(info.strip())
    DATA["memory"][name] = DATA["memory"][name][-30:]
    save_data()
    await update.message.reply_text(f"✅ Memory saved: {name}")

async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    name = clean_name(arg_text(update.message.text))
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    items = DATA["memory"].get(name, [])
    if not items:
        await update.message.reply_text(f"{name} এর memory নেই।")
        return
    await update.message.reply_text("\n".join(f"• {x}" for x in items[-10:]))

async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(f"⛔ Admin only. তোমার ID: {update.effective_user.id}")
        return
    name = clean_name(arg_text(update.message.text))
    if not name:
        await update.message.reply_text("Use: /forget name")
        return
    DATA["memory"].pop(name, None)
    save_data()
    await update.message.reply_text(f"✅ Deleted memory: {name}")

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    lines = ["👥 Users"]
    for u in list(DATA["users"].values())[-50:]:
        lines.append(f"• {u['name']} | {u['id']} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        await update.message.reply_text("🛠 Repair mode ON. /repair_off দাও।")
        return
    target, reason = parse_target_reason(arg_text(update.message.text))
    if not target:
        await update.message.reply_text("Use: /roast name reason")
        return
    memtxt = " | ".join(DATA["memory"].get(target, [])[-3:])
    await update.message.reply_text(await ai_roast(target, reason, memtxt))

async def vs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = arg_text(update.message.text)
    parts = re.split(r"\s+vs\s+|\s+বনাম\s+", arg, flags=re.I)
    if len(parts) < 2:
        await update.message.reply_text("Use: /vs name1 name2")
        return
    a, b = clean_name(parts[0]), clean_name(parts[1])
    await update.message.reply_text(await ai_roast(f"{a} বনাম {b}", "দুইজনকে compare করে savage roast", ""))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    text = (msg.text or "").strip()
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair"):
        return
    if not DATA.get("normal_reply"):
        return
    if not group_allowed(update):
        return

    # Reply targeting
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target = clean_name(display_name(msg.reply_to_message.from_user))
        reason = text
        await msg.reply_text(await ai_roast(target, reason, " | ".join(DATA["memory"].get(target, [])[-3:])))
        return

    # VS auto
    if re.search(r"\bvs\b|\s+বনাম\s+", text, flags=re.I):
        parts = re.split(r"\s+vs\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            a, b = clean_name(parts[0]), clean_name(parts[1])
            await msg.reply_text(await ai_roast(f"{a} বনাম {b}", "compare savage roast", ""))
            return

    target, reason = parse_target_reason(text)
    if not target:
        return

    if not reason:
        mems = DATA["memory"].get(target, [])
        if mems:
            await msg.reply_text(await ai_roast(target, "", " | ".join(mems[-3:])))
        else:
            await msg.reply_text(f"{target} এর roast করার মতো তথ্য নেই। /mem {target} কিছু_তথ্য দাও।")
        return

    DATA["memory"].setdefault(target, [])
    DATA["memory"][target].append(reason)
    DATA["memory"][target] = DATA["memory"][target][-30:]
    save_data()
    await msg.reply_text(await ai_roast(target, reason, " | ".join(DATA["memory"].get(target, [])[-3:])))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("BOT ERROR: %s", context.error)

def main():
    log.info("Starting bot | admins=%s | username=%s | openai=%s", ADMIN_IDS, BOT_USERNAME, bool(OPENAI_API_KEY))
    app = Application.builder().token(BOT_TOKEN).build()

    for cmd, fn in {
        "start": start, "ping": ping, "status": status, "help": help_cmd,
        "repair_on": repair_on, "repair_off": repair_off, "repair": repair_cmd,
        "normal_on": normal_on, "normal_off": normal_off,
        "lockgroup": lockgroup, "unlockgroup": unlockgroup, "lock": lock_cmd,
        "setgroup": setgroup, "mem": mem, "save": mem,
        "memory": memory, "forget": forget, "delete": forget,
        "users": users, "roast": roast_cmd, "vs": vs_cmd,
    }.items():
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
