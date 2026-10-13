import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.raw import functions
from pyrogram.raw.types import InputPeerChannel, InputPeerChat

# ==================== CONFIGURATION (SECURED) ====================
# Mengambil data dari Environment Variables yang diset di Railway
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

# Validasi sederhana untuk memastikan variabel sudah terisi
if not API_ID or not API_HASH or not SESSION_STRING:
    raise ValueError("WARNING: API_ID, API_HASH, atau SESSION_STRING belum dikonfigurasi di Environment Variables!")

app = Client("my_userbot11", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

async def process_reaction_list(client: Client, message: Message):
    """Fungsi helper untuk memproses dan mengambil daftar username serta total react"""
    target_msg = message.reply_to_message
    user_list = []
    total_react_count = 0

    try:
        # 1. Ambil hitungan total reaksi aktual dari pesan
        updated_msg = await client.get_messages(chat_id=message.chat.id, message_ids=target_msg.id)
        if updated_msg.reactions and updated_msg.reactions.reactions:
            for r in updated_msg.reactions.reactions:
                total_react_count += r.count

        # 2. Penanganan Khusus Supergroup/Channel-Chat (Bypass MSG_ID_INVALID)
        if message.chat.type in ["supergroup", "channel"]:
            channel_id = int(str(message.chat.id).replace("-100", ""))
            chat_info = await client.get_chat(message.chat.id)
            access_hash = chat_info.linked_chat.access_hash if getattr(chat_info, "linked_chat", None) else 0
            
            if not access_hash:
                resolved_peer = await client.resolve_peer(message.chat.id)
                access_hash = getattr(resolved_peer, "access_hash", 0)
                
            chat_peer = InputPeerChannel(channel_id=channel_id, access_hash=access_hash)
        else:
            chat_peer = await client.resolve_peer(message.chat.id)
        
        # 3. Ambil daftar user dari database Telegram
        raw_reply = await client.invoke(
            functions.messages.GetMessageReactionsList(
                peer=chat_peer,
                id=target_msg.id,
                limit=100
            )
        )
        
        # 4. Ekstrak data username
        # 4. Ekstrak data username / display name
        if hasattr(raw_reply, "users"):
            for raw_user in raw_reply.users:
                username = None
                if getattr(raw_user, "username", None):
                    username = raw_user.username
                elif getattr(raw_user, "usernames", None):
                    for u in raw_user.usernames:
                        if getattr(u, "active", False) or getattr(u, "editable", False):
                            username = u.username
                            break

                if username:
                    user_list.append(f"@{username}")
                else:
                    first = getattr(raw_user, "first_name", "") or ""
                    last = getattr(raw_user, "last_name", "") or ""
                    dn = f"{first} {last}".strip().replace("`", "")
                    if dn:
                        user_list.append(f"{dn} (no usn)")

    except Exception as e:
        print(f"Error: {str(e)}")

    user_list = list(set(user_list))
    usernames_string = "No-Users-Detected" if not user_list else " ".join(user_list)
    
    return usernames_string, total_react_count


# ==================== COMMANDS ====================

@app.on_message(filters.command("done", prefixes=["/", "."]) & filters.group)
async def cmd_done(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Rep terus /done")
        return

    usernames_string, total_react_count = await process_reaction_list(client, message)
    caption_template = f"`{usernames_string} ({total_react_count})`"
    
    await message.reply_text(text=caption_template, disable_web_page_preview=False)


@app.on_message(filters.command("doni", prefixes=["/", "."]) & filters.group)
async def cmd_doni(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Rep terus /doni")
        return

    usernames_string, total_react_count = await process_reaction_list(client, message)
    
    caption_template = (
            "``` \n"
            "ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ\n"
            "𝗦𝗬𝗡𝗖 𝗣𝗔𝗖𝗧: Mutual terms enforced.\n"
            f"Alignment forms beyond consent, presence settles refuses 2 shift. 𝘕𝘰 𝘧𝘳𝘢𝘤𝘵𝘶𝘳𝘦 𝘰𝘯𝘤𝘦 𝘪𝘵 𝘴𝘦𝘵𝘴: {usernames_string} ({total_react_count}) bound. Balanced force, no reversal (+KT9.) https://t.me/HOTROVERs/4.\n"
            "ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ```"
    )
    
    await message.reply_text(text=caption_template, disable_web_page_preview=False)


print("⚡ Userbot /done & /doni v10 Aktif dengan Sistem Keamanan Variabel!")
app.run()
