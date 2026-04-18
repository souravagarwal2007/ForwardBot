import asyncio
import os
import json
import logging
import re
from pyrogram import Client, filters, errors
from info import API_ID, API_HASH, SESSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

CONFIG_FILE = "forwarder_config.json"
PROGRESS_FILE = "forwarder_progress.json"
BATCH_SIZE = 100
SLEEP_BETWEEN_BATCHES = 4

# Initialize Client
app = Client(
    "ForwarderSession",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION
)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    # Default configs if file doesn't exist yet
    return {"SOURCE_CHANNELS": [-1002480896027], "DESTINATION_CHANNEL": -1003816028004}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

config = load_config()

# Helper to dynamically check if a chat is in source channels
def is_source(_, __, message):
    if not message.chat:
        return False
    return message.chat.id in config["SOURCE_CHANNELS"]

source_filter = filters.create(is_source)


# ---------------- INTERACTIVE COMMANDS ----------------

@app.on_message(filters.me & filters.command("setdump", prefixes=["/", ".", "!"]))
async def set_dump(client, message):
    try:
        chat_id = int(message.command[1])
        config["DESTINATION_CHANNEL"] = chat_id
        save_config(config)
        await message.reply_text(f"✅ Dump channel set to `{chat_id}`")
    except Exception:
        await message.reply_text("Usage: `/setdump <chat_id>`\nExample: `/setdump -100123456789`")

@app.on_message(filters.me & filters.command("addsource", prefixes=["/", ".", "!"]))
async def add_source(client, message):
    try:
        chat_id = int(message.command[1])
        if chat_id not in config["SOURCE_CHANNELS"]:
            config["SOURCE_CHANNELS"].append(chat_id)
            save_config(config)
        await message.reply_text(f"✅ Added `{chat_id}` to source channels.")
    except Exception:
        await message.reply_text("Usage: `/addsource <chat_id>`")

@app.on_message(filters.me & filters.command("rmsource", prefixes=["/", ".", "!"]))
async def rm_source(client, message):
    try:
        chat_id = int(message.command[1])
        if chat_id in config["SOURCE_CHANNELS"]:
            config["SOURCE_CHANNELS"].remove(chat_id)
            save_config(config)
            await message.reply_text(f"✅ Removed `{chat_id}` from source channels.")
        else:
            await message.reply_text("❌ Channel not found in source list.")
    except Exception:
        await message.reply_text("Usage: `/rmsource <chat_id>`")

@app.on_message(filters.me & filters.command("status", prefixes=["/", ".", "!"]))
async def status_cmd(client, message):
    text = f"**Forwarder Engine Status:**\n\n"
    text += f"**Dump (Destination) Channel:** `{config.get('DESTINATION_CHANNEL', 'Not Set')}`\n\n"
    text += f"**Source Channels (Listening Active):**\n"
    sources = config.get("SOURCE_CHANNELS", [])
    if not sources:
        text += "- None\n"
    for s in sources:
        text += f"- `{s}`\n"
        
    await message.reply_text(text)

@app.on_message(filters.me & filters.command("forwardfrom", prefixes=["/", ".", "!"]))
async def forward_from(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/forwardfrom <telegram_message_link>`\nExample: `/forwardfrom https://t.me/c/-100.../50`")
        
    link = message.command[1]
    
    # Regex to extract Chat ID and Message ID from the Telegram link
    match = re.match(r"(https?://)?([tT]\.[mM][eE]/|telegram\.[mM][eE]/|telegram\.dog/)(c/)?([^/]+)/(\d+)", link)
    if not match:
        return await message.reply_text("❌ Invalid Telegram message link.")
        
    is_private = match.group(3) is not None
    chat_username_or_id = match.group(4)
    start_msg_id = int(match.group(5))
    
    if is_private and chat_username_or_id.isdigit():
        chat_id = int("-100" + chat_username_or_id)
    else:
        try:
            chat_id = int(chat_username_or_id)
        except ValueError:
            chat_id = chat_username_or_id # It's a public @username

    if not config.get("DESTINATION_CHANNEL"):
        return await message.reply_text("❌ No dump channel set! Use `/setdump` first.")

    await message.reply_text(f"⏳ **Batch Forward Started!**\n\n- Source Chat: `{chat_id}`\n- Starting from message ID: `{start_msg_id}`\n\nI will continue running this in the background!")
    
    # Run the batch forward in the background so the script doesn't freeze and can still process real-time messages!
    asyncio.create_task(run_batch_forward(chat_id, start_msg_id, message))


# ---------------- BACKGROUND BATCH TASK ----------------

async def run_batch_forward(source_chat, start_msg_id, reply_message):
    try:
        latest_id = 0
        async for msg in app.get_chat_history(source_chat, limit=1):
            latest_id = msg.id
            break
            
        if latest_id == 0:
            return await reply_message.reply_text(f"❌ Failed to get latest message from `{source_chat}`. Either it's empty or I lack access.")

        progress = load_progress()
        dest_channel = config["DESTINATION_CHANNEL"]
        
        logging.info(f"Batch Task: Target range {start_msg_id} -> {latest_id}")
        
        for start_id in range(start_msg_id, latest_id + 1, BATCH_SIZE):
            end_id = min(start_id + BATCH_SIZE - 1, latest_id)
            msg_ids = list(range(start_id, end_id + 1))
            
            while True:
                try:
                    logging.info(f"Batch Task: Forwarding messages {msg_ids[0]} to {msg_ids[-1]}...")
                    await app.forward_messages(
                        chat_id=dest_channel,
                        from_chat_id=source_chat,
                        message_ids=msg_ids,
                        drop_author=True  # Hides forwarded-from tag
                    )
                    break 
                except errors.FloodWait as e:
                    wait_time = e.value + 5
                    logging.warning(f"Batch Task: FloodWait hit! Sleeping for {wait_time} seconds.")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    logging.error(f"Batch Task: Failed to forward chunk. Ignoring and proceeding past it... {e}")
                    break
            
            progress[f"{source_chat}_manual"] = end_id
            save_progress(progress)
            await asyncio.sleep(SLEEP_BETWEEN_BATCHES)

        await reply_message.reply_text(f"✅ **Batch Forward Complete!**\nCaught up to the latest message (`{latest_id}`) in chat `{source_chat}`.")
        
    except Exception as e:
        await reply_message.reply_text(f"❌ Error during batch forward process: `{e}`")


# ---------------- REAL-TIME ACTIVE LISTENER ----------------

@app.on_message(source_filter & ~filters.me)
async def realtime_listener(client, message):
    dest = config.get("DESTINATION_CHANNEL")
    if not dest:
        return
        
    try:
        # Directly copying/forwarding the incoming new message
        await message.forward(
            chat_id=dest,
            drop_author=True  # Ensures no 'Forwarded from' tag on real-time uploads
        )
        logging.info(f"Real-time: Forwarded new incoming upload (ID: {message.id}) from {message.chat.id}")
    except errors.FloodWait as e:
        await asyncio.sleep(e.value + 2)
        await message.forward(chat_id=dest, drop_author=True)
    except Exception as e:
        logging.error(f"Real-time forward failed: {e}")


async def main():
    await app.start()
    logging.info("Fetching dialogs to prime peer cache (Fixes 'Peer id invalid' crash)...")
    try:
        async for _ in app.get_dialogs():
            pass
    except Exception as e:
        logging.warning(f"Dialog fetch error (safe to ignore): {e}")
        
    logging.info("Forwarder active! Listening for commands in Saved Messages...")
    # Keep the bot running
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    logging.info("Starting Fully Interactive Forwarder Userbot...")
    app.run(main())
