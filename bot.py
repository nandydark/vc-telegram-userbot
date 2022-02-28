
import os
import json
import time
import shlex
import asyncio
from config import Config
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from pyrogram import filters, Client, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped, AudioVideoPiped, VideoParameters
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


def get_media(m):
    return m.audio or m.video or m.document


def get_media_name(m):
    return Path(getattr(get_media(m), 'file_name', 'Media')).stem.title()


def clear_cache(chat_id, all = False):
    if all:
        for i in FILES[chat_id]:
            os.remove(i)
        return FILES[chat_id].clear()
    for i in FILES[chat_id]:
        if i not in PLAYING[chat_id]:
            os.remove(i)
    FILES[chat_id] = [*(PLAYING[chat_id][1:] or tuple())]


async def get_subprocess_output(cmd):
    process = await asyncio.create_subprocess_shell(
             cmd,
             stdout=asyncio.subprocess.PIPE,
             stderr=asyncio.subprocess.PIPE
    )
    if await process.wait() == 0:
         return (await process.stdout.read()).decode()
    raise Exception("Error Occurred:\n" + (await process.stderr.read()).decode())


async def fetch_metadata(file):
    cmd = "ffprobe -v error -show_entries stream=width,height,codec_type,codec_name -of json {file}"
    _output = await get_subprocess_output(cmd.format(file=shlex.quote(file)))
    try:
        output = json.loads(_output) or {}
    except json.JSONDecodeError:
        output = {}
    streams = output.get('streams', [])
    width, height, have_video, have_audio  = 0, 0, False, False
    for stream in streams:
        if stream.get('codec_type', '') == 'video':
            width = min(int(stream.get('width', 0)), 1280)
            height = min(int(stream.get('height', 0)), 720)
            if width and height:
                have_video = True
        elif stream.get('codec_type', '') == "audio":
            have_audio = True
    return height, width, have_video, have_audio


async def play_media(file, msg):
    height, width, have_video, have_audio = await fetch_metadata(file)
    stream = AudioPiped('http://duramecho.com/Misc/SilentCd/Silence01s.mp3')
    if have_video and have_audio:
        stream = AudioVideoPiped(
            file,
            video_parameters=VideoParameters(
                width,
                height,
                25
            )
        )
    else:
        stream = AudioPiped(file)
    await vc.change_stream(
        msg.chat.id,
        stream
    )


async def tg_down(message):
    my_message = await message.reply('Downloading...')
    original_file = await message.download(DEFAULT_DOWNLOAD_DIR)

    await asyncio.gather(
        my_message.edit("Passing it to VC..."),
        play_media(original_file, message)
    )
    FILES[message.chat.id].append(original_file)
    await my_message.edit(f"Playing **{get_formatted_link(get_media_name(message), message.link)}**")
    return original_file


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
        PLAYING[chat_id] = get_formatted_link(get_media_name(msg), msg.link), await tg_down(msg)
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
async def _ping(_, message):
    start = datetime.now()
    rape = await message.reply('Pong!')
    end = datetime.now()
    m_s = (end - start).microseconds / 1000
    uptime = format_time(time.time() - START_TIME)
    await rape.edit(f'**Pong!**\n> `{m_s} ms`\n\n**NodeJS Core Ping**\n> `{await vc.ping} ms`\n\n**Uptime**\n> `{uptime}`')


@app.on_message(
    ((autoqueue_filter
    & filters.create(lambda _,__,m: bool(get_media(m))))
    | filters.command('play')) & self_or_contact_filter)
async def _play(_, message):
    replied = message if get_media(message) else message.reply_to_message
    if not (replied and get_media(replied)):
        return await message.reply("Invalid file...")
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
        return await message.reply(get_scheduled_text(message.chat.id, get_media_name(replied), replied.link),
            disable_web_page_preview = True
        )
    await handle_queue(message.chat.id)


@app.on_message(filters.command('stop') & self_or_contact_filter)
async def _stop(__, message):
    await handle_queue(message.chat.id, True)
    clear_cache(message.chat.id, True)
    await message.reply('Stopped')


@app.on_message(filters.command('joinvc') & self_or_contact_filter)
async def _join_vc(_, message):
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
async def _leave_vc(_, message):
    chat_id = message.chat.id
    await handle_queue(chat_id, True)
    await vc.leave_group_call(
        message.chat.id,
    )
    VOICE_CHATS.pop(chat_id)
    clear_cache(chat_id)
    await message.reply('Left')


@app.on_message(filters.command('leave_group') & self_or_contact_filter)
async def _leave_group(_, message):
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
async def _join_group(_, message):
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
async def _queue(_, message):
    queue = QUEUE[message.chat.id]
    _no = (len(queue) + 1) if PLAYING[message.chat.id] else len(queue)
    if not _no:
        return await message.reply("Queue is empty.")
    msg = (f'**__{_no} Song{"s" if _no > 1 else ""} in queue:__**\n\n'
            f"▶ {PLAYING[message.chat.id][0]}\n")
    for m in queue:
        msg += f"● {get_formatted_link(get_media_name(m), m.link)}\n"
    await message.reply(msg.strip(), disable_web_page_preview=True)


@app.on_message(filters.command('skip') & self_or_contact_filter)
async def _skip(_, message):
    if message.chat.id in list(map(lambda x: x.chat_id, vc.calls)):
        await handle_queue(message.chat.id)
        await message.reply("Skipped")


@app.on_message(filters.command('auto') & self_or_contact_filter)
async def _autoQ(_, message):
    res = autoqueue_filter.switch()
    await message.reply(f"**__Auto Queue {'' if res else 'de'}activated__**")


app.start()
vc.start()
print('started successfully')
idle()
app.stop()
print('stopping...')
