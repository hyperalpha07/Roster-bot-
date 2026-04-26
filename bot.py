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

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

# =========================================================
# ALPHA ULTRA SMART AI ROAST BOT
# Dynamic AI roast + fallback. No fixed reply.
# Clean savage Bengali roast only. No slur/threat/hate.
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "roast_memory.json"))

# supports both ADMIN_IDS and ADMIN_USER_IDS
_admin_raw = (os.getenv("ADMIN_IDS", "") + "," + os.getenv("ADMIN_USER_IDS", "")).replace(";", ",")
ADMIN_IDS = {int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alpha-roast")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

DEFAULT_DATA = {
    "repair": False,
    "normal_reply": True,
    "group_lock": False,
    "allowed_groups": [],
    "users": {},
    "memory": {},
    "chat_messages": {},
    "roast_level": "brutal",  # light / savage / brutal
}


def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("memory load failed")
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")


DATA = load_data()
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if (AsyncOpenAI and OPENAI_API_KEY) else None

FAMILY_WORDS = {"kaka", "vai", "bhai", "mama", "apu", "dada", "ভাই", "কাকা", "মামা", "আপু", "দাদা", "চাচা"}
IGNORE_WORDS = {"hi", "hello", "ok", "okay", "hmm", "হাই", "হ্যালো", "ঠিক", "আচ্ছা"}


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def key_name(s: str) -> str:
    s = clean_text(s).lower()
    s = re.sub(r"[@#:/\\|,.;!?]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def display_name(user) -> str:
    if not user:
        return "ওইজন"
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
        "last_seen": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_data()


def store_chat_message(update: Update, text: str):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not text:
        return
    cid = str(chat.id)
    DATA["chat_messages"].setdefault(cid, [])
    DATA["chat_messages"][cid].append({
        "uid": user.id,
        "name": display_name(user),
        "text": text[:500],
        "time": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
    })
    DATA["chat_messages"][cid] = DATA["chat_messages"][cid][-120:]
    save_data()


def recent_context(chat_id: int, limit: int = 12) -> str:
    msgs = DATA.get("chat_messages", {}).get(str(chat_id), [])[-limit:]
    return "\n".join([f"{m['name']}: {m['text']}" for m in msgs])


def memory_for(name: str) -> str:
    mems = DATA.get("memory", {}).get(key_name(name), [])
    return " | ".join(mems[-5:]) if mems else ""


def save_point(name: str, point: str):
    n = key_name(name)
    p = clean_text(point)
    if not n or not p or len(p) < 2:
        return
    DATA["memory"].setdefault(n, [])
    DATA["memory"][n].append(p[:300])
    DATA["memory"][n] = DATA["memory"][n][-30:]
    save_data()


def command_arg(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def parse_target_reason(text: str):
    """Smart parse: joni kaka faforbarj -> target joni kaka, reason faforbarj"""
    raw = clean_text(text)
    if not raw:
        return None, None

    # Remove bot mention prefix if any
    raw = re.sub(rf"@{re.escape(BOT_USERNAME)}", "", raw, flags=re.I).strip() if BOT_USERNAME else raw
    words = raw.split()
    if not words:
        return None, None

    # Known memory names longest match
    low = key_name(raw)
    known = sorted(DATA.get("memory", {}).keys(), key=len, reverse=True)
    for name in known:
        if low == name:
            return name, ""
        if low.startswith(name + " "):
            reason = raw[len(name):].strip()
            return name, reason

    # VS no parse here
    if re.search(r"\bvs\b|\bversus\b| বনাম ", raw, re.I):
        return None, None

    # mentions like @user point
    if words[0].startswith("@") and len(words) >= 2:
        return words[0], " ".join(words[1:])

    # one-word only: memory roast if exists, otherwise ignore except command
    if len(words) == 1:
        return key_name(words[0]), ""

    # first two words as name if second is relationship word
    if len(words) >= 3 and key_name(words[1]) in FAMILY_WORDS:
        return " ".join(words[:2]), " ".join(words[2:])

    # If first word is common greeting, don't use it as target
    if key_name(words[0]) in IGNORE_WORDS:
        return None, None

    return words[0], " ".join(words[1:])


async def generate_roast(target: str, reason: str, attacker: str = "", ctx: str = "", mem: str = "") -> str:
    target = clean_text(target) or "ওইজন"
    reason = clean_text(reason) or "অযথা ফাপর"
    level = DATA.get("roast_level", "brutal")

    if client:
        prompt = f"""
তুমি একটি বাংলা গ্রুপের ultra savage roast bot।
তোমার কাজ: target কে খুব তীক্ষ্ণ, বিদ্রূপাত্মক, অপমানজনক কিন্তু clean roast করা।

কঠোর নিয়ম:
- শুধু বাংলা ভাষা; English শব্দ যত কম সম্ভব, দরকার হলে group/online টাইপ common শব্দ চলবে।
- ১ থেকে ৩ লাইনের বেশি নয়।
- কোনো explanation, analysis, memory dump, bullet point নয়।
- কোনো গালি, যৌন অপমান, পরিবার নিয়ে আক্রমণ, ধর্ম/জাতি/দেশ/লিঙ্গ/শারীরিক অক্ষমতা নিয়ে আক্রমণ নয়।
- সরাসরি target এর নাম ধরে বলবে।
- punchline ধারালো হবে; ভদ্র motivational কথা নয়।
- একই রকম fixed line লিখবে না; message-এর point থেকে নতুন roast বানাবে।
- target কে ছোট করে দেবে, কিন্তু হুমকি বা সহিংসতা নয়।

Roast intensity: {level}
Target: {target}
Attacker/Sender: {attacker or 'অজানা'}
Current point/reason: {reason}
Saved memory about target: {mem or 'নেই'}
Recent group context:
{ctx or 'নেই'}

এখন final roast দাও:
""".strip()
        try:
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "তুমি শুধু ছোট, ধারালো, clean বাংলা roast লিখবে।"},
                    {"role": "user", "content": prompt},
                ],
                temperature=1.05,
                max_tokens=140,
            )
            out = (resp.choices[0].message.content or "").strip()
            out = re.sub(r"^[\"'“”]+|[\"'“”]+$", "", out).strip()
            if 8 <= len(out) <= 600:
                return out
        except Exception:
            log.exception("OpenAI roast failed")

    # Local fallback still dynamic-ish
    bits = [
        "কথার জোরে পাহাড় সরায়, কাজে গেলে নিজের ছায়াও খুঁজে পায় না।",
        "এত ফাপর মারে যে নীরবতাও ওকে দেখে লজ্জা পায়।",
        "ভাব এমন, যেন গ্রুপটা ওর নামে চলে; বাস্তবে ওর কথাই সবচেয়ে কম দামে বিকায়।",
        "মুখে আগুন, কাজে ভেজা দিয়াশলাই।",
        "নিজেকে বড় চালাক ভাবে, কিন্তু কথার ফাঁকেই নিজের বোকামির বিজ্ঞাপন দিয়ে দেয়।",
        "ওর আত্মবিশ্বাস দেখে মনে হয় নেতা, ফলাফল দেখে মনে হয় ট্রায়াল ভার্সন।",
        "যে লেভেলের আওয়াজ করে, সেই লেভেলের কাজ থাকলে আজ কিংবদন্তি হয়ে যেত।",
    ]
    starts = ["শোন", "ওহে", "দেখ", "আবার শুরু হলো"]
    return f"{random.choice(starts)} {target}, {reason} নিয়ে এত ভাব দেখাস না—{random.choice(bits)}"


def group_blocked(update: Update) -> bool:
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
    await update.message.reply_text(
        "🔥 Alpha Ultra Smart Roast Bot active\n\n"
        "Test:\n/ping\n/status\njoni kaka faforbarj\nReply দিয়ে কারো point লিখো\n\n"
        "Group normal message ধরতে BotFather → /setprivacy → Disable"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    await update.message.reply_text(
        "📌 Status\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(client) else 'OFF fallback'}\n"
        f"Roast level: {DATA.get('roast_level')}\n"
        f"Admins: {sorted(list(ADMIN_IDS))}\n"
        f"Chat ID: {chat.id if chat else 'unknown'}"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands\n"
        "/ping\n/status\n/repair_on\n/repair_off\n/normal_on\n/normal_off\n"
        "/lockgroup\n/unlockgroup\n/setgroup\n"
        "/level light|savage|brutal\n"
        "/mem name info\n/memory name\n/forget name\n"
        "/roast name reason\n/vs name1 name2\n/users"
    )


async def set_bool(update, key, val, label):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে")
        return
    DATA[key] = val
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if val else 'OFF'}")


async def repair_on(update, context): await set_bool(update, "repair", True, "Repair")
async def repair_off(update, context): await set_bool(update, "repair", False, "Repair")
async def normal_on(update, context): await set_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await set_bool(update, "normal_reply", False, "Normal reply")
async def lockgroup(update, context): await set_bool(update, "group_lock", True, "Group lock")
async def unlockgroup(update, context): await set_bool(update, "group_lock", False, "Group lock")


async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে")
        return
    gid = str(update.effective_chat.id)
    if gid not in DATA["allowed_groups"]:
        DATA["allowed_groups"].append(gid)
    save_data()
    await update.message.reply_text(f"✅ Group allowed: {gid}")


async def level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে")
        return
    arg = key_name(command_arg(update.message.text))
    if arg not in {"light", "savage", "brutal"}:
        await update.message.reply_text("Use: /level light | savage | brutal")
        return
    DATA["roast_level"] = arg
    save_data()
    await update.message.reply_text(f"✅ Roast level set: {arg}")


async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_arg(update.message.text)
    if len(arg.split()) < 2:
        await update.message.reply_text("Use: /mem name info")
        return
    name, info = arg.split(maxsplit=1)
    save_point(name, info)
    await update.message.reply_text(f"✅ Memory saved for {name}")


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = key_name(command_arg(update.message.text))
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    mems = DATA.get("memory", {}).get(name, [])
    await update.message.reply_text("\n".join([f"• {m}" for m in mems[-10:]]) if mems else f"{name} এর memory নেই")


async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ শুধু admin করতে পারবে")
        return
    name = key_name(command_arg(update.message.text))
    if name in DATA.get("memory", {}):
        del DATA["memory"][name]
        save_data()
        await update.message.reply_text(f"✅ Deleted memory: {name}")
    else:
        await update.message.reply_text("Memory পাওয়া যায়নি")


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    lines = ["👥 Users"]
    for u in list(DATA.get("users", {}).values())[-50:]:
        lines.append(f"• {u['name']} | {u['id']} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))


async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        return
    arg = command_arg(update.message.text)
    target, reason = parse_target_reason(arg)
    if not target:
        await update.message.reply_text("Use: /roast name reason")
        return
    save_point(target, reason)
    out = await generate_roast(target, reason, display_name(update.effective_user), recent_context(update.effective_chat.id), memory_for(target))
    await update.message.reply_text(out)


async def vs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    arg = command_arg(update.message.text)
    parts = re.split(r"\s+vs\s+|\s+বনাম\s+", arg, flags=re.I)
    if len(parts) < 2:
        await update.message.reply_text("Use: /vs name1 name2")
        return
    target = f"{parts[0].strip()} বনাম {parts[1].strip()}"
    reason = "দুইজনকে তুলনা করে ধারালো বিদ্রূপাত্মক roast"
    out = await generate_roast(target, reason, display_name(update.effective_user), recent_context(update.effective_chat.id), "")
    await update.message.reply_text(out)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = clean_text(msg.text)
    store_chat_message(update, text)
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply") or group_blocked(update):
        return

    # protect bot messages and very short greetings
    if msg.from_user and msg.from_user.is_bot:
        return

    attacker = display_name(update.effective_user)
    ctx = recent_context(update.effective_chat.id)

    # reply targeting: target is replied user, reason is current text
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target = display_name(msg.reply_to_message.from_user)
        reason = text
        save_point(target, reason)
        out = await generate_roast(target, reason, attacker, ctx, memory_for(target))
        await msg.reply_text(out)
        return

    # VS auto
    if re.search(r"\bvs\b|\bversus\b| বনাম ", text, re.I):
        parts = re.split(r"\s+vs\s+|\s+versus\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            target = f"{parts[0].strip()} বনাম {parts[1].strip()}"
            out = await generate_roast(target, "দুইজনকে compare করে savage roast", attacker, ctx, "")
            await msg.reply_text(out)
            return

    target, reason = parse_target_reason(text)

    # If normal random chat like hello, do not roast unless group wants all messages.
    # But two+ word messages will roast using first word as target.
    if not target:
        return

    if not reason:
        mem = memory_for(target)
        if not mem:
            return
        out = await generate_roast(target, "আগের memory থেকে roast", attacker, ctx, mem)
        await msg.reply_text(out)
        return

    save_point(target, reason)
    out = await generate_roast(target, reason, attacker, ctx, memory_for(target))
    await msg.reply_text(out)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Telegram update error: %s", context.error)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [
        ("start", start), ("ping", ping), ("status", status), ("help", help_cmd),
        ("repair_on", repair_on), ("repair_off", repair_off),
        ("normal_on", normal_on), ("normal_off", normal_off),
        ("lockgroup", lockgroup), ("unlockgroup", unlockgroup), ("setgroup", setgroup),
        ("level", level), ("mem", mem_cmd), ("save", mem_cmd),
        ("memory", memory_cmd), ("forget", forget_cmd), ("delete", forget_cmd),
        ("users", users_cmd), ("roast", roast_cmd), ("vs", vs_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # old style aliases
    app.add_handler(CommandHandler("repair", lambda u, c: repair_on(u, c) if "on" in command_arg(u.message.text).lower() else repair_off(u, c)))
    app.add_handler(CommandHandler("lock", lambda u, c: lockgroup(u, c) if "on" in command_arg(u.message.text).lower() else unlockgroup(u, c)))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log.info("Bot starting | OpenAI=%s | Admins=%s", bool(client), ADMIN_IDS)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
