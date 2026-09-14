# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject

from novelreader.qt_bridge import DesktopBridge


class _Window(QObject):
    def isMaximized(self):
        return False

    def isFullScreen(self):
        return False


class _Library:
    def __init__(self, path):
        self.path = path

    def load_library(self):
        return {"books": [], "total": 0}


class _Speech:
    def __init__(self):
        self.values = {}

    def set_voice(self, value):
        self.values["voice"] = value

    def set_rate(self, value):
        self.values["rate"] = value

    def set_sentence_gap(self, value):
        self.values["gap"] = value

    def set_volume(self, value):
        self.values["volume"] = value


class _Playback:
    def __init__(self):
        self.speech_controller = _Speech()
        self.session_id = ""
        self.events = []
        self.closed = False

    @staticmethod
    def _position():
        return {"chapterIndex": 0, "charOffset": 0, "progressPercent": 0.0}

    def snapshot(self):
        return {
            "status": "idle",
            "position": self._position(),
            "sentence": None,
            "requestedBackend": "sapi",
            "activeBackend": None,
            "fallbackActive": False,
        }

    def bind_session(self, session_id, book_id, content, chapter_index, char_offset):
        self.session_id = session_id
        return self.snapshot()

    def set_position(self, chapter_index, char_offset, restart_playing=False):
        return {"chapterIndex": chapter_index, "charOffset": char_offset}

    def control(self, command, command_id=None, session_id=None):
        if session_id != self.session_id:
            raise RuntimeError("reader session is not bound")
        return {"commandId": "command-1", "accepted": command == "play"}

    def drain_events(self):
        events, self.events = self.events, []
        return events

    def shutdown(self, timeout=2.0):
        self.closed = True
        return True


class _Reader:
    session_id = "session-1"

    def __init__(self):
        self.global_settings = self._settings()

    @staticmethod
    def _position():
        return {"chapterIndex": 0, "charOffset": 0, "progressPercent": 0.0}

    @classmethod
    def _window(cls):
        return {
            "sessionId": cls.session_id,
            "bookId": "book-1",
            "chapterIndex": 0,
            "chapterTitle": "第一章",
            "chapterCharCount": 4,
            "anchorOffset": 0,
            "windowStartOffset": 0,
            "windowEndOffset": 4,
            "hasBefore": False,
            "hasAfter": False,
            "blocks": [{
                "id": "0:0:4",
                "startOffset": 0,
                "endOffset": 4,
                "text": "真实正文",
                "startsParagraph": True,
                "endsParagraph": True,
            }],
        }

    @staticmethod
    def _settings():
        return {
            "fontFamily": "微软雅黑",
            "fontSize": 17,
            "lineSpacing": 1.5,
            "paragraphMode": 1,
            "firstLineIndent": True,
            "ttsRate": 200,
            "ttsVoiceId": "",
            "volume": 100,
            "sentenceGapSeconds": 0.1,
        }

    def open_book(self, book_id):
        return {
            "sessionId": self.session_id,
            "book": {
                "id": book_id,
                "title": "真实书籍",
                "author": "",
                "format": "TXT",
                "totalChars": 4,
                "chapters": [{"index": 0, "title": "第一章", "charCount": 4}],
            },
            "position": self._position(),
            "window": self._window(),
            "settings": self._settings(),
            "bookmarkCount": 0,
        }

    def get_session_content(self, session_id):
        if session_id != self.session_id:
            raise RuntimeError("expired")
        return object()

    def get_window(self, session_id, chapter_index, anchor_offset):
        return self._window()

    def navigate(self, session_id, target):
        return {"position": self._position(), "window": self._window()}

    def update_position(self, session_id, chapter_index, char_offset):
        return {"updated": True, "position": self._position()}

    def search(self, session_id, query, cursor, cancel_event):
        return {"query": query, "total": 0, "nextCursor": "", "results": []}

    def list_bookmarks(self, session_id, cursor):
        return {"total": 0, "nextCursor": "", "items": []}

    def add_bookmark(self, session_id, chapter_index, start_offset, end_offset, note):
        return {
            "id": "bookmark-1",
            "chapterIndex": 0,
            "chapterTitle": "第一章",
            "startOffset": 0,
            "endOffset": 2,
            "text": "真实",
            "note": note,
            "createdAt": 1.0,
        }

    def remove_bookmark(self, session_id, bookmark_id):
        return {"bookmarkId": bookmark_id, "removed": True}

    def update_settings(self, session_id, patch):
        settings = self._settings()
        settings.update(patch)
        self.global_settings = settings
        return settings

    def settings_state(self):
        return dict(self.global_settings)

    def update_global_settings(self, patch):
        self.global_settings.update(patch)
        return dict(self.global_settings)


class Stage3QtBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.playback = _Playback()
        self.bridge = DesktopBridge(
            _Window(),
            library=_Library(Path(self.temp_dir.name) / "library.json"),
            reader=_Reader(),
            playback=self.playback,
        )

    def tearDown(self):
        self.bridge.shutdown()
        self.temp_dir.cleanup()

    @staticmethod
    def _data(raw):
        payload = json.loads(raw)
        if not payload["ok"]:
            raise AssertionError(payload)
        return payload["data"]

    def test_reader_capabilities_and_frozen_native_slots(self):
        state = self._data(self.bridge.getInitialState())
        self.assertTrue(state["capabilities"]["reader"])
        self.assertTrue(state["capabilities"]["tts"])
        self.assertTrue(state["capabilities"]["floatingReader"])
        meta = self.bridge.metaObject()
        signatures = {
            bytes(meta.method(index).methodSignature()).decode()
            for index in range(meta.methodCount())
        }
        for signature in (
            "openReaderBook(QString)",
            "getReaderWindow(QString)",
            "navigateReader(QString)",
            "updateReaderPosition(QString)",
            "searchReader(QString)",
            "listReaderBookmarks(QString)",
            "addReaderBookmark(QString)",
            "removeReaderBookmark(QString)",
            "controlReaderPlayback(QString)",
            "updateReaderSettings(QString)",
            "updateSpeechPreferences(QString)",
            "getFloatingReaderState()",
            "showFloatingReader()",
            "closeFloatingReader()",
            "updateFloatingReaderSettings(QString)",
            "startFloatingWindowMove()",
            "startFloatingWindowResize(QString)",
        ):
            self.assertIn(signature, signatures)

    def test_open_search_and_playback_events_follow_contract(self):
        opened = []
        searched = []
        playback_events = []
        self.bridge.readerOpened.connect(lambda raw: opened.append(json.loads(raw)))
        self.bridge.readerSearchFinished.connect(lambda raw: searched.append(json.loads(raw)))
        self.bridge.readerPlaybackChanged.connect(
            lambda raw: playback_events.append(json.loads(raw))
        )

        start = self._data(self.bridge.openReaderBook("book-1"))
        self.bridge._reader_thread.join(2)
        self.bridge._drain_reader_events()
        self.assertEqual(start["state"], "loading")
        self.assertEqual(opened[0]["requestId"], start["requestId"])
        self.assertEqual(opened[0]["data"]["window"]["blocks"][0]["text"], "真实正文")
        self.assertEqual(opened[0]["data"]["playback"]["status"], "idle")

        search = self._data(self.bridge.searchReader(json.dumps({
            "sessionId": "session-1", "query": "真实", "cursor": ""
        })))
        self.bridge._search_thread.join(2)
        self.bridge._drain_reader_events()
        self.assertEqual(searched[0]["requestId"], search["requestId"])
        self.assertEqual(searched[0]["data"]["query"], "真实")

        self.playback.events.append({
            "schemaVersion": 2,
            "sessionId": "session-1",
            "bookId": "book-1",
            "sequence": 1,
            "commandId": "command-1",
            "reason": "state",
            "playback": self.playback.snapshot(),
            "error": None,
        })
        self.bridge._drain_reader_events()
        self.assertEqual(playback_events[0]["sequence"], 1)

    def test_sync_reader_controls_and_settings(self):
        self._data(self.bridge.openReaderBook("book-1"))
        self.bridge._reader_thread.join(2)
        self.bridge._drain_reader_events()
        session = "session-1"
        self.assertEqual(self._data(self.bridge.getReaderWindow(json.dumps({
            "sessionId": session, "chapterIndex": 0, "anchorOffset": 0
        })))["blocks"][0]["text"], "真实正文")
        self.assertIn("playback", self._data(self.bridge.navigateReader(json.dumps({
            "sessionId": session,
            "target": {"kind": "position", "chapterIndex": 0, "charOffset": 0},
        }))))
        self.assertTrue(self._data(self.bridge.updateReaderPosition(json.dumps({
            "sessionId": session, "chapterIndex": 0, "charOffset": 0
        })))["updated"])
        self.assertEqual(self._data(self.bridge.addReaderBookmark(json.dumps({
            "sessionId": session,
            "chapterIndex": 0,
            "startOffset": 0,
            "endOffset": 2,
            "note": "测试",
        })))["id"], "bookmark-1")
        self.assertTrue(self._data(self.bridge.removeReaderBookmark(json.dumps({
            "sessionId": session, "bookmarkId": "bookmark-1"
        })))["removed"])
        self.assertEqual(self._data(self.bridge.controlReaderPlayback(json.dumps({
            "sessionId": session, "command": "play"
        })))["commandId"], "command-1")
        settings = self._data(self.bridge.updateReaderSettings(json.dumps({
            "sessionId": session, "patch": {"fontSize": 20, "volume": 60}
        })))
        self.assertEqual(settings["fontSize"], 20)
        self.assertEqual(self.playback.speech_controller.values["volume"], 60)

    def test_speech_settings_are_available_without_open_book_and_apply_live(self):
        state = self._data(self.bridge.getInitialState())
        edge_voices = [voice for voice in state["speech"]["voices"] if voice["backend"] == "edge"]
        self.assertEqual(len(edge_voices), 9)
        updated = self._data(self.bridge.updateSpeechPreferences(json.dumps({
            "patch": {
                "ttsVoiceId": "zh-CN-YunxiNeural",
                "ttsRate": 260,
                "sentenceGapSeconds": 0.25,
            }
        })))
        self.assertEqual(updated["settings"]["ttsRate"], 260)
        self.assertEqual(self.playback.speech_controller.values["voice"], "zh-CN-YunxiNeural")
        self.assertEqual(self.playback.speech_controller.values["gap"], 0.25)


if __name__ == "__main__":
    unittest.main()
