import os
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

MEMORY_FILE = "memory.json"
REPAIR_MODE = False

def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

memory = load_memory()

async def save_message(uid, name, text):
    uid = str(uid)
    if uid not in memory["users"]:
        memory["users"][uid] = {"name": name, "messages": []}
    
    memory["users"][uid]["messages"].append({"text": text, "time": datetime.now().isoformat()})
    
    if len(memory["users"][uid]["messages"]) > 30:
        memory["users"][uid]["messages"] = memory["users"][uid]["messages"][-30:]
    
    save_memory(memory)

def is_targeting(text):
    targets = ['তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'গাধা', 'ফাপর', 
               'বাজে', 'রে', 'নিয়া', 'নিয়ে', 'কথা', 'বলেন', 'বলো', 'গাদা', 
               'পোলা', 'ভাই', 'কি বলছিস', 'কী বলছ', 'monir', 'joni', 'akta', 'gadha',
               'niye', 'kichu', 'bolen', 'faltu', 'bot', 'take', 'rost', 'kor']
    t = text.lower()
    return any(x in t for x in targets)

async def generate_roast(attacker_name, target_name, user_message, old_messages):
    """শুধু বিশুদ্ধ বাংলায় রোস্ট"""
    
    # পুরনো মেসেজ থেকে পয়েন্ট বের করে
    memory_hint = ""
    if old_messages and len(old_messages) > 2:
        recent = old_messages[-8:]
        interesting = [m['text'] for m in recent if len(m['text']) > 5]
        if interesting:
            memory_hint = f"\n\n{target_name} এর আগের কিছু বাক্য: " + " | ".join(interesting[:3])
    
    prompt = f"""তুমি একজন সাহসী বাংলা রোস্টার। নিচের নিয়মগুলো কঠোরভাবে মেনে চলবে:

নিয়ম:
1. শুধু বিশুদ্ধ বাংলা ভাষায় উত্তর দেবে - একটাও ইংরেজি/হিন্দি/উর্দু শব্দ ব্যবহার করবে না
2. 'তুই', 'তোর' ব্যবহার করবে
3. প্রতিটি রোস্ট হবে ২ লাইনের
4. শেষ লাইনে একটা কিলার punchline দেবে

এখন {attacker_name} {target_name} কে বলেছে: "{user_message}"{memory_hint}

{target_name} এর হয়ে {attacker_name} কে একটি স্যাভেজ রোস্ট দাও:

উদাহরণ (এই স্টাইলে):
"জনি কাকা, তোর কনফিডেন্স দেখে মনে হয় গ্রুপের সিইও অথচ কাজের বেলায় নেটওয়ার্কের বাইরে।
তোর চেয়ে গ্রুপের 'বট' বেশি কাজ করে রে ভাই!"

এখন তোর রোস্ট দে:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "তুমি শুধু বাংলা ভাষায় উত্তর দেবে। কোনো মিক্সড ল্যাঙ্গুয়েজ নয়। তুমি মজার স্যাভেজ রোস্টার।"},
                {"role": "user", "content": prompt}
            ],
            temperature=1.1,
            max_tokens=180
        )
        roast = response.choices[0].message.content.strip()
        
        # ফিল্টার: যদি ইংরেজি/হিন্দি বেশি থাকে তাহলে ডিফল্ট
        english_chars = sum(1 for c in roast if ord(c) < 128 and c.isalpha())
        if english_chars > 20:
            return f"{attacker_name}, তুই এত ফাপর যে রোস্ট দিতে বটের ভাষাই হারিয়ে গেল! 🤣"
        
        return roast
    except:
        return f"🃏 {attacker_name}, তোর মতো ফাপরবাজ আগে দেখি নাই বলেই API কান্না করছে! 😂"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    
    if REPAIR_MODE:
        return
    
    m = update.message
    if not m or not m.text:
        return
    
    chat = m.chat
    if chat.type not in ["group", "supergroup"]:
        return
    
    sender = m.from_user
    text = m.text
    
    if text.startswith('/'):
        return
    
    await save_message(sender.id, sender.first_name or sender.username or "কে যেন", text)
    
    # টার্গেট চেক
    is_target = is_targeting(text.lower())
    is_reply = m.reply_to_message is not None
    
    if not is_target and not is_reply:
        return
    
    # টার্গেট বের করো
    target = None
    if is_reply and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
    elif m.entities:
        for e in m.entities:
            if e.type == "text_mention":
                target = e.user
                break
    
    if not target:
        # টেক্সট থেকে নাম বের করার চেষ্টা
        words = text.lower().split()
        for w in words:
            if w in ['monir', 'joni', 'alpha', 'mehedi', 'রবি', 'জনি', 'মনির']:
                # সিমুলেটেড টার্গেট - রিপ্লাই না থাকলে সেন্ডারকেই ধরো
                target = sender
                break
        if not target:
            target = sender
    
    if target.id == context.bot.id:
        await m.reply_text(f"🫡 {sender.first_name}, বটের পিছনে না লেগে আগে নিজের দাগ দেখো!")
        return
    
    # টার্গেটের পুরনো মেসেজ
    target_uid = str(target.id)
    old_msgs = memory["users"].get(target_uid, {}).get("messages", [])
    
    # রোস্ট জেনারেট
    roast = await generate_roast(
        sender.first_name or sender.username or "কে যেন",
        target.first_name or target.username or target.first_name or "ওই ভাই",
        text,
        old_msgs
    )
    
    await m.reply_text(f"🎯 {roast}")

# ========== কমান্ড ==========

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Bangla Savage Roast Bot**\n\n"
        "কে কাউকে কিছু বললেই বট চরম রোস্ট দেবে!\n\n"
        "📌 **কমান্ড:**\n"
        "/repair_on - বট বন্ধ\n"
        "/repair_off - বট চালু\n"
        "/clear - সব মেমরি ডিলিট\n"
        "/users - ইউজার লিস্ট\n"
        "/status - বট স্ট্যাটাস",
        parse_mode="Markdown"
    )

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন নয়")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔴 রিপেয়ার মোড অন - বট বন্ধ")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন নয়")
        return
    REPAIR_MODE = False
    await update.message.reply_text("🟢 রিপেয়ার মোড অফ - বট চালু")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন নয়")
        return
    global memory
    memory = {"users": {}}
    save_memory(memory)
    await update.message.reply_text("🗑️ সব মেমরি ডিলিট")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 কোনো ডাটা নাই")
        return
    lines = []
    for uid, data in list(memory["users"].items())[:15]:
        name = data.get("name", "নামবিহীন")
        msg_count = len(data.get("messages", []))
        lines.append(f"👤 {name} - {msg_count}টি মেসেজ")
    await update.message.reply_text("📋 ইউজার লিস্ট:\n" + "\n".join(lines))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uc = len(memory["users"])
    mc = sum(len(u.get("messages", [])) for u in memory["users"].values())
    mode = "🔧 রিপেয়ার" if REPAIR_MODE else "✅ নরমাল"
    await update.message.reply_text(f"📊 স্ট্যাটাস\n👥 ইউজার: {uc}\n💬 মেসেজ: {mc}\n⚙️ মোড: {mode}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    
    print("✅ বাংলা স্যাভেজ বট চালু...")
    app.run_polling()

if __name__ == "__main__":
    main()
