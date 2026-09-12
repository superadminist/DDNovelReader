# -*- coding: utf-8 -*-
"""UI 无关的阅读朗读协调器。

本类不创建 ``SpeechController``，只包装宿主注入的唯一实例。调用方必须只通过
``drain_events`` 消费该实例的事件队列，避免主阅读器、播放条等各自 drain。
"""
from __future__ import annotations

import bisect
import threading
import uuid
from collections import deque

from .textproc import clean_to_orig


SCHEMA_VERSION = 1
PLAYBACK_COMMANDS = frozenset(
    {"play", "pause", "stop", "previousSentence", "nextSentence"}
)


class PlaybackService:
    """把一个阅读会话绑定到宿主提供的唯一 ``SpeechController``。"""

    def __init__(self, speech_controller):
        if speech_controller is None:
            raise ValueError("speech_controller is required")
        self._speech = speech_controller
        self._lock = threading.RLock()
        self._session_id = ""
        self._book_id = ""
        self._book = None
        self._chapter_index = 0
        self._char_offset = 0
        self._status = "idle"
        self._sentence = None
        self._fallback_active = False
        self._active_backend = None
        self._generation = self._speech.generation()
        self._sequence = 0
        self._command_id = ""
        self._terminal_generation = None
        self._pending_events = deque()
        self._sentence_cache = {}
        self._closed = False

    @property
    def speech_controller(self):
        return self._speech

    def bind_session(
        self,
        session_id,
        book_id,
        book,
        chapter_index=0,
        char_offset=0,
    ):
        """绑定唯一当前阅读会话，并使上一朗读 generation 失效。"""
        if not session_id or not book_id or book is None or not book.chapters:
            raise ValueError("reader session, book id and content are required")
        with self._lock:
            self._ensure_open()
            self._generation = self._speech.stop()
            self._session_id = str(session_id)
            self._book_id = str(book_id)
            self._book = book
            self._sentence_cache.clear()
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, char_offset
            )
            self._status = "idle"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            self._command_id = ""
            self._terminal_generation = None
            self._pending_events.clear()
            self._speech.set_book_id(self._book_id)
            return self.snapshot()

    def set_position(self, chapter_index, char_offset, restart_playing=False):
        """同步阅读位置；显式导航可从新位置继续正在进行的朗读。"""
        with self._lock:
            self._ensure_bound()
            if self._status == "playing" and not restart_playing:
                return self._position()
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, char_offset
            )
            self._sentence = None
            if self._status == "playing":
                self._generation = self._speech.start(
                    self._book, self._chapter_index, self._char_offset
                )
                self._active_backend = self._speech.backend()
                self._terminal_generation = None
                self._queue_event("state")
            elif self._status == "paused":
                self._generation = self._speech.stop()
                self._active_backend = None
                self._terminal_generation = None
                self._queue_event("state")
            elif self._status in {"finished", "error"}:
                self._status = "idle"
                self._active_backend = None
                self._fallback_active = False
            return self._position()

    def control(self, command, command_id=None, session_id=None):
        """接受冻结契约中的五种 ReaderPlaybackCommand。"""
        if command not in PLAYBACK_COMMANDS:
            raise ValueError("unsupported playback command")
        command_id = str(command_id or uuid.uuid4().hex)
        with self._lock:
            self._ensure_bound()
            if session_id is not None and str(session_id) != self._session_id:
                raise RuntimeError("reader session is not bound")
            self._command_id = command_id
            if command == "play":
                accepted = self._play()
            elif command == "pause":
                accepted = self._pause()
            elif command == "stop":
                accepted = self._stop()
            else:
                accepted = self._step_sentence(-1 if command == "previousSentence" else 1)
            return {"commandId": command_id, "accepted": bool(accepted)}

    def snapshot(self):
        with self._lock:
            requested = self._speech.backend()
            return {
                "status": self._status,
                "position": self._position(),
                "sentence": dict(self._sentence) if self._sentence else None,
                "requestedBackend": requested,
                "activeBackend": self._active_backend,
                "fallbackActive": self._fallback_active,
            }

    def drain_events(self):
        """唯一底层 drain 入口，返回冻结的 ReaderPlaybackEvent 快照。"""
        with self._lock:
            self._ensure_open()
            output = list(self._pending_events)
            self._pending_events.clear()
            raw_events = self._speech.drain()
            for raw in raw_events:
                event = self._consume_raw_event(raw)
                if event is not None:
                    output.append(event)
            return output

    def shutdown(self, timeout=2.0):
        """停止唯一控制器；等待有上限，返回工作线程是否已退出。"""
        with self._lock:
            if self._closed:
                return True
            self._closed = True
            self._status = "idle"
            self._sentence = None
            self._active_backend = None
            self._fallback_active = False
        return self._speech.shutdown(timeout)

    def _play(self):
        if self._status == "playing":
            return False
        if self._status == "paused" and self._speech.resume():
            self._status = "playing"
        else:
            self._generation = self._speech.start(
                self._book, self._chapter_index, self._char_offset
            )
            self._status = "playing"
        self._terminal_generation = None
        self._fallback_active = False
        self._active_backend = self._speech.backend()
        self._queue_event("state")
        return True

    def _pause(self):
        if self._status != "playing" or not self._speech.pause():
            return False
        self._status = "paused"
        self._queue_event("state")
        return True

    def _stop(self):
        if self._status not in {"playing", "paused", "error"} and not self._speech.is_active():
            return False
        self._generation = self._speech.stop()
        self._terminal_generation = None
        self._status = "idle"
        self._sentence = None
        self._fallback_active = False
        self._active_backend = None
        self._queue_event("state")
        return True

    def _step_sentence(self, delta):
        target = self._adjacent_position(delta)
        if target is None:
            return False
        chapter_index, char_offset, sentence = target
        active = self._speech.is_active()
        self._chapter_index = chapter_index
        self._char_offset = char_offset
        self._sentence = sentence
        self._fallback_active = False
        self._terminal_generation = None
        if active:
            self._generation = self._speech.start(
                self._book, chapter_index, char_offset
            )
            self._status = "playing"
            self._active_backend = self._speech.backend()
        else:
            self._status = "idle"
            self._active_backend = None
        self._queue_event("state")
        return True

    def _consume_raw_event(self, raw):
        generation = raw.get("generation")
        if generation != self._generation:
            return None
        event_type = raw.get("type")
        if event_type == "sentence_start":
            chapter_index = int(raw["chapter_idx"])
            start = int(raw["char_offset"])
            end = int(raw["char_end"])
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, start
            )
            self._sentence = {
                "chapterIndex": self._chapter_index,
                "startOffset": self._char_offset,
                "endOffset": max(self._char_offset, end),
                "text": str(raw.get("text", "")),
            }
            self._status = "playing" if self._speech.is_playing() else self._status
            self._fallback_active = False
            self._active_backend = self._speech.backend()
            return self._event("sentenceStart")
        if event_type == "sentence_done":
            self._chapter_index, self._char_offset = self._clamp_position(
                raw["chapter_idx"], raw["char_offset"]
            )
            return self._event("sentenceDone")
        if event_type == "chapter":
            chapter_index = int(raw.get("chapter_idx", 0))
            if 0 <= chapter_index < len(self._book.chapters):
                self._chapter_index = chapter_index
                self._char_offset = 0
                self._sentence = None
                return self._event("state")
            return None
        if event_type == "finished":
            self._chapter_index = len(self._book.chapters) - 1
            self._char_offset = len(self._book.chapters[self._chapter_index].content)
            self._status = "finished"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            self._terminal_generation = generation
            return self._event("finished")
        if event_type == "error":
            error = {
                "code": str(raw.get("code") or "TTS_FAILED"),
                "message": str(raw.get("message") or "朗读出错"),
                "retryable": bool(raw.get("retryable", True)),
            }
            fallback_backend = raw.get("fallback_backend")
            if fallback_backend:
                self._fallback_active = True
                self._active_backend = str(fallback_backend)
                return self._event("fallback", error)
            self._status = "error"
            self._active_backend = None
            self._terminal_generation = generation
            return self._event("error", error)
        if event_type == "stopped":
            if self._terminal_generation == generation:
                return None
            self._status = "idle"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            return self._event("state")
        return None

    def _queue_event(self, reason, error=None):
        self._pending_events.append(self._event(reason, error))

    def _event(self, reason, error=None):
        self._sequence += 1
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sessionId": self._session_id,
            "bookId": self._book_id,
            "sequence": self._sequence,
            "commandId": self._command_id,
            "reason": reason,
            "playback": self.snapshot(),
            "error": error,
        }

    def _position(self):
        if self._book is None:
            return {"chapterIndex": 0, "charOffset": 0, "progressPercent": 0.0}
        absolute = self._book.cum[self._chapter_index] + self._char_offset
        percent = absolute / self._book.total_chars * 100 if self._book.total_chars else 0.0
        return {
            "chapterIndex": self._chapter_index,
            "charOffset": self._char_offset,
            "progressPercent": round(max(0.0, min(100.0, percent)), 3),
        }

    def _clamp_position(self, chapter_index, char_offset):
        chapter_index = max(0, min(int(chapter_index), len(self._book.chapters) - 1))
        content = self._book.chapters[chapter_index].content
        char_offset = max(0, min(int(char_offset), len(content)))
        return chapter_index, char_offset

    def _sentence_entries(self, chapter_index):
        cached = self._sentence_cache.get(chapter_index)
        if cached is not None:
            return cached
        chapter = self._book.chapters[chapter_index]
        clean_text, cmap = chapter.tts_content()
        entries = []
        clean_offset = 0
        while clean_offset < len(clean_text):
            text, next_offset, relative_start = self._speech._next_chunk(
                clean_text, clean_offset
            )
            if not text or next_offset <= clean_offset:
                break
            start = clean_to_orig(
                cmap, clean_offset + relative_start, len(chapter.content)
            )
            end = clean_to_orig(cmap, next_offset, len(chapter.content))
            entries.append((start, max(start, end), text))
            clean_offset = next_offset
        self._sentence_cache[chapter_index] = entries
        return entries

    def _adjacent_position(self, delta):
        entries = self._sentence_entries(self._chapter_index)
        if not entries:
            return None
        starts = [entry[0] for entry in entries]
        current = max(0, bisect.bisect_right(starts, self._char_offset) - 1)
        target = current + delta
        chapter_index = self._chapter_index
        if target < 0:
            if chapter_index == 0:
                return None
            chapter_index -= 1
            entries = self._sentence_entries(chapter_index)
            if not entries:
                return None
            target = len(entries) - 1
        elif target >= len(entries):
            if chapter_index >= len(self._book.chapters) - 1:
                return None
            chapter_index += 1
            entries = self._sentence_entries(chapter_index)
            if not entries:
                return None
            target = 0
        start, end, text = entries[target]
        sentence = {
            "chapterIndex": chapter_index,
            "startOffset": start,
            "endOffset": end,
            "text": text,
        }
        return chapter_index, start, sentence

    def _ensure_bound(self):
        self._ensure_open()
        if self._book is None or not self._session_id:
            raise RuntimeError("reader session is not bound")

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("playback service is closed")
