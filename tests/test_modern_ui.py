# -*- coding: utf-8 -*-
import os
import tempfile
import tkinter as tk
import unittest

from novelreader.book_loader import BookContent, Chapter
from novelreader.gui import NovelReaderApp
from novelreader.modern_ui import _submit_paste, clamp_geometry, normalize_floating_settings, parse_geometry
from novelreader.storage import DEFAULT_SETTINGS


class GeometryTests(unittest.TestCase):
    def test_invalid_geometry_uses_default(self):
        self.assertEqual(parse_geometry("bad"), (560, 270, 80, 80))
        self.assertEqual(parse_geometry("300x100+1+1"), (560, 270, 80, 80))

    def test_geometry_is_clamped_and_keeps_24px_visible(self):
        self.assertEqual(clamp_geometry("560x270-9999+9999", 1920, 1080), "560x270-536+1056")
        self.assertEqual(clamp_geometry("9999x9999+0+0", 1280, 720), "1260x700+0+0")

    def test_new_settings_defaults(self):
        self.assertEqual(DEFAULT_SETTINGS["floating_reader_geometry"], "")
        self.assertTrue(DEFAULT_SETTINGS["floating_reader_topmost"])
        self.assertEqual(DEFAULT_SETTINGS["floating_reader_opacity"], .92)
        self.assertEqual(DEFAULT_SETTINGS["floating_reader_font_size"], 22)
        self.assertEqual(DEFAULT_SETTINGS["floating_reader_background"], "light")

    def test_invalid_floating_settings_are_normalized(self):
        clean = normalize_floating_settings({
            "floating_reader_opacity": "bad",
            "floating_reader_font_size": 200,
            "floating_reader_topmost": "yes",
            "floating_reader_background": "missing",
        })
        self.assertEqual(clean["floating_reader_opacity"], .92)
        self.assertEqual(clean["floating_reader_font_size"], 40)
        self.assertTrue(clean["floating_reader_topmost"])
        self.assertEqual(clean["floating_reader_background"], "light")


class ModernGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ddmodern_test_")
        os.environ["DOUBAO_NOVEL_DATA"] = self.tmp.name
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = NovelReaderApp(self.root)
        self.book = BookContent(
            title="测试内容",
            author="",
            fmt="txt",
            chapters=[Chapter("第一章", "第一句。第二句！第三句？")],
        )
        path = os.path.join(self.tmp.name, "source.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("第一句。第二句！第三句？")
        bid = self.app._save_import(self.book, path)
        self.app.open_book(bid)
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.app._on_close()
        except Exception:
            pass
        self.tmp.cleanup()

    def test_single_controller_and_floating_lifecycle(self):
        controller = self.app.tts
        self.app._toggle_floating_reader()
        first = self.app._floating_reader
        self.assertIsNotNone(first)
        self.assertIs(controller, self.app.tts)
        self.assertEqual(first.minsize(), (430, 238))
        self.app._toggle_floating_reader()
        self.assertIsNone(self.app._floating_reader)
        self.assertIs(controller, self.app.tts)

    def test_adjacent_sentence_and_seek_sync(self):
        self.app.char_offset = 4
        self.assertEqual(self.app._adjacent_sentences(), ("第一句。", "第二句！", "第三句？"))
        self.app._step_sentence(1)
        self.assertEqual(self.app.char_offset, 8)
        self.assertEqual(self.app._highlight_index[0], 0)

    def test_close_floating_does_not_stop_tts(self):
        calls = []
        original = self.app.tts.stop
        self.app.tts.stop = lambda: calls.append("stop")
        self.app._toggle_floating_reader()
        self.app._destroy_floating_reader(save=False)
        self.assertEqual(calls, [])
        self.app.tts.stop = original

    def test_floating_geometry_persists_on_close(self):
        self.app._toggle_floating_reader()
        self.app._floating_reader.geometry("600x300+120+140")
        self.root.update_idletasks()
        self.app._destroy_floating_reader(save=True)
        self.assertEqual(self.app.storage.get_setting("floating_reader_geometry"), "600x300+120+140")

    def test_paste_uses_unique_local_source(self):
        imported = []
        self.app._import_single = imported.append
        class Value:
            def __init__(self, value): self.value = value
            def get(self, *args): return self.value
        class Dialog:
            def destroy(self): pass
        class Error:
            def configure(self, **kwargs): raise AssertionError(kwargs)
        _submit_paste(self.app, Dialog(), Value(""), Value("首行标题\n正文内容。"), Error())
        _submit_paste(self.app, Dialog(), Value(""), Value("首行标题\n正文内容。"), Error())
        self.assertEqual(len(imported), 2)
        self.assertNotEqual(imported[0], imported[1])
        self.assertTrue(all(os.path.isfile(path) for path in imported))

    def test_library_search_filters_without_mutation(self):
        before = set(self.app.storage.all_books())
        self.app._library_query.set("不存在的标题")
        self.app._refresh_library_home()
        self.assertEqual(before, set(self.app.storage.all_books()))
        self.assertIn("0", self.app._library_count.cget("text"))

    def test_compact_paragraph_highlight_follows_wrapped_line(self):
        content = "".join(f"第{i + 1}段的第一句话内容。第二句话内容在这里。" for i in range(120))
        self.app.book = BookContent("长书", "", "txt", [Chapter("第一章", content)])
        self.app.chapter_idx = 0
        self.app.char_offset = 0
        self.app.settings["paragraph_mode"] = 3
        self.root.geometry("1365x820")
        self.root.deiconify()
        self.app._show_reader_page()
        self.app._render_chapter()
        self.root.update()
        rendered = self.app.text.get("1.0", "end-1c")
        self.assertEqual(len(self.app.text.get("3.0", "end-1c")), len(content),
                         (self.app.text.index("end"), repr(rendered[:80])))
        for off in (0, len(content) // 2, int(len(content) * .85)):
            self.app._highlight_sentence(0, off, content[off:off + 8])
            self.root.update()
            top = self.app.text.index("@0,0")
            highlight = self.app.text.index(self.app._highlight_index[1])
            self.assertEqual(top.split(".")[0], highlight.split(".")[0], (top, highlight))


if __name__ == "__main__":
    unittest.main()
