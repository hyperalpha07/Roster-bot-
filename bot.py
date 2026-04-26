import os
import json
import asyncio
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
    if not user_messages or len(user_messages) < 3:
        return None
    
    messages_text = "\n".join([f"- {m['text']}" for m in user_messages[-30:]])
    
    prompt = f"""তুমি একজন সাইকোলজিকাল অ্যানালিস্ট। {target_name} এর নিচের কথাগুলো পড়ে তার দুর্বলতা, ভন্ডামি, ফাপরামি, অতিরিক্ত আত্মবিশ্বাস, বোকামি, বা মজার অভ্যাস বের কর।

শুধু পয়েন্টগুলো লিখবি, এক লাইনে একটি পয়েন্ট। কোনো ব্যাখ্যা নয়। তীক্ষ্ণ, ব্যাঙ্গাত্মক, এবং রোস্টের উপযোগী করে লিখবি।

{target_name} এর কথাবার্তা:
{messages_text}

{target_name} এর দুর্বলতা/ফাপরামির পয়েন্টসমূহ:
"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",  # GPT-4 for better roast
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        # Fallback to GPT-3.5 if GPT-4 fails
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except:
            return None

async def generate_savage_roast(attacker_name, target_name, current_message, flaws_text, chat_history):
    prompt = f"""তুই "স্যাভেজ রোস্ট বট" — বাংলার সবচেয়ে গালিগালাজহীন কিন্তু তীক্ষ্ণ কমেডিয়ান। তোর রোস্ট হবে একদম কস্টিক, ব্যাঙ্গাত্মক, এবং নাম ধরে টার্গেট করা।

পরিস্থিতি: {attacker_name} {target_name} কে টার্গেট করে বলেছে: "{current_message}"

{target_name} এর পুরনো দুর্বলতা/ফাপরামি যা তুই ইউজ করতে পারবি:
{flaws_text if flaws_text else "কোনো পুরনো ডাটা নেই"}

এখন {target_name} এর হয়ে {attacker_name} কে একটি স্যাভেজ রোস্ট দে। নিয়ম:
- শুধু বাংলা, বানান ঠিক রাখবি
- নাম ধরে (যেমন: "হায়দার, তুই...")
- ২-৪ লাইনের বেশি না
- পুরনো পয়েন্ট ইউজ করবি যদি থাকে
- গালি দিবি না, তীব্র ব্যাঙ্গ দিবি
- শুরুতেই জোরালো আঘাত দিবি
- শেষ করতে পারিস একটি কিলার লাইন দিয়ে

উদাহরণ স্টাইল:
"জনি কাকা, তোর কনফিডেন্স দেখে মনে হয় গ্রুপের সিইও, কিন্তু কাজের বেলায় নেটওয়ার্কের বাইরে। তোর সেই 'আমি পারি' আবার শুনলাম? আগে নিজের পারফরম্যান্স রিপোর্ট দে ভাই।"

এখন {attacker_name} কে তোর রোস্ট দে:
"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.1,
            max_tokens=250
        )
        return response.choices[0].message.content.strip()
    except:
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=1.1,
                max_tokens=250
            )
            return response.choices[0].message.content.strip()
        except:
            return f"🃏 {attacker_name}, তোর রোস্ট দেওয়ার মতো শব্দ বাংলা ডিকশনারিতে নাই বলেই API গেলো! 😂"

def has_targeting(text):
    targeting_words = ['তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'ফাপর', 'চুপ', 'বস', 'আয়', 'দেখ', 'শুন', 'রে', 'কি বলছিস', 'কী বলছ', 'অভিনয়', 'নাটক', 'কনফিডেন্স', 'সিইও', 'নেটওয়ার্ক']
    text_lower = text.lower()
    return any(word in text_lower for word in targeting_words)

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
    
    # Check if targeting someone
    is_targeting = has_targeting(text)
    is_reply = message.reply_to_message is not None
    
    if not is_targeting and not is_reply:
        return
    
    # Determine target
    target = None
    attacker = sender
    
    if is_reply and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    elif message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                target = entity.user
                break
    
    if not target and is_targeting:
        # Try to find @username in text
        words = text.split()
        for word in words:
            if word.startswith('@'):
                username = word[1:]
                # Could look up, but skip for now
        if not target:
            return  # Can't determine target
    
    if not target:
        return
    
    # Don't roast the bot
    if target.id == context.bot.id:
        await message.reply_text(f"🫡 {sender.first_name}, বটকে রোস্ট করতে চাস? আগে নিজের দাগ দেখ।")
        return
    
    # Don't roast admin if protected (optional)
    # Get target's flaws from memory
    target_id_str = str(target.id)
    target_data = memory["users"].get(target_id_str, {})
    old_messages = target_data.get("messages", [])
    existing_flaws = target_data.get("flaws", [])
    
    # Extract new flaws from messages
    flaws_text = None
    if old_messages:
        new_flaws = await extract_flaws_from_messages(old_messages, target.first_name or target.username or "ওই ব্যক্তি")
        if new_flaws:
            flaws_text = new_flaws
            # Store flaws for future
            if "flaws" not in memory["users"].get(target_id_str, {}):
                memory["users"].setdefault(target_id_str, {})["flaws"] = []
            memory["users"][target_id_str]["flaws"].append({
                "text": new_flaws,
                "time": datetime.now().isoformat()
            })
            save_memory(memory)
    
    # If we have stored flaws, use them
    if existing_flaws and not flaws_text:
        latest_flaw = existing_flaws[-1].get("text") if existing_flaws else None
        flaws_text = latest_flaw
    
    target_name = target.first_name or target.username or "ওই ভাই"
    attacker_name = sender.first_name or sender.username or "কে যেন"
    
    roast = await generate_savage_roast(attacker_name, target_name, text, flaws_text, old_messages)
    
    await message.reply_text(f"🎯 {roast}")

# ============ ADMIN COMMANDS ============

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if not update.effective_user:
        return
    admins = await update.effective_chat.get_administrators()
    admin_ids = [a.user.id for a in admins]
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text("👑 শুধু অ্যাডমিন রিপেয়ার মোড অন করতে পারে।")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔧 রিপেয়ার মোড অন। বট কিছু করবে না।")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if not update.effective_user:
        return
    admins = await update.effective_chat.get_administrators()
    admin_ids = [a.user.id for a in admins]
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text("👑 শুধু অ্যাডমিন রিপেয়ার মোড অফ করতে পারে।")
        return
    REPAIR_MODE = False
    await update.message.reply_text("✅ রিপেয়ার মোড অফ। বট আবার সচল।")

async def delete_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    admins = await update.effective_chat.get_administrators()
    admin_ids = [a.user.id for a in admins]
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text("👑 শুধু অ্যাডমিন মেমরি ডিলিট করতে পারে।")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ ব্যবহার: /deletememory @username অথবা /deletememory all")
        return
    
    if args[0] == "all":
        memory["users"] = {}
        save_memory(memory)
        await update.message.reply_text("🗑️ সব ইউজারের মেমরি পুরোপুরি ডিলিট করা হয়েছে।")
    else:
        target_name = args[0].replace('@', '')
        found = None
        for uid, udata in memory["users"].items():
            if udata.get("name", "").lower() == target_name.lower():
                found = uid
                break
        if found:
            del memory["users"][found]
            save_memory(memory)
            await update.message.reply_text(f"🗑️ @{target_name} এর মেমরি ডিলিট করা হয়েছে।")
        else:
            await update.message.reply_text(f"❌ @{target_name} পাওয়া যায়নি।")

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 এখনো কোনো ইউজারের ডাটা নেই।")
        return
    
    user_list = []
    for uid, udata in list(memory["users"].items())[:15]:
        name = udata.get("name", "নামবিহীন")
        msg_count = len(udata.get("messages", []))
        flaw_count = len(udata.get("flaws", []))
        user_list.append(f"👤 {name} - {msg_count} টি মেসেজ, {flaw_count} টি দুর্বলতা")
    
    await update.message.reply_text(f"📋 ইউজার লিস্ট:\n\n" + "\n".join(user_list))

async def group_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 গ্রুপ লক বর্তমানে: **সব গ্রুপে সক্রিয়**\n\n"
        "লক করতে: /lockgroup\n"
        "আনলক করতে: /unlockgroup"
    )

async def roastme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """যখন কেউ নিজে রোস্ট চায়"""
    user = update.effective_user
    await update.message.reply_text(
        f"🤣 {user.first_name}, তুই নিজে রোস্ট খেতে চাস? এই নে:\n\n"
        f"তোর কনফিডেন্স দেখে মনে হয় গ্রুপের বাদশা, কিন্তু আসলেই তুই বাটপার। 😂"
    )

async def vs_roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """দুই জনের মধ্যে VS রোস্ট"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("ব্যবহার: /vs @username1 @username2")
        return
    
    user1 = args[0].replace('@', '')
    user2 = args[1].replace('@', '')
    
    roast = f"💥 VS রোস্ট: {user1} আর {user2} — দুইজনেই ফাপরবাজ। একজন কনফিডেন্স দেয়, আরেকজন এক্সকিউজ। গ্রুপের ভাগ্য ভালো যে এরা একসাথে কিছু করে না!"
    await update.message.reply_text(roast)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("deletememory", delete_memory))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(CommandHandler("grouplock", group_lock))
    app.add_handler(CommandHandler("roastme", roastme))
    app.add_handler(CommandHandler("vs", vs_roast))
    
    print("🤖 স্যাভেজ রোস্ট বট চালু হয়েছে...")
    print(f"বট টোকেন: {BOT_TOKEN[:10]}...")
    app.run_polling()

if __name__ == "__main__":
    main()
