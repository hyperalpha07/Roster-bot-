# -*- coding: utf-8 -*-
"""
FINAL AI ROAST VERSION - Telegram Group Roast Bot
Author: AlphA project

Install:
  pip install python-telegram-bot==21.6 openai==1.54.4

Railway Start Command:
  python final_ai_roast_bot.py

Required ENV:
  BOT_TOKEN=your_telegram_bot_token
  ADMIN_IDS=123456789,987654321

Optional ENV:
  OPENAI_API_KEY=your_openai_api_key
  OPENAI_MODEL=gpt-4o-mini
  DATA_FILE=bot_data.json
  ALLOWED_GROUP_IDS=-1001234567890,-1009876543210
  BOT_USERNAME=roster_you_bot
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from telegram import Update, User
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

# =========================================================
# ENV / CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Colombo"))

ADMIN_IDS = set()
for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(","):
    if x.strip().lstrip("-").isdigit():
        ADMIN_IDS.add(int(x.strip()))

ALLOWED_GROUP_IDS = set()
for x in os.getenv("ALLOWED_GROUP_IDS", "").replace(" ", "").split(","):
    if x.strip().lstrip("-").isdigit():
        ALLOWED_GROUP_IDS.add(int(x.strip()))

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing. Add BOT_TOKEN in Railway Variables.")

ai_client = None
if OPENAI_API_KEY and AsyncOpenAI:
    ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# =========================================================
# DATA
# =========================================================
DEFAULT_DATA = {
    "repair_mode": False,
    "normal_reply": True,
    "group_lock": False,
    "allowed_groups": [],
    "users": {},
    "aliases": {},
    "memory": {},
    "shifts": {},
    "settings": {
        "roast_level": "savage",
        "max_lines": 2,
        "bangla_only": True,
        "ai_enabled": True,
    },
}


def load_data() -> Dict:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULT_DATA.copy()
            merged.update(data)
            for k, v in DEFAULT_DATA.items():
                if isinstance(v, dict):
                    merged.setdefault(k, {})
            return merged
        except Exception:
            return DEFAULT_DATA.copy()
    return DEFAULT_DATA.copy()


def save_data() -> None:
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")


DATA = load_data()

# env allowed groups also saved/used
for gid in ALLOWED_GROUP_IDS:
    if gid not in DATA.get("allowed_groups", []):
        DATA.setdefault("allowed_groups", []).append(gid)

# =========================================================
# TEXT HELPERS
# =========================================================
BENGALI_RE = re.compile(r"[\u0980-\u09FF]")
URL_RE = re.compile(r"https?://|www\.", re.I)
MENTION_RE = re.compile(r"@([a-zA-Z0-9_]{4,})")

STOP_WORDS = {
    "ami", "tumi", "tumra", "amra", "ora", "tara", "se", "ke", "ki", "koi",
    "kothai", "kore", "korbe", "korlo", "korche", "kortese", "hobe", "hoi", "ase",
    "ache", "na", "to", "ar", "r", "ei", "ai", "oi", "eta", "ata", "je", "jodi",
    "kintu", "mane", "bujle", "bolo", "dekh", "dekho", "message", "reply", "group",
    "amar", "tomar", "or", "tar", "oder", "sob", "shob", "sobai", "shobai", "kaj",
    "one", "on", "off", "status", "help", "start", "hi", "hello", "vai", "bhai", "bro",
    "the", "and", "is", "are", "you", "me", "i", "we", "they", "he", "she",
}

BANGLA_STOP = {
    "আমি", "তুমি", "আমরা", "ওরা", "তারা", "সে", "কে", "কি", "কী", "কই", "কোথায়",
    "করে", "করবে", "করলো", "করছে", "হবে", "হয়", "আসে", "আছে", "না", "তো",
    "আর", "এই", "ওই", "এটা", "যে", "যদি", "কিন্তু", "মানে", "বলো", "দেখ", "দেখো",
    "মেসেজ", "রিপ্লাই", "গ্রুপ", "আমার", "তোমার", "তার", "ওর", "সব", "সবাই", "কাজ",
    "হাই", "হ্যালো", "ভাই",
}

INSULT_WORDS = {
    "fapor", "fafor", "faporbaz", "faporbaj", "faforbaz", "faforbarj", "faporbarj",
    "chapabaz", "chapabaji", "chittar", "cheater", "chor", "batpar", "faltu", "loser",
    "lazy", "olosh", "bokachoda", "pagol", "nonsense", "showoff", "vong", "bogus",
    "ফাপর", "ফাপরবাজ", "চাপাবাজ", "চিটার", "চোর", "বাটপার", "ফালতু", "অলস", "পাগল", "ভণ্ড",
    "বোগাস", "লোকদেখানো", "বড়াই", "নাটকবাজ", "বেকার", "কিপটা", "লেভেল", "ভাব",
}

POSITIVE_OR_NORMAL = {
    "hi", "hello", "kemon", "aso", "good", "thanks", "thank", "ok", "okay", "হাই", "কেমন", "আছো", "ধন্যবাদ", "ওকে",
}

NAME_HINT_WORDS = {"kaka", "vai", "bhai", "apu", "dada", "mama", "joni", "surjo", "mony", "alon", "sakib", "alpha"}


def clean_text(text: str) -> str:
    text = text or ""
    text = text.replace("\u200c", "").replace("\u200d", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_bot_suffix(cmd: str) -> str:
    if "@" in cmd:
        return cmd.split("@", 1)[0]
    return cmd


def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def normalize_key(name: str) -> str:
    name = clean_text(name).lower()
    name = re.sub(r"[^\w\u0980-\u09FF ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def display_name(user: Optional[User]) -> str:
    if not user:
        return "unknown"
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(x for x in parts if x).strip()
    return name or user.username or str(user.id)


def register_user(user: Optional[User]) -> None:
    if not user:
        return
    uid = str(user.id)
    name = display_name(user)
    username = (user.username or "").lower()
    DATA.setdefault("users", {})[uid] = {
        "id": user.id,
        "name": name,
        "username": username,
        "last_seen": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
    }
    # aliases for target matching
    aliases = DATA.setdefault("aliases", {})
    aliases[normalize_key(name)] = uid
    if username:
        aliases[normalize_key(username)] = uid
    first = normalize_key(user.first_name or "")
    if first:
        aliases[first] = uid
    save_data()


def memory_for(name_or_id: str) -> List[str]:
    key = normalize_key(name_or_id)
    mem = DATA.setdefault("memory", {})
    if key in mem:
        return mem.get(key, [])[-8:]
    uid = DATA.setdefault("aliases", {}).get(key)
    if uid and uid in mem:
        return mem.get(uid, [])[-8:]
    return []


def add_memory(name: str, info: str) -> None:
    key = normalize_key(name)
    DATA.setdefault("memory", {}).setdefault(key, [])
    info = clean_text(info)
    if info and info not in DATA["memory"][key]:
        DATA["memory"][key].append(info)
        DATA["memory"][key] = DATA["memory"][key][-30:]
    save_data()


def delete_memory(name: str) -> bool:
    key = normalize_key(name)
    deleted = False
    for k in [key, DATA.setdefault("aliases", {}).get(key)]:
        if k and k in DATA.setdefault("memory", {}):
            del DATA["memory"][k]
            deleted = True
    save_data()
    return deleted


def allowed_group(chat_id: int) -> bool:
    allowed = set(DATA.get("allowed_groups", [])) | ALLOWED_GROUP_IDS
    return not allowed or chat_id in allowed


def repair_on() -> bool:
    return bool(DATA.get("repair_mode"))


def group_locked() -> bool:
    return bool(DATA.get("group_lock"))


def tokenize(text: str) -> List[str]:
    text = clean_text(text)
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u0980-\u09FF]+", text)
    return [t for t in tokens if t]


def has_insult_point(text: str) -> bool:
    low = text.lower()
    if any(w in low for w in INSULT_WORDS if re.search(r"[a-z]", w)):
        return True
    if any(w in text for w in INSULT_WORDS if BENGALI_RE.search(w)):
        return True
    # Banglish common suffix/meaning patterns
    if re.search(r"\b\w*(baz|baj|baji|barj)\b", low):
        return True
    return False


def extract_target_and_point(text: str, reply_user: Optional[User] = None) -> Tuple[Optional[str], str, str]:
    """Return target, point/reason, mode."""
    text = clean_text(text)
    original = text
    low = text.lower()

    # VS pattern
    m_vs = re.search(r"(.+?)\s+(?:vs|VS|ভিএস|বনাম)\s+(.+)", text)
    if m_vs:
        return clean_text(m_vs.group(1)), clean_text(m_vs.group(2)), "vs"

    # reply targeting: replied user is target, current text is point
    if reply_user and not reply_user.is_bot:
        return display_name(reply_user), original, "reply"

    # mention target
    m = MENTION_RE.search(text)
    if m:
        target = m.group(1)
        point = clean_text(MENTION_RE.sub("", text))
        return target, point, "mention"

    tokens = tokenize(text)
    if not tokens:
        return None, "", "none"

    # name-only memory roast
    if len(tokens) <= 3 and not has_insult_point(text):
        possible = normalize_key(" ".join(tokens))
        if memory_for(possible):
            return " ".join(tokens), "memory", "name_only"
        if len(tokens) == 1 and memory_for(tokens[0]):
            return tokens[0], "memory", "name_only"
        return None, original, "normal"

    # user alias exact prefix, e.g. "surjo sobar taka khai"
    aliases = sorted(DATA.setdefault("aliases", {}).keys(), key=lambda x: len(x), reverse=True)
    low_norm = normalize_key(text)
    for alias in aliases:
        if alias and (low_norm == alias or low_norm.startswith(alias + " ")):
            point = clean_text(text[len(alias):]) if text.lower().startswith(alias) else original
            return alias, point or original, "alias_prefix"

    # Heuristic: target is first 1-2 meaningful tokens before insult point.
    target_tokens = []
    for tok in tokens[:4]:
        ltok = tok.lower()
        if ltok in STOP_WORDS or tok in BANGLA_STOP:
            continue
        if ltok in INSULT_WORDS or tok in INSULT_WORDS:
            break
        target_tokens.append(tok)
        if len(target_tokens) >= 2:
            break

    # If no insult point, don't auto roast normal sentence.
    if not has_insult_point(text):
        return None, original, "normal"

    target = " ".join(target_tokens).strip()
    if not target:
        return None, original, "normal"

    # point is everything after target phrase, but keep full text for context too.
    point = original
    if original.lower().startswith(target.lower()):
        point = clean_text(original[len(target):]) or original
    return target, point, "auto"


def protect_target(target: Optional[str]) -> bool:
    if not target:
        return False
    t = normalize_key(target)
    protected = {"bot", "roster bot", "roster bot", "admin", "alpha", "alphA".lower()}
    if BOT_USERNAME:
        protected.add(BOT_USERNAME)
    if t in protected:
        return True
    # admin names/ids
    for uid, info in DATA.get("users", {}).items():
        if int(uid) in ADMIN_IDS and t in {normalize_key(info.get("name", "")), normalize_key(info.get("username", ""))}:
            return True
    return False


def get_shift_context(user_id: Optional[int] = None) -> str:
    now = datetime.now(TIMEZONE).time()
    current = "day" if time(6, 0) <= now < time(18, 0) else "night"
    if user_id:
        shift = DATA.setdefault("shifts", {}).get(str(user_id))
        if shift:
            return f"বর্তমান সময়: {current}; ব্যবহারকারীর শিফট: {shift}"
    return f"বর্তমান সময়: {current}"


def fallback_dynamic_roast(target: str, point: str, memories: List[str], sender_name: str = "") -> str:
    """Dynamic fallback without OpenAI. It uses random templates, not one fixed reply."""
    target = clean_text(target) or "ওইজন"
    point = clean_text(point) or "ভাব"
    point_low = point.lower()

    theme = "ভাব"
    if any(x in point_low for x in ["fapor", "fafor", "faporbaz", "faporbaj", "faforbarj", "chapabaz"]):
        theme = "ফাপরবাজি"
    elif any(x in point_low for x in ["taka", "money", "khai", "khoroch"]):
        theme = "টাকার হিসাব"
    elif any(x in point_low for x in ["cheat", "chittar", "chitar", "churi", "chor"]):
        theme = "চিটারপনা"
    elif any(x in point_low for x in ["lazy", "olosh", "kaj kore na"]):
        theme = "অলসতা"
    elif any(x in point for x in ["ফাপর", "চাপা", "বড়াই"]):
        theme = "ফাপরবাজি"
    elif any(x in point for x in ["টাকা", "খায়", "হিসাব"]):
        theme = "টাকার হিসাব"
    elif any(x in point for x in ["চিটার", "চোর"]):
        theme = "চিটারপনা"

    mem_line = ""
    if memories:
        mem_line = random.choice(memories[-5:])
        mem_line = re.sub(r"\s+", " ", mem_line).strip()
        mem_line = mem_line[:80]

    templates = {
        "ফাপরবাজি": [
            f"{target} এমন ফাপরবাজ, কথা শুনলে গ্রুপের সিইও লাগে—কাজের সময় খুঁজলে নেটওয়ার্কের বাইরে।",
            f"{target} ফাপর এমন মারে, মনে হয় পুরো গ্রুপ তার নামে চলে; বাস্তবে কাজের বেলায় শুধু লোডিং স্ক্রিন।",
            f"{target} কথা বলে হাই-ভোল্টেজে, কিন্তু কাজের সময় ব্যাটারি লো—ফাপর কমাও, আগে পারফরম্যান্স দেখাও।",
            f"{target}-এর ফাপর শুনলে মনে হয় মিটিংয়ের বস, কিন্তু কাজে গেলে উপস্থিতি পর্যন্ত সন্দেহজনক।",
        ],
        "টাকার হিসাব": [
            f"{target} টাকার বিষয়ে এমন চালাক, ক্যালকুলেটরও দেখে বলে: ভাই, এত হিসাব আমি পারব না।",
            f"{target} টাকা খাওয়ার লাইনে এত সিরিয়াস, মনে হয় গ্রুপ না—নিজের বুফে খুলে বসেছে।",
            f"{target}-এর টাকা দেখলেই চোখে এমন আলো আসে, যেন ওয়ালেট নয়, ঈদের চাঁদ দেখছে।",
            f"{target} হিসাবের সময় এমন গায়েব হয়, মনে হয় টাকা দেখলেই তার লোকেশন সার্ভিস বন্ধ হয়ে যায়।",
        ],
        "চিটারপনা": [
            f"{target} এমন চিটার, সত্য কথা বললেও পাশে নোটারি লাগে।",
            f"{target}-এর চালাকি এত পুরোনো, গ্রুপের সবাই আগেই আপডেট পেয়ে গেছে।",
            f"{target} প্ল্যান করে এমন ভাবে, শেষে নিজের ফাঁদেই নিজে লগইন করে বসে।",
            f"{target}-এর বিশ্বাসযোগ্যতা এমন, স্ক্রিনশটও আগে দুইবার ভেরিফাই করতে চায়।",
        ],
        "অলসতা": [
            f"{target} কাজের সময় এমন স্লো, তাকে দেখলে ঘড়িও বিশ্রাম নিতে চায়।",
            f"{target} কাজ শুরু করার আগেই এমন ক্লান্ত, মনে হয় জন্ম থেকেই লো-পাওয়ার মোডে আছে।",
            f"{target}-এর কাজের স্পিড দেখে ওয়াই-ফাইও লজ্জায় কানেকশন কেটে দেয়।",
            f"{target} কাজে এমন offline, তাকে খুঁজতে গেলে আগে সার্চ ওয়ারেন্ট লাগে।",
        ],
        "ভাব": [
            f"{target} এমন ভাব নেয়, মনে হয় গ্রুপ তার নামে রেজিস্টার্ড; বাস্তবে সবাই শুধু মজা দেখছে।",
            f"{target} কথায় আগুন, কাজে ধোঁয়া—দূর থেকে ভয়ংকর, কাছে গেলে ফাঁকা প্যাকেট।",
            f"{target} নিজের লেভেল এমন দেখায়, যেন premium version; ব্যবহার করলে বোঝা যায় trial expired।",
            f"{target} এত confidence নিয়ে চলে, মনে হয় আয়না পর্যন্ত তাকে mute করে রাখতে চায়।",
        ],
    }
    line = random.choice(templates.get(theme, templates["ভাব"]))
    if mem_line and random.random() < 0.45:
        line += f" পুরনো রেকর্ডও বলে: {mem_line}"
    return line[:700]


async def ai_roast(target: str, point: str, memories: List[str], sender: str, mode: str, sender_id: Optional[int]) -> str:
    if not ai_client or not DATA.get("settings", {}).get("ai_enabled", True):
        return fallback_dynamic_roast(target, point, memories, sender)

    mem_txt = " | ".join(memories[-5:]) if memories else "নেই"
    shift_txt = get_shift_context(sender_id)
    system = (
        "তুমি একটি Telegram group roast bot. তোমার কাজ হলো message থেকে target ও ছোট point ধরে "
        "Bangla-only clean savage roast লেখা। অশ্লীল গালি, hate speech, sexual content, threat, doxxing নয়। "
        "Reply ১-২ লাইনের হবে। কোনো explanation, title, memory dump, bullet point নয়। "
        "Hardcoded line ব্যবহার করবে না; প্রতিবার natural নতুন punchline বানাবে। "
        "Banglish input পেলেও output বাংলা লিপিতে হবে।"
    )
    user = (
        f"Target: {target}\n"
        f"Point/reason from message: {point}\n"
        f"Mode: {mode}\n"
        f"Sender: {sender}\n"
        f"Target memory: {mem_txt}\n"
        f"Context: {shift_txt}\n"
        "Output: শুধু roast text।"
    )
    try:
        resp = await ai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.95,
            max_tokens=150,
        )
        text = resp.choices[0].message.content.strip()
        text = re.sub(r"^(রোস্ট|Roast|Output)\s*[:：-]\s*", "", text).strip()
        text = re.sub(r"\n{2,}", "\n", text)
        # keep concise
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        text = "\n".join(lines[:2])
        if not text:
            raise ValueError("empty ai roast")
        return text[:700]
    except Exception:
        return fallback_dynamic_roast(target, point, memories, sender)


async def ai_vs_roast(left: str, right: str, sender: str, sender_id: Optional[int]) -> str:
    if not ai_client or not DATA.get("settings", {}).get("ai_enabled", True):
        a = fallback_dynamic_roast(left, f"{right} এর সাথে compare", memory_for(left), sender)
        b = fallback_dynamic_roast(right, f"{left} এর সাথে compare", memory_for(right), sender)
        return f"{a}\n{b}"
    system = (
        "তুমি Bangla-only Telegram roast bot. দুইজনকে compare করে ১-২ লাইনের clean savage VS roast দাও। "
        "অশ্লীল গালি, hate speech, threat নয়। explanation নয়।"
    )
    user = f"Name 1: {left}\nName 2: {right}\nContext: {get_shift_context(sender_id)}\nOutput only roast."
    try:
        resp = await ai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=1.0,
            max_tokens=160,
        )
        return resp.choices[0].message.content.strip()[:700]
    except Exception:
        return fallback_dynamic_roast(left, f"{right} এর সাথে compare", memory_for(left), sender)


def normal_message_reply() -> str:
    options = [
        "এইটা সাধারণ কথা। কাউকে রোস্ট করতে চাইলে নামের সাথে কারণ লিখো।",
        "টার্গেট আর পয়েন্ট দাও, তারপর দেখি কার ফাপর কোথায় আটকায়।",
        "এভাবে হবে না—নাম + কারণ লিখো, যেমন: joni kaka faporbaj।",
    ]
    return random.choice(options)

# =========================================================
# COMMANDS
# =========================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "Roster Bot ready.\n"
        "Group normal message দেখতে BotFather থেকে privacy Disable করতে হবে।\n"
        "Use /help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "Commands\n"
        "/status\n"
        "/repair_on | /repair_off - admin only\n"
        "/lockgroup | /unlockgroup - admin only\n"
        "/normal_on | /normal_off - admin only\n"
        "/setgroup - current group allow, admin only\n"
        "/users - user list + shift\n"
        "/setuser USER_ID DAY_NAME NIGHT_NAME ROLE - admin only\n"
        "/shift name day|night|off - admin only\n"
        "/mem name text - memory save\n"
        "/save name text - memory save\n"
        "/memory name - memory দেখবে\n"
        "/forget name - memory delete, admin only\n"
        "/roast name optional reason\n"
        "/vs name1 name2\n\n"
        "Use\n"
        "joni kaka faporbaj\n"
        "surjo sobar taka khai\n"
        "joni vs mony\n"
        "কারো message-এ reply দিয়ে কারণ লিখবে"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    chat_id = update.effective_chat.id if update.effective_chat else 0
    await update.message.reply_text(
        f"Status\n"
        f"repair_mode: {'ON' if DATA.get('repair_mode') else 'OFF'}\n"
        f"group_lock: {'ON' if DATA.get('group_lock') else 'OFF'}\n"
        f"normal_reply: {'ON' if DATA.get('normal_reply') else 'OFF'}\n"
        f"ai_enabled: {'ON' if DATA.get('settings', {}).get('ai_enabled', True) else 'OFF'}\n"
        f"current_group: {chat_id}\n"
        f"group_allowed: {'YES' if allowed_group(chat_id) else 'NO'}\n"
        f"users: {len(DATA.get('users', {}))}\n"
        f"memory_targets: {len(DATA.get('memory', {}))}"
    )


async def cmd_repair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    cmd = strip_bot_suffix(update.message.text.split()[0].lower())
    DATA["repair_mode"] = cmd in ["/repair_on", "/repairon"] or (context.args and context.args[0].lower() == "on")
    save_data()
    await update.message.reply_text(f"Repair mode {'ON' if DATA['repair_mode'] else 'OFF'}")


async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    cmd = strip_bot_suffix(update.message.text.split()[0].lower())
    DATA["group_lock"] = cmd in ["/lockgroup", "/lock", "/lock_on"]
    save_data()
    await update.message.reply_text(f"Group lock {'ON' if DATA['group_lock'] else 'OFF'}")


async def cmd_normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    cmd = strip_bot_suffix(update.message.text.split()[0].lower())
    DATA["normal_reply"] = cmd in ["/normal_on", "/normalon"] or (context.args and context.args[0].lower() == "on")
    save_data()
    await update.message.reply_text(f"Normal reply {'ON' if DATA['normal_reply'] else 'OFF'}")


async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    chat_id = update.effective_chat.id
    DATA.setdefault("allowed_groups", [])
    if chat_id not in DATA["allowed_groups"]:
        DATA["allowed_groups"].append(chat_id)
    save_data()
    await update.message.reply_text(f"এই group allow করা হলো: {chat_id}")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    users = DATA.get("users", {})
    if not users:
        return await update.message.reply_text("No users saved yet.")
    lines = ["Users"]
    for uid, info in list(users.items())[-50:]:
        shift = DATA.get("shifts", {}).get(uid, "-")
        username = f"@{info.get('username')}" if info.get("username") else ""
        lines.append(f"{uid} | {info.get('name')} {username} | shift: {shift}")
    await update.message.reply_text("\n".join(lines)[:4000])


async def cmd_setuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    if len(context.args) < 4:
        return await update.message.reply_text("Use: /setuser USER_ID DAY_NAME NIGHT_NAME ROLE")
    uid, day_name, night_name, role = context.args[0], context.args[1], context.args[2], " ".join(context.args[3:])
    if not uid.lstrip("-").isdigit():
        return await update.message.reply_text("USER_ID number হতে হবে।")
    DATA.setdefault("users", {}).setdefault(uid, {"id": int(uid), "name": day_name, "username": ""})
    DATA["users"][uid].update({"day_name": day_name, "night_name": night_name, "role": role})
    DATA.setdefault("aliases", {})[normalize_key(day_name)] = uid
    DATA.setdefault("aliases", {})[normalize_key(night_name)] = uid
    save_data()
    await update.message.reply_text("User set done.")


async def cmd_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("এই command শুধু admin-এর জন্য।")
    if len(context.args) < 2:
        return await update.message.reply_text("Use: /shift name day|night|off")
    name = context.args[0]
    shift = context.args[1].lower()
    key = DATA.setdefault("aliases", {}).get(normalize_key(name), normalize_key(name))
    if shift == "off":
        DATA.setdefault("shifts", {}).pop(str(key), None)
    elif shift in ["day", "night"]:
        DATA.setdefault("shifts", {})[str(key)] = shift
    else:
        return await update.message.reply_text("shift হবে day/night/off")
    save_data()
    await update.message.reply_text("Shift updated.")


async def cmd_mem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    text = clean_text(" ".join(context.args))
    if not text or " " not in text:
        return await update.message.reply_text("Use: /mem name text")
    parts = text.split(" ", 1)
    name, info = parts[0], parts[1]
    # allow 2-word target if second word is kin/name hint and enough remaining
    toks = text.split()
    if len(toks) >= 3 and toks[1].lower() in NAME_HINT_WORDS:
        name = " ".join(toks[:2])
        info = " ".join(toks[2:])
    add_memory(name, info)
    await update.message.reply_text(f"Memory saved: {name}")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not context.args:
        return await update.message.reply_text("Use: /memory name")
    name = " ".join(context.args)
    mem = memory_for(name)
    if not mem:
        return await update.message.reply_text("এই target-এর কোনো memory নেই।")
    await update.message.reply_text(f"Memory: {name}\n" + "\n".join(f"- {m}" for m in mem[-10:]))


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("Memory delete শুধু admin করতে পারবে।")
    if not context.args:
        return await update.message.reply_text("Use: /forget name")
    name = " ".join(context.args)
    ok = delete_memory(name)
    await update.message.reply_text("Memory deleted." if ok else "এই নামে memory পাইনি।")


async def cmd_roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if repair_on():
        return
    if not context.args:
        return await update.message.reply_text("Use: /roast name reason")
    text = " ".join(context.args)
    target, point, mode = extract_target_and_point(text)
    if not target:
        toks = text.split()
        target = toks[0]
        point = " ".join(toks[1:]) or "memory"
    if protect_target(target):
        return await update.message.reply_text("Admin বা bot কে roast করা যাবে না।")
    mem = memory_for(target)
    if point == "memory" and not mem:
        return await update.message.reply_text(f"{target} সম্পর্কে roast করার মতো memory নেই। আগে /mem দিয়ে info save করো।")
    reply = await ai_roast(target, point, mem, display_name(update.effective_user), "command", update.effective_user.id)
    await update.message.reply_text(reply)


async def cmd_vs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if repair_on():
        return
    if len(context.args) < 2:
        return await update.message.reply_text("Use: /vs name1 name2")
    left = context.args[0]
    right = " ".join(context.args[1:])
    if protect_target(left) or protect_target(right):
        return await update.message.reply_text("Admin বা bot কে VS roast করা যাবে না।")
    reply = await ai_vs_roast(left, right, display_name(update.effective_user), update.effective_user.id)
    await update.message.reply_text(reply)

# =========================================================
# MESSAGE HANDLER
# =========================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    register_user(update.effective_user)

    chat = update.effective_chat
    text = clean_text(update.message.text or update.message.caption or "")
    if not text or URL_RE.search(text):
        return

    # ignore commands here
    if text.startswith("/"):
        return

    # groups only obey allowed group and lock
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if not allowed_group(chat.id):
            return
        if group_locked():
            return

    if repair_on():
        return

    reply_user = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        reply_user = update.message.reply_to_message.from_user

    target, point, mode = extract_target_and_point(text, reply_user)

    if mode == "vs" and target and point:
        if protect_target(target) or protect_target(point):
            return await update.message.reply_text("Admin বা bot কে roast করা যাবে না।")
        reply = await ai_vs_roast(target, point, display_name(update.effective_user), update.effective_user.id)
        return await update.message.reply_text(reply)

    # normal message
    if not target:
        if DATA.get("normal_reply", True):
            # avoid replying to every tiny normal chat in groups unless bot is mentioned/replied
            if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and len(tokenize(text)) < 3:
                return
            return await update.message.reply_text(normal_message_reply())
        return

    if protect_target(target):
        return await update.message.reply_text("Admin বা bot কে roast করা যাবে না।")

    mem = memory_for(target)
    if mode == "name_only" and not mem:
        return await update.message.reply_text(f"{target} সম্পর্কে roast করার মতো তথ্য নেই। আগে তার বিষয়ে কিছু বলো।")

    # Auto-save useful point as memory when insult/reason exists
    if has_insult_point(point) or has_insult_point(text):
        add_memory(target, point if point != "memory" else text)
        mem = memory_for(target)

    reply = await ai_roast(target, point, mem, display_name(update.effective_user), mode, update.effective_user.id)
    await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", context.error)

# =========================================================
# MAIN
# =========================================================
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler(["help"], cmd_help))
    app.add_handler(CommandHandler(["status"], cmd_status))

    app.add_handler(CommandHandler(["repair_on", "repair_off", "repair"], cmd_repair))
    app.add_handler(CommandHandler(["lockgroup", "unlockgroup", "lock", "unlock", "lock_on", "lock_off"], cmd_lock))
    app.add_handler(CommandHandler(["normal_on", "normal_off", "normal"], cmd_normal))
    app.add_handler(CommandHandler(["setgroup"], cmd_setgroup))

    app.add_handler(CommandHandler(["users"], cmd_users))
    app.add_handler(CommandHandler(["setuser"], cmd_setuser))
    app.add_handler(CommandHandler(["shift"], cmd_shift))

    app.add_handler(CommandHandler(["mem", "save"], cmd_mem))
    app.add_handler(CommandHandler(["memory"], cmd_memory))
    app.add_handler(CommandHandler(["forget", "delete", "delmem"], cmd_forget))
    app.add_handler(CommandHandler(["roast"], cmd_roast))
    app.add_handler(CommandHandler(["vs"], cmd_vs))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("Final AI Roast Bot running...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
