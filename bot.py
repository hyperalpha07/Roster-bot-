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
# ALPHA FINAL SAVAGE ROAST BOT
# Dynamic Bangla roast + memory + admin controls
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",")
    if x.strip().isdigit()
}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
TZ = ZoneInfo(os.getenv("TZ", "Asia/Colombo"))
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("alpha-roast-bot")

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

BANGLA_HINT_WORDS = [
    "ফাপর", "ফাপরবাজ", "বাজ", "খায়", "চোর", "আলস", "ঢং", "নাটক", "ভাব",
    "লেভেল", "নোবেল", "বড়াই", "বড়াই", "চাল", "ফালতু", "পাত্তা", "বেহুদা",
    "fafor", "faforbarj", "fapor", "faporbaj", "faporbaz", "chapabaj",
    "borai", "dhong", "natok", "chillai", "faltu", "boka", "lazy", "over"
]

NORMAL_WORDS = {
    "hi", "hello", "হাই", "হ্যালো", "kemon aso", "ki obosta", "ok", "okay",
    "thanks", "thank you", "ধন্যবাদ", "assalamu alaikum", "আসসালামু আলাইকুম"
}

PROTECTED_NAMES = {"bot", "roster bot", "roster_you_bot", "admin", "alpha"}

LOCAL_PUNCHES = [
    "কথা শুনলে মনে হয় গ্রুপের সিইও, কিন্তু কাজের সময় খুঁজলে নেটওয়ার্কের বাইরে।",
    "আওয়াজে আগুন, কাজে পানি—পুরো low battery performance।",
    "confidence এমন, যেন নিজের নামে fan club আছে; reality তে কাজের বেলায় loading screen।",
    "ফাপরটা premium, কিন্তু result এমন সস্তা যে calculator-ও হিসাব নিতে লজ্জা পায়।",
    "গ্রুপে ঢুকে এমন ভাব নেয়, যেন সবাই তার screenshot নেওয়ার অপেক্ষায় আছে।",
    "কথায় champion, কাজে trial version—এটাই আসল পরিচয়।",
    "মুখে rocket speed, কাজে 2G internet—এত lag নিয়ে আবার attitude!",
    "ভাবটা VIP lounge, কাজের মান broken chair—নিজেকে আগে update করুক।",
    "মুখে leadership, কাজে internship-ও পাস করবে কিনা সন্দেহ।",
    "ফাপর কমাক, আগে নিজের performance-এর funeral বন্ধ করুক।",
    "কথায় এত গরম, কিন্তু কাজে এমন ঠান্ডা যে fridge-ও respect দিয়ে পাশে বসে।",
    "নিজেকে boss ভাবে, কিন্তু বাস্তবে group-এর background noise ছাড়া কিছু না।",
    "এত বড়াই করে, মনে হয় Nobel নিতে যাচ্ছে; শেষে দেখা যায় attendance-ই ঠিক নাই।",
    "কথা বলে high level, কাজ করলে দেখা যায় system error।",
    "মুখে hero entry, কাজে side character-এরও নিচে rank।",
]

REASON_MAP = {
    "fafor": "ফাপরবাজ",
    "fapor": "ফাপরবাজ",
    "faforbarj": "ফাপরবাজ",
    "faporbaj": "ফাপরবাজ",
    "faporbaz": "ফাপরবাজ",
    "chapabaj": "চাপাবাজ",
    "borai": "বড়াইবাজ",
    "dhong": "ঢংবাজ",
    "natok": "নাটকবাজ",
    "lazy": "আলসেমির দোকান",
    "faltu": "ফালতু চালের মানুষ",
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


DATA = load_data()


def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[@#:/\\|]+", " ", s)
    s = re.sub(r"[^0-9a-zA-Z\u0980-\u09FF\s._-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_reason(reason: str) -> str:
    r = (reason or "").strip()
    if not r:
        return ""
    return " ".join(REASON_MAP.get(clean_name(w), w) for w in r.split())


def display_name(user) -> str:
    name = " ".join([x for x in [getattr(user, "first_name", None), getattr(user, "last_name", None)] if x]).strip()
    return name or getattr(user, "username", None) or str(user.id)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
    p = (text or "").split(maxsplit=1)
    return p[1].strip() if len(p) > 1 else ""


def is_protected_target(target: str) -> bool:
    t = clean_name(target)
    if not t:
        return False
    if t in PROTECTED_NAMES:
        return True
    if BOT_USERNAME and (t == BOT_USERNAME or BOT_USERNAME in t):
        return True
    return False


def is_normal_only(text: str) -> bool:
    return clean_name(text) in NORMAL_WORDS


def has_roast_signal(text: str) -> bool:
    low = clean_name(text)
    if re.search(r"\bvs\b| বনাম ", low, re.I):
        return True
    return any(w in low for w in BANGLA_HINT_WORDS)


def parse_target_reason(text: str):
    raw = (text or "").strip()
    low = clean_name(raw)
    if not low:
        return None, None

    names = sorted(DATA.get("memory", {}).keys(), key=len, reverse=True)
    for name in names:
        if low == name:
            return name, ""
        if low.startswith(name + " "):
            return name, raw[len(name):].strip()

    words = raw.split()
    if len(words) == 1:
        return clean_name(words[0]), ""

    relation_words = {"kaka", "ভাই", "vai", "bhai", "mama", "মামা", "চাচা", "apu", "আপু", "dada", "দাদা"}
    if len(words) >= 3 and clean_name(words[1]) in relation_words:
        target = " ".join(words[:2])
        reason = " ".join(words[2:])
    else:
        target = words[0]
        reason = " ".join(words[1:])
    return clean_name(target), reason.strip()


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


def local_roast(target: str, reason: str = "", memory: str = "") -> str:
    target = target.strip() or "এই জন"
    reason = normalize_reason(reason).strip()
    memory = normalize_reason(memory).strip()
    point = reason or memory or "ফাপরবাজি"
    punch1 = random.choice(LOCAL_PUNCHES)
    punch2 = random.choice([p for p in LOCAL_PUNCHES if p != punch1])
    templates = [
        f"{target} এমন {point}, {punch1} {punch2}",
        f"{target}-এর {point} দেখে মনে হয় নিজেই নিজের hype-man। {punch1} আগে ফাপর কমা, তারপর কথা বল।",
        f"{target} আবার {point} mode চালু করছে। {punch1} {punch2}",
        f"{target}, তোর {point} এত বেশি যে group mute করলেও vibration লাগে। {punch1}",
        f"{target} মুখে full HD {point}, কাজে 144p buffering। {punch1}",
        f"{target} এমন {point}, কথা শুনলে VIP লাগে, কাজের সময় খুঁজলে pending request। {punch1}",
    ]
    return random.choice(templates)[:850]


async def ai_roast(target: str, reason: str = "", memory: str = "") -> str:
    if is_protected_target(target):
        return "Admin বা bot-কে roast করা যাবে না। টার্গেট ঠিক করে দাও।"

    if not OPENAI_API_KEY:
        return local_roast(target, reason, memory)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""
তুমি বাংলা Telegram savage roast bot।

কাজ:
- User message থেকে পাওয়া target-কে clean savage roast করবে।
- Reply হবে আগের example থেকেও বেশি savage, কিন্তু অশ্লীল/হুমকি/জাতি-ধর্ম-লিঙ্গ নিয়ে attack নয়।
- ১ বা ২ লাইনের বেশি নয়।
- কোনো explanation, bullet, title, memory dump, disclaimer দেবে না।
- Bangla প্রধান থাকবে, কিন্তু group/CEO/performance/network/offline/loading এসব natural mixed word ব্যবহার করা যাবে।
- Target-এর নাম শুরুতে থাকবে।
- Reason/point থেকে punchline বানাবে।
- একই ধরনের line বারবার দেবে না।
- Direct, funny, insulting, sharp, group-chat style.

Example quality target:
"জনি কাকা এমন ফাপরবাজ, কথা শুনলে মনে হয় group-এর CEO, কিন্তু কাজের সময় খুঁজলে দেখা যায় network-এর বাইরে। ফাপর কমা, আগে নিজের performance দেখাও।"

এটার থেকেও savage কিন্তু clean করে লিখো।

Target: {target}
Point/Reason: {reason or "নেই"}
Memory context: {memory or "নেই"}
""".strip()
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.05,
            max_tokens=140,
        )
        out = (resp.choices[0].message.content or "").strip()
        return (out or local_roast(target, reason, memory))[:900]
    except Exception:
        log.exception("OpenAI failed; using local fallback")
        return local_roast(target, reason, memory)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    u = update.effective_user
    await update.message.reply_text(
        "🔥 Alpha Savage Roast Bot active.\n\n"
        f"তোমার Telegram ID: {u.id}\n"
        f"Detected name: {display_name(u)}\n\n"
        "Test:\n/ping\n/status\njoni kaka faforbarj\njoni vs mony\n\n"
        "Group normal message কাজ না করলে BotFather → /setprivacy → Disable"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    await update.message.reply_text(
        "Commands\n"
        "/ping - alive check\n/status - settings check\n"
        "/repair_on /repair_off - admin only\n"
        "/lockgroup /unlockgroup - admin only\n/setgroup - current group allow\n"
        "/normal_on /normal_off - admin only\n"
        "/mem name text - memory save\n/memory name - memory show\n"
        "/forget name - memory delete\n/users - users list\n"
        "/roast name reason - direct roast\n/vs name1 name2 - VS roast\n"
        "/shift name day|night|off - shift set"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    chat = update.effective_chat
    await update.message.reply_text(
        "📌 Status\n"
        f"Repair: {'ON' if DATA.get('repair') else 'OFF'}\n"
        f"Group lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(OPENAI_API_KEY) else 'OFF - local savage fallback'}\n"
        f"Admins set: {len(ADMIN_IDS)}\n"
        f"Current chat id: {chat.id if chat else 'unknown'}\n"
        f"Allowed groups: {DATA.get('allowed_groups') or 'all'}"
    )


async def admin_set_bool(update: Update, key: str, value: bool, label: str):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    DATA[key] = value
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if value else 'OFF'}")


async def repair_on(update, context): await admin_set_bool(update, "repair", True, "Repair mode")
async def repair_off(update, context): await admin_set_bool(update, "repair", False, "Repair mode")
async def lockgroup(update, context): await admin_set_bool(update, "group_lock", True, "Group lock")
async def unlockgroup(update, context): await admin_set_bool(update, "group_lock", False, "Group lock")
async def normal_on(update, context): await admin_set_bool(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await admin_set_bool(update, "normal_reply", False, "Normal reply")


async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    gid = str(update.effective_chat.id)
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
    target, reason = parse_target_reason(arg)
    if not target or not reason:
        await update.message.reply_text("Use: /mem name text")
        return
    DATA["memory"].setdefault(target, [])
    DATA["memory"][target].append(reason.strip())
    DATA["memory"][target] = DATA["memory"][target][-30:]
    save_data()
    await update.message.reply_text(f"✅ Memory saved for {target}")


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
    for u in list(DATA["users"].values())[-80:]:
        username = f"@{u.get('username')}" if u.get("username") else ""
        lines.append(f"• {u['name']} | {u['id']} {username}")
    await update.message.reply_text("\n".join(lines))


async def shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু admin করতে পারবে।")
        return
    arg = command_arg_text(update.message.text)
    parts = arg.split()
    if len(parts) < 2:
        await update.message.reply_text("Use: /shift name day|night|off")
        return
    name = clean_name(" ".join(parts[:-1]))
    mode = clean_name(parts[-1])
    if mode not in {"day", "night", "off"}:
        await update.message.reply_text("Use: /shift name day|night|off")
        return
    DATA["shifts"][name] = mode
    save_data()
    await update.message.reply_text(f"✅ {name} shift set: {mode}")


async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if DATA.get("repair"):
        return
    arg = command_arg_text(update.message.text)
    target, reason = parse_target_reason(arg)
    if not target:
        await update.message.reply_text("Use: /roast name reason")
        return
    if is_protected_target(target):
        await update.message.reply_text("Admin বা bot-কে target করা যাবে না।")
        return
    memtxt = " | ".join(DATA["memory"].get(target, [])[-4:])
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
    reply = await ai_roast(f"{a} বনাম {b}", f"{a} আর {b} কে compare করে savage roast", "")
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
    if is_normal_only(text):
        return

    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target = clean_name(display_name(msg.reply_to_message.from_user))
        reason = text
        if is_protected_target(target):
            return
        DATA["memory"].setdefault(target, [])
        DATA["memory"][target].append(reason)
        DATA["memory"][target] = DATA["memory"][target][-30:]
        save_data()
        memtxt = " | ".join(DATA["memory"].get(target, [])[-4:])
        reply = await ai_roast(target, reason, memtxt)
        await msg.reply_text(reply)
        return

    if re.search(r"\bvs\b| বনাম ", clean_name(text), re.I):
        parts = re.split(r"\s+vs\s+|\s+বনাম\s+", text, flags=re.I)
        if len(parts) >= 2:
            a, b = clean_name(parts[0]), clean_name(parts[1])
            reply = await ai_roast(f"{a} বনাম {b}", f"{a} আর {b} কে compare করে savage roast", "")
            await msg.reply_text(reply)
            return

    target, reason = parse_target_reason(text)
    if not target or is_protected_target(target):
        return

    if not reason:
        mems = DATA["memory"].get(target, [])
        if not mems:
            await msg.reply_text(f"{target} এর roast করার মতো তথ্য নেই। আগে /mem {target} কিছু তথ্য দাও।")
            return
        reply = await ai_roast(target, "", " | ".join(mems[-4:]))
        await msg.reply_text(reply)
        return

    if not has_roast_signal(text) and target not in DATA["memory"]:
        await msg.reply_text("এই message আমার জন্য না। কাউকে roast করতে চাইলে target-এর নাম আর point বলো।")
        return

    DATA["memory"].setdefault(target, [])
    DATA["memory"][target].append(reason)
    DATA["memory"][target] = DATA["memory"][target][-30:]
    save_data()
    memtxt = " | ".join(DATA["memory"].get(target, [])[-4:])
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
    app.add_handler(CommandHandler("shift", shift))
    app.add_handler(CommandHandler("roast", roast_cmd))
    app.add_handler(CommandHandler("vs", vs_cmd))

    async def repair_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
        arg = command_arg_text(update.message.text).lower()
        if "on" in arg:
            await repair_on(update, context)
        elif "off" in arg:
            await repair_off(update, context)
        else:
            await update.message.reply_text("Use: /repair on অথবা /repair off")

    async def lock_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
        arg = command_arg_text(update.message.text).lower()
        if "on" in arg:
            await lockgroup(update, context)
        elif "off" in arg:
            await unlockgroup(update, context)
        else:
            await update.message.reply_text("Use: /lock on অথবা /lock off")

    app.add_handler(CommandHandler("repair", repair_alias))
    app.add_handler(CommandHandler("lock", lock_alias))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log.info("Bot starting | admins=%s | openai=%s | username=%s", ADMIN_IDS, bool(OPENAI_API_KEY), BOT_USERNAME)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
