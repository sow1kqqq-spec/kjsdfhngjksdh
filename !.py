import os, io, logging, tempfile, shutil, base64, time, json
import requests
import telebot
from telebot import types
from PIL import Image, ImageOps

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, APIC, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.asf import ASF
from mutagen.wave import WAVE

TOKEN       = "8831747632:AAHQBP07TKxs9jc9Nc8opT5cQqTcurfgeCA"
CHANNEL_ID  = -1004218500440
CHANNEL_URL = "https://t.me/vk_only_News"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

def ce(eid: str, fb: str = "⭐") -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

E_MUSIC  = "5429351107576997410"
E_TITLE  = "5343792034736009111"
E_ARTIST = "5343792034736009111"
E_COVER  = "6039802767931871481"
E_SKIP   = "5343669198671342116"
E_SEND   = "5377811534384768829"
E_WAIT   = "5260396302562266399"
E_DONE   = "5260521071362214474"
E_SUB    = "5465522218337332957"

AUDIO_MIME: dict[str, str] = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/mp4":  ".m4a", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a",
    "video/mp4":  ".mp4",
    "audio/aac":  ".aac",
    "audio/ogg":  ".ogg", "audio/vorbis": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac", "audio/x-flac": ".flac",
    "audio/wav":  ".wav",  "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/wma":  ".wma",  "audio/x-ms-wma": ".wma",
    "audio/webm": ".webm", "video/webm": ".webm",
}
FMT_NAME: dict[str, str] = {
    ".mp3": "MP3", ".m4a": "M4A", ".mp4": "MP4", ".aac": "AAC",
    ".ogg": "OGG", ".opus": "OPUS", ".flac": "FLAC",
    ".wav": "WAV", ".wma": "WMA", ".webm": "WebM",
}

def is_subscribed(uid: int) -> bool:
    try:
        member = bot.get_chat_member(CHANNEL_ID, uid)
        return member.status in ("creator", "administrator", "member", "restricted")
    except Exception as e:
        log.warning(f"Sub check failed for {uid}: {e}")
        return False

def send_sub_prompt(uid: int):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("НОВОСТИ моих ботов", url=CHANNEL_URL),
        types.InlineKeyboardButton("Проверить подписку", callback_data="check_sub")
    )
    bot.send_message(
        uid,
        f"{ce(E_SUB, '❗')} чтобы использовать бота, подпишитесь на НОВОСТИ моих ботов",
        reply_markup=kb,
        parse_mode="HTML"
    )

def ensure_sub(uid: int) -> bool:
    if not is_subscribed(uid):
        send_sub_prompt(uid)
        return False
    return True

def detect_audio_ext(mime: str, filename: str = "") -> str | None:
    if filename:
        _, ext = os.path.splitext(filename.lower())
        if ext in FMT_NAME:
            return ext
    if mime:
        ml = mime.lower()
        for k, v in AUDIO_MIME.items():
            if ml.startswith(k):
                return v
        if "audio" in ml:
            return ".mp3"
    return None

users: dict = {}

def _blank() -> dict:
    return {
        "step":        "WAIT_AUDIO",
        "audio_path":  None,
        "fmt":         ".mp3",
        "title":       None,
        "artist":      None,
        "cover_path":  None,
        "last_msg_id": None,
    }

def get_user(uid: int) -> dict:
    if uid not in users:
        users[uid] = _blank()
    return users[uid]

def reset(uid: int):
    users[uid] = _blank()

def delete_last(uid: int):
    u   = get_user(uid)
    mid = u.get("last_msg_id")
    if mid:
        try: bot.delete_message(uid, mid)
        except Exception: pass
        u["last_msg_id"] = None

def send_step(uid: int, text: str, markup=None) -> types.Message:
    delete_last(uid)
    msg = bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")
    get_user(uid)["last_msg_id"] = msg.message_id
    return msg

def skip_kb() -> str:
    return json.dumps({
        "inline_keyboard": [[
            {
                "text": "пропустить",
                "callback_data": "skip",
                "icon_custom_emoji_id": E_SKIP
            }
        ]]
    })

def download_file(file_id: str, suffix: str = ".mp3") -> str:
    info = bot.get_file(file_id)
    url  = f"https://api.telegram.org/file/bot{TOKEN}/{info.file_path}"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(r.content)
    tmp.flush(); tmp.close()
    return tmp.name

def cover_jpeg_bytes(cover_path: str) -> bytes:
    with open(cover_path, "rb") as f:
        raw = f.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.fit(img, (600, 600), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()

def avatar_thumb_bytes(cover_path: str) -> bytes:
    with open(cover_path, "rb") as f:
        raw = f.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.fit(img, (320, 320), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

def apply_tags(audio_path: str, fmt: str,
               title: str | None, artist: str | None,
               cover_path: str | None) -> tuple[str, str]:
    out = audio_path + "_tagged" + fmt
    shutil.copy2(audio_path, out)

    cover = cover_jpeg_bytes(cover_path) if cover_path else None

    try:
        audio = MutagenFile(out)
    except Exception:
        audio = None

    actual_fmt = fmt

    if isinstance(audio, MP4):
        actual_fmt = ".m4a"
        if title:  audio["\xa9nam"] = [title]
        if artist: audio["\xa9ART"] = [artist]
        if cover:
            audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

    elif isinstance(audio, FLAC):
        actual_fmt = ".flac"
        if title:  audio["title"]  = [title]
        if artist: audio["artist"] = [artist]
        if cover:
            pic = Picture()
            pic.type = 3; pic.mime = "image/jpeg"; pic.data = cover
            audio.clear_pictures()
            audio.add_picture(pic)
        audio.save()

    elif isinstance(audio, OggVorbis):
        actual_fmt = ".ogg"
        if title:  audio["title"]  = [title]
        if artist: audio["artist"] = [artist]
        if cover:
            pic = Picture()
            pic.type = 3; pic.mime = "image/jpeg"; pic.data = cover
            audio["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")
            ]
        audio.save()

    elif isinstance(audio, OggOpus):
        actual_fmt = ".opus"
        if title:  audio["title"]  = [title]
        if artist: audio["artist"] = [artist]
        if cover:
            pic = Picture()
            pic.type = 3; pic.mime = "image/jpeg"; pic.data = cover
            audio["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")
            ]
        audio.save()

    elif isinstance(audio, ASF):
        actual_fmt = ".wma"
        if title:  audio["Title"]  = [title]
        if artist: audio["Author"] = [artist]
        audio.save()

    elif isinstance(audio, WAVE):
        actual_fmt = ".wav"
        if not audio.tags: audio.add_tags()
        if title:  audio.tags["TIT2"] = TIT2(encoding=3, text=title)
        if artist: audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
        if cover:
            audio.tags.delall("APIC")
            audio.tags.add(APIC(encoding=3, mime="image/jpeg",
                                type=3, desc="Cover", data=cover))
        audio.save()

    else:
        actual_fmt = ".mp3" if fmt in (".m4a", ".mp4") else fmt
        try:
            try:    tags = ID3(out)
            except ID3NoHeaderError: tags = ID3()
            if title:  tags["TIT2"] = TIT2(encoding=3, text=title)
            if artist: tags["TPE1"] = TPE1(encoding=3, text=artist)
            if cover:
                tags.delall("APIC")
                tags.add(APIC(encoding=3, mime="image/jpeg",
                              type=3, desc="Cover", data=cover))
            tags.save(out, v2_version=3)
        except Exception as e:
            log.warning(f"Fallback tag write failed ({fmt}): {e}")

    return out, actual_fmt

def ask_title(uid: int):
    send_step(uid,
        f"{ce(E_TITLE, '✏️')} Напишите новое название трека:",
        markup=skip_kb())
    get_user(uid)["step"] = "WAIT_TITLE"

def ask_artist(uid: int):
    send_step(uid,
        f"{ce(E_ARTIST, '🎤')} Напишите нового исполнителя:",
        markup=skip_kb())
    get_user(uid)["step"] = "WAIT_ARTIST"

def ask_cover(uid: int):
    send_step(uid,
        f"{ce(E_COVER, '🖼️')} Пришли новую обложку (аватарку) трека:",
        markup=skip_kb())
    get_user(uid)["step"] = "WAIT_COVER"

def do_save(uid: int):
    u = get_user(uid)
    delete_last(uid)

    m1 = bot.send_message(uid, f"{ce(E_SEND, '📤')} отправляю файл!", parse_mode="HTML")
    time.sleep(0.6)
    try: bot.delete_message(uid, m1.message_id)
    except Exception: pass

    m2 = bot.send_message(uid, f"{ce(E_WAIT, '⏳')} ожидайте!", parse_mode="HTML")

    out_path = None
    try:
        out_path, real_fmt = apply_tags(
            u["audio_path"], u["fmt"],
            u["title"], u["artist"], u["cover_path"]
        )
    except Exception as e:
        log.exception(e)
        bot.edit_message_text(f"❌ Ошибка: {e}", uid, m2.message_id)
        return

    try: bot.delete_message(uid, m2.message_id)
    except Exception: pass

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("владелец", url="https://t.me/vk_only"))

    fname = f"{u['artist'] or 'Unknown'} - {u['title'] or 'Track'}{real_fmt}"
    thumb_bytes = avatar_thumb_bytes(u["cover_path"]) if u.get("cover_path") else None

    try:
        with open(out_path, "rb") as f:
            thumb_file = types.InputFile(io.BytesIO(thumb_bytes), file_name="thumb.jpg") if thumb_bytes else None
            bot.send_audio(
                uid,
                types.InputFile(f, file_name=fname),
                title=u["title"] or None,
                performer=u["artist"] or None,
                thumbnail=thumb_file
            )
        bot.send_message(uid,
            f"готово {ce(E_DONE, '✅')} вот твой трек!",
            reply_markup=kb, parse_mode="HTML")
    except TypeError:
        with open(out_path, "rb") as f:
            bot.send_audio(
                uid,
                (fname, f),
                title=u["title"] or None,
                performer=u["artist"] or None,
                thumb=thumb_bytes
            )
        bot.send_message(uid,
            f"готово {ce(E_DONE, '✅')} вот твой трек!",
            reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        log.exception(e)
        bot.send_message(uid, f"❌ Не удалось отправить: {e}")
    finally:
        for p in [u.get("audio_path"), u.get("cover_path"), out_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        reset(uid)

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    reset(uid)
    if not ensure_sub(uid):
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("владелец", url="https://t.me/vk_only"))
    bot.send_message(uid,
        f"{ce(E_MUSIC, '🎵')} Пришли трек, чтобы изменить название, исполнителя или обложку трека.",
        reply_markup=kb, parse_mode="HTML")

@bot.message_handler(commands=["reset"])
def cmd_reset(msg: types.Message):
    uid = msg.from_user.id
    reset(uid)
    if not ensure_sub(uid):
        return
    bot.send_message(uid, "🔄 Сброшено. Отправь новый трек.")

def _route_document(msg: types.Message):
    uid = msg.from_user.id
    if not ensure_sub(uid):
        return
    u     = get_user(uid)
    mime  = msg.document.mime_type or ""
    fname = msg.document.file_name or ""

    if u["step"] == "WAIT_COVER" and mime.startswith("image/"):
        _save_cover_from_file_id(uid, u, msg.document.file_id)
        return

    ext = detect_audio_ext(mime, fname)
    if not ext:
        supported = ", ".join(sorted(FMT_NAME.values()))
        bot.send_message(uid,
            f"⚠️ Формат не поддерживается.\n"
            f"Поддерживаю: <b>{supported}</b>",
            parse_mode="HTML")
        return
    _handle_audio_file(uid, u, msg.document.file_id, mime, fname)

def _save_cover_from_file_id(uid: int, u: dict, file_id: str):
    try:
        path = download_file(file_id, suffix=".jpg")
    except Exception as e:
        log.exception(e)
        bot.send_message(uid, "❌ Не удалось скачать обложку трека.")
        return
    u["cover_path"] = path
    do_save(uid)

def _handle_audio_file(uid: int, u: dict, file_id: str, mime: str, fname: str):
    if u["step"] == "WAIT_COVER":
        bot.send_message(uid, "⚠️ Жду обложку трека, не аудио. Отправь картинку или нажми «пропустить».")
        return
    ext = detect_audio_ext(mime, fname) or ".mp3"
    wm = bot.send_message(uid,
        f"{ce(E_SEND, '📤')} скачиваю трек...", parse_mode="HTML")
    try:
        path = download_file(file_id, suffix=ext)
    except Exception as e:
        log.exception(e)
        bot.edit_message_text("❌ Не удалось скачать файл.", uid, wm.message_id)
        return
    try: bot.delete_message(uid, wm.message_id)
    except Exception: pass
    reset(uid)
    u = get_user(uid)
    u["audio_path"] = path
    u["fmt"]        = ext
    ask_title(uid)

@bot.message_handler(content_types=["audio"])
def handle_audio(msg: types.Message):
    uid = msg.from_user.id
    if not ensure_sub(uid):
        return
    u = get_user(uid)
    _handle_audio_file(uid, u,
        msg.audio.file_id,
        msg.audio.mime_type or "",
        msg.audio.file_name or "")

@bot.message_handler(content_types=["video"])
def handle_video(msg: types.Message):
    uid = msg.from_user.id
    if not ensure_sub(uid):
        return
    u = get_user(uid)
    _handle_audio_file(uid, u,
        msg.video.file_id,
        msg.video.mime_type or "video/mp4",
        msg.video.file_name or "video.mp4")

@bot.message_handler(content_types=["document"])
def handle_document(msg: types.Message):
    _route_document(msg)

@bot.message_handler(content_types=["photo"])
def handle_photo(msg: types.Message):
    uid = msg.from_user.id
    if not ensure_sub(uid):
        return
    u = get_user(uid)
    if u["step"] != "WAIT_COVER":
        bot.send_message(uid, "⚠️ Сначала отправь аудио-файл.")
        return
    _save_cover_from_file_id(uid, u, msg.photo[-1].file_id)

@bot.message_handler(content_types=["text"])
def handle_text(msg: types.Message):
    uid = msg.from_user.id
    if not ensure_sub(uid):
        return
    u    = get_user(uid)
    text = msg.text.strip()
    if text.startswith("/"):
        return
    step = u.get("step")
    if step == "WAIT_TITLE":
        try: bot.delete_message(uid, msg.message_id)
        except Exception: pass
        u["title"] = text
        ask_artist(uid)
    elif step == "WAIT_ARTIST":
        try: bot.delete_message(uid, msg.message_id)
        except Exception: pass
        u["artist"] = text
        ask_cover(uid)
    elif step == "WAIT_COVER":
        bot.send_message(uid, f"{ce(E_COVER, '🖼️')} Жду <b>фото</b> для обложки трека, не текст!",
                         parse_mode="HTML")
    else:
        bot.send_message(uid, "🎵 Сначала отправь аудио-файл!")

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def handle_check_sub(call: types.CallbackQuery):
    uid = call.from_user.id
    if is_subscribed(uid):
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        try: bot.delete_message(uid, call.message.message_id)
        except Exception: pass
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("владелец", url="https://t.me/vk_only"))
        bot.send_message(uid,
            f"{ce(E_MUSIC, '🎵')} Пришли трек, чтобы изменить название, исполнителя или обложку трека.",
            reply_markup=kb, parse_mode="HTML")
    else:
        bot.answer_callback_query(call.id, "❌ Вы ещё не подписались на канал!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "skip")
def handle_skip(call: types.CallbackQuery):
    uid = call.from_user.id
    if not ensure_sub(uid):
        bot.answer_callback_query(call.id)
        return
    u = get_user(uid)
    bot.answer_callback_query(call.id)
    step = u.get("step")
    if step == "WAIT_TITLE":
        ask_artist(uid)
    elif step == "WAIT_ARTIST":
        ask_cover(uid)
    elif step == "WAIT_COVER":
        do_save(uid)

if __name__ == "__main__":
    log.info("🎵 Bot started")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)