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
# FINAL AI ROAST BOT - FIXED DEBUG VERSION
# Works even without OpenAI key using local dynamic roast fallback.
# For group normal messages, BotFather privacy MUST be disabled.
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",") if x.strip().isdigit()}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("roast-bot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing. Add BOT_TOKEN in Railway Variables.")

DEFAULT_DATA = {
    "repair": False,
    "group_lock": False,
    "normal_reply": True,
    "allowed_groups": [],
    "memory": {},
    "users": {},
    "shifts": {},
}

def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("Could not load data file; using defaults")
    return json.loads(json.dumps(DEFAULT_DATA))

def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")

DATA = load_data()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def clean_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[@#:/\\|]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def display_name(user) -> str:
    name = " ".join([p for p in [user.first_name, user.last_name] if p]).strip()
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

def command_arg_text(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""

def strip_bot_mention(cmd: str) -> str:
    if "@" in cmd:
        return cmd.split("@", 1)[0]
    return cmd

def parse_target_reason(text: str):
    """Return (target, reason). Designed for text like: 'joni kaka faforbarj'."""
    raw = text.strip()
    low = clean_name(raw)
    if not low:
        return None, None

    # VS pattern
    if re.search(r"\bvs\b| বনাম | বনাম", low, re.I):
        return None, None

    # Known memory name first: longest match wins
    names = sorted(DATA.get("memory", {}).keys(), key=len, reverse=True)
    for name in names:
        if low == name or low.startswith(name + " "):
            reason = raw[len(name):].strip() if low.startswith(name + " ") else ""
            return name, reason

    words = raw.split()
    if len(words) == 1:
        return clean_name(words[0]), ""
    if len(words) == 2:
        return clean_name(words[0]), words[1]

    # Heuristic: target is first 1-2 words, reason is rest.
    family_words = {"kaka", "ভাই", "vai", "mama", "মামা", "চাচা", "bhai", "apu", "আপু"}
    if clean_name(words[1]) in family_words:
        target = " ".join(words[:2])
        reason = " ".join(words[2:])
    else:
        target = words[0]
        reason = " ".join(words[1:])
    return clean_name(target), reason.strip()

ROAST_BITS = [
    "কথা শুনলে মনে হয় গ্রুপের সিইও, কাজে গেলে নেটওয়ার্কের বাইরে।",
    "আওয়াজটা বড়, কিন্তু কাজের সময় ব্যাটারি লো।",
    "এত ফাপর মারে, মনে হয় নিজের কথাতেই নিজে VIP pass বানায়।",
    "confidence ফুল চার্জ, কিন্তু performance সবসময় power saving mode-এ।",
    "কথায় আগুন, কাজে ধোঁয়া—এই হলো আসল পরিচয়।",
    "গ্রুপে ঢুকে এমন ভাব নেয়, যেন সবাই তার screenshot নেওয়ার অপেক্ষায় আছে।",
    "ফাপর কমাক, আগে নিজের system update করুক।",
]

def local_dynamic_roast(target: str, reason: str, memory: str = "") -> str:
    reason_clean = reason.strip() or memory.strip() or "ফাপর"
    t = target.strip() or "এই জন"
    patterns = [
        f"{t} এমন {reason_clean}, {random.choice(ROAST_BITS)}",
        f"{t} আবার {reason_clean} mood চালু করছে—{random.choice(ROAST_BITS)}",
        f"{t}-এর {reason_clean} level এমন, {random.choice(ROAST_BITS)}",
        f"{t} শুধু {reason_clean} দেখায়; বাস্তবে {random.choice(ROAST_BITS)}",
    ]
    return random.choice(patterns)

async def ai_roast(target: str, reason: str, memory: str = "") -> str:
    if not OPENAI_API_KEY:
        return local_dynamic_roast(target, reason, memory)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""
তুমি একটি বাংলা roast bot।
নিয়ম:
- শুধু বাংলা ভাষায় লিখবে।
- ১-২ লাইনের বেশি না।
- কোনো explanation, memory dump, bullet, disclaimer না।
- target কে direct savage কিন্তু clean roast করবে।
- অশ্লীল/হুমকি/ঘৃণামূলক কথা নয়।
- একই reply বারবার দেবে না।

Target: {target}
Point/Reason: {reason or 'নেই'}
Memory context: {memory or 'নেই'}
""".strip()
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95,
            max_tokens=90,
        )
        out = (resp.choices[0].message.content or "").strip()
        if not out:
            return local_dynamic_roast(target, reason, memory)
        return out
    except Exception:
        log.exception("OpenAI failed; using local fallback")
        return local_dynamic_roast(target, reason, memory)

def should_ignore_group(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return True
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if DATA.get("group_lock"):
            return True
        allowed = DATA.get("allowed_groups") or []
        if allowed and str(chat.id) not in [str(x) for x in allowed]:
            return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    u = update.effective_user
    await update.message.reply_text(
        "🔥 Ultra Savage Roast Bot active.\n\n"
        f"তোমার Telegram ID: {u.id}\n"
        f"Detected name: {display_name(u)}\n\n"
        "Test:\n"
        "/ping\n"
        "/status\n"
        "joni kaka faforbarj\n"
        "joni vs mony\n\n"
        "যদি group normal message-এ reply না আসে: BotFather → /setprivacy → Disable"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive. Normal message পড়তে হলে privacy Disable থাকতে হবে।")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        "Commands\n"
        "/ping - bot alive check\n"
        "/status - settings check\n"
        "/repair_on /repair_off - admin only\n"
        "/lockgroup /unlockgroup - admin only\n"
        "/setgroup - current group allow, admin only\n"
        "/normal_on /normal_off - admin only\n"
        "/mem name text - memory save\n"
        "/memory name - memory show\n"
        "/forget name - memory delete, admin only\n"
        "/users - user list\n"
        "/roast name reason - direct roast\n"
        "/vs name1 name2 - VS roast\n"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    await update.message.reply_text(
        "📌 Status\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(OPENAI_API_KEY) else 'OFF - local fallback'}\n"
        f"Admins set: {len(ADMIN_IDS)}\n"
        f"Current chat id: {chat.id if chat else 'unknown'}\n"
        f"Allowed groups: {DATA.get('allowed_groups') or 'all'}"
    )

async def admin_bool(update: Update, key: str, value: bool, label: str):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    DATA[key] = value
    save_data()
    await update.message.reply_text(f"✅ {label} {'ON' if value else 'OFF'}")

async def repair_on(update, context): await admin_bool(update, "repair", True, "Repair mode")
async def repair_off(update, context): await admin_bool(update, "repair", False, "Repair mode")
async def lockgroup(update, context): await admin_bool(update, "group_lock", True, "Group lock")
async def unlockgroup(update, context): await admin_bool(update, "group_lock", False, "Group lock")
async def normal_on(update, context): await admin_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await admin_bool(update, "normal_reply", False, "Normal reply")

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    chat = update.effective_chat
    gid = str(chat.id)
    if gid not in DATA["allowed_groups"]:
        DATA["allowed_groups"].append(gid)
    save_data()
    await update.message.reply_text(f"✅ এই group allow করা হলো।\nGroup ID: {gid}")

async def mem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_arg_text(update.message.text)
    if not arg or len(arg.split()) < 2:
        await update.message.reply_text("Use: /mem name text")
        return
    name, info = arg.split(maxsplit=1)
    name = clean_name(name)
    DATA["memory"].setdefault(name, [])
    DATA["memory"][name].append(info.strip())
    DATA["memory"][name] = DATA["memory"][name][-20:]
    save_data()
    await update.message.reply_text(f"✅ Memory saved for {name}")

async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    name = clean_name(command_arg_text(update.message.text))
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    mems = DATA["memory"].get(name)
    if not mems:
        await update.message.reply_text(f"{name} এর জন্য memory নেই।")
        return
    await update.message.reply_text("\n".join([f"• {m}" for m in mems[-10:]]))

async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    name = clean_name(command_arg_text(update.message.text))
    if not name:
        await update.message.reply_text("Use: /forget name")
        return
    if name in DATA["memory"]:
        del DATA["memory"][name]
        save_data()
        await update.message.reply_text(f"✅ {name} এর memory delete করা হয়েছে।")
    else:
        await update.message.reply_text(f"{name} এর memory পাওয়া যায়নি।")

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not DATA["users"]:
        await update.message.reply_text("No users tracked yet.")
        return
    lines = ["👥 Users"]
    for u in list(DATA["users"].values())[-50:]:
        lines.append(f"• {u['name']} | {u['id']} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        return
    arg = command_arg_text(update.message.text)
    target, reason = parse_target_reason(arg)
    if not target:
        await update.message.reply_text("Use: /roast name reason")
        return
    memtxt = " | ".join(DATA["memory"].get(target, [])[-3:])
    reply = await ai_roast(target, reason, memtxt)
    await update.message.reply_text(reply)

async def vs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        return
    arg = command_arg_text(update.message.text)
    parts = re.split(r"\s+vs\s+|\s+বনাম\s+", arg, flags=re.I)
    if len(parts) < 2:
        await update.message.reply_text("Use: /vs name1 name2")
        return
    a, b = clean_name(parts[0]), clean_name(parts[1])
    prompt_reason = f"{a} আর {b} এর VS roast; দুইজনকেই ছোট করে পচাও"
    reply = await ai_roast(f"{a} বনাম {b}", prompt_reason, "")
    await update.message.reply_text(reply)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply") or should_ignore_group(update):
        return

    # Reply targeting: if user replies to someone with reason text
    if msg.reply_to_message and not msg.reply_to_message.from_user.is_bot:
        target = clean_name(display_name(msg.reply_to_message.from_user))
        reason = text
        memtxt = " | ".join(DATA["memory"].get(target, [])[-3:])
        reply = await ai_roast(target, reason, memtxt)
        await msg.reply_text(reply)
        return

    # VS auto
    if re.search(r"\bvs\b| বনাম ", clean_name(text), re.I):
        parts = re.split(r"\s+vs\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            a, b = clean_name(parts[0]), clean_name(parts[1])
            reply = await ai_roast(f"{a} বনাম {b}", f"{a} আর {b} কে compare করে clean savage roast", "")
            await msg.reply_text(reply)
            return

    target, reason = parse_target_reason(text)
    if not target:
        return

    # single-name only: roast only if memory exists
    if not reason:
        mems = DATA["memory"].get(target, [])
        if not mems:
            await msg.reply_text(f"{target} এর roast করার মতো তথ্য আমার কাছে নেই। আগে /mem {target} কিছু_তথ্য দাও।")
            return
        reply = await ai_roast(target, "", " | ".join(mems[-3:]))
        await msg.reply_text(reply)
        return

    # Save point into memory automatically, then roast
    DATA["memory"].setdefault(target, [])
    DATA["memory"][target].append(reason)
    DATA["memory"][target] = DATA["memory"][target][-20:]
    save_data()
    memtxt = " | ".join(DATA["memory"].get(target, [])[-3:])
    reply = await ai_roast(target, reason, memtxt)
    await msg.reply_text(reply)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Update caused error: %s", context.error)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("lockgroup", lockgroup))
    app.add_handler(CommandHandler("unlockgroup", unlockgroup))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("normal_on", normal_on))
    app.add_handler(CommandHandler("normal_off", normal_off))
    app.add_handler(CommandHandler("mem", mem))
    app.add_handler(CommandHandler("save", mem))
    app.add_handler(CommandHandler("memory", memory))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("delete", forget))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("roast", roast_cmd))
    app.add_handler(CommandHandler("vs", vs_cmd))

    # aliases with slash style from older versions
    app.add_handler(CommandHandler("repair", lambda u, c: repair_on(u, c) if "on" in command_arg_text(u.message.text).lower() else repair_off(u, c)))
    app.add_handler(CommandHandler("lock", lambda u, c: lockgroup(u, c) if "on" in command_arg_text(u.message.text).lower() else unlockgroup(u, c)))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log.info("Bot starting. Admins=%s OpenAI=%s", ADMIN_IDS, bool(OPENAI_API_KEY))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
