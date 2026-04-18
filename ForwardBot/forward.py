import asyncio
import os
import json
import logging
from pyrogram import Client, errors
from info import API_ID, API_HASH, SESSION

# Configuration
SOURCE_CHANNELS = [-1002480896027]  # Channels to forward FROM
DESTINATION_CHANNEL = -1003816028004  # Channel to forward TO
PROGRESS_FILE = "forwarder_progress.json"

# Settings for performance and flood safety
BATCH_SIZE = 100
SLEEP_BETWEEN_BATCHES = 4  # Wait seconds between sending batches to avoid bans

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize the User Session
app = Client(
    "ForwarderSession",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION,
    no_updates=True  # We don't need update handling for a pure forwarder
)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

async def get_latest_msg_id(chat_id):
    """Fetches the highest message ID in the channel"""
    async for msg in app.get_chat_history(chat_id, limit=1):
        return msg.id
    return 0

async def main():
    logging.info("Starting up forwarder session...")
    await app.start()
    progress = load_progress()
    
    for source in SOURCE_CHANNELS:
        logging.info(f"Processing source channel: {source}")
        
        last_forwarded_id = progress.get(str(source), 0)
        latest_id = await get_latest_msg_id(source)
        
        if latest_id == 0:
            logging.info(f"Could not get latest message id automatically, skipping channel {source}. (Make sure your session has joined this channel)")
            continue

        logging.info(f"Target range: Message IDs from {last_forwarded_id} to {latest_id}")
        
        # We process purely by iterating sequential message IDs instead of fetching the entire history.
        # This is extremely fast and Telegram purely ignores deleted/missing message IDs.
        for start_id in range(last_forwarded_id + 1, latest_id + 1, BATCH_SIZE):
            end_id = min(start_id + BATCH_SIZE - 1, latest_id)
            
            # Create a list of 100 continuous message IDs
            msg_ids = list(range(start_id, end_id + 1))
            
            await forward_batch(source, msg_ids)
            
            # Save our exact place
            progress[str(source)] = end_id
            save_progress(progress)
            
            # Crucial wait to avoid API limitations/spamming
            await asyncio.sleep(SLEEP_BETWEEN_BATCHES)
            
    await app.stop()
    logging.info("Forwarding process fully wrapped up!")

async def forward_batch(source, msg_ids):
    while True:
        try:
            logging.info(f"Forwarding messages {msg_ids[0]} to {msg_ids[-1]}...")
            await app.forward_messages(
                chat_id=DESTINATION_CHANNEL,
                from_chat_id=source,
                message_ids=msg_ids,
                drop_author=True  # Completely hides the "Forwarded from" tag
            )
            break
        except errors.FloodWait as e:
            # e.value is strictly the wait duration in Pyrogram V2
            wait_time = e.value + 5
            logging.warning(f"FloodWait hit! Telegram tells us to wait. Sleeping for {wait_time} seconds (Don't close the script).")
            await asyncio.sleep(wait_time)
        except Exception as e:
            # If an obscure error occurs, we ignore instead of crashing the whole 1-million loop
            logging.error(f"Failed to forward a batch (ignoring and proceeding past it): {e}")
            break

if __name__ == "__main__":
    app.run(main())
