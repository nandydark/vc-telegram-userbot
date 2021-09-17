
import asyncio
import ffmpeg
import glob
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from config import Config
from collections import defaultdict
from pytgcalls import GroupCallFactory
from pytgcalls.exceptions import GroupCallNotFoundError
from datetime import datetime
from pyrogram import filters, Client, idle
from pyrogram.raw.types import InputPeerChannel


VOICE_CHATS = dict()
DEFAULT_DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads/')
PLAYING = defaultdict(lambda: "")
QUEUE = defaultdict(list)
FILES = defaultdict(list)


api_id = Config.API_ID
api_hash = Config.API_HASH
session_name = Config.STRING_SESSION
app = Client(session_name, api_id, api_hash)
factory = GroupCallFactory(app)
EXECUTOR = ThreadPoolExecutor(app.WORKERS)

self_or_contact_filter = filters.create(
    lambda
    _,
    __,
    message:
    (message.from_user and message.from_user.is_contact) or message.outgoing
)


def parse_id(peer):
	if isinstance(peer, InputPeerChannel):
		return -1000000000000 - peer.channel_id
	return -peer.chat_id


def get_scheduled_text(chat, title, link):
	s = "Scheduled [{title}]({link}) on #{position} position"
	return s.format(title=title, link=link, position=len(QUEUE[chat])+1)


def get_first_song(title, link):
	return f"[{title}]({link})"

async def convert(name):
	input_filename = os.path.join(os.getcwd(),
	f'{os.path.splitext(os.path.basename(name))[0]}.raw')
	def _c():
		ffmpeg.input(name).output(
			input_filename,
			format='s16le',
			acodec='pcm_s16le',
			ac=2, ar='48k',
		).overwrite_output().run()
		return input_filename
	loop = asyncio.get_event_loop()
	return await loop.run_in_executor(EXECUTOR, _c)


async def tg_down(message):
	audio = message.audio
	my_message = await message.reply('Downloading...')
	audio_original = await message.download(DEFAULT_DOWNLOAD_DIR)

	await my_message.edit("Encoding...")
	VOICE_CHATS[message.chat.id].input_filename = file = await convert(audio_original)
	FILES[message.chat.id].append(file)
	await my_message.edit(f"Playing **[{audio.title}]({message.link})**")
	os.remove(audio_original)


async def _skip(c, __):
	await handle_queue(c)


async def handle_queue(call, clear = False):
	
	call.stop_playout()

	if clear:
		QUEUE[parse_id(call.chat_peer)].clear()

	if not QUEUE[parse_id(call.chat_peer)]:
		PLAYING[parse_id(call.chat_peer)] = ""
		return

	shutil.rmtree(DEFAULT_DOWNLOAD_DIR, ignore_errors=True)
	msg = QUEUE[parse_id(call.chat_peer)].pop(0)
	try:
		PLAYING[parse_id(call.chat_peer)] = get_first_song(msg.audio.title, msg.link)
		await tg_down(msg)
	except Exception as err:
		PLAYING[parse_id(call.chat_peer)] = ""
		out = f"**ERROR:** `{str(err)}`"
		if QUEUE[parse_id(call.chat_peer)]:
			out += "\n\n`Playing next Song.`"
		await call.client.send_message(
			parse_id(call.chat_peer),
			out,
			disable_web_page_preview=True
	        )
		await handle_queue(call)
	finally:
		shutil.rmtree(DEFAULT_DOWNLOAD_DIR, ignore_errors=True)


@app.on_message(filters.command('ping') & self_or_contact_filter)
async def ping(client, message):
	start = datetime.now()
	rape = await message.reply('Pong!')
	end = datetime.now()
	m_s = (end - start).microseconds / 1000
	await rape.edit(f'**Pong!**\n> `{m_s} ms`')


@app.on_message(filters.command('play') & self_or_contact_filter)
async def play_track(client, message):
	if not (replied:=message.reply_to_message) or not message.reply_to_message.audio:
		return await message.reply("Invalid audio file")
	if not VOICE_CHATS or message.chat.id not in VOICE_CHATS:
		try:
			group_call = factory.get_file_group_call()
			await group_call.start(message.chat.id)
			group_call.on_playout_ended(_skip)
		except GroupCallNotFoundError:
			await message.reply('First start a VC in this group rotor')
			return
		VOICE_CHATS[message.chat.id] = group_call
	QUEUE[message.chat.id].append(replied)
	if PLAYING[message.chat.id]:
		return await message.reply(get_scheduled_text(message.chat.id, replied.audio.title, replied.link),
			disable_web_page_preview = True
		)
	await handle_queue(VOICE_CHATS[message.chat.id])


@app.on_message(filters.command('stop') & self_or_contact_filter)
async def stop_playing(client, message):
	group_call = VOICE_CHATS[message.chat.id]
	await handle_queue(group_call, True)
	group_call.stop_playout()
	shutil.rmtree(DEFAULT_DOWNLOAD_DIR, ignore_errors=True)
	for i in FILES[message.chat.id]:
		os.remove(i)
		FILES[message.chat.id].clear()
	await message.reply('Stopped')


@app.on_message(filters.command('joinvc') & self_or_contact_filter)
async def join_voice_chat(client, message):
	if message.chat.id in VOICE_CHATS:
		await message.reply('Already in')
		return
	chat_id = message.chat.id
	try:
		group_call = factory.get_file_group_call()
		await group_call.start(chat_id)
		group_call.on_playout_ended(_skip)
	except GroupCallNotFoundError:
		await message.reply('First start a VC in this group rotor')
		return
	except Exception as e:
		await message.reply('Error Now rape me!')
		print(e)
		return
	VOICE_CHATS[chat_id] = group_call
	await message.reply('Joined ')


@app.on_message(filters.command('leavevc') & self_or_contact_filter)
async def leave_voice_chat(client, message):
	chat_id = message.chat.id
	group_call = VOICE_CHATS[chat_id]
	await handle_queue(group_call, True)
	await group_call.stop()
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

@app.on_message(filters.command('clear_cache') & self_or_contact_filter)
async def clear_cache(_, message):
	shutil.rmtree(DEFAULT_DOWNLOAD_DIR, ignore_errors=True)
	for i in FILES[message.chat.id]:
		os.remove(i)
		FILES[message.chat.id].clear()
	await message.reply_text("Cleared all Downloaded Files")

@app.on_message(filters.command('queue') & self_or_contact_filter)
async def show_queue(_, message):
	queue = QUEUE[message.chat.id]
	_no = (len(queue) + 1) if PLAYING[message.chat.id] else len(queue)
	if not _no:
		return await message.reply("Queue is empty.")
	msg = (f'**__{_no} Song{"s" if _no > 1 else ""} in queue:__**\n\n'
			f"▶ {PLAYING[message.chat.id]}\n")
	for m in queue:
		msg += f"● [{m.audio.title}]({m.link})\n"
	await message.reply(msg.strip(), disable_web_page_preview=True)

@app.on_message(filters.command('skip') & self_or_contact_filter)
async def skip_song(_, message):
	if message.chat.id in VOICE_CHATS:
		await handle_queue(VOICE_CHATS[message.chat.id])
		await message.reply("Skipped")

app.start()
print('started successfully')
idle()
app.stop()
print('stopping...')

