import os
import asyncio
import re
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.raw import functions
from pyrogram.raw.types import InputPeerChannel
from pyrogram.errors import FloodWait
from pyrogram.raw import types as raw_types

# ==================== CONFIGURATION (SECURED) ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

if not API_ID or not API_HASH or not SESSION_STRING:
    raise ValueError("WARNING: API_ID, API_HASH, atau SESSION_STRING belum dikonfigurasi di Environment Variables!")

app = Client("my_userbot11", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)


async def process_reaction_list(client: Client, message: Message):
    """Fungsi helper untuk memproses dan mengambil daftar username serta total react"""
    target_msg = message.reply_to_message
    user_list = []
    total_react_count = 0

    try:
        updated_msg = await client.get_messages(chat_id=message.chat.id, message_ids=target_msg.id)
        if updated_msg.reactions and updated_msg.reactions.reactions:
            for r in updated_msg.reactions.reactions:
                total_react_count += r.count

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

        raw_reply = await client.invoke(
            functions.messages.GetMessageReactionsList(
                peer=chat_peer,
                id=target_msg.id,
                limit=100
            )
        )

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


# ==================== AUTO-BAN SAAT LEFT CHANNEL & /unbin ====================
# Syarat: akun userbot ini harus ADMIN di channel dengan izin "Ban users".
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1003882339899"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "10"))      # jeda cek admin log (detik)
BACKFILL = os.environ.get("BACKFILL", "0") == "1"                  # 0 = hanya yang left setelah bot jalan
EXEMPT_IDS = {int(x) for x in os.environ.get("EXEMPT_IDS", "").split(",") if x.strip()}

USERNAME_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})")

unban_mark = {}   # user_id -> id event admin log terakhir saat di-unban
user_cache = {}   # user_id -> objek user dari admin log
pending = {}      # user_id -> (id event left, objek user), antrean ban yang kena FloodWait


async def get_channel_input(client: Client):
    peer = await client.resolve_peer(CHANNEL_ID)
    return raw_types.InputChannel(channel_id=peer.channel_id, access_hash=peer.access_hash)


async def set_ban(client: Client, channel, input_peer, banned: bool):
    """banned=True -> ban dari channel, banned=False -> unban."""
    if banned:
        rights = raw_types.ChatBannedRights(until_date=0, view_messages=True)
    else:
        rights = raw_types.ChatBannedRights(until_date=0)
    await client.invoke(
        functions.channels.EditBanned(channel=channel, participant=input_peer, banned_rights=rights)
    )


async def is_banned(client: Client, channel, peer):
    try:
        res = await client.invoke(
            functions.channels.GetParticipant(channel=channel, participant=peer)
        )
    except Exception as e:
        if "USER_NOT_PARTICIPANT" in str(e):
            return False
        raise
    p = res.participant
    return isinstance(p, raw_types.ChannelParticipantBanned) and bool(
        getattr(p.banned_rights, "view_messages", False)
    )


async def latest_event_id(client: Client, channel):
    res = await client.invoke(
        functions.channels.GetAdminLog(channel=channel, q="", max_id=0, min_id=0, limit=1)
    )
    return res.events[0].id if res.events else 0


async def ban_with_retry(client: Client, channel, user):
    """Return 'ok' kalau berhasil, 'retry' kalau masih kena FloodWait, 'fail' kalau error lain."""
    peer = raw_types.InputPeerUser(user_id=user.id, access_hash=user.access_hash)
    for _ in range(3):
        try:
            await set_ban(client, channel, peer, True)
            return "ok"
        except FloodWait as e:
            wait = getattr(e, "value", None) or getattr(e, "x", 10)
            print(f"[autoban] FloodWait {wait}s saat ban {user.id}, nunggu")
            await asyncio.sleep(wait + 2)
        except Exception as e:
            print(f"[autoban] Gagal ban {user.id}: {type(e).__name__}: {e}")
            return "fail"
    return "retry"


async def fetch_leave_events(client: Client, channel, min_id: int):
    """Ambil semua event 'left' di admin log dengan id > min_id. Return (events, users_by_id)."""
    events, users, seen = [], {}, set()
    max_id = 0
    while True:
        res = await client.invoke(
            functions.channels.GetAdminLog(
                channel=channel,
                q="",
                max_id=max_id,
                min_id=min_id,
                limit=100,
                events_filter=raw_types.ChannelAdminLogEventsFilter(leave=True),
            )
        )
        for u in res.users:
            users[u.id] = u
        new = [e for e in res.events if e.id not in seen]
        for e in new:
            seen.add(e.id)
        events.extend(new)
        if len(res.events) < 100 or not new:
            break
        max_id = min(e.id for e in res.events)
    return events, users


async def autoban_loop(client: Client):
    """Cek 'Recent actions' channel, ban setiap orang yang left."""
    try:
        async for _ in client.get_dialogs():  # isi cache peer supaya channel bisa ditemukan
            pass
        channel = await get_channel_input(client)
        first = await client.invoke(
            functions.channels.GetAdminLog(channel=channel, q="", max_id=0, min_id=0, limit=1)
        )
    except Exception as e:
        print(f"[autoban] Tidak bisa baca admin log (akun harus admin channel {CHANNEL_ID}): {type(e).__name__}: {e}")
        return

    last = 0
    if not BACKFILL and first.events:
        last = first.events[0].id

    me = await client.get_me()
    print(f"[autoban] Memantau {CHANNEL_ID} tiap {POLL_INTERVAL:.0f} detik (backfill={'ya' if BACKFILL else 'tidak'})")

    while True:
        try:
            events, users = await fetch_leave_events(client, channel, last)
            user_cache.update(users)

            for ev in sorted(events, key=lambda e: e.id):
                uid = ev.user_id
                u = users.get(uid)
                skip = (
                    uid == me.id
                    or uid in EXEMPT_IDS
                    or getattr(u, "bot", False)
                    or ev.id <= unban_mark.get(uid, 0)   # left lama sebelum di-unban
                )
                if not skip:
                    if u is None or not getattr(u, "access_hash", None):
                        print(f"[autoban] Data user {uid} tidak ada di admin log, dilewati")
                    else:
                        result = await ban_with_retry(client, channel, u)
                        if result == "ok":
                            pending.pop(uid, None)
                            print(f"[autoban] 🚫 Ban {uid} (left channel)")
                        elif result == "retry":
                            pending[uid] = (ev.id, u)
                            print(f"[autoban] {uid} masuk antrean, dicoba lagi nanti")
                last = max(last, ev.id)

            # coba lagi yang tadi kena FloodWait
            for uid, (eid, u) in list(pending.items()):
                if eid <= unban_mark.get(uid, 0):
                    pending.pop(uid, None)   # sudah di-unban, batal
                    continue
                result = await ban_with_retry(client, channel, u)
                if result == "ok":
                    pending.pop(uid, None)
                    print(f"[autoban] 🚫 Ban {uid} (left channel, retry)")
                elif result == "fail":
                    pending.pop(uid, None)

        except FloodWait as e:
            wait = getattr(e, "value", None) or getattr(e, "x", 10)
            print(f"[autoban] FloodWait {wait}s saat baca admin log")
            await asyncio.sleep(wait + 5)
        except Exception as e:
            print(f"[autoban] Error baca admin log: {type(e).__name__}: {e}")
        await asyncio.sleep(POLL_INTERVAL)


@app.on_message(filters.command("unbin", prefixes=["/", "."]) & filters.group)
async def cmd_unbin(client: Client, message: Message):
    me = await client.get_me()
    refs = [a.lstrip("@") for a in message.command[1:]]

    r = message.reply_to_message
    if not refs and r:
        text = r.text or r.caption or ""
        refs += USERNAME_RE.findall(text)
        for ent in (r.entities or []) + (r.caption_entities or []):
            if getattr(ent, "user", None):
                refs.append(ent.user.id)
        if not refs and r.from_user and not r.from_user.is_self:
            refs.append(r.from_user.id)

    cleaned, seen = [], set()
    for ref in refs:
        key = str(ref).lower()
        if key in seen or key == str(me.id) or (me.username and key == me.username.lower()):
            continue
        seen.add(key)
        cleaned.append(ref)

    if not cleaned:
        await message.reply_text("Reply bot, atau tulis /unbin @username")
        return

    try:
        channel = await get_channel_input(client)
    except Exception as e:
        await message.reply_text(f"Channel tidak ditemukan: {type(e).__name__}: {e}")
        return

    ok, not_banned, fail = [], [], []
    for ref in cleaned:
        try:
            is_id = str(ref).lstrip("-").isdigit()
            uid, name, peer = None, None, None

            if is_id and int(ref) in user_cache:
                cu = user_cache[int(ref)]
                uid = cu.id
                name = f"@{cu.username}" if getattr(cu, "username", None) else str(cu.id)
                peer = raw_types.InputPeerUser(user_id=cu.id, access_hash=cu.access_hash)

            if peer is None:
                user = await client.get_users(int(ref) if is_id else ref)
                uid = user.id
                name = f"@{user.username}" if user.username else str(user.id)
                peer = await client.resolve_peer(user.id)

            if not await is_banned(client, channel, peer):
                pending.pop(uid, None)
                not_banned.append(name)
                continue

            await set_ban(client, channel, peer, False)
            unban_mark[uid] = await latest_event_id(client, channel)
            pending.pop(uid, None)
            ok.append(name)
        except Exception as e:
            fail.append(f"{ref} ({type(e).__name__}: {e})")

    lines = [f"{x} unbanned" for x in ok]
    lines += [f"{x} tidak diban" for x in not_banned]
    if fail:
        lines.append("gagal: " + ", ".join(fail))
    await message.reply_text("\n".join(lines))


async def main():
    await app.start()
    task = asyncio.create_task(autoban_loop(app))
    await idle()
    task.cancel()
    await app.stop()


print("⚡ Userbot /done & /doni v10 Aktif dengan Sistem Keamanan Variabel!")
app.run(main())
