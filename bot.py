import os
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

MEMORY_FILE = "memory.json"
REPAIR_MODE = False

def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}, "group_settings": {}}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

memory = load_memory()

async def save_user_message(user_id, username, first_name, message_text):
    user_id_str = str(user_id)
    if user_id_str not in memory["users"]:
        memory["users"][user_id_str] = {
            "name": username or first_name or f"User_{user_id_str}",
            "messages": [],
            "flaws": []
        }
    
    memory["users"][user_id_str]["messages"].append({
        "text": message_text,
        "time": datetime.now().isoformat()
    })
    
    if len(memory["users"][user_id_str]["messages"]) > 50:
        memory["users"][user_id_str]["messages"] = memory["users"][user_id_str]["messages"][-50:]
    
    save_memory(memory)

async def extract_flaws_from_messages(user_messages, target_name):
    if not user_messages or len(user_messages) < 2:
        return None
    
    messages_text = "\n".join([f"- {m['text']}" for m in user_messages[-20:]])
    
    prompt = f"""তুমি একজন বিশ্লেষক। {target_name} এর নিচের কথাগুলো পড়ে তার দুর্বলতা, ভন্ডামি, ফাপরামি বের কর।
শুধু পয়েন্ট লিখো, এক লাইনে একটি।

{target_name} এর কথাবার্তা:
{messages_text}

পয়েন্টসমূহ:"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except:
        return None

async def generate_savage_roast(attacker_name, target_name, current_message, flaws_text):
    flaws_part = f"\n{target_name} এর দুর্বলতা: {flaws_text}" if flaws_text else ""
    
    prompt = f"""তুমি স্যাভেজ রোস্ট বট। {attacker_name} {target_name} কে বলেছে: "{current_message}"{flaws_part}

{target_name} এর হয়ে {attacker_name} কে একটি তীক্ষ্ণ বাংলা রোস্ট দাও (২-৩ লাইন):
"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"🃏 {attacker_name}, তোর রোস্ট দিতে API কাজ করছে না! 😂"

def has_targeting(text):
    keywords = ['তুই', 'তোকে', 'তোর', 'শালা', 'পাগলা', 'বোকা', 'ফাপর', 'রে', 'কনফিডেন্স']
    return any(k in text.lower() for k in keywords)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    
    if REPAIR_MODE:
        return
    
    message = update.message
    if not message or not message.text:
        return
    
    chat = message.chat
    sender = message.from_user
    text = message.text
    
    if chat.type not in ["group", "supergroup"]:
        return
    
    await save_user_message(sender.id, sender.username, sender.first_name, text)
    
    is_targeting = has_targeting(text)
    is_reply = message.reply_to_message is not None
    
    if not is_targeting and not is_reply:
        return
    
    target = None
    if is_reply and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    elif message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                target = entity.user
                break
    
    if not target:
        return
    
    if target.id == context.bot.id:
        await message.reply_text(f"🫡 {sender.first_name}, বটকে রোস্ট দিতে পারবি না!")
        return
    
    target_data = memory["users"].get(str(target.id), {})
    old_messages = target_data.get("messages", [])
    
    flaws_text = None
    if old_messages:
        flaws_text = await extract_flaws_from_messages(old_messages, target.first_name or target.username or "ওই ভাই")
    
    roast = await generate_savage_roast(
        sender.first_name or sender.username or "কে যেন",
        target.first_name or target.username or "ওই ভাই",
        text,
        flaws_text
    )
    
    await message.reply_text(f"🎯 {roast}")

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if update.effective_user.id != 777000:  # Telegram anonymous admin
        admins = await update.effective_chat.get_administrators()
        if update.effective_user.id not in [a.user.id for a in admins]:
            await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন।")
            return
    REPAIR_MODE = True
    await update.message.reply_text("🔧 রিপেয়ার মোড অন।")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if update.effective_user.id != 777000:
        admins = await update.effective_chat.get_administrators()
        if update.effective_user.id not in [a.user.id for a in admins]:
            await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন।")
            return
    REPAIR_MODE = False
    await update.message.reply_text("✅ রিপেয়ার মোড অফ।")

async def delete_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন।")
        return
    
    args = context.args
    if not args or args[0] != "all":
        await update.message.reply_text("⚠️ /deletememory all - সব মেমরি ডিলিট হবে")
        return
    
    memory["users"] = {}
    save_memory(memory)
    await update.message.reply_text("🗑️ সব মেমরি ডিলিট করা হয়েছে।")

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 কোনো ইউজার ডাটা নেই।")
        return
    
    lines = []
    for uid, data in list(memory["users"].items())[:15]:
        name = data.get("name", "নামবিহীন")
        msg_count = len(data.get("messages", []))
        lines.append(f"👤 {name} - {msg_count} টি মেসেজ")
    
    await update.message.reply_text("📋 ইউজার লিস্ট:\n" + "\n".join(lines))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **রোস্টার বট চালু!**\n\n"
        "কেউ কাউকে টার্গেট করলেই বট রোস্ট দেবে।\n\n"
        "**কমান্ড:**\n"
        "/repair_on - বট বন্ধ\n"
        "/repair_off - বট চালু\n"
        "/deletememory all - সব ডাটা ডিলিট\n"
        "/users - ইউজার লিস্ট দেখুন",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("deletememory", delete_memory))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot is starting...")
    print(f"Token: {BOT_TOKEN[:10]}...")
    
    app.run_polling()

if __name__ == "__main__":
    main()
