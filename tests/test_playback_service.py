# -*- coding: utf-8 -*-
import asyncio
import queue
import threading
import time
import types
import unittest
from unittest import mock

from novelreader.book_loader import BookContent, Chapter
from novelreader.playback_service import PlaybackService
from novelreader.tts_engine import SpeechController, synth_audio


class FakeSpeechController:
    def __init__(self):
        self._generation = 0
        self._state = "idle"
        self._backend = "sapi"
        self._events = queue.Queue()
        self.book_id = ""
        self.starts = []
        self.prepares = []
        self.shutdown_timeout = None

    def generation(self):
        return self._generation

    def backend(self):
        return self._backend

    def set_book_id(self, book_id):
        self.book_id = book_id

    def prepare(self, book, chapter_index, char_offset):
        self.prepares.append((chapter_index, char_offset))

    def start(self, book, chapter_index, char_offset):
        self._generation += 1
        self._state = "playing"
        self.starts.append((chapter_index, char_offset))
        return self._generation

    def pause(self):
        if self._state != "playing":
            return False
        self._state = "paused"
        return True

    def resume(self):
        if self._state != "paused":
            return False
        self._state = "playing"
        return True

    def stop(self):
        self._generation += 1
        self._state = "idle"
        return self._generation

    def is_playing(self):
        return self._state == "playing"

    def is_active(self):
        return self._state in {"playing", "paused"}

    def drain(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def emit(self, event):
        self._events.put(event)

    def shutdown(self, timeout):
        self.shutdown_timeout = timeout
        self._state = "idle"
        return True

    _next_chunk = staticmethod(SpeechController._next_chunk)


def make_book(first="第一句。第二句！第三句？", second="第四句。第五句。"):
    return BookContent(
        "测试书",
        "",
        "txt",
        [Chapter("第一章", first), Chapter("第二章", second)],
    )


class PlaybackServiceTests(unittest.TestCase):
    def setUp(self):
        self.speech = FakeSpeechController()
        self.book = make_book()
        self.service = PlaybackService(self.speech)
        self.service.bind_session("reader-1", "book-1", self.book, 0, 0)

    def test_playback_event_matches_frozen_schema(self):
        result = self.service.control("play", "command-1")
        generation = self.speech.generation()
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 0,
            "char_end": 4,
            "text": "第一句。",
        })

        events = self.service.drain_events()

        self.assertEqual(result, {"commandId": "command-1", "accepted": True})
        self.assertEqual([event["reason"] for event in events], ["state", "sentenceStart"])
        event = events[-1]
        self.assertEqual(
            set(event),
            {"schemaVersion", "sessionId", "bookId", "sequence", "commandId", "reason", "playback", "error"},
        )
        self.assertEqual(event["schemaVersion"], 2)
        self.assertEqual(event["sessionId"], "reader-1")
        self.assertEqual(event["playback"]["sentence"]["endOffset"], 4)

    def test_floating_context_is_lazy_and_uses_bound_session(self):
        self.assertEqual(
            self.service.session_identity(),
            {"sessionId": "reader-1", "bookId": "book-1"},
        )
        self.assertEqual(self.service._sentence_cache, {})

        context = self.service.floating_context()

        self.assertEqual(context["chapterIndex"], 0)
        self.assertEqual(context["chapterTitle"], "第一章")
        self.assertIsNone(context["previous"])
        self.assertEqual(context["current"]["text"], "第一句。")
        self.assertEqual(context["next"]["text"], "第二句！")
        self.assertEqual(set(self.service._sentence_cache), {0})

    def test_binding_and_idle_navigation_prepare_the_current_position(self):
        self.assertEqual(self.speech.prepares, [(0, 0)])

        self.service.set_position(1, 2)

        self.assertEqual(self.speech.prepares[-1], (1, 2))

    def test_sentence_done_does_not_advance_the_visible_floating_lyric(self):
        self.service.control("play", "play-1")
        generation = self.speech.generation()
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 0,
            "char_end": 4,
            "text": "第一句。",
        })
        self.service.drain_events()
        self.speech.emit({
            "type": "sentence_done",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 4,
        })
        self.service.drain_events()

        self.assertEqual(self.service.floating_context()["current"]["text"], "第一句。")

        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 4,
            "char_end": 8,
            "text": "第二句！",
        })
        self.service.drain_events()
        self.assertEqual(self.service.floating_context()["current"]["text"], "第二句！")

    def test_pause_freezes_a_sentence_start_that_races_with_event_polling(self):
        self.service.control("play", "play-1")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 0,
            "char_end": 4,
            "text": "第一句。",
        })
        self.service.drain_events()

        self.service.control("pause", "pause-1")
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 4,
            "char_end": 8,
            "text": "第二句！",
        })
        paused_events = self.service.drain_events()

        self.assertEqual(paused_events[-1]["playback"]["status"], "paused")
        self.assertEqual(self.service.snapshot()["sentence"]["text"], "第一句。")
        self.assertEqual(self.service.floating_context()["current"]["text"], "第一句。")

        self.service.control("play", "resume-1")
        resumed_events = self.service.drain_events()
        self.assertEqual(
            [event["reason"] for event in resumed_events],
            ["state"],
        )
        self.assertEqual(self.service.snapshot()["sentence"]["text"], "第一句。")
        self.assertEqual(self.service.floating_context()["current"]["text"], "第一句。")

        # SAPI was interrupted by Pause and must announce its replay from the
        # worker, not advance from a stale, deferred next-sentence event.
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 0,
            "char_end": 4,
            "text": "第一句。",
        })
        replayed = self.service.drain_events()
        self.assertEqual([event["reason"] for event in replayed], ["sentenceStart"])
        self.assertEqual(replayed[0]["playback"]["sentence"]["text"], "第一句。")

    def test_pause_and_resume_after_done_keep_both_surfaces_until_audio_starts(self):
        self.service.control("play", "play-1")
        generation = self.speech.generation()
        self.speech.emit({
            "type": "sentence_start", "generation": generation,
            "chapter_idx": 0, "char_offset": 0, "char_end": 4,
            "text": "第一句。",
        })
        self.service.drain_events()
        self.speech.emit({
            "type": "sentence_done", "generation": generation,
            "chapter_idx": 0, "char_offset": 4,
        })
        self.service.drain_events()

        self.service.control("pause", "pause-1")
        paused = self.service.drain_events()[-1]["playback"]
        self.assertEqual(paused["sentence"]["text"], "第一句。")
        self.assertEqual(self.service.floating_context()["current"]["text"], "第一句。")
        self.service.control("play", "resume-1")
        resumed = self.service.drain_events()[-1]["playback"]
        self.assertEqual(resumed["sentence"]["text"], "第一句。")
        self.assertEqual(self.service.floating_context()["current"]["text"], "第一句。")
        self.speech.emit({
            "type": "sentence_start", "generation": generation,
            "chapter_idx": 0, "char_offset": 4, "char_end": 8,
            "text": "第二句！",
        })
        started = self.service.drain_events()[-1]["playback"]
        self.assertEqual(started["sentence"]["text"], "第二句！")
        self.assertEqual(self.service.floating_context()["current"]["text"], "第二句！")

    def test_edge_pause_resumes_the_deferred_audio_start_in_place(self):
        self.speech._backend = "edge"
        self.service.control("play", "play-edge")
        generation = self.speech.generation()
        self.service.drain_events()
        self.service.control("pause", "pause-edge")
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 0,
            "char_end": 4,
            "text": "第一句。",
        })
        self.service.drain_events()
        self.assertIsNone(self.service.snapshot()["sentence"])
        self.service.control("play", "resume-edge")
        resumed = self.service.drain_events()
        self.assertEqual([event["reason"] for event in resumed], ["sentenceStart", "state"])
        self.assertEqual(resumed[0]["playback"]["sentence"]["text"], "第一句。")

    def test_voice_or_rate_refresh_restarts_current_sentence_and_preserves_pause(self):
        self.service.control("play", "play-1")
        generation = self.speech.generation()
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 4,
            "char_end": 8,
            "text": "第二句！",
        })
        self.service.drain_events()

        self.service.refresh_speech(restart_current=True)
        self.assertEqual(self.speech.starts[-1], (0, 4))
        self.assertEqual(self.service.snapshot()["status"], "playing")

        self.service.control("pause", "pause-1")
        self.service.drain_events()
        self.service.refresh_speech(restart_current=True)
        self.assertEqual(self.service.snapshot()["status"], "paused")
        self.assertEqual(self.speech._state, "idle")
        self.service.control("play", "resume-1")
        self.assertEqual(self.speech.starts[-1], (0, 4))

    def test_stale_generation_is_discarded_after_restart(self):
        self.service.control("play", "play-1")
        old_generation = self.speech.generation()
        self.service.control("nextSentence", "next-1")
        new_generation = self.speech.generation()
        self.assertGreater(new_generation, old_generation)
        self.speech.emit({
            "type": "stopped",
            "generation": old_generation,
        })
        self.speech.emit({
            "type": "sentence_start",
            "generation": new_generation,
            "chapter_idx": 0,
            "char_offset": 4,
            "char_end": 8,
            "text": "第二句！",
        })

        events = self.service.drain_events()

        self.assertNotIn("idle", [event["playback"]["status"] for event in events])
        self.assertEqual(events[-1]["playback"]["sentence"]["text"], "第二句！")

    def test_explicit_navigation_restarts_playing_with_a_new_generation(self):
        self.service.control("play", "play-1")
        old_generation = self.speech.generation()
        self.service.drain_events()

        position = self.service.set_position(1, 2, restart_playing=True)

        self.assertGreater(self.speech.generation(), old_generation)
        self.assertEqual(self.speech.starts[-1], (1, 2))
        self.assertEqual(position["chapterIndex"], 1)
        self.assertEqual(self.service.drain_events()[-1]["playback"]["status"], "playing")

    def test_passive_scroll_does_not_move_active_playback(self):
        self.service.control("play", "play-1")
        self.service.drain_events()

        position = self.service.set_position(1, 2)

        self.assertEqual(position["chapterIndex"], 0)
        self.assertEqual(self.speech.starts, [(0, 0)])

    def test_edge_fallback_keeps_playing(self):
        self.speech._backend = "edge"
        self.service.control("play", "play-edge")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "error",
            "generation": generation,
            "code": "EDGE_OFFLINE_FALLBACK",
            "message": "联网语音生成失败，本句已用系统语音朗读",
            "retryable": True,
            "fallback_backend": "sapi",
        })

        event = self.service.drain_events()[0]

        self.assertEqual(event["reason"], "fallback")
        self.assertEqual(event["playback"]["status"], "playing")
        self.assertEqual(event["playback"]["requestedBackend"], "edge")
        self.assertEqual(event["playback"]["activeBackend"], "sapi")
        self.assertTrue(event["playback"]["fallbackActive"])

    def test_edge_fallback_stays_visible_across_sentences_pause_and_resume(self):
        self.speech._backend = "edge"
        self.service.control("play", "play-edge")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "error",
            "generation": generation,
            "code": "EDGE_OFFLINE_FALLBACK",
            "message": "暂时使用系统语音",
            "retryable": True,
            "fallback_backend": "sapi",
        })
        self.service.drain_events()
        self.speech.emit({
            "type": "sentence_start",
            "generation": generation,
            "chapter_idx": 0,
            "char_offset": 4,
            "char_end": 8,
            "text": "第二句！",
        })

        sentence_event = self.service.drain_events()[0]
        self.assertTrue(sentence_event["playback"]["fallbackActive"])
        self.assertEqual(sentence_event["playback"]["activeBackend"], "sapi")

        self.service.control("pause", "pause-edge")
        self.service.drain_events()
        self.service.control("play", "resume-edge")
        resumed = self.service.drain_events()[-1]
        self.assertTrue(resumed["playback"]["fallbackActive"])
        self.assertEqual(resumed["playback"]["activeBackend"], "sapi")

    def test_confirmed_edge_recovery_clears_fallback_state(self):
        self.speech._backend = "edge"
        self.service.control("play", "play-edge")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "error",
            "generation": generation,
            "code": "EDGE_OFFLINE_FALLBACK",
            "message": "暂时使用系统语音",
            "retryable": True,
            "fallback_backend": "sapi",
        })
        self.service.drain_events()
        self.speech.emit({
            "type": "edge_recovered",
            "generation": generation,
            "backend": "edge",
        })

        event = self.service.drain_events()[0]

        self.assertEqual(event["reason"], "recovered")
        self.assertFalse(event["playback"]["fallbackActive"])
        self.assertEqual(event["playback"]["activeBackend"], "edge")

    def test_explicit_speech_refresh_starts_a_fresh_backend_attempt(self):
        self.speech._backend = "edge"
        self.service.control("play", "play-edge")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "error",
            "generation": generation,
            "code": "EDGE_OFFLINE_FALLBACK",
            "message": "暂时使用系统语音",
            "retryable": True,
            "fallback_backend": "sapi",
        })
        self.service.drain_events()

        snapshot = self.service.refresh_speech(restart_current=True)

        self.assertFalse(snapshot["fallbackActive"])
        self.assertEqual(snapshot["activeBackend"], "edge")

    def test_fatal_error_is_not_overwritten_by_following_stopped(self):
        self.service.control("play", "play-fatal")
        generation = self.speech.generation()
        self.service.drain_events()
        self.speech.emit({
            "type": "error",
            "generation": generation,
            "code": "SAPI_PLAYBACK_FAILED",
            "message": "朗读出错",
            "retryable": True,
            "fallback_backend": None,
        })
        self.speech.emit({"type": "stopped", "generation": generation})

        events = self.service.drain_events()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reason"], "error")
        self.assertEqual(events[0]["playback"]["status"], "error")

    def test_previous_and_next_sentence_reuse_bound_book(self):
        next_result = self.service.control("nextSentence", "next")
        next_event = self.service.drain_events()[0]
        previous_result = self.service.control("previousSentence", "previous")
        previous_event = self.service.drain_events()[0]

        self.assertTrue(next_result["accepted"])
        self.assertEqual(next_event["playback"]["sentence"]["text"], "第二句！")
        self.assertTrue(previous_result["accepted"])
        self.assertEqual(previous_event["playback"]["sentence"]["text"], "第一句。")

    def test_shutdown_delegates_to_the_only_controller(self):
        self.assertTrue(self.service.shutdown(0.25))
        self.assertEqual(self.speech.shutdown_timeout, 0.25)
        with self.assertRaises(RuntimeError):
            self.service.drain_events()

    def test_20k_and_100k_sentence_index_are_linear_enough(self):
        elapsed = []
        for size in (20_000, 100_000):
            text = ("这是一句用于性能回归的文字。" * (size // 14 + 1))[:size]
            service = PlaybackService(FakeSpeechController())
            service.bind_session("perf", "book", make_book(text, "末章。"), 0, 0)
            started = time.perf_counter()
            entries = service._sentence_entries(0)
            elapsed.append(time.perf_counter() - started)
            self.assertTrue(entries)
        self.assertLess(elapsed[0], 1.0)
        self.assertLess(elapsed[1], 3.0)
        self.assertLess(elapsed[1] / max(elapsed[0], 0.001), 10.0)


class SpeechControllerContractTests(unittest.TestCase):
    @staticmethod
    def _wait_for_stop(controller, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline and not controller.is_stopped():
            time.sleep(0.01)

    def test_events_include_generation_and_original_end_offset(self):
        controller = SpeechController()
        def speak(text, generation, start_event=None):
            controller._post(dict(start_event), generation)
            return True
        controller._speak_sapi = speak
        book = make_book("第一句。。。 😀 第二句。", "")

        generation = controller.start(book, 0, 0)
        self._wait_for_stop(controller)
        events = controller.drain()
        controller.shutdown()

        self.assertTrue(events)
        self.assertTrue(all(event["generation"] == generation for event in events))
        starts = [event for event in events if event["type"] == "sentence_start"]
        done = [event for event in events if event["type"] == "sentence_done"]
        self.assertGreaterEqual(len(starts), 2)
        self.assertGreater(starts[0]["char_end"], starts[0]["char_offset"])
        self.assertEqual(starts[0]["char_end"], done[0]["char_offset"])

    def test_pause_during_edge_fallback_replays_the_same_sapi_sentence(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        first_started = threading.Event()
        replay_started = threading.Event()
        calls = []

        def speak_edge(text, generation, *args, **kwargs):
            controller._active_sentence_backend = "sapi"
            calls.append(text)
            if len(calls) == 1:
                first_started.set()
                deadline = time.time() + 1
                while time.time() < deadline and not controller.is_paused():
                    time.sleep(0.005)
            elif len(calls) == 2:
                replay_started.set()
            return True

        controller._speak_edge = speak_edge
        book = make_book("第一句。第二句！", "")
        try:
            controller.start(book, 0, 0)
            self.assertTrue(first_started.wait(0.5))
            self.assertTrue(controller.pause())
            time.sleep(0.05)
            self.assertEqual(calls, ["第一句。"])
            self.assertTrue(controller.resume())
            self.assertTrue(replay_started.wait(0.5))
        finally:
            controller.stop()
            controller.shutdown()

        self.assertEqual(calls[:2], ["第一句。", "第一句。"])

    def test_edge_failure_is_structured_and_falls_back(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        controller._edge_synthesize = lambda text: None
        def speak(text, generation, start_event=None):
            controller._post(dict(start_event), generation)
            return True
        controller._speak_sapi = speak
        book = make_book("第一句。", "")

        generation = controller.start(book, 0, 0)
        self._wait_for_stop(controller)
        events = controller.drain()
        controller.shutdown()

        errors = [event for event in events if event["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["generation"], generation)
        self.assertEqual(errors[0]["code"], "EDGE_OFFLINE_FALLBACK")
        self.assertTrue(errors[0]["retryable"])
        self.assertEqual(errors[0]["fallback_backend"], "sapi")

    def test_edge_recovery_probe_switches_back_only_on_a_sentence_boundary(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        controller._book = make_book()
        controller._state = "playing"
        controller._gen = 23
        controller._edge_session_fallback = True
        controller._edge_recovery_due_at = 0.0
        controller._edge_synthesize = lambda text: b"online"
        controller._speak_sapi = lambda text, generation, start_event=None: True
        controller._speak_edge_play = lambda audio, generation, start_event=None: audio == b"online"
        with controller._cv:
            controller._schedule_edge_recovery_locked()
            controller._edge_recovery_due_at = 0.0

        with mock.patch("novelreader.tts_engine.time.monotonic", return_value=1.0):
            controller._edge_recovery_due_at = 1.0
            self.assertTrue(
                controller._speak_edge("第二句！", 23, 0, 4, 4, "", 8)
            )
        deadline = time.time() + 1
        while time.time() < deadline:
            ready = controller._edge_recovery_event
            if ready is not None and ready.is_set():
                break
            time.sleep(0.01)

        self.assertTrue(controller._edge_session_fallback)
        self.assertTrue(
            controller._speak_edge("第三句？", 23, 0, 8, 8, "", 12)
        )
        events = controller.drain()

        self.assertFalse(controller._edge_session_fallback)
        self.assertEqual(
            [event["type"] for event in events],
            ["edge_recovered"],
        )

    def test_edge_synthesis_has_a_bounded_whole_request_timeout(self):
        class HangingCommunicate:
            def __init__(self, *args, **kwargs):
                pass

            async def stream(self):
                await asyncio.sleep(1)
                if False:
                    yield None

        fake_edge_tts = types.SimpleNamespace(Communicate=HangingCommunicate)
        with (
            mock.patch("novelreader.tts_engine.edge_tts", fake_edge_tts),
            mock.patch("novelreader.tts_engine._EDGE_SYNTH_TIMEOUT_SECONDS", 0.01),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                synth_audio("网络超时。", "zh-CN-XiaoxiaoNeural")

    def test_edge_synthesis_retries_once_with_the_same_voice_and_rate(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-YunjianNeural")
        controller.set_rate(236)
        calls = []

        def flaky_synth(text, voice, rate, timeout=None):
            calls.append((text, voice, rate, timeout))
            if len(calls) == 1:
                raise ConnectionError("temporary network failure")
            return b"recovered-audio"

        with (
            mock.patch("novelreader.tts_engine.synth_audio", side_effect=flaky_synth),
            mock.patch("novelreader.tts_engine._EDGE_RETRY_DELAY_SECONDS", 0),
        ):
            audio = controller._edge_synthesize("网络恢复。")
        controller.shutdown()

        self.assertEqual(audio, b"recovered-audio")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[1:3] == ("zh-CN-YunjianNeural", 236) for call in calls))
        self.assertTrue(all(0 < call[3] <= 20 for call in calls))

    def test_edge_resume_at_sentence_boundary_advances_without_waiting_for_consumed_offset(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        controller._edge_synthesize = lambda text: text.encode("utf-8")
        played = []

        def play(audio, generation, start_event=None):
            played.append(audio.decode("utf-8"))
            if start_event is not None:
                controller._post(dict(start_event), generation)
            if len(played) == 1:
                controller.pause()
            return True

        controller._speak_edge_play = play
        try:
            controller.start(make_book("第一句。第二句！", ""), 0, 0)
            deadline = time.time() + 1
            while not controller.is_paused() and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(controller.is_paused())

            self.assertTrue(controller.resume())
            self._wait_for_stop(controller)

            self.assertTrue(controller.is_stopped())
            self.assertEqual(played, ["第一句。", "第二句！"])
        finally:
            controller.stop()
            controller.shutdown()

    def test_sapi_lifecycle_stays_on_the_worker_thread(self):
        calls = []

        class FakeEngine:
            def __init__(self):
                self.callbacks = {}

            def startLoop(self, useDriverLoop=False):
                calls.append(("startLoop", threading.get_ident()))

            def connect(self, topic, callback):
                token = {"topic": topic, "cb": callback}
                self.callbacks[topic] = callback
                return token

            def disconnect(self, token):
                self.callbacks.pop(token["topic"], None)

            def say(self, text):
                calls.append(("say", threading.get_ident()))

            def iterate(self):
                started = self.callbacks.pop("started-utterance", None)
                if started:
                    calls.append(("startedCallback", threading.get_ident()))
                    started()
                finished = self.callbacks.pop("finished-utterance", None)
                if finished:
                    finished()

            def setProperty(self, name, value):
                pass

            def stop(self):
                calls.append(("stop", threading.get_ident()))

            def endLoop(self):
                calls.append(("endLoop", threading.get_ident()))

        engine = FakeEngine()

        class FakePyttsx3:
            @staticmethod
            def init():
                calls.append(("init", threading.get_ident()))
                return engine

        main_thread = threading.get_ident()
        with mock.patch("novelreader.tts_engine.pyttsx3", FakePyttsx3):
            controller = SpeechController()
            original_post = controller._post

            def track_post(event, generation):
                if event.get("type") == "sentence_start":
                    calls.append(("sentenceStart", threading.get_ident()))
                return original_post(event, generation)

            controller._post = track_post
            controller.prepare(make_book("第一句。", ""), 0, 0)
            deadline = time.time() + 1
            while time.time() < deadline and not any(name == "init" for name, _ in calls):
                time.sleep(0.01)
            self.assertTrue(any(name == "init" for name, _ in calls))
            controller.start(make_book("第一句。", ""), 0, 0)
            self._wait_for_stop(controller)
            self.assertTrue(controller.shutdown())

        worker_threads = {thread_id for _, thread_id in calls}
        self.assertEqual(len(worker_threads), 1)
        self.assertNotIn(main_thread, worker_threads)
        self.assertIn("init", [name for name, _ in calls])
        self.assertEqual([name for name, _ in calls].count("init"), 1)
        event_order = [name for name, _ in calls]
        self.assertLess(event_order.index("say"), event_order.index("startedCallback"))
        self.assertLess(
            event_order.index("startedCallback"), event_order.index("sentenceStart")
        )
        self.assertIn("endLoop", [name for name, _ in calls])

    def test_edge_prepare_is_single_flight_and_reused_by_play(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        controller.set_book_id("book-1")
        started = threading.Event()
        release = threading.Event()
        calls = []

        def synthesize(text):
            calls.append(text)
            started.set()
            release.wait(1)
            return b"prepared-audio"

        def play(audio, generation, start_event=None):
            controller._post(dict(start_event), generation)
            return True

        controller._edge_synthesize = synthesize
        controller._speak_edge_play = play
        book = make_book("第一句。", "")
        controller.prepare(book, 0, 0)
        self.assertTrue(started.wait(1))
        generation = controller.start(book, 0, 0)
        time.sleep(0.05)
        self.assertFalse(any(
            event["type"] == "sentence_start" for event in controller.drain()
        ))
        release.set()
        self._wait_for_stop(controller)
        events = controller.drain()
        controller.shutdown()

        self.assertEqual(calls, ["第一句。"])
        starts = [event for event in events if event["type"] == "sentence_start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["generation"], generation)

    def test_edge_prepare_prioritizes_current_with_two_lookahead_workers(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        started = []
        started_lock = threading.Lock()
        three_started = threading.Event()
        release = threading.Event()

        def synthesize(text):
            with started_lock:
                started.append(text)
                if len(started) >= 3:
                    three_started.set()
            release.wait(1)
            return text.encode("utf-8")

        controller._edge_synthesize = synthesize
        controller.prepare(make_book("第一句。第二句！第三句？第四句。", ""), 0, 0)
        try:
            self.assertTrue(three_started.wait(0.5))
            self.assertEqual(started[0], "第一句。")
            self.assertEqual(set(started[1:3]), {"第二句！", "第三句？"})
        finally:
            release.set()
            controller.shutdown()

    def test_edge_continuation_waits_for_the_inflight_voice_without_duplicate_synthesis(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        observed = {}

        class InflightPrefetch:
            def __init__(self):
                self.calls = 0

            def get_expected(self, clean_off, text, timeout=None):
                self.calls += 1
                observed["request"] = (clean_off, text, timeout)
                return (self.calls >= 2), b"edge-second" if self.calls >= 2 else None

            def close(self):
                pass

        prefetch = InflightPrefetch()
        controller._edge_prefetch = prefetch
        controller._edge_synthesize = lambda text: self.fail(
            "a late continuation must not start a duplicate network synthesis"
        )
        controller._speak_sapi = lambda text, generation, start_event=None: self.fail(
            "an in-flight Edge continuation must not change voices"
        )
        controller._speak_edge_play = lambda audio, generation, start_event=None: audio == b"edge-second"
        controller._book = make_book()
        controller._state = "playing"
        controller._gen = 7

        result = controller._speak_edge(
            "第二句！", 7, 0, 4, 4, "第一句。第二句！", 8
        )

        self.assertTrue(result)
        self.assertEqual(prefetch.calls, 2)
        self.assertEqual(observed["request"], (4, "第二句！", 0.10))
        self.assertEqual(controller.drain(), [])

    def test_edge_continuation_reports_buffering_while_network_audio_is_pending(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")

        class DelayedPrefetch:
            def __init__(self):
                self.calls = 0

            def get_expected(self, clean_off, text, timeout=None):
                self.calls += 1
                return (self.calls >= 2), b"edge-second" if self.calls >= 2 else None

            def close(self):
                pass

        controller._edge_prefetch = DelayedPrefetch()
        controller._speak_edge_play = lambda audio, generation, start_event=None: True
        controller._book = make_book()
        controller._state = "playing"
        controller._gen = 8

        with mock.patch("novelreader.tts_engine._EDGE_BUFFERING_NOTICE_SECONDS", 0):
            result = controller._speak_edge(
                "第二句！", 8, 0, 4, 4, "第一句。第二句！", 8
            )

        self.assertTrue(result)
        self.assertEqual(controller.drain(), [{"type": "buffering", "generation": 8}])

    def test_edge_prefetch_synthesizes_ahead_concurrently_and_consumes_in_order(self):
        release = threading.Event()
        two_started = threading.Event()
        started = []
        lock = threading.Lock()

        def synthesize(text):
            with lock:
                started.append(text)
                if len(started) >= 2:
                    two_started.set()
            release.wait(1)
            return text.encode("utf-8")

        prefetch = __import__(
            "novelreader.tts_engine", fromlist=["_EdgePrefetch"]
        )._EdgePrefetch(synthesize, "第一句。第二句！第三句？", 0, 5)
        try:
            self.assertTrue(two_started.wait(0.5))
            release.set()
            for offset, text in ((0, "第一句。"), (4, "第二句！"), (8, "第三句？")):
                ready, audio = prefetch.get_expected(offset, text, timeout=1)
                self.assertTrue(ready)
                self.assertEqual(audio, text.encode("utf-8"))
        finally:
            prefetch.close()

    def test_edge_hard_failure_falls_back_once_without_flapping_back(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        sapi_calls = []

        class FailedPrefetch:
            calls = 0

            def get_expected(self, clean_off, text, timeout=None):
                self.calls += 1
                return True, None

            def close(self):
                pass

        prefetch = FailedPrefetch()
        controller._edge_prefetch = prefetch
        controller._speak_sapi = lambda text, generation, start_event=None: sapi_calls.append(text) or True
        controller._book = make_book()
        controller._state = "playing"
        controller._gen = 9

        self.assertTrue(controller._speak_edge("第二句！", 9, 0, 4, 4, "", 8))
        self.assertTrue(controller._speak_edge("第三句？", 9, 0, 8, 8, "", 12))

        self.assertEqual(prefetch.calls, 1)
        self.assertEqual(sapi_calls, ["第二句！", "第三句？"])
        errors = [event for event in controller.drain() if event["type"] == "error"]
        self.assertEqual(len(errors), 1)

    def test_edge_recent_audio_is_reused_after_restart(self):
        controller = SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        controller.set_book_id("restart-book")
        calls = []

        def synthesize(text):
            calls.append(text)
            return b"sentence-audio"

        def play(audio, generation, start_event=None):
            if start_event is not None:
                controller._post(dict(start_event), generation)
            return True

        controller._edge_synthesize = synthesize
        controller._speak_edge_play = play
        book = make_book("第一句。", "")
        try:
            controller.start(book, 0, 0)
            self._wait_for_stop(controller)
            controller.drain()
            controller.start(book, 0, 0)
            self._wait_for_stop(controller)
        finally:
            controller.shutdown()

        self.assertEqual(calls, ["第一句。"])


if __name__ == "__main__":
    unittest.main()
