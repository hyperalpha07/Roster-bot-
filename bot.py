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
# ALPHA SMART SAVAGE ROAST BOT V3
# - Dynamic Bangla roast
# - Reply targeting
# - @username targeting
# - Name + point targeting: "joni kaka faforbarj"
# - Memory from users/messages
# - Works with or without OpenAI API key
# =========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("alpha-roast-v3")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").replace("@", "").strip().lower()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "alpha_roast_memory.json"))

# Accept both old and new env names
_admin_raw = (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_USER_IDS") or "").replace(";", ",")
ADMIN_IDS = {int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()}

# Env default states, can be changed by commands and saved in DATA
ENV_REPAIR = (os.getenv("REPAIR_MODE", "OFF").strip().upper() in {"ON", "TRUE", "1", "YES"})
ENV_GROUP_LOCK = (os.getenv("GROUP_LOCK", "OFF").strip().upper() in {"ON", "TRUE", "1", "YES"})
ENV_NORMAL_REPLY = not (os.getenv("NORMAL_REPLY", "ON").strip().upper() in {"OFF", "FALSE", "0", "NO"})
ROAST_GROUP_ID = (os.getenv("ROAST_GROUP_ID") or "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

DEFAULT_DATA = {
    "repair": ENV_REPAIR,
    "group_lock": ENV_GROUP_LOCK,
    "normal_reply": ENV_NORMAL_REPLY,
    "allowed_groups": [ROAST_GROUP_ID] if ROAST_GROUP_ID else [],
    "users": {},       # user_id -> profile + messages + points
    "names": {},       # alias/name/username -> user_id
    "target_memory": {}, # target text -> points
}


def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("Memory file corrupt; using defaults")
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))

DATA = load_data()


def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def clean(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\u200b\u200c\u200d]", "", s)
    s = re.sub(r"[@#:/\\|,.;!?]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def display_name(user) -> str:
    if not user:
        return "অজানা"
    name = " ".join([x for x in [user.first_name, user.last_name] if x]).strip()
    return name or (f"@{user.username}" if user.username else str(user.id))


def is_admin(uid: int) -> bool:
    # If ADMIN_IDS is empty, use Telegram group admin check only in admin commands where possible.
    return bool(uid in ADMIN_IDS)


def add_alias(alias: str, uid: int):
    a = clean(alias)
    if a:
        DATA["names"][a] = str(uid)


def remember_user(update: Update):
    u = update.effective_user
    msg = update.message
    if not u:
        return
    uid = str(u.id)
    profile = DATA["users"].setdefault(uid, {"id": u.id, "name": display_name(u), "username": u.username or "", "messages": [], "points": []})
    profile["name"] = display_name(u)
    profile["username"] = u.username or ""
    profile["last_seen"] = now()
    add_alias(profile["name"], u.id)
    if u.username:
        add_alias(u.username, u.id)
        add_alias("@" + u.username, u.id)
    # Track short first-name aliases too
    for part in profile["name"].split():
        if len(part) >= 3:
            add_alias(part, u.id)
    if msg and msg.text and not msg.text.startswith("/"):
        profile["messages"].append({"text": msg.text.strip(), "time": now()})
        profile["messages"] = profile["messages"][-60:]
    save_data()


def command_arg(text: str) -> str:
    return text.split(maxsplit=1)[1].strip() if text and len(text.split(maxsplit=1)) > 1 else ""


def group_allowed(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return True
    if DATA.get("group_lock"):
        return False
    allowed = [str(x) for x in DATA.get("allowed_groups", []) if str(x).strip()]
    if allowed and str(chat.id) not in allowed:
        return False
    return True


def add_target_memory(target: str, point: str):
    t = clean(target)
    p = (point or "").strip()
    if not t or not p:
        return
    DATA["target_memory"].setdefault(t, [])
    DATA["target_memory"][t].append(p)
    DATA["target_memory"][t] = DATA["target_memory"][t][-30:]
    save_data()


def get_target_memory(target: str, target_id: str | None = None) -> str:
    items = []
    t = clean(target)
    if t in DATA.get("target_memory", {}):
        items += DATA["target_memory"][t][-5:]
    if target_id and str(target_id) in DATA.get("users", {}):
        u = DATA["users"][str(target_id)]
        # use recent points and messages as hints, not dump
        items += [p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in u.get("points", [])[-3:]]
        items += [m.get("text", "") for m in u.get("messages", [])[-4:]]
    # Remove duplicates and too long lines
    out = []
    for x in items:
        x = re.sub(r"\s+", " ", str(x)).strip()
        if x and x not in out:
            out.append(x[:120])
    return " | ".join(out[-6:])


INSULT_HINTS = [
    "fafor", "fapor", "ফাপর", "ফাপরবাজ", "ফাফর", "faltu", "ফালতু", "boka", "বোকা", "gadha", "গাধা",
    "বাটপার", "batpar", "চালাক", "ভাব", "over", "ওভার", "নাটক", "lazy", "লেইজি", "ঢং", "ভাও", "লেভেল"
]
FAMILY_WORDS = {"kaka", "কাকা", "vai", "ভাই", "bhai", "mama", "মামা", "chacha", "চাচা", "apu", "আপু", "dada", "দাদা"}
STOP_WORDS = {"তুই", "তুমি", "তোর", "তোকে", "রে", "এই", "ওই", "ভাই", "কাকা"}


def detect_from_mention(text: str):
    # @username mention typed as text. Telegram cannot always resolve to user object.
    m = re.search(r"@([A-Za-z0-9_]{3,})", text or "")
    if not m:
        return None, None, text
    uname = m.group(1).lower()
    uid = DATA.get("names", {}).get(uname) or DATA.get("names", {}).get("@" + uname)
    target_name = "@" + uname
    if uid and uid in DATA.get("users", {}):
        target_name = DATA["users"][uid].get("name") or target_name
    reason = re.sub(r"@" + re.escape(uname), "", text, flags=re.I).strip()
    return target_name, uid, reason


def parse_target_reason(text: str):
    """Return target_name, target_id, reason. Handles @mention, reply handled outside."""
    raw = (text or "").strip()
    if not raw:
        return None, None, None

    # @username
    tn, tid, reason = detect_from_mention(raw)
    if tn:
        return tn, tid, reason

    low = clean(raw)

    # known alias/name longest match
    aliases = sorted(DATA.get("names", {}).keys(), key=len, reverse=True)
    for alias in aliases:
        if len(alias) < 3:
            continue
        if low == alias or low.startswith(alias + " "):
            uid = DATA["names"].get(alias)
            target_name = DATA.get("users", {}).get(str(uid), {}).get("name") or alias
            reason = raw[len(alias):].strip() if low.startswith(alias + " ") else ""
            return target_name, str(uid), reason

    # target_memory known target longest match
    targets = sorted(DATA.get("target_memory", {}).keys(), key=len, reverse=True)
    for t in targets:
        if low == t or low.startswith(t + " "):
            reason = raw[len(t):].strip() if low.startswith(t + " ") else ""
            return t, None, reason

    words = raw.split()
    if len(words) == 1:
        # only name/alias
        return clean(words[0]), DATA.get("names", {}).get(clean(words[0])), ""

    # Pattern: joni kaka faforbarj -> target first 2 words when second is family word
    if len(words) >= 3 and clean(words[1]) in FAMILY_WORDS:
        return clean(" ".join(words[:2])), DATA.get("names", {}).get(clean(words[0])), " ".join(words[2:]).strip()

    # If first token is common target-like name, target first word
    return clean(words[0]), DATA.get("names", {}).get(clean(words[0])), " ".join(words[1:]).strip()


def looks_like_roast_trigger(text: str, reason: str) -> bool:
    full = clean((text or "") + " " + (reason or ""))
    if any(x in full for x in INSULT_HINTS):
        return True
    # at least target + reason sentence
    return len((reason or "").split()) >= 1 and len((text or "").split()) >= 2


FALLBACK_OPENINGS = ["শোন", "ওহে", "এই যে", "দেখো"]
FALLBACK_PUNCH = [
    "কথা শুনলে মনে হয় পুরো গ্রুপের পরিচালক, কাজে গেলে সিগন্যালই পাওয়া যায় না।",
    "ফাপর এমন মারে, মনে হয় নিজের কথার জন্য আলাদা মাইক ভাড়া করেছে।",
    "আওয়াজে ঝড়, কাজে শূন্য—এই কম্বোটা সত্যিই বিরল।",
    "ভাবটা প্রিমিয়াম, কিন্তু কাজের সময় ফ্রি ট্রায়ালও চালু হয় না।",
    "নিজের লেভেল দেখার আগে এত ফাপর দিলে আয়নাও লজ্জা পায়।",
    "কথায় রাজা, কাজে লগইন পেজেই আটকে থাকা ইউজার।",
]


def fallback_roast(target: str, reason: str, memory: str = "") -> str:
    reason = (reason or "ফাপরবাজি").strip()
    t = target or "ভাই"
    style = random.choice([
        f"{random.choice(FALLBACK_OPENINGS)} {t}, {reason} নিয়ে এত ভাব নিও না—{random.choice(FALLBACK_PUNCH)}",
        f"{t}, তোমার {reason} দেখে মনে হয় তুমি নিজের গল্পের নায়ক; সমস্যা হলো গল্পটা কেউ সিরিয়াসলি নেয় না।",
        f"{t}, {reason} কমাও। {random.choice(FALLBACK_PUNCH)}",
        f"{random.choice(FALLBACK_OPENINGS)} {t}, {reason} দিয়ে গ্রুপ গরম করছো, কিন্তু নিজের পারফরম্যান্স এখনো ঠান্ডা চায়ের মতো।",
    ])
    return style


def sanitize_roast(text: str, target: str, reason: str, memory: str) -> str:
    out = (text or "").strip().strip('"')
    # Remove labels / explanations
    out = re.sub(r"^(রোস্ট|উত্তর|reply|roast)\s*[:：-]\s*", "", out, flags=re.I).strip()
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    out = "\n".join(lines[:3])
    # Too much English means fallback, but allow group/CEO/network/performance if user likes mixed examples
    if len(out) < 15:
        return fallback_roast(target, reason, memory)
    if len(out) > 380:
        out = out[:360].rsplit(" ", 1)[0] + "…"
    return out


async def ai_roast(target: str, reason: str, memory: str = "") -> str:
    if not OPENAI_API_KEY:
        return fallback_roast(target, reason, memory)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""
তুমি একটি বাংলা savage roast bot।
কাজ: target কে ১-২ লাইনে ধারালো, মজার, savage roast করবে।

Target: {target}
বর্তমান point/reason: {reason or 'নেই'}
পুরনো memory hint: {memory or 'নেই'}

কঠোর নিয়ম:
- কোনো explanation দেবে না।
- memory dump করবে না।
- ১-২ লাইনের বেশি না।
- punchline থাকবে।
- গালি, হুমকি, ধর্ম/জাতি/শরীর/পরিবার নিয়ে আক্রমণ নয়।
- কথার point ধরে roast করবে, generic reply নয়।
- একই style বারবার নয়।
- বাংলা প্রধান থাকবে; group, CEO, network, performance টাইপ অল্প English চলবে।
- target-এর নাম দিয়ে শুরু করবে।

ভালো style example:
"জনি কাকা এমন ফাপরবাজ, কথা শুনলে মনে হয় group-এর CEO, কিন্তু কাজের সময় network-এর বাইরে। ফাপর কমা, আগে নিজের performance দেখাও।"

এর থেকেও বেশি sharp কিন্তু clean করে এখন reply দাও।
""".strip()
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You generate short clean Bangla savage roasts. No explanations."},
                {"role": "user", "content": prompt},
            ],
            temperature=1.05,
            max_tokens=130,
        )
        return sanitize_roast(resp.choices[0].message.content, target, reason, memory)
    except Exception:
        log.exception("OpenAI failed")
        return fallback_roast(target, reason, memory)


async def is_chat_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    if is_admin(uid):
        return True
    try:
        member = await update.effective_chat.get_member(uid)
        return member.status in {"administrator", "creator"}
    except Exception:
        return False


# ================= COMMANDS =================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        "🔥 Alpha Smart Roast Bot active.\n\n"
        "Test:\n/ping\n/status\njoni kaka faforbarj\n@username ফাপরবাজ\nকারো message reply দিয়ে: ফাপরবাজ\n\n"
        "Group normal message ধরতে BotFather /setprivacy Disable থাকতে হবে।"
    )

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive. আমি message পাচ্ছি।")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    await update.message.reply_text(
        "📌 Status\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(OPENAI_API_KEY) else 'OFF - local fallback'}\n"
        f"Admins env: {len(ADMIN_IDS)}\n"
        f"Chat ID: {chat.id if chat else 'unknown'}\n"
        f"Allowed groups: {DATA.get('allowed_groups') or 'all'}\n"
        f"Users tracked: {len(DATA.get('users', {}))}"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands\n"
        "/ping\n/status\n/repair_on /repair_off\n/normal_on /normal_off\n/lockgroup /unlockgroup\n/setgroup\n/mem name point\n/memory name\n/forget name\n/users\n/roast name reason\n/vs name1 name2"
    )

async def set_bool(update: Update, key: str, value: bool, label: str):
    remember_user(update)
    if not await is_chat_admin(update):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    DATA[key] = value
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if value else 'OFF'}")

async def repair_on(update, context): await set_bool(update, "repair", True, "Repair mode")
async def repair_off(update, context): await set_bool(update, "repair", False, "Repair mode")
async def normal_on(update, context): await set_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await set_bool(update, "normal_reply", False, "Normal reply")
async def lockgroup(update, context): await set_bool(update, "group_lock", True, "Group lock")
async def unlockgroup(update, context): await set_bool(update, "group_lock", False, "Group lock")

async def setgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not await is_chat_admin(update):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    gid = str(update.effective_chat.id)
    if gid not in DATA["allowed_groups"]:
        DATA["allowed_groups"].append(gid)
    save_data()
    await update.message.reply_text(f"✅ এই group allow করা হলো।\nGroup ID: {gid}")

async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_arg(update.message.text)
    if not arg or len(arg.split()) < 2:
        await update.message.reply_text("Use: /mem name point")
        return
    name, point = arg.split(maxsplit=1)
    add_target_memory(name, point)
    await update.message.reply_text(f"✅ {name} এর memory save হয়েছে।")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    name = clean(command_arg(update.message.text))
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    mems = DATA["target_memory"].get(name, [])[-10:]
    if not mems:
        await update.message.reply_text(f"{name} এর memory নেই।")
        return
    await update.message.reply_text("\n".join([f"• {m}" for m in mems]))

async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not await is_chat_admin(update):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    name = clean(command_arg(update.message.text))
    if name in DATA["target_memory"]:
        del DATA["target_memory"][name]
        save_data()
        await update.message.reply_text(f"✅ {name} memory delete হয়েছে।")
    else:
        await update.message.reply_text("Memory পাওয়া যায়নি।")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    lines = ["👥 Users"]
    for uid, u in list(DATA.get("users", {}).items())[-60:]:
        lines.append(f"• {u.get('name')} | {uid} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        return
    arg = command_arg(update.message.text)
    target, tid, reason = parse_target_reason(arg)
    if not target:
        await update.message.reply_text("Use: /roast name reason")
        return
    add_target_memory(target, reason)
    reply = await ai_roast(target, reason, get_target_memory(target, tid))
    await update.message.reply_text("🔥 " + reply)

async def vs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_arg(update.message.text)
    parts = re.split(r"\s+vs\s+|\s+বনাম\s+", arg, flags=re.I)
    if len(parts) < 2:
        await update.message.reply_text("Use: /vs name1 name2")
        return
    a, b = clean(parts[0]), clean(parts[1])
    reply = await ai_roast(f"{a} বনাম {b}", f"{a} আর {b} কে compare করে savage roast", "")
    await update.message.reply_text("⚔️ " + reply)

# ================= MESSAGE HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply") or not group_allowed(update):
        return
    if text.startswith("/"):
        return

    # Bot/admin protection: don't roast bot itself
    bot_user = await context.bot.get_me()

    # Reply targeting always strongest
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target_user = msg.reply_to_message.from_user
        target = display_name(target_user)
        tid = str(target_user.id)
        reason = text
        add_target_memory(target, reason)
        reply = await ai_roast(target, reason, get_target_memory(target, tid))
        await msg.reply_text("🔥 " + reply)
        return

    if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == bot_user.id:
        await msg.reply_text("😏 আমাকে না, আগে target-এর নাম আর point দাও।")
        return

    # VS auto
    if re.search(r"\bvs\b|\s+বনাম\s+", text, flags=re.I):
        parts = re.split(r"\s+vs\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            a, b = clean(parts[0]), clean(parts[1])
            reply = await ai_roast(f"{a} বনাম {b}", f"{a} আর {b} কে compare করে savage roast", "")
            await msg.reply_text("⚔️ " + reply)
            return

    target, tid, reason = parse_target_reason(text)
    if not target:
        return

    # Prevent obvious bot targeting
    if BOT_USERNAME and clean(target) in {BOT_USERNAME, "@" + BOT_USERNAME, "bot", "বট"}:
        await msg.reply_text("😏 বটের দিকে ফাপর না মেরে target-এর নাম বলো।")
        return

    # Single-name only: roast only if memory exists
    if not reason:
        mem = get_target_memory(target, tid)
        if not mem:
            await msg.reply_text(f"{target} এর roast করার মতো তথ্য এখনো নেই। আগে বলো: {target} কী করছে?")
            return
        reply = await ai_roast(target, "আগের memory থেকে roast", mem)
        await msg.reply_text("🔥 " + reply)
        return

    # Must look like target + point
    if not looks_like_roast_trigger(text, reason):
        return

    add_target_memory(target, reason)
    reply = await ai_roast(target, reason, get_target_memory(target, tid))
    await msg.reply_text("🔥 " + reply)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Error while handling update: %s", context.error)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("normal_on", normal_on))
    app.add_handler(CommandHandler("normal_off", normal_off))
    app.add_handler(CommandHandler("lockgroup", lockgroup))
    app.add_handler(CommandHandler("unlockgroup", unlockgroup))
    app.add_handler(CommandHandler("setgroup", setgroup_cmd))
    app.add_handler(CommandHandler("mem", mem_cmd))
    app.add_handler(CommandHandler("save", mem_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))
    app.add_handler(CommandHandler("delete", forget_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("roast", roast_cmd))
    app.add_handler(CommandHandler("vs", vs_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("Starting Alpha Roast V3 | admins=%s | openai=%s | allowed_groups=%s", ADMIN_IDS, bool(OPENAI_API_KEY), DATA.get("allowed_groups"))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
