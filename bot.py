import os
import random
import json
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

MEMORY_FILE = "god_memory.json"

# ================= MEMORY =================
def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

memory = load_memory()

# ================= CONFIG =================
ADMIN_NAMES = ["alpha", "alfa", "admin", "alphA"]

PRESET_MEMORY = {
    "monir": "নিজেকে বুদ্ধিমান ভাবে কিন্তু কিছু না",
    "joni": "ফাফরবাজ",
    "mony": "গাঁজা আর মলম বিক্রেতা",
    "alon": "হুতাসে চলে",
    "surjo": "অলস আর bathroom lover"
}

# ================= AI ROAST =================
async def ai_roast(target, msg, extra):
    prompt = f"""
তুমি একটি savage বাংলা roast bot।

Target: {target}
Message: {msg}
Extra Info: {extra}

নিয়ম:
- ২ লাইনের মধ্যে
- তীক্ষ্ণ, অপমানজনক কিন্তু গালি সহ 
- pure বাংলা
- শেষে killer punchline

রোস্ট দাও:
"""
    try:
        res = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.2,
            max_tokens=120
        )
        return res.choices[0].message.content.strip()
    except:
        return f"{target} আবার শুরু করছে—কথা বেশি, কাজ শূন্য। classic useless system।"

# ================= HELPER =================
def get_name(user):
    return user.first_name.lower()

def detect_target(text, reply_user):
    words = text.split()

    if reply_user:
        return get_name(reply_user)

    if len(words) > 0:
        return words[0].lower()

    return None

# ================= MAIN =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.lower()
    sender = msg.from_user
    sender_name = get_name(sender)

    # ===== SAVE MEMORY =====
    if sender_name not in memory:
        memory[sender_name] = []
    memory[sender_name].append(text)
    memory[sender_name] = memory[sender_name][-20:]
    save_memory(memory)

    # ===== ADMIN PROTECT =====
    if any(a in text for a in ADMIN_NAMES):
        await msg.reply_text("Admin নিয়ে কথা বলার আগে নিজের লেভেলটা চেক করো।")
        return

    if "ke baniyese" in text or "who made" in text:
        await msg.reply_text("এই বটটা AlphA বানিয়েছে—লেভেল বুঝে কথা বলো।")
        return

    # ===== PRAISE RESPONSE =====
    if "valo" in text or "good" in text:
        await msg.reply_text("তেল মারিস না, কাজে দেখাইলে বুঝবো।")
        return

    # ===== TARGET =====
    reply_user = msg.reply_to_message.from_user if msg.reply_to_message else None
    target = detect_target(text, reply_user)

    if not target:
        return

    if target in ADMIN_NAMES:
        return

    # ===== EXTRA INFO =====
    extra = ""

    if target in PRESET_MEMORY:
        extra += PRESET_MEMORY[target]

    if target in memory:
        extra += " ".join(memory[target][-5:])

    # ===== GENERATE ROAST =====
    roast = await ai_roast(target, text, extra)

    await msg.reply_text(roast)

# ================= RUN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🔥 GOD LEVEL BOT RUNNING 🔥")
    app.run_polling()

if __name__ == "__main__":
    main()
