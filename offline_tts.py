"""Offline German speech using an explicitly configured local eSpeak NG engine."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unicodedata

DEFAULT_SPEECH_PATH = Path(r'D:\BaiduNetdiskDownload\DeutschWortschatz\Speech')
MAX_AUDIO = 15 * 1024 * 1024
_LOCK = threading.RLock()
_ENGINE = None


def clear_missing_audio_warnings(messages):
    return [message for message in messages if not message.startswith(
        ('本地暂无此词的录音', '暂无真人录音', 'TTS 不可用'))]


def available(root=DEFAULT_SPEECH_PATH):
    root = Path(root)
    return ((root / 'espeakng_loader' / 'espeak-ng.dll').is_file()
            and (root / 'espeakng_loader' / 'espeak-ng-data' / 'de_dict').is_file())


class _Voice(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('languages', ctypes.c_char_p),
                ('identifier', ctypes.c_char_p), ('gender', ctypes.c_ubyte),
                ('age', ctypes.c_ubyte), ('variant', ctypes.c_ubyte),
                ('reserved', ctypes.c_ubyte), ('score', ctypes.c_int), ('spare', ctypes.c_void_p)]


class _Engine:
    def __init__(self, root):
        self.root = Path(root).resolve()
        package = self.root / 'espeakng_loader'
        self.lib = ctypes.CDLL(str(package / 'espeak-ng.dll'))
        self.lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        self.lib.espeak_Initialize.restype = ctypes.c_int
        self.sample_rate = self.lib.espeak_Initialize(2, 0, str(package).encode('utf-8'), 0)
        if self.sample_rate <= 0:
            raise RuntimeError('本地语音引擎初始化失败，请检查语言数据目录。')
        self.lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        self.lib.espeak_SetVoiceByName.restype = ctypes.c_int
        if self.lib.espeak_SetVoiceByName(b'de') != 0:
            raise RuntimeError('未找到德语声音，未使用其他语言代替。')
        self.lib.espeak_GetCurrentVoice.restype = ctypes.POINTER(_Voice)
        voice = self.lib.espeak_GetCurrentVoice().contents
        if not voice.languages or not voice.languages[1:].startswith(b'de'):
            raise RuntimeError('当前声音不是德语，已停止合成。')
        self.voice = (voice.name or b'German').decode('utf-8', errors='replace')
        self.lib.espeak_Info.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self.lib.espeak_Info.restype = ctypes.c_char_p
        self.version = self.lib.espeak_Info(None).decode('utf-8', errors='replace')
        self.lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.espeak_SetParameter(1, 150, 0)
        self._callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
        self._pcm = bytearray()
        self._overflow = False

        def callback(samples, count, events):
            if count > 0 and samples:
                if len(self._pcm) + count * 2 > MAX_AUDIO - 44:
                    self._overflow = True
                    return 1
                self._pcm.extend(ctypes.string_at(samples, count * 2))
            return 0

        self._callback = self._callback_type(callback)
        self.lib.espeak_SetSynthCallback.argtypes = [self._callback_type]
        self.lib.espeak_SetSynthCallback(self._callback)
        self.lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint,
            ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
        self.lib.espeak_Synth.restype = ctypes.c_int
        self.lib.espeak_Synchronize.restype = ctypes.c_int

    def render(self, text):
        self._pcm.clear()
        self._overflow = False
        encoded = text.encode('utf-8')
        identifier = ctypes.c_uint()
        result = self.lib.espeak_Synth(encoded, len(encoded) + 1, 0, 1, 0,
                                       1 | 0x1000, ctypes.byref(identifier), None)
        synchronized = self.lib.espeak_Synchronize()
        if result != 0 or synchronized != 0 or self._overflow or len(self._pcm) < 1000:
            raise RuntimeError('本地德语语音未生成有效音频。')
        pcm = bytes(self._pcm)
        return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt '
                + struct.pack('<IHHIIHH', 16, 1, 1, self.sample_rate, self.sample_rate * 2, 2, 16)
                + b'data' + struct.pack('<I', len(pcm)) + pcm)


def _engine(root):
    global _ENGINE
    if not available(root):
        raise FileNotFoundError('未找到本地德语语音资源，请设置 D 盘上的语音目录。')
    root = Path(root).resolve()
    if _ENGINE is None or _ENGINE.root != root:
        _ENGINE = _Engine(root)
    return _ENGINE


def _valid_audio(path):
    if not path.is_file() or not 44 < path.stat().st_size <= MAX_AUDIO:
        return False
    with path.open('rb') as handle:
        header = handle.read(12)
    return ((header.startswith(b'RIFF') and header[8:12] == b'WAVE')
            or header.startswith((b'OggS', b'ID3', b'fLaC'))
            or header[0] == 255 and header[1] & 0xe0 == 0xe0)


def generate(text, audio_root, speech_root=DEFAULT_SPEECH_PATH):
    text = unicodedata.normalize('NFC', str(text)).strip()
    if not text or len(text) > 200 or any(unicodedata.category(char).startswith('C') for char in text):
        raise ValueError('朗读文本必须为 1–200 个字符的单行德语。')
    with _LOCK:
        engine = _engine(speech_root)
        identity = f'espeak-ng:{engine.version}:de:150:{text}'
        filename = 'offline-de-' + hashlib.sha256(identity.encode('utf-8')).hexdigest() + '.wav'
        root = Path(audio_root)
        root.mkdir(parents=True, exist_ok=True)
        target = root / filename
        if not _valid_audio(target):
            data = engine.render(text)
            with tempfile.NamedTemporaryFile(dir=root, suffix='.part', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return {'audio_file': filename, 'audio_kind': 'offline_tts', 'audio_url': None,
                'audio_license': 'eSpeak NG 本地合成（非真人录音）',
                'attribution': f'eSpeak NG {engine.version} · {engine.voice} (de) · 合成读音请核对。'
                    '引擎及语言数据：GPL-3.0-or-later；https://github.com/espeak-ng/espeak-ng'}


def ensure_audio(store, row, audio_root, speech_root=DEFAULT_SPEECH_PATH):
    filename = row.get('audio_file')
    if filename and not any(char in filename for char in '/\\:'):
        target = Path(audio_root) / filename
        if _valid_audio(target):
            return row, False
    fields = generate(row.get('dictionary_word') or row['word'], audio_root, speech_root)
    row = store.attach_audio(row['id'], fields)
    messages = json.loads(row.get('lookup_warnings_json') or '[]')
    filtered = clear_missing_audio_warnings(messages)
    if filtered != messages:
        row = store.refresh(row['id'], {'lookup_warnings': filtered})
    return row, True


def fill_missing(store, audio_root, speech_root=DEFAULT_SPEECH_PATH):
    count, errors = 0, []
    for row in store.list():
        try:
            _, changed = ensure_audio(store, row, audio_root, speech_root)
            count += int(changed)
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"{row['word']}：{exc}")
    return count, errors
