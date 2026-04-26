import os
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ChatMember
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
            "points": []
        }
    
    memory["users"][user_id_str]["messages"].append({
        "text": message_text,
        "time": datetime.now().isoformat()
    })
    
    # Keep last 50 messages only
    if len(memory["users"][user_id_str]["messages"]) > 50:
        memory["users"][user_id_str]["messages"] = memory["users"][user_id_str]["messages"][-50:]
    
    save_memory(memory)

async def extract_points_from_messages(user_messages, target_name):
    if not user_messages:
        return None
    
    messages_text = "\n".join([m["text"] for m in user_messages[-30:]])
    
    prompt = f"""তুমি একজন স্যাভেজ রোস্ট বট। নিচে {target_name} এর কিছু পুরনো কথাবার্তা দেওয়া আছে। 
এই কথাগুলো থেকে {target_name} এর দুর্বলতা, অদ্ভুত আচরণ, ফাপরামি, ভুল তথ্য, বা মজার পয়েন্ট বের করে একটি লিস্ট তৈরি কর।

প্রতিটি পয়েন্ট হবে ছোট, তীক্ষ্ণ, এবং রোস্ট করার উপযোগী। শুধু পয়েন্টগুলো দাও, এক লাইনে একটিমাত্র পয়েন্ট।

{target_name} এর কথাবার্তা:
{messages_text}

পয়েন্ট লিস্ট:
"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=300
        )
        points = response.choices[0].message.content.strip()
        return points
    except:
        return None

async def generate_roast(target_name, target_id, attacker_name, current_message, memory_points=None):
    target_id_str = str(target_id)
    user_memory = memory["users"].get(target_id_str, {})
    old_messages = user_memory.get("messages", [])
    
    memory_text = ""
    if old_messages and memory_points:
        memory_text = f"\n\n{target_name} এর পুরনো কথার ভিত্তিতে পাওয়া পয়েন্ট:\n{memory_points}"
    
    prompt = f"""তুমি "রোস্টার বট" — একজন উর্দু-বাংলা মিক্স স্যাভেজ কমেডিয়ান। তুমি তীক্ষ্ণ, মজার, এবং একদম গায়ে লাগানো রোস্ট দাও।

{attacker_name} {target_name} কে টার্গেট করে বলেছে: "{current_message}"

{memory_text}

এখন {target_name} এর হয়ে {attacker_name} কে একটি স্যাভেজ রোস্ট দাও। রোস্ট হবে:
- সম্পূর্ণ বাংলায় (সাবলীল, তীক্ষ্ণ, আঞ্চলিক মেশানো যেতে পারে)
- নাম ধরে টার্গেট করে
- short and punchy (২-৩ লাইনের বেশি না)
- পুরনো পয়েন্ট ব্যবহার করে যদি থাকে
- একদম জ্বালাতন করা টাইপের

রোস্ট:
"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=200
        )
        roast = response.choices[0].message.content.strip()
        return roast
    except Exception as e:
        return f"🃏 {attacker_name}, তোর কিল দিবো কিন্তু API তো গেলো! 😂"

async def contains_targeting(text):
    targeting_patterns = [
        "তুই", "তোকে", "তোর", "তোরা",
        "@", "রে", "পাগলা", "বোকা", "ফাপর", "চুপ", "শালা"
    ]
    return any(p in text for p in targeting_patterns)

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
    
    # Save user message to memory
    await save_user_message(
        sender.id, 
        sender.username, 
        sender.first_name, 
        text
    )
    
    # Check if someone is targeting someone
    is_targeting = await contains_targeting(text.lower())
    is_reply = message.reply_to_message is not None
    
    if not is_targeting and not is_reply:
        return
    
    # Determine target and attacker
    if is_reply and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        attacker = sender
        target_message = text
    elif is_targeting:
        # Find mentioned user or assume last message sender
        target = None
        if message.entities:
            for entity in message.entities:
                if entity.type == "text_mention":
                    target = entity.user
                    break
        if not target:
            target = sender  # fallback: roasting themselves? use attacker as target
            attacker = sender
        target_message = text
    else:
        return
    
    if target.id == context.bot.id:
        await message.reply_text(f"🫡 {sender.first_name}, আমি বট তোকে ফুটাও? নিজের মিরর দেখ নে।")
        return
    
    # Get target's memory points
    target_id_str = str(target.id)
    user_memory = memory["users"].get(target_id_str, {})
    old_messages = user_memory.get("messages", [])
    
    memory_points = None
    if old_messages:
        memory_points = await extract_points_from_messages(old_messages, target.first_name or target.username or "উস)খালা")
    
    # Generate roast from target's perspective to attacker
    roast = await generate_roast(
        target.first_name or target.username or "ওই যে",
        target.id,
        sender.first_name or sender.username or "কে যেন",
        text,
        memory_points
    )
    
    # Save the roast point back to memory for future
    if memory_points:
        if "points" not in memory["users"].get(target_id_str, {}):
            memory["users"].setdefault(target_id_str, {}).setdefault("points", [])
        memory["users"][target_id_str]["points"].append({
            "roast": roast,
            "time": datetime.now().isoformat()
        })
        save_memory(memory)
    
    await message.reply_text(f"🎯 {roast}")

# Admin Commands
async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if update.effective_user.id not in [admin.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন রিপেয়ার মোড অন করতে পারে।")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔧 রিপেয়ার মোড অন। বট কিছু করবে না।")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if update.effective_user.id not in [admin.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন রিপেয়ার মোড অফ করতে পারে।")
        return
    REPAIR_MODE = False
    await update.message.reply_text("✅ রিপেয়ার মোড অফ। বট আবার সচল।")

async def delete_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in [admin.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন মেমরি ডিলিট করতে পারে।")
        return
    args = context.args
    if not args:
        await update.message.reply_text("!deletememory @username অথবা !deletememory all")
        return
    if args[0] == "all":
        memory["users"] = {}
        save_memory(memory)
        await update.message.reply_text("🗑️ সব ইউজারের মেমরি ডিলিট করা হয়েছে।")
    else:
        await update.message.reply_text("কোনো ইউজারনির্দিষ্ট ডিলিট ফিচার পরে যোগ করুন।")

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 এখনো কোনো ইউজারের ডাটা নেই।")
        return
    user_list = "\n".join([f"👤 {u.get('name', 'নামবিহীন')} - {len(u.get('messages', []))} টি মেসেজ" for u in memory["users"].values()][:20])
    await update.message.reply_text(f"📋 ইউজার লিস্ট:\n{user_list}")

async def group_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔒 গ্রুপ লক ফিচার: বট সব গ্রুপে সক্রিয়। সীমিত করতে চাইলে পরে।")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("deletememory", delete_memory))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(CommandHandler("grouplock", group_lock))
    
    print("🤖 বট চালু হয়েছে...")
    app.run_polling()

if __name__ == "__main__":
    main()
