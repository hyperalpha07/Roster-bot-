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

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

# =========================================================
# ALPHA ULTRA ROAST CUSTOM BOT
# Dynamic AI roast + strong local fallback
# Admin protection: AlphA / Alpha / Alfa / Admin / Bot protected
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "roster_you_bot").replace("@", "").strip().lower()
ADMIN_IDS = {int(x) for x in re.split(r"[,;\s]+", os.getenv("ADMIN_IDS", os.getenv("ADMIN_USER_IDS", ""))) if x.isdigit()}
DATA_FILE = Path(os.getenv("DATA_FILE", "alpha_roast_memory.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alpha-roast")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in Railway Variables")

# ---------------- DEFAULT MEMORY ----------------
DEFAULT_DATA = {
    "repair": False,
    "normal_reply": True,
    "group_lock": False,
    "level": "brutal",
    "users": {},
    "memory": {
        "monir": ["নিজেকে অনেক বুদ্ধিমান মনে করে, আসলে কিছু না"],
        "joni": ["ফাফরবাজ, ফাফর ছাড়া তার ভেতর আর কিছু নেই"],
        "জনি": ["ফাফরবাজ, ফাফর ছাড়া তার ভেতর আর কিছু নেই"],
        "mony": ["গাঁজা ও মলম বিক্রেতা"],
        "মনি": ["গাঁজা ও মলম বিক্রেতা"],
        "alon": ["হুতাসে চলে, কোনো কারণ ছাড়া লাফালাফি করে"],
        "surjo": ["অলস, খাওয়া আর ঘন ঘন বাথরুমে যাওয়া"],
        "সূর্য": ["অলস, খাওয়া আর ঘন ঘন বাথরুমে যাওয়া"],
    }
}

PROTECTED_NAMES = {
    "alpha", "alfa", "alphа", "আলফা", "আলফ", "admin", "এডমিন", "অ্যাডমিন", "bot", "বট", "roster", BOT_USERNAME
}

ADMIRATION_WORDS = [
    "ভালো", "valo", "good", "best", "joss", "jos", "জোস", "সুন্দর", "right", "ঠিক", "sothik", "সঠিক", "ধন্যবাদ", "thanks", "thank"
]

TARGET_ALIASES = {
    "joni kaka": "joni",
    "জনি কাকা": "joni",
    "joni": "joni",
    "জনি": "joni",
    "monir": "monir",
    "মনির": "monir",
    "mony": "mony",
    "মনি": "mony",
    "alon": "alon",
    "আলন": "alon",
    "surjo": "surjo",
    "surjo": "surjo",
    "সূর্য": "surjo",
}

ACTION_TO_POINT = {
    "utase": "হুতাসে চলে",
    "hutase": "হুতাসে চলে",
    "উতাসে": "হুতাসে চলে",
    "হুতাসে": "হুতাসে চলে",
    "fafor": "ফাফরবাজি করে",
    "fapor": "ফাফরবাজি করে",
    "faforbarj": "ফাফরবাজি করে",
    "ফাফর": "ফাফরবাজি করে",
    "ফাপর": "ফাফরবাজি করে",
    "লাফালাফি": "কারণ ছাড়া লাফালাফি করে",
    "lazy": "অলসতা করে",
    "অলস": "অলসতা করে",
    "bathroom": "ঘন ঘন বাথরুমে যায়",
    "বাথরুম": "ঘন ঘন বাথরুমে যায়",
    "ganja": "গাঁজার গল্প নিয়ে ঘোরে",
    "গাঞ্জা": "গাঁজার গল্প নিয়ে ঘোরে",
    "মলম": "মলম বিক্রেতার মতো কথা বলে",
}

PUNCHLINES = [
    "কথায় সিংহ, কাজে সাইলেন্ট মোড।",
    "ভাব দেখে মনে হয় রাজত্ব চালায়, বাস্তবে নিজের অজুহাতও ঠিকমতো সামলাতে পারে না।",
    "এত ফাপর দিলে গ্রুপের বাতাসও লজ্জা পায়।",
    "হেডাম দেখায় পাহাড়ের মতো, কাজের সময় নেটওয়ার্কের বাইরে।",
    "নিজেকে প্রধান চরিত্র ভাবে, কিন্তু বাস্তবে শুধু ব্যাকগ্রাউন্ডের শব্দ।",
    "তার আত্মবিশ্বাসের অর্ধেক যদি কাজে লাগত, আজ গ্রুপে কিংবদন্তি না হলেও মানুষ হত।",
    "মুখে আগুন, কাজে শুধু ধোঁয়া।",
    "যে ভঙ্গিতে কথা বলে, মনে হয় পুরস্কার জিতেছে; ফলাফল দেখলে বোঝা যায় অংশগ্রহণ সনদও পায়নি।",
]

OPENAI_CLIENT = AsyncOpenAI(api_key=OPENAI_API_KEY) if (AsyncOpenAI and OPENAI_API_KEY) else None

# ---------------- DATA ----------------
def load_data():
    if DATA_FILE.exists():
        try:
            d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_DATA.items():
                d.setdefault(k, v)
            for k, v in DEFAULT_DATA["memory"].items():
                d["memory"].setdefault(k, v)
            return d
        except Exception:
            log.exception("memory load failed")
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))

DATA = load_data()

def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")

def is_admin(uid):
    return uid in ADMIN_IDS

def clean(s):
    s = (s or "").strip().lower()
    s = s.replace("@", " ")
    s = re.sub(r"[^\w\s\u0980-\u09FF-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def display_name(user):
    if not user:
        return "কেউ একজন"
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
        "last": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_data()

def arg_text(text):
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""

def canonical_name(name):
    c = clean(name)
    if c in TARGET_ALIASES:
        return TARGET_ALIASES[c]
    return c

def is_protected_name(name):
    c = clean(name)
    if c in PROTECTED_NAMES:
        return True
    for p in PROTECTED_NAMES:
        if p and (c == p or c.startswith(p + " ") or p in c.split()):
            return True
    return False

def detect_question_about_owner(text):
    t = clean(text)
    owner_patterns = [
        "ke baniyese", "কে বানিয়েছে", "কে বানিয়েছে", "tomake ke", "তোমাকে কে", "bot er malik", "বটের মালিক", "owner", "malik", "মালিক"
    ]
    return any(p in t for p in owner_patterns)

def detect_bot_praise(text):
    t = clean(text)
    has_bot = "bot" in t or "বট" in t or BOT_USERNAME in t
    has_praise = any(w in t for w in ADMIRATION_WORDS)
    return has_bot and has_praise

def extract_target_reason(text):
    raw = (text or "").strip()
    t = clean(raw)
    if not t:
        return None, None

    # protected direct mention
    if is_protected_name(t):
        return "__protected__", raw

    # find longest alias inside text
    aliases = sorted(TARGET_ALIASES.keys(), key=len, reverse=True)
    for alias in aliases:
        ca = clean(alias)
        if re.search(rf"(^|\s){re.escape(ca)}(\s|$)", t):
            target = TARGET_ALIASES[alias]
            reason = raw
            # remove alias from reason softly
            reason = re.sub(re.escape(alias), "", reason, flags=re.I).strip()
            if not reason:
                reason = "আগের মেমরি অনুযায়ী ফাপর দেখাচ্ছে"
            # action mapping
            rt = clean(reason)
            for key, val in ACTION_TO_POINT.items():
                if clean(key) in rt:
                    reason = val
                    break
            return target, reason

    # first word/first two words fallback
    words = raw.split()
    if len(words) >= 2:
        maybe_two = clean(" ".join(words[:2]))
        maybe_one = clean(words[0])
        if is_protected_name(maybe_one) or is_protected_name(maybe_two):
            return "__protected__", raw
        family = {"kaka", "কাকা", "vai", "ভাই", "mama", "মামা", "bhai"}
        if len(words) >= 3 and clean(words[1]) in family:
            return canonical_name(" ".join(words[:2])), " ".join(words[2:])
        return canonical_name(words[0]), " ".join(words[1:])

    return canonical_name(raw), ""

def memory_for(target):
    target = canonical_name(target)
    return DATA["memory"].get(target, [])[-5:]

def save_point(target, point):
    target = canonical_name(target)
    if not target or target == "__protected__" or is_protected_name(target):
        return
    if not point:
        return
    DATA["memory"].setdefault(target, [])
    if point not in DATA["memory"][target]:
        DATA["memory"][target].append(point)
        DATA["memory"][target] = DATA["memory"][target][-30:]
        save_data()

def local_roast(target, reason):
    mems = memory_for(target)
    base = random.choice(mems) if mems else "নিজেকে বড় কিছু ভাবে"
    reason = reason or base
    name = target
    starts = [
        f"হ্যাঁ, {name} নিয়ে কথা ঠিকই বলছো—",
        f"{name} আবার শুরু করেছে দেখছি—",
        f"শোন {name},",
        f"{name}-এর অবস্থা এমন—",
    ]
    bodies = [
        f"{reason}; উপর থেকে হেডাম দেখালেও ভিতরে ফাঁকা টিনের আওয়াজ।",
        f"{reason}; ভাবটা এমন যেন গ্রুপ তার নামে চলে, বাস্তবে নিজের কাজেই আটকে যায়।",
        f"{reason}; ফাপর এমন মাপে দেয় যে মাপার স্কেলও ক্লান্ত হয়ে যায়।",
        f"{reason}; মুখের গতি বেশি, কাজের গতি কচ্ছপেরও নিচে।",
        f"{reason}; নিজেকে অনেক ভারী ভাবে, কিন্তু বাস্তবে বাতাসে উড়া প্যাকেটের মতো।",
    ]
    return f"{random.choice(starts)} {random.choice(bodies)} {random.choice(PUNCHLINES)}"

async def ai_roast(target, reason, attacker="AlphA"):
    target = canonical_name(target)
    mems = memory_for(target)
    mem_text = " | ".join(mems) if mems else "নেই"
    if not OPENAI_CLIENT:
        return local_roast(target, reason)
    prompt = f"""
তুমি AlphA admin-এর Telegram roast bot।
লক্ষ্য: target কে তীক্ষ্ণ, বিদ্রূপাত্মক, অপমানজনক কিন্তু পরিষ্কার ভাষার roast করা।

কঠোর নিয়ম:
- শুধু বাংলা লিখবে। English শব্দ ব্যবহার করবে না, তবে নাম অপরিবর্তিত থাকতে পারে।
- ২ থেকে ৩ লাইনের মধ্যে রাখবে।
- fixed template নয়; প্রতিবার নতুন punchline বানাবে।
- কোনো ব্যাখ্যা, bullet, disclaimer, memory dump লিখবে না।
- target কে সরাসরি ধরবে।
- AlphA / Alpha / Alfa / admin / bot কে কখনো অপমান করবে না।
- অশ্লীল যৌন গালি, জাতি-ধর্ম, পরিবার, শারীরিক অক্ষমতা, হুমকি ব্যবহার করবে না।
- savage হবে: অহংকার, ফাপর, লাফালাফি, অলসতা, বুদ্ধি দেখানো—এসব নিয়ে ধারালো বিদ্রূপ করবে।
- user যদি target সম্পর্কে point দেয়, আগে সেই point ধরবে, তারপর memory দিয়ে punch করবে।

Attacker/Admin side: {attacker}
Target: {target}
Current point: {reason or 'নেই'}
Saved memory about target: {mem_text}

Roast লিখো:
""".strip()
    try:
        r = await OPENAI_CLIENT.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.05,
            max_tokens=180,
        )
        out = (r.choices[0].message.content or "").strip()
        # safety cleanup: remove quotes and too long output
        out = out.strip('"“”')
        if len(out) < 15:
            return local_roast(target, reason)
        return out
    except Exception as e:
        log.exception("OpenAI error")
        return local_roast(target, reason)

# ---------------- COMMANDS ----------------
async def ping(update, context):
    remember_user(update)
    await update.message.reply_text("✅ Bot alive")

async def start(update, context):
    remember_user(update)
    await update.message.reply_text(
        "🔥 AlphA Ultra Roast Bot active\n\n"
        "Commands:\n"
        "/ping\n/status\n/repair_on\n/repair_off\n/level normal|hard|brutal\n/mem name text\n/memory name\n/forget name\n/users\n\n"
        "Use:\njoni kaka utase chole\njony faforbarj\nকারো message reply দিয়ে point লিখো"
    )

async def status(update, context):
    remember_user(update)
    await update.message.reply_text(
        f"📌 Status\nRepair: {'ON' if DATA['repair'] else 'OFF'}\n"
        f"Normal reply: {'ON' if DATA['normal_reply'] else 'OFF'}\n"
        f"Group lock: {'ON' if DATA['group_lock'] else 'OFF'}\n"
        f"OpenAI: {'ON' if bool(OPENAI_CLIENT) else 'OFF'}\n"
        f"Level: {DATA.get('level')}\n"
        f"Admins: {sorted(ADMIN_IDS)}\n"
        f"Chat ID: {update.effective_chat.id}"
    )

async def admin_set(update, key, value, label):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু AlphA admin করতে পারবে।")
        return
    DATA[key] = value
    save_data()
    await update.message.reply_text(f"✅ {label}: {'ON' if value else 'OFF'}")

async def repair_on(update, context): await admin_set(update, "repair", True, "Repair")
async def repair_off(update, context): await admin_set(update, "repair", False, "Repair")
async def normal_on(update, context): await admin_set(update, "normal_reply", True, "Normal reply")
async def normal_off(update, context): await admin_set(update, "normal_reply", False, "Normal reply")

async def level_cmd(update, context):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু AlphA admin করতে পারবে।")
        return
    lvl = arg_text(update.message.text).lower().strip()
    if lvl not in {"normal", "hard", "brutal"}:
        await update.message.reply_text("Use: /level normal | hard | brutal")
        return
    DATA["level"] = lvl
    save_data()
    await update.message.reply_text(f"✅ Roast level set: {lvl}")

async def mem_cmd(update, context):
    remember_user(update)
    a = arg_text(update.message.text)
    if not a or len(a.split()) < 2:
        await update.message.reply_text("Use: /mem name text")
        return
    name, info = a.split(maxsplit=1)
    name = canonical_name(name)
    if is_protected_name(name):
        await update.message.reply_text("🛡️ AlphA/admin/bot protected।")
        return
    save_point(name, info)
    await update.message.reply_text(f"✅ Memory saved for {name}")

async def memory_cmd(update, context):
    remember_user(update)
    name = canonical_name(arg_text(update.message.text))
    if not name:
        await update.message.reply_text("Use: /memory name")
        return
    mems = memory_for(name)
    await update.message.reply_text("\n".join([f"• {x}" for x in mems]) if mems else f"{name} এর memory নেই।")

async def forget_cmd(update, context):
    remember_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ এটা শুধু AlphA admin করতে পারবে।")
        return
    name = canonical_name(arg_text(update.message.text))
    if name in DATA["memory"]:
        del DATA["memory"][name]
        save_data()
        await update.message.reply_text(f"✅ {name} memory deleted")
    else:
        await update.message.reply_text("Memory পাওয়া যায়নি।")

async def users_cmd(update, context):
    remember_user(update)
    lines = ["👥 Users"]
    for u in list(DATA["users"].values())[-30:]:
        lines.append(f"• {u['name']} | {u['id']} | @{u.get('username','')}")
    await update.message.reply_text("\n".join(lines))

# ---------------- MESSAGE HANDLER ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    if not text or text.startswith("/"):
        return
    log.info("TEXT chat=%s user=%s text=%r", update.effective_chat.id, update.effective_user.id, text)

    if DATA.get("repair") or not DATA.get("normal_reply"):
        return
    if update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and DATA.get("group_lock"):
        return

    # owner/admin question
    if detect_question_about_owner(text):
        await msg.reply_text("আমাকে AlphA বানিয়েছে—এই গ্রুপের আসল চালক। বাকিরা যেখানে ফাপর মারে, AlphA সেখানে সিস্টেম দাঁড় করায়।")
        return

    # bot praise = don't get impressed; roast sender using memory if possible
    if detect_bot_praise(text):
        sender_name = display_name(update.effective_user)
        await msg.reply_text(f"{sender_name}, তেল মারলে লাভ নেই—আমি প্রশংসায় নরম হই না। আগে নিজের ফাইলটা পরিষ্কার করো, তারপর বটকে মুগ্ধ করতে আসো।")
        return

    # reply targeting
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        target_user = msg.reply_to_message.from_user
        target_name = canonical_name(display_name(target_user))
        if is_protected_name(target_name) or target_user.id in ADMIN_IDS:
            await msg.reply_text("🛡️ AlphA/admin protected। ওদের নিয়ে ফাপর না, সম্মান দেখাও।")
            return
        reason = text
        save_point(target_name, reason)
        roast = await ai_roast(target_name, reason, display_name(update.effective_user))
        await msg.reply_text(roast)
        return

    target, reason = extract_target_reason(text)
    if not target:
        return
    if target == "__protected__" or is_protected_name(target):
        await msg.reply_text("🛡️ AlphA/admin/bot নিয়ে কথা না। এখানে সম্মান থাকবে, ফাপর অন্যদের জন্য।")
        return

    # no reason and unknown memory -> ask info
    if not reason and not memory_for(target):
        await msg.reply_text(f"{target} কে পচানোর মতো তথ্য এখনো কম। আগে তার একটা point বলো।")
        return

    if reason:
        save_point(target, reason)
    roast = await ai_roast(target, reason, display_name(update.effective_user))
    await msg.reply_text(roast)

async def error_handler(update, context):
    log.exception("Error: %s", context.error)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("normal_on", normal_on))
    app.add_handler(CommandHandler("normal_off", normal_off))
    app.add_handler(CommandHandler("level", level_cmd))
    app.add_handler(CommandHandler(["mem", "save"], mem_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler(["forget", "delete"], forget_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("Bot starting | OpenAI=%s | Admins=%s", bool(OPENAI_CLIENT), ADMIN_IDS)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
