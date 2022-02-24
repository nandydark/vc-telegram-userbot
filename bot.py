
import os
import shutil
import time
from config import Config
from itertools import chain
from datetime import datetime
from collections import defaultdict
from pyrogram import filters, Client, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
from pytgcalls.exceptions import NoActiveGroupCall


VOICE_CHATS = dict()
DEFAULT_DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads/')
PLAYING = defaultdict(tuple)
QUEUE = defaultdict(list)
FILES = defaultdict(list)
START_TIME = time.time()


api_id = Config.API_ID
api_hash = Config.API_HASH
session_name = Config.STRING_SESSION
app = Client(session_name, api_id, api_hash)
vc = PyTgCalls(app, overload_quiet_mode=True)


self_or_contact_filter = filters.create(
    lambda
    _,
    __,
    message:
    (message.from_user and message.from_user.is_contact) or message.outgoing
)

autoqueue_filter = filters.create(
    lambda
    self,
    _,
    __:
    self.flag,
    flag = False,
    switch = lambda self: setattr(self, "flag", not self.flag) or self.flag
)


def format_time(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "")
    return tmp[:-2]


def get_scheduled_text(chat, title, link):
    s = "Scheduled **[{title}]({link})** on #{position} position"
    return s.format(title=title, link=link, position=len(QUEUE[chat])+1)


def get_formatted_link(title, link):
    return f"[{title}]({link})"

def clear_cache(chat_id, all = False):
    if all:
        for i in FILES[chat_id]:
            os.remove(i)
        return FILES[chat_id].clear()
    for i in FILES[chat_id]:
        if i not in PLAYING[chat_id]:
            os.remove(i)
    FILES[chat_id] = [PLAYING[chat_id][1]]

async def tg_down(message):
    audio = message.audio
    my_message = await message.reply('Downloading...')
    audio_original = await message.download(DEFAULT_DOWNLOAD_DIR)

    await my_message.edit("Passing it to VC...")
    await vc.change_stream(
        message.chat.id,
        AudioPiped(audio_original)
    )
    FILES[message.chat.id].append(audio_original)
    await my_message.edit(f"Playing **[{audio.title}]({message.link})**")
    return audio_original


async def handle_queue(chat_id, clear = False):

    if clear:
        QUEUE[chat_id].clear()

    if not QUEUE[chat_id]:
        if PLAYING[chat_id]:
            await vc.change_stream(
                chat_id,
                AudioPiped(
                    'http://duramecho.com/Misc/SilentCd/Silence01s.mp3'
                )
            )
        PLAYING[chat_id] = tuple()
        return

    clear_cache(chat_id)
    msg = QUEUE[chat_id].pop(0)
    try:
        PLAYING[chat_id] = get_formatted_link(msg.audio.title, msg.link), await tg_down(msg)
    except Exception as err:
        PLAYING[chat_id] = tuple()
        out = f"**ERROR:** `{str(err)}`"
        if QUEUE[chat_id]:
            out += "\n\n`Playing next Song.`"
        await app.send_message(
            chat_id,
            out,
            disable_web_page_preview=True
        )
        await handle_queue(chat_id)
    finally:
        clear_cache(chat_id) 


@vc.on_stream_end()
async def _skip(_, u):
    await handle_queue(u.chat_id)


@app.on_message(filters.command('ping') & self_or_contact_filter)
async def ping(_, message):
    start = datetime.now()
    rape = await message.reply('Pong!')
    end = datetime.now()
    m_s = (end - start).microseconds / 1000
    uptime = format_time(time.time() - START_TIME)
    await rape.edit(f'**Pong!**\n> `{m_s} ms`\n\n**NodeJS Core Ping**\n> `{await vc.ping} ms`\n\n**Uptime**\n> `{uptime}`')


@app.on_message(((autoqueue_filter & filters.audio) | filters.command('play')) & self_or_contact_filter)
async def play_track(_, message):
    replied = message if message.audio else message.reply_to_message
    if not (replied and replied.audio):
        return await message.reply("Invalid audio file")
    if not vc.calls or message.chat.id not in list(map(lambda x: x.chat_id, vc.calls)):
        try:
            await vc.join_group_call(
                message.chat.id,
                AudioPiped(
                    'http://duramecho.com/Misc/SilentCd/Silence08s.mp3'
                )
            )
        except NoActiveGroupCall:
            await message.reply('First start a VC in this group rotor')
            return
    QUEUE[message.chat.id].append(replied)
    if PLAYING[message.chat.id]:
        return await message.reply(get_scheduled_text(message.chat.id, replied.audio.title, replied.link),
            disable_web_page_preview = True
        )
    await handle_queue(message.chat.id)


@app.on_message(filters.command('stop') & self_or_contact_filter)
async def stop_playing(__, message):
    await handle_queue(message.chat.id, True)
    clear_cache(message.chat.id, True)
    await message.reply('Stopped')


@app.on_message(filters.command('joinvc') & self_or_contact_filter)
async def join_voice_chat(_, message):
    if message.chat.id in list(map(lambda x: x.chat_id, vc.calls)):
        await message.reply('Already in')
        return
    try:
        await vc.join_group_call(
            message.chat.id,
            AudioPiped(
                'http://duramecho.com/Misc/SilentCd/Silence01s.mp3'
            )
        )
    except NoActiveGroupCall:
        await message.reply('First start a VC in this group rotor')
        return
    except Exception as e:
        await message.reply('Error Now rape me!')
        print(e)
        return
    await message.reply('Joined ')


@app.on_message(filters.command('leavevc') & self_or_contact_filter)
async def leave_voice_chat(_, message):
    chat_id = message.chat.id
    await handle_queue(chat_id, True)
    await vc.leave_group_call(
        message.chat.id,
    )
    VOICE_CHATS.pop(chat_id, None)
    await message.reply('Left')


@app.on_message(filters.command('leave_group') & self_or_contact_filter)
async def leave_group(_, message):
    if len(message.command) != 2:
        await message.reply_text("/leave_group `GroupID`")
        return
    try:
        chat_id = message.text.split(None, 1)[1]
        await app.leave_chat(chat_id)
        await message.reply_text("`Successfully Left That Group`")
    except Exception as e:
        await message.reply_text(str(e))
        print(str(e))


@app.on_message(filters.command('join_group') & self_or_contact_filter)
async def join_group(_, message):
    if len(message.command) != 2:
        await message.reply_text("/join_group `GroupID`")
        return
    try:
        chat_id = message.text.split(None, 1)[1]
        await app.join_chat(chat_id)
        await message.reply_text("`Successfully Joined That Group`")
    except Exception as e:
        await message.reply_text(str(e))
        print(str(e))


@app.on_message(filters.command('cacheclear') & self_or_contact_filter)
async def _clear_cache(_, message):
    clear_cache(message.chat.id)
    await message.reply_text("Cleared all Downloaded Files")


@app.on_message(filters.command('queue') & self_or_contact_filter)
async def show_queue(_, message):
    queue = QUEUE[message.chat.id]
    _no = (len(queue) + 1) if PLAYING[message.chat.id] else len(queue)
    if not _no:
        return await message.reply("Queue is empty.")
    msg = (f'**__{_no} Song{"s" if _no > 1 else ""} in queue:__**\n\n'
            f"▶ {PLAYING[message.chat.id][0]}\n")
    for m in queue:
        msg += f"● {get_formatted_link(m.audio.title, m.link)}\n"
    await message.reply(msg.strip(), disable_web_page_preview=True)


@app.on_message(filters.command('skip') & self_or_contact_filter)
async def skip_song(_, message):
    if message.chat.id in list(map(lambda x: x.chat_id, vc.calls)):
        await handle_queue(message.chat.id)
        await message.reply("Skipped")


@app.on_message(filters.command('auto') & self_or_contact_filter)
async def auto_queue(_, message):
    res = autoqueue_filter.switch()
    await message.reply(f"**__Auto Queue {'' if res else 'de'}activated__**")


app.start()
vc.start()
print('started successfully')
idle()
app.stop()
print('stopping...')
