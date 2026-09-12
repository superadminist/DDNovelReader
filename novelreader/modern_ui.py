# -*- coding: utf-8 -*-
"""Prototype-faithful desktop shell for the existing reader business layer.

This module deliberately owns presentation only.  The application object remains
the single source of truth for books, progress, settings and SpeechController.
"""
import os
import re
import sys
import tkinter as tk
import bisect
from tkinter import messagebox, ttk

from . import __version__


LIGHT = {
    "root": "#e9edf8", "chrome": "#f6f7fb", "rail": "#f3f5fa",
    "page": "#f7f8fc", "sheet": "#ffffff", "card": "#ffffff",
    "border": "#e1e4ed", "text": "#1f2430", "muted": "#8b91a1",
    "accent": "#5966d9", "accent_soft": "#e8eaff", "cyan": "#57a7c8",
    "lavender": "#8a62cb", "green": "#45a795", "highlight": "#fff0b8",
}
DARK = {
    "root": "#151824", "chrome": "#202432", "rail": "#1b1f2c",
    "page": "#181c28", "sheet": "#242938", "card": "#242938",
    "border": "#343a4d", "text": "#f3f4f9", "muted": "#9ba2b4",
    "accent": "#7c86ee", "accent_soft": "#303655", "cyan": "#69b7d8",
    "lavender": "#a47ce0", "green": "#62b9a9", "highlight": "#67572d",
}


def _font(size, weight="normal"):
    return ("Microsoft YaHei UI", -int(size), weight)


def parse_geometry(value, default=(560, 270, 80, 80)):
    """Parse Tk geometry safely; invalid or undersized values use defaults."""
    m = re.fullmatch(r"\s*(\d+)x(\d+)([+-]\d+)([+-]\d+)\s*", str(value or ""))
    if not m:
        return default
    w, h, x, y = map(int, m.groups())
    if w < 430 or h < 238:
        return default
    return w, h, x, y


def clamp_geometry(value, screen_w, screen_h, screen_x=0, screen_y=0):
    """Keep the floating reader visible and inside the current work area."""
    w, h, x, y = parse_geometry(value)
    max_w, max_h = max(430, int(screen_w) - 20), max(238, int(screen_h) - 20)
    w, h = min(w, max_w), min(h, max_h)
    x = min(max(x, int(screen_x) - w + 24), int(screen_x) + int(screen_w) - 24)
    y = min(max(y, int(screen_y)), int(screen_y) + int(screen_h) - 24)
    return f"{w}x{h}{x:+d}{y:+d}"


def normalize_floating_settings(settings):
    """Normalize untrusted values merged from an older/corrupt library.json."""
    clean = dict(settings)
    try:
        clean["floating_reader_opacity"] = max(.65, min(1.0, float(clean.get("floating_reader_opacity", .92))))
    except (TypeError, ValueError):
        clean["floating_reader_opacity"] = .92
    try:
        clean["floating_reader_font_size"] = max(14, min(40, int(clean.get("floating_reader_font_size", 22))))
    except (TypeError, ValueError):
        clean["floating_reader_font_size"] = 22
    for key, default in (("floating_reader_topmost", True), ("floating_reader_follow_font", True), ("floating_reader_bilingual", False)):
        if not isinstance(clean.get(key), bool):
            clean[key] = default
    if clean.get("floating_reader_background") not in ("light", "beige", "dark"):
        clean["floating_reader_background"] = "light"
    if clean.get("library_view_mode") not in ("grid", "list"):
        clean["library_view_mode"] = "grid"
    return clean


def _screen_bounds(win):
    try:
        import ctypes
        user32 = ctypes.windll.user32
        x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def _button(parent, text, command, *, bg, fg, width=None, font=None, pady=7,
            cursor="hand2", active=None, relief="flat", state="normal"):
    return tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg, activebackground=active or bg,
        activeforeground=fg, bd=0, highlightthickness=0, relief=relief,
        cursor=cursor if state == "normal" else "arrow", width=width,
        font=font or _font(13), pady=pady, state=state,
    )


def _clear(frame):
    for child in frame.winfo_children():
        child.destroy()


def _cover_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "covers", "library.png")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "prototype", "public", "covers", "library.png")


def build_modern_ui(app):
    """Build the new desktop shell while retaining compatibility widget contracts."""
    app.settings = normalize_floating_settings(app.settings)
    app.root.title(f"多多朗读 v{__version__}")
    app.root.geometry(app._default_geometry())
    app.root.minsize(960, 620)
    icon = app._icon_path()
    if icon:
        try:
            app.root.iconbitmap(icon)
        except Exception:
            pass
    app._modern_dark = app.settings.get("theme") == "夜间"
    app._modern_ui_ready = False
    app._scrollbars = []
    app._cover_images = []
    app._floating_reader = None
    app._floating_sentence = ("", "", "")
    app._modern_sentence_cache = {}

    app._window_shell = tk.Frame(app.root, bg=LIGHT["root"], bd=0)
    app._window_shell.pack(fill="both", expand=True)
    _build_titlebar(app)
    app._body = tk.Frame(app._window_shell, bg=LIGHT["page"])
    app._body.pack(fill="both", expand=True)
    _build_rail(app)
    app._page_host = tk.Frame(app._body, bg=LIGHT["page"])
    app._page_host.pack(side="left", fill="both", expand=True)
    _build_library(app)
    _build_reader(app)
    _build_compatibility(app)
    _build_menus(app)
    app._setup_drag_drop()
    app._modern_ui_ready = True
    app._apply_modern_palette()
    app._show_library_page()


def _build_titlebar(app):
    c = LIGHT
    bar = tk.Frame(app._window_shell, bg=c["chrome"], height=54,
                   highlightthickness=1, highlightbackground=c["border"])
    bar.pack(fill="x")
    bar.pack_propagate(False)
    dots = tk.Frame(bar, bg=c["chrome"])
    dots.pack(side="left", padx=(18, 0), fill="y")
    _button(dots, "●", app._on_close, bg=c["chrome"], fg="#ff5f57", font=_font(18), pady=10).pack(side="left")
    _button(dots, "●", app.root.iconify, bg=c["chrome"], fg="#febc2e", font=_font(18), pady=10).pack(side="left")
    _button(dots, "●", lambda: _toggle_zoom(app), bg=c["chrome"], fg="#28c840", font=_font(18), pady=10).pack(side="left")
    app._window_title = tk.Label(bar, text="多多朗读", bg=c["chrome"], fg="#5d6270", font=_font(13, "bold"))
    app._window_title.place(relx=.5, rely=.5, anchor="center")
    right = tk.Frame(bar, bg=c["chrome"])
    right.pack(side="right", padx=18, fill="y")
    _button(right, "⌕", app._focus_library_search, bg=c["chrome"], fg=c["muted"], font=_font(24), pady=7).pack(side="left", padx=5)
    tk.Label(right, text="D", bg=c["accent"], fg="white", width=2, font=_font(13, "bold"), pady=7).pack(side="left", padx=(5, 0), pady=8)
    app._titlebar = bar


def _toggle_zoom(app):
    try:
        app.root.state("normal" if app.root.state() == "zoomed" else "zoomed")
    except Exception:
        pass


def _build_rail(app):
    c = LIGHT
    rail = tk.Frame(app._body, bg=c["rail"], width=72,
                    highlightthickness=1, highlightbackground=c["border"])
    rail.pack(side="left", fill="y")
    rail.pack_propagate(False)
    tk.Label(rail, text="▣", bg=c["rail"], fg=c["accent"], font=_font(26, "bold")).pack(pady=(17, 16))
    app._rail_buttons = {}
    items = [
        ("library", "▥", "内容库", app._show_library_page),
        ("reader", "▤", "阅读器", app._show_reader_page),
        ("audio", "♬", "音频内容", app._show_audio_notice),
    ]
    for key, icon, tip, cmd in items:
        b = _button(rail, icon, cmd, bg=c["rail"], fg=c["muted"], font=_font(21), pady=10)
        b.pack(fill="x", padx=13, pady=3)
        b.bind("<Enter>", lambda e, t=tip: app._flash_status(t))
        app._rail_buttons[key] = b
    tk.Frame(rail, bg=c["rail"]).pack(fill="both", expand=True)
    app._rail_dark = _button(rail, "◔", app._toggle_modern_dark, bg=c["rail"], fg=c["muted"], font=_font(21), pady=10)
    app._rail_dark.pack(fill="x", padx=13, pady=3)
    app._rail_settings = _button(rail, "⚙", app._open_modern_settings, bg=c["rail"], fg=c["muted"], font=_font(20), pady=10)
    app._rail_settings.pack(fill="x", padx=13, pady=(3, 15))
    app._rail = rail


def _build_library(app):
    c = LIGHT
    page = tk.Frame(app._page_host, bg=c["page"])
    page.place(x=0, y=0, relwidth=1, relheight=1)
    canvas = tk.Canvas(page, bg=c["page"], bd=0, highlightthickness=0)
    sb = tk.Scrollbar(page, command=canvas.yview, bd=0, relief="flat")
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(fill="both", expand=True)
    content = tk.Frame(canvas, bg=c["page"])
    win = canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units") if getattr(app, "_active_page", "") == "library" else None)
    head = tk.Frame(content, bg=c["page"])
    head.pack(fill="x", padx=48, pady=(39, 0))
    left = tk.Frame(head, bg=c["page"])
    left.pack(side="left")
    app._library_kicker = tk.Label(left, text="我的内容", bg=c["page"], fg=c["accent"], font=_font(12, "bold"))
    app._library_kicker.pack(anchor="w")
    app._library_heading = tk.Label(left, text="内容库", bg=c["page"], fg=c["text"], font=_font(31, "bold"))
    app._library_heading.pack(anchor="w", pady=(2, 0))
    app._library_subtitle = tk.Label(left, text="让文字成为可以随时聆听的陪伴。", bg=c["page"], fg=c["muted"], font=_font(13))
    app._library_subtitle.pack(anchor="w", pady=(3, 0))
    search_box = tk.Frame(head, bg=c["card"], highlightthickness=1, highlightbackground=c["border"])
    search_box.pack(side="right", pady=4)
    tk.Label(search_box, text="⌕", bg=c["card"], fg=c["muted"], font=_font(18)).pack(side="left", padx=(12, 4))
    app._library_query = tk.StringVar()
    app._library_search = tk.Entry(search_box, textvariable=app._library_query, relief="flat", bd=0,
                                   width=27, bg=c["card"], fg=c["text"], insertbackground=c["text"], font=_font(13))
    app._library_search.pack(side="left", ipady=11, padx=(0, 12))
    app._library_search.insert(0, "搜索书籍或文章")
    app._library_search.bind("<FocusIn>", lambda e: _search_focus(app, True))
    app._library_search.bind("<FocusOut>", lambda e: _search_focus(app, False))
    app._library_query.trace_add("write", lambda *_: app._refresh_library_home())

    app._import_cards = tk.Frame(content, bg=c["page"])
    app._import_cards.pack(fill="x", padx=48, pady=(42, 0))
    specs = [
        ("▤", "粘贴文本", "快速开始一段朗读", c["accent"], app._open_paste_dialog, True),
        ("↗", "网页链接", "后续支持 · 提取干净文章正文", c["cyan"], app._show_web_notice, False),
        ("♬", "播客 / 音频", "暂未支持 · 导入并整理音频内容", c["lavender"], app._show_audio_notice, False),
        ("↥", "导入文件", "TXT、EPUB、DOCX、PDF", c["green"], app._add_book, True),
    ]
    for i in range(4):
        app._import_cards.grid_columnconfigure(i, weight=1, uniform="imports")
    for i, spec in enumerate(specs):
        _make_import_card(app, app._import_cards, *spec).grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 7, 0 if i == 3 else 7))

    row = tk.Frame(content, bg=c["page"])
    row.pack(fill="x", padx=48, pady=(38, 13))
    app._recent_heading = tk.Label(row, text="最近阅读", bg=c["page"], fg=c["text"], font=_font(19, "bold"))
    app._recent_heading.pack(side="left")
    app._library_count = tk.Label(row, text="0  项内容", bg=c["page"], fg=c["muted"], font=_font(12))
    app._library_count.pack(side="left", padx=12, pady=(5, 0))
    app._view_mode_btn = _button(row, "☷  列表", app._show_list_notice, bg=c["card"], fg=c["muted"], font=_font(12), pady=7)
    app._view_mode_btn.pack(side="right")
    app._library_grid = tk.Frame(content, bg=c["page"])
    app._library_grid.pack(fill="both", expand=True, padx=48, pady=(0, 42))
    app._library_page = page
    app._library_canvas = canvas


def _search_focus(app, focused):
    text = app._library_search.get()
    if focused and text == "搜索书籍或文章":
        app._library_search.delete(0, "end")
    elif not focused and not text.strip():
        app._library_search.insert(0, "搜索书籍或文章")


def _make_import_card(app, parent, icon, title, subtitle, accent, command, enabled):
    c = LIGHT
    card = tk.Frame(parent, bg=c["card"], highlightthickness=1, highlightbackground=c["border"], height=92)
    card.grid_propagate(False)
    card.grid_columnconfigure(1, weight=1)
    icon_lbl = tk.Label(card, text=icon, bg="#eef0ff" if enabled else "#f1f2f6", fg=accent, font=_font(22, "bold"), width=2)
    icon_lbl.grid(row=0, column=0, rowspan=2, padx=(15, 11), pady=20, sticky="ns")
    title_lbl = tk.Label(card, text=title, bg=c["card"], fg=c["text"] if enabled else c["muted"], font=_font(14, "bold"), anchor="w")
    title_lbl.grid(row=0, column=1, sticky="sew", pady=(20, 0))
    sub_lbl = tk.Label(card, text=subtitle, bg=c["card"], fg=c["muted"], font=_font(11), anchor="w")
    sub_lbl.grid(row=1, column=1, sticky="new", pady=(2, 20))
    arrow = tk.Label(card, text="›", bg=c["card"], fg="#b1b5c0", font=_font(23))
    arrow.grid(row=0, column=2, rowspan=2, padx=(5, 14))
    for w in (card, icon_lbl, title_lbl, sub_lbl, arrow):
        w.configure(cursor="hand2")
        w.bind("<Button-1>", lambda e, fn=command: fn())
    card._palette_children = (icon_lbl, title_lbl, sub_lbl, arrow)
    return card


def _build_reader(app):
    c = LIGHT
    page = tk.Frame(app._page_host, bg=c["page"])
    page.place(x=0, y=0, relwidth=1, relheight=1)
    page.grid_columnconfigure(0, weight=1)
    page.grid_rowconfigure(1, weight=1)
    app._main = page
    bar = tk.Frame(page, bg=c["chrome"], height=58, highlightthickness=1, highlightbackground=c["border"])
    bar.grid(row=0, column=0, sticky="ew")
    bar.grid_propagate(False)
    app._toolbar = bar
    _button(bar, "‹  内容库", app._show_library_page, bg=c["chrome"], fg=c["text"], font=_font(13), pady=9).pack(side="left", padx=(18, 3), pady=7)
    app.toc_btn = _button(bar, "☷  目录", app._toggle_toc, bg=c["chrome"], fg=c["text"], font=_font(13), pady=9)
    app.toc_btn.pack(side="left", padx=3, pady=7)
    app.title_label = tk.Label(bar, text="未打开书籍", bg=c["chrome"], fg=c["text"], font=_font(14, "bold"))
    app.title_label.pack(side="left", padx=17)
    controls = tk.Frame(bar, bg=c["chrome"])
    controls.pack(side="right", padx=16)
    _button(controls, "A−", lambda: app._change_font_size(-1), bg=c["chrome"], fg=c["text"], font=_font(13), pady=9).pack(side="left")
    app._visible_size_label = tk.Label(controls, text=str(app.settings.get("font_size", 17)), bg=c["chrome"], fg=c["text"], font=_font(12, "bold"), width=3)
    app._visible_size_label.pack(side="left")
    _button(controls, "A+", lambda: app._change_font_size(1), bg=c["chrome"], fg=c["text"], font=_font(13), pady=9).pack(side="left")
    _button(controls, "排版", app._open_modern_settings, bg=c["chrome"], fg=c["text"], font=_font(13), pady=9).pack(side="left", padx=(7, 0))
    app._floating_toolbar_btn = _button(controls, "▱  悬浮朗读", app._toggle_floating_reader, bg=c["accent_soft"], fg=c["accent"], font=_font(13, "bold"), pady=9)
    app._floating_toolbar_btn.pack(side="left", padx=6)
    _button(controls, "⚙", app._open_modern_settings, bg=c["chrome"], fg=c["muted"], font=_font(18), pady=7).pack(side="left")

    app._inner_paned = ttk.Panedwindow(page, orient="horizontal")
    app._inner_paned.grid(row=1, column=0, sticky="nsew")
    app.chapter_panel = tk.Frame(app._inner_paned, width=270, bg=c["chrome"], highlightthickness=1, highlightbackground=c["border"])
    app.chapter_panel.pack_propagate(False)
    toc_head = tk.Frame(app.chapter_panel, bg=c["chrome"])
    toc_head.pack(fill="x", padx=20, pady=(21, 10))
    app._toc_heading = tk.Label(toc_head, text="目录", bg=c["chrome"], fg=c["text"], font=_font(18, "bold"))
    app._toc_heading.pack(side="left")
    app._toc_count = tk.Label(toc_head, text="0 章", bg=c["chrome"], fg=c["muted"], font=_font(11))
    app._toc_count.pack(side="right", pady=(5, 0))
    app.chapter_list = tk.Listbox(app.chapter_panel, bd=0, highlightthickness=0, activestyle="none",
                                  bg=c["chrome"], fg=c["text"], selectbackground=c["accent_soft"],
                                  selectforeground=c["accent"], font=_font(12), exportselection=False)
    app.chapter_list.pack(fill="both", expand=True, padx=(13, 7), pady=(0, 14))
    app.chapter_list.bind("<<ListboxSelect>>", app._on_panel_select)
    app.chapter_list.bind("<Button-3>", app._popup_bookmark_menu)
    app._panel_mode = "toc"
    app._panel_toc_btn = tk.Button(app.chapter_panel)
    app._panel_bm_btn = tk.Button(app.chapter_panel)
    app._chapter_panel_visible = True
    app._inner_paned.add(app.chapter_panel, weight=0)

    read_bg = tk.Frame(app._inner_paned, bg=c["page"])
    sheet = tk.Frame(read_bg, bg=c["sheet"], highlightthickness=1, highlightbackground=c["border"])
    sheet.pack(fill="both", expand=True, padx=34, pady=24)
    app._chapter_index_label = tk.Label(sheet, text="CHAPTER --", bg=c["sheet"], fg=c["accent"], font=_font(10, "bold"))
    app._chapter_index_label.place(x=54, y=24)
    app._reading_progress_label = tk.Label(sheet, text="0.0%", bg=c["sheet"], fg=c["muted"], font=_font(10))
    app._reading_progress_label.place(relx=1, rely=1, x=-24, y=-18, anchor="se")
    app.text = tk.Text(sheet, wrap="word", undo=False, padx=54, pady=54, bd=0, relief="flat",
                       cursor="arrow", bg=c["sheet"], fg=c["text"], insertbackground=c["text"])
    tscroll = tk.Scrollbar(sheet, command=app.text.yview, bd=0, relief="flat")
    app.text.configure(yscrollcommand=tscroll.set)
    tscroll.pack(side="right", fill="y")
    app.text.pack(fill="both", expand=True)
    app._chapter_index_label.lift()
    app._reading_progress_label.lift()
    app.text.configure(state="disabled")
    app.text.tag_configure("tts", background=c["highlight"], foreground=c["text"])
    app.text.tag_configure("bm", background="#c8e6c9", foreground="#000000")
    app.text.bind("<MouseWheel>", app._on_scroll)
    app.text.bind("<ButtonRelease-1>", app._on_scroll)
    app.text.bind("<KeyRelease>", app._on_scroll)
    app.text.bind("<Configure>", app._on_text_resize)
    app.text.bind("<Button-4>", app._on_scroll)
    app.text.bind("<Button-5>", app._on_scroll)
    app.text.bind("<Button-3>", app._popup_text_menu)
    app._read_frame = read_bg
    app._sheet = sheet
    app._inner_paned.add(read_bg, weight=1)
    app._left = tk.Frame(app._inner_paned, width=1)
    app._shelf_visible = False

    _build_player(app, page)
    app._reader_page = page
    app._fullscreen = False
    app._read_seconds = 0
    import time
    app._app_start = time.time()
    app._last_second = int(time.time())
    app._timer_minutes = 0
    app._timer_deadline = None
    app._timer_running = False
    app._overlay = tk.Frame(page, bg="#202124", highlightthickness=1, highlightbackground="#444444")
    app._ov_chap = tk.Label(app._overlay, text="", fg="#d0d0d0", bg="#202124", font=_font(10))
    app._ov_chap.pack(side="left", padx=14, pady=6)
    app._ov_prog = tk.Label(app._overlay, text="", fg="#f0c36d", bg="#202124", font=_font(10, "bold"))
    app._ov_prog.pack(side="right", padx=14, pady=6)
    app._ov_read = tk.Label(app._overlay, text="", fg="#9fc5ff", bg="#202124", font=_font(10))
    app._ov_read.pack(side="right", padx=(0, 14), pady=6)
    app._ov_time = tk.Label(app._overlay, text="", fg="#e8e8e8", bg="#202124", font=_font(10, "bold"))
    app._ov_time.pack(side="right", padx=(0, 8), pady=6)


def _build_player(app, page):
    c = LIGHT
    status = tk.Frame(page, bg=c["chrome"], height=82, highlightthickness=1, highlightbackground=c["border"])
    status.grid(row=2, column=0, sticky="ew")
    status.grid_propagate(False)
    meta = tk.Frame(status, bg=c["chrome"])
    meta.pack(side="left", padx=(22, 12), pady=13)
    app._player_chapter = tk.Label(meta, text="尚未选择内容", bg=c["chrome"], fg=c["text"], font=_font(13, "bold"), anchor="w")
    app._player_chapter.pack(anchor="w")
    app.tts_status_label = tk.Label(meta, text="", bg=c["chrome"], fg=c["muted"], font=_font(10), anchor="w")
    app.tts_status_label.pack(anchor="w", pady=(3, 0))
    app._status_timer = None
    playback = tk.Frame(status, bg=c["chrome"])
    playback.pack(side="left", pady=12)
    app._prev_sentence_btn = _button(playback, "│◀", lambda: app._step_sentence(-1), bg=c["chrome"], fg=c["text"], font=_font(18), pady=7)
    app._prev_sentence_btn.pack(side="left", padx=3)
    app._main_play_btn = _button(playback, "▶", app._tts_toggle, bg=c["accent"], fg="white", font=_font(20), pady=8)
    app._main_play_btn.pack(side="left", padx=4)
    app._next_sentence_btn = _button(playback, "▶│", lambda: app._step_sentence(1), bg=c["chrome"], fg=c["text"], font=_font(18), pady=7)
    app._next_sentence_btn.pack(side="left", padx=3)
    app._main_stop_btn = _button(playback, "■", app._tts_stop, bg=c["chrome"], fg=c["muted"], font=_font(15), pady=7, state="disabled")
    app._main_stop_btn.pack(side="left", padx=3)
    progress = tk.Frame(status, bg=c["chrome"])
    progress.pack(side="left", fill="x", expand=True, padx=17, pady=17)
    app.progress_var = tk.DoubleVar(value=0)
    app._seeking = False
    app._seek_style = "Modern.Horizontal.TScale"
    app._ttk_style = ttk.Style(app.root)
    try:
        app._ttk_style.theme_use("clam")
    except Exception:
        pass
    app._ttk_style.configure(app._seek_style, troughcolor="#dde1ec", background=c["accent"], sliderlength=14)
    app.progress_scale = ttk.Scale(progress, from_=0, to=100, variable=app.progress_var, command=app._on_seek, style=app._seek_style)
    app.progress_scale.pack(fill="x")
    app.progress_scale.bind("<ButtonPress-1>", app._on_seek_press)
    app.progress_scale.bind("<ButtonRelease-1>", app._on_seek_release)
    labels = tk.Frame(progress, bg=c["chrome"])
    labels.pack(fill="x", pady=(2, 0))
    app.percent_label = tk.Label(labels, text="0.0%", bg=c["chrome"], fg=c["muted"], font=_font(10), cursor="hand2")
    app.percent_label.pack(side="left")
    app.percent_label.bind("<Button-1>", lambda e: app._open_percent_dialog())
    app.pos_label = tk.Label(labels, text="", bg=c["chrome"], fg=c["muted"], font=_font(10))
    app.pos_label.pack(side="right")
    right = tk.Frame(status, bg=c["chrome"])
    right.pack(side="right", padx=(8, 18), pady=10)
    speed = tk.Frame(right, bg=c["chrome"])
    speed.pack(side="left", padx=5)
    tk.Label(speed, text="语速", bg=c["chrome"], fg=c["muted"], font=_font(10)).pack()
    app._speed_button = _button(speed, "1.0×", lambda: app._change_rate(10), bg=c["chrome"], fg=c["text"], font=_font(11, "bold"), pady=0)
    app._speed_button.pack()
    volume = tk.Frame(right, bg=c["chrome"])
    volume.pack(side="left", padx=5)
    tk.Label(volume, text="音量", bg=c["chrome"], fg=c["muted"], font=_font(10)).pack()
    app.volume_var = tk.DoubleVar(value=100)
    app.volume_scale = ttk.Scale(volume, from_=0, to=100, variable=app.volume_var, command=app._on_volume_change, length=74)
    app.volume_scale.pack()
    app.volume_label = tk.Label(volume, text="100", bg=c["chrome"], fg=c["text"], font=_font(9))
    app.volume_label.pack()
    app._floating_player_btn = _button(right, "▱", app._toggle_floating_reader, bg=c["accent_soft"], fg=c["accent"], font=_font(18), pady=8)
    app._floating_player_btn.pack(side="left", padx=(8, 0))
    app.tts_cache_label = tk.Label(status, text="", bg=c["chrome"], fg="#3366aa", font=_font(9))
    app.book_cache_label = tk.Label(status, text="", bg=c["chrome"], fg="#8a5a00", font=_font(9), cursor="hand2")
    app.book_cache_label.bind("<Button-1>", app._on_status_cache_click)
    app.total_label = tk.Label(status, text="", bg=c["chrome"], fg=c["muted"], font=_font(9))
    app._player = status


def _build_compatibility(app):
    hidden = tk.Frame(app.root)
    app._compat_frame = hidden
    app.shelf_tree = ttk.Treeview(hidden, columns=("progress", "title", "size", "time"), show="headings", selectmode="extended")
    for col, text in (("progress", "进度"), ("title", "书名"), ("size", "大小"), ("time", "时间")):
        app.shelf_tree.heading(col, text=text, command=lambda c=col: app._shelf_sort(c))
    app.shelf_tree.bind("<Double-Button-1>", lambda e: app._open_selected())
    app.shelf_tree.bind("<Return>", lambda e: app._open_selected())
    app.shelf_tree.bind("<Button-3>", app._popup_shelf_menu)
    app.chapter_cb = ttk.Combobox(hidden, state="readonly")
    app.chapter_cb.bind("<<ComboboxSelected>>", app._on_chapter_cb)
    app.font_cb = ttk.Combobox(hidden, state="readonly")
    app.font_cb.bind("<<ComboboxSelected>>", app._on_font_change)
    app.size_label = tk.Label(hidden, text="17")
    app.spacing_label = tk.Label(hidden, text="1.5")
    app.paragraph_cb = ttk.Combobox(hidden, state="readonly", values=["不压缩", "合并为一行", "清理所有行"])
    app.paragraph_cb.bind("<<ComboboxSelected>>", app._on_paragraph_mode)
    from .constants import THEMES
    app.theme_cb = ttk.Combobox(hidden, state="readonly", values=list(THEMES.keys()))
    app.theme_cb.bind("<<ComboboxSelected>>", app._on_theme_change)
    app.gap_label = tk.Label(hidden, text="0.10")
    app.rate_label = tk.Label(hidden, text="200")
    app.voice_cb = ttk.Combobox(hidden, state="readonly")
    app.voice_cb["values"] = app._friendly_voices()
    app.voice_cb.bind("<<ComboboxSelected>>", app._on_voice_change)
    # Existing business/tests address these historical widget names.  They stay
    # off-screen while the visible player uses compact prototype controls.
    app.tts_toggle_btn = ttk.Button(hidden, text="▶ 开始朗读", command=app._tts_toggle)
    app.tts_stop_btn = ttk.Button(hidden, text="⏹ 结束", command=app._tts_stop, state="disabled")
    app.tts_cache_btn = ttk.Button(hidden, text="整本缓存", command=app._open_cache_dialog)
    app.timer_btn = ttk.Button(hidden, text="定时", command=app._open_timer_dialog)


def _build_menus(app):
    app.shelf_menu = tk.Menu(app.root, tearoff=0)
    app.shelf_menu.add_command(label="打开书籍", command=app._open_selected)
    app.shelf_menu.add_separator()
    app.shelf_menu.add_command(label="添加书籍", command=app._add_book)
    app.shelf_menu.add_separator()
    app.shelf_menu.add_command(label="复制原文件", command=app._copy_book_file)
    app.shelf_menu.add_command(label="复制书名", command=app._copy_book_title)
    app.shelf_menu.add_separator()
    app.shelf_menu.add_command(label="删除（保留缓存）", command=lambda: app._remove_book(False))
    app.shelf_menu.add_command(label="删除文件（清空缓存）", command=lambda: app._remove_book(True))
    app.text_menu = tk.Menu(app.root, tearoff=0)
    app.text_menu.add_command(label="复制", command=app._copy_selection)
    app.text_menu.add_command(label="🔖 添加书签/划线", command=app._add_bookmark_from_selection)
    app.text_menu.add_command(label="从该段开始朗读", command=app._read_from_paragraph)
    app.text_menu.add_separator()
    app.text_menu.add_command(label="百度搜索", command=lambda: app._search_selection("baidu"))
    app.text_menu.add_command(label="谷歌搜索", command=lambda: app._search_selection("google"))
    app.text_menu.add_command(label="必应搜索", command=lambda: app._search_selection("bing"))
    app.text_menu.add_separator()
    app.text_menu.add_command(label="翻译", command=lambda: app._search_selection("translate"))


class ModernMethods:
    def _show_library_page(self):
        self._library_page.lift()
        self._active_page = "library"
        self._set_rail_active("library")
        self._refresh_library_home()

    def _show_reader_page(self):
        if not self.book:
            self._show_library_page()
            messagebox.showinfo("阅读器", "请先从内容库选择或导入内容。", parent=self.root)
            return
        self._reader_page.lift()
        self._active_page = "reader"
        self._set_rail_active("reader")

    def _set_rail_active(self, key):
        c = DARK if self._modern_dark else LIGHT
        for k, btn in self._rail_buttons.items():
            btn.configure(bg=c["accent_soft"] if k == key else c["rail"],
                          fg=c["accent"] if k == key else c["muted"])

    def _focus_library_search(self):
        self._show_library_page()
        self._library_search.focus_set()
        self._library_search.selection_range(0, "end")

    def _show_web_notice(self):
        messagebox.showinfo("网页链接", "网页正文提取将在后续版本支持。\n当前不会创建空内容或发起网页抓取。", parent=self.root)

    def _show_audio_notice(self):
        messagebox.showinfo("播客 / 音频", "音频导入与语音转写暂未支持。\n现有朗读功能不会被当作音频转写使用。", parent=self.root)

    def _show_list_notice(self):
        messagebox.showinfo("内容库视图", "列表视图将在后续版本支持，当前保持网格视图。", parent=self.root)

    def _refresh_library_home(self):
        if not getattr(self, "_modern_ui_ready", False):
            return
        c = DARK if self._modern_dark else LIGHT
        _clear(self._library_grid)
        self._cover_images = []
        self._library_card_refs = {}
        books = list(self.storage.all_books().values())
        books.sort(key=lambda b: b.get("last_read_at", b.get("added_at", 0)) or 0, reverse=True)
        query = self._library_query.get().strip()
        if query == "搜索书籍或文章":
            query = ""
        if query:
            books = [b for b in books if query.casefold() in str(b.get("title", "")).casefold()]
        self._library_count.configure(text=f"{len(books)}  项内容")
        if not books:
            box = tk.Frame(self._library_grid, bg=c["card"], highlightthickness=1, highlightbackground=c["border"])
            box.pack(fill="x", pady=4)
            text = "没有匹配的内容" if query else "内容库还是空的"
            tk.Label(box, text=text, bg=c["card"], fg=c["text"], font=_font(17, "bold")).pack(pady=(28, 5))
            tk.Label(box, text="清空搜索后查看全部内容" if query else "导入文件或粘贴文本即可开始朗读", bg=c["card"], fg=c["muted"], font=_font(12)).pack(pady=(0, 12))
            if query:
                _button(box, "清空搜索", self._clear_library_search, bg=c["accent_soft"], fg=c["accent"], font=_font(12), pady=7).pack(pady=(0, 25))
            return
        for i in range(4):
            self._library_grid.grid_columnconfigure(i, weight=1, uniform="books")
        for i, book in enumerate(books):
            _make_book_card(self, self._library_grid, book).grid(row=i // 4, column=i % 4, sticky="new", padx=(0 if i % 4 == 0 else 8, 0 if i % 4 == 3 else 8), pady=(0, 17))

    def _update_library_progress(self, bid, percent):
        ref = getattr(self, "_library_card_refs", {}).get(bid)
        if not ref:
            return
        label, line, colors = ref
        label.configure(text=f"{float(percent):.0f} %")
        width = max(1, line.winfo_width())
        line.delete("all")
        line.create_rectangle(0, 1, width, 4, fill=colors["border"], outline="")
        line.create_rectangle(0, 1, width * float(percent) / 100, 4, fill=colors["accent"], outline="")

    def _clear_library_search(self):
        self._library_query.set("")
        self._library_search.focus_set()

    def _open_paste_dialog(self):
        _open_paste_dialog(self)

    def _open_modern_settings(self):
        _open_settings(self)

    def _toggle_modern_dark(self):
        self._modern_dark = not self._modern_dark
        theme = "夜间" if self._modern_dark else "护眼"
        self.settings["theme"] = theme
        self.storage.set_setting("theme", theme)
        self._apply_theme(theme)
        self._apply_modern_palette()

    def _apply_modern_palette(self):
        c = DARK if self._modern_dark else LIGHT
        _recolor_tree(self._window_shell, c)
        for widget, key in ((self.root, "root"), (self._window_shell, "root"), (self._body, "page"),
                            (self._page_host, "page"), (self._library_page, "page"),
                            (self._reader_page, "page"), (self._rail, "rail"),
                            (self._titlebar, "chrome"), (self._toolbar, "chrome"),
                            (self._player, "chrome"), (self.chapter_panel, "chrome"),
                            (self._sheet, "sheet"), (self.text, "sheet")):
            try:
                widget.configure(bg=c[key])
            except Exception:
                pass
        self.text.configure(fg=c["text"], insertbackground=c["text"])
        self.text.tag_configure("tts", background=c["highlight"], foreground=c["text"])
        self._chapter_index_label.configure(bg=c["sheet"], fg=c["accent"])
        self._reading_progress_label.configure(bg=c["sheet"], fg=c["muted"])
        self._library_canvas.configure(bg=c["page"])
        self._window_title.configure(bg=c["chrome"], fg=c["muted"])
        self._library_kicker.configure(bg=c["page"], fg=c["accent"])
        self._library_heading.configure(bg=c["page"], fg=c["text"])
        self._library_subtitle.configure(bg=c["page"], fg=c["muted"])
        self._recent_heading.configure(bg=c["page"], fg=c["text"])
        self._library_count.configure(bg=c["page"], fg=c["muted"])
        self.title_label.configure(bg=c["chrome"], fg=c["text"])
        self._toc_heading.configure(bg=c["chrome"], fg=c["text"])
        self._toc_count.configure(bg=c["chrome"], fg=c["muted"])
        self.chapter_list.configure(bg=c["chrome"], fg=c["text"], selectbackground=c["accent_soft"], selectforeground=c["accent"])
        for w in (self._player_chapter, self.tts_status_label, self.percent_label, self.pos_label,
                  self.rate_label, self.volume_label, self.tts_cache_label, self.book_cache_label, self.total_label):
            try:
                w.configure(bg=c["chrome"])
            except Exception:
                pass
        self._refresh_library_home()
        self._set_rail_active(getattr(self, "_active_page", "library"))

    def _toggle_floating_reader(self):
        if self._floating_reader is not None and self._floating_reader.winfo_exists():
            self._destroy_floating_reader(save=True)
            return
        if not self.book:
            messagebox.showinfo("悬浮朗读", "请先从内容库选择一本书。", parent=self.root)
            return
        _create_floating_reader(self)

    def _destroy_floating_reader(self, save=True):
        win = getattr(self, "_floating_reader", None)
        if not win:
            return
        if save:
            self._save_floating_geometry()
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        self._floating_reader = None
        for btn in (getattr(self, "_floating_toolbar_btn", None), getattr(self, "_floating_player_btn", None)):
            try:
                btn.configure(relief="flat")
            except Exception:
                pass

    def _save_floating_geometry(self):
        win = getattr(self, "_floating_reader", None)
        if not win or not win.winfo_exists():
            return
        sx, sy, sw, sh = _screen_bounds(win)
        geo = clamp_geometry(win.geometry(), sw, sh, sx, sy)
        self.settings["floating_reader_geometry"] = geo
        self.storage.set_setting("floating_reader_geometry", geo)

    def _restore_floating_after_minimize(self):
        win = getattr(self, "_floating_reader", None)
        if not win or not win.winfo_exists():
            return
        try:
            win.deiconify()
            if self.settings.get("floating_reader_topmost", True):
                win.attributes("-topmost", True)
            win.lift()
        except Exception:
            pass

    def _toggle_floating_topmost(self):
        value = not bool(self.settings.get("floating_reader_topmost", True))
        self.settings["floating_reader_topmost"] = value
        self.storage.set_setting("floating_reader_topmost", value)
        if self._floating_reader:
            self._floating_reader.attributes("-topmost", value)
        self._floating_pin.configure(text="◆" if value else "◇")

    def _change_floating_font(self, delta):
        size = max(14, min(40, int(self.settings.get("floating_reader_font_size", 22)) + delta))
        self.settings["floating_reader_font_size"] = size
        self.storage.set_setting("floating_reader_font_size", size)
        self._update_floating_reader()

    def _set_floating_opacity(self, value, persist=False):
        try:
            value = max(.65, min(1.0, float(value)))
        except (TypeError, ValueError):
            value = .92
        self.settings["floating_reader_opacity"] = value
        win = getattr(self, "_floating_reader", None)
        if win and win.winfo_exists():
            win.attributes("-alpha", value)
        if persist:
            self.storage.set_setting("floating_reader_opacity", value)

    def _set_floating_follow_font(self):
        value = bool(self._floating_follow_var.get())
        self.settings["floating_reader_follow_font"] = value
        self.storage.set_setting("floating_reader_follow_font", value)
        self._update_floating_reader()

    def _cycle_floating_background(self):
        modes = ["light", "beige", "dark"]
        cur = self.settings.get("floating_reader_background", "light")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "light"
        self.settings["floating_reader_background"] = nxt
        self.storage.set_setting("floating_reader_background", nxt)
        self._apply_floating_palette()

    def _apply_floating_palette(self):
        mode = self.settings.get("floating_reader_background", "light")
        palettes = {
            "light": ("#ffffff", "#1f2430", "#8b91a1", "#f1f2f8"),
            "beige": ("#f7f0df", "#342f28", "#8e8373", "#e9dfca"),
            "dark": ("#202432", "#f7f7fb", "#aeb5c7", "#2d3242"),
        }
        bg, fg, muted, control = palettes.get(mode, palettes["light"])
        for w in (self._floating_reader, self._floating_titlebar, self._floating_content,
                  self._floating_controls, self._floating_viewport, self._floating_sentence_box):
            w.configure(bg=bg)
        for w in (self._floating_chapter, self._floating_current):
            w.configure(bg=bg, fg=fg)
        self._floating_dot.configure(bg=bg)
        for w in (self._floating_prev, self._floating_next, self._floating_state):
            w.configure(bg=bg, fg=muted)
        for w in (self._floating_pin, self._floating_close, self._floating_font_down,
                  self._floating_font_up, self._floating_theme, self._floating_prev_btn,
                  self._floating_next_btn, self._floating_stop_btn, self._floating_bilingual):
            w.configure(bg=control, activebackground=control, fg=fg)
        self._floating_play.configure(bg="#5966d9", activebackground="#5966d9", fg="white")
        self._floating_progress.configure(bg=bg)

    def _update_floating_reader(self, sentence=None):
        win = getattr(self, "_floating_reader", None)
        if not win or not win.winfo_exists() or not self.book:
            return
        if sentence:
            self._floating_sentence = sentence
        elif not any(self._floating_sentence):
            self._floating_sentence = self._adjacent_sentences()
        prev, current, nxt = self._floating_sentence
        ch = self.book.chapters[self.chapter_idx]
        self._floating_chapter.configure(text=ch.title[:40])
        self._floating_prev.configure(text=prev or "已到本章开头")
        self._floating_current.configure(text=current or "准备朗读")
        self._floating_next.configure(text=nxt or "已到本章结尾")
        size = int(self.settings.get("floating_reader_font_size", 22))
        fam = self.settings.get("font_family", "微软雅黑") if self.settings.get("floating_reader_follow_font", True) else "Microsoft YaHei UI"
        self._floating_current.configure(font=(fam, size, "bold"))
        self._floating_prev.configure(font=(fam, max(10, size - 9)))
        self._floating_next.configure(font=(fam, max(10, size - 8)))
        try:
            pct = self._compute_percent(self.chapter_idx, self.char_offset)
            width = max(1, int(self._floating_progress.winfo_width() or 78))
            self._floating_progress.delete("all")
            self._floating_progress.create_rectangle(0, 2, width, 6, fill="#dfe2ed", outline="")
            self._floating_progress.create_rectangle(0, 2, width * pct / 100, 6, fill="#5966d9", outline="")
        except Exception:
            pass

    def _sync_modern_playback(self, evt=None):
        if self.book:
            ch = self.book.chapters[self.chapter_idx]
            self._player_chapter.configure(text=ch.title)
            self._toc_count.configure(text=f"{len(self.book.chapters)} 章")
            self._chapter_index_label.configure(text=f"CHAPTER {self.chapter_idx + 1:02d}")
            pct = self._compute_percent(self.chapter_idx, self.char_offset)
            self._reading_progress_label.configure(text=f"总进度 {pct:.1f}%")
            if not self.tts_status_label.cget("text"):
                self.tts_status_label.configure(text=f"已同步阅读进度 · {pct:.1f}%")
        if evt and evt.get("type") == "sentence_start":
            self._floating_sentence = self._adjacent_sentences(evt.get("char_offset", self.char_offset), evt.get("text", ""))
        self._update_floating_reader()

    def _sync_modern_tts_state(self, state):
        playing = state == "playing"
        paused = state == "paused"
        try:
            self._main_play_btn.configure(text="Ⅱ" if playing else "▶")
            self._main_stop_btn.configure(state="normal" if (playing or paused) else "disabled")
            self.tts_status_label.configure(text="正在朗读" if playing else ("朗读已暂停" if paused else "已同步阅读进度"))
            self._speed_button.configure(text=f"{int(self.settings.get('tts_rate', 200)) / 200:.1f}×")
        except Exception:
            pass
        win = getattr(self, "_floating_reader", None)
        if win and win.winfo_exists():
            self._floating_play.configure(text="Ⅱ" if playing else "▶")
            self._floating_state.configure(text="正在朗读" if playing else ("已暂停" if paused else "准备就绪"))
            self._floating_dot.configure(fg="#6e79e8" if playing else ("#e2a843" if paused else "#9ca2b3"))
            self._floating_stop_btn.configure(state="normal" if (playing or paused) else "disabled")

    def _sentence_entries(self, chapter_idx=None):
        if not self.book:
            return []
        ci = self.chapter_idx if chapter_idx is None else chapter_idx
        ch = self.book.chapters[ci]
        key = (id(ch), len(ch.content))
        cached = self._modern_sentence_cache.get(key)
        if cached is not None:
            return cached
        from .textproc import clean_to_orig
        clean_text, cmap = ch.tts_content()
        entries = []
        clean_off = 0
        while clean_off < len(clean_text):
            text, nxt, sent_start = self.tts._next_chunk(clean_text, clean_off)
            if not text or nxt <= clean_off:
                break
            start = clean_to_orig(cmap, clean_off + sent_start, len(ch.content))
            end = clean_to_orig(cmap, nxt, len(ch.content))
            entries.append((start, max(start, end), text))
            clean_off = nxt
        self._modern_sentence_cache[key] = entries
        return entries

    def _adjacent_sentences(self, offset=None, current_text=""):
        if not self.book:
            return "", "", ""
        off = self.char_offset if offset is None else int(offset)
        entries = self._sentence_entries()
        if not entries:
            return "", "", ""
        starts = [entry[0] for entry in entries]
        idx = max(0, min(len(entries) - 1, bisect.bisect_right(starts, off) - 1))
        def seg(i):
            return entries[i][2] if 0 <= i < len(entries) else ""
        return seg(idx - 1), current_text.strip() or seg(idx), seg(idx + 1)

    def _step_sentence(self, delta):
        if not self.book:
            return
        entries = self._sentence_entries()
        if not entries:
            return
        starts = [entry[0] for entry in entries]
        cur = max(0, bisect.bisect_right(starts, self.char_offset) - 1)
        target = cur + (1 if delta > 0 else -1)
        ci = self.chapter_idx
        if target < 0 and ci > 0:
            ci -= 1
            prev_entries = self._sentence_entries(ci)
            off = prev_entries[-1][0] if prev_entries else 0
        elif target >= len(entries) and ci < len(self.book.chapters) - 1:
            ci += 1
            next_entries = self._sentence_entries(ci)
            off = next_entries[0][0] if next_entries else 0
        else:
            off = entries[max(0, min(target, len(entries) - 1))][0]
        active = self.tts.is_active()
        self._save_now()
        self.chapter_idx, self.char_offset = ci, off
        self._render_chapter()
        self._highlight_sentence(ci, off, self._adjacent_sentences(off)[1])
        self._schedule_save()
        if active:
            self.tts.start(self.book, ci, off)
            self._set_tts_ui("playing")
        self._floating_sentence = self._adjacent_sentences(off)
        self._sync_modern_playback()


def _make_book_card(app, parent, book):
    c = DARK if app._modern_dark else LIGHT
    card = tk.Frame(parent, bg=c["card"], highlightthickness=1, highlightbackground=c["border"], cursor="hand2")
    bid = book["id"]
    cover = tk.Frame(card, bg="#233d79", height=205)
    cover.pack(fill="x")
    cover.pack_propagate(False)
    path = _cover_path()
    try:
        img = tk.PhotoImage(file=path)
        ratio = max(1, img.width() // 210)
        img = img.subsample(ratio, ratio)
        app._cover_images.append(img)
        tk.Label(cover, image=img, bg="#233d79").pack(fill="both", expand=True)
    except Exception:
        tk.Label(cover, text="DD", bg="#173b76", fg="white", font=_font(45, "bold")).pack(fill="both", expand=True)
    fmt = str(book.get("format", "TXT")).upper()
    tk.Label(cover, text=fmt, bg="#303444", fg="white", font=_font(9, "bold"), padx=6, pady=2).place(x=10, y=10)
    info = tk.Frame(card, bg=c["card"])
    info.pack(fill="x", padx=13, pady=11)
    title = tk.Label(info, text=book.get("title", "未命名"), bg=c["card"], fg=c["text"], font=_font(14, "bold"), anchor="w")
    title.pack(fill="x")
    prog = book.get("progress") or {}
    ci = int(prog.get("chapter_idx", 0) or 0)
    chapters = book.get("chapter_titles") or []
    ch = chapters[ci] if chapters and 0 <= ci < len(chapters) else "从头开始"
    sub = tk.Label(info, text=ch, bg=c["card"], fg=c["muted"], font=_font(11), anchor="w")
    sub.pack(fill="x", pady=(5, 7))
    pct = float(prog.get("percent", 0) or 0)
    row = tk.Frame(info, bg=c["card"])
    row.pack(fill="x")
    line = tk.Canvas(row, height=5, bg=c["card"], bd=0, highlightthickness=0)
    line.pack(side="left", fill="x", expand=True, pady=5)
    line.bind("<Configure>", lambda e, cv=line, p=pct, cc=c: (cv.delete("all"), cv.create_rectangle(0, 1, e.width, 4, fill=cc["border"], outline=""), cv.create_rectangle(0, 1, e.width * p / 100, 4, fill=cc["accent"], outline="")))
    pct_label = tk.Label(row, text=f"{pct:.0f} %", bg=c["card"], fg=c["muted"], font=_font(10))
    pct_label.pack(side="right", padx=(9, 0))
    app._library_card_refs[bid] = (pct_label, line, c)
    _bind_click_tree(card, lambda e, b=bid: app.open_book(b))
    return card


def _bind_click_tree(widget, callback):
    widget.bind("<Button-1>", callback)
    try:
        widget.configure(cursor="hand2")
    except Exception:
        pass
    for child in widget.winfo_children():
        _bind_click_tree(child, callback)


def _recolor_tree(widget, target):
    color_keys = tuple(LIGHT.keys())
    color_map = {}
    for key in color_keys:
        color_map[LIGHT[key].lower()] = target[key]
        color_map[DARK[key].lower()] = target[key]
    for option in ("background", "foreground", "activebackground", "activeforeground", "highlightbackground"):
        try:
            value = str(widget.cget(option)).lower()
            if value in color_map:
                widget.configure(**{option: color_map[value]})
        except Exception:
            pass
    for child in widget.winfo_children():
        _recolor_tree(child, target)


def _open_paste_dialog(app):
    c = DARK if app._modern_dark else LIGHT
    dlg = tk.Toplevel(app.root)
    dlg.title("粘贴文本")
    dlg.geometry("600x460")
    dlg.minsize(560, 430)
    dlg.transient(app.root)
    dlg.configure(bg=c["page"])
    app._center_window(dlg)
    try:
        dlg.grab_set()
    except Exception:
        pass
    tk.Label(dlg, text="粘贴文本", bg=c["page"], fg=c["text"], font=_font(24, "bold")).pack(anchor="w", padx=34, pady=(27, 3))
    tk.Label(dlg, text="标题可选，正文将继续使用现有分章与朗读链路。", bg=c["page"], fg=c["muted"], font=_font(12)).pack(anchor="w", padx=34)
    tk.Label(dlg, text="标题", bg=c["page"], fg=c["text"], font=_font(11, "bold")).pack(anchor="w", padx=34, pady=(19, 5))
    title = tk.Entry(dlg, bd=0, highlightthickness=1, highlightbackground=c["border"], bg=c["card"], fg=c["text"], insertbackground=c["text"], font=_font(13))
    title.pack(fill="x", padx=34, ipady=10)
    tk.Label(dlg, text="正文", bg=c["page"], fg=c["text"], font=_font(11, "bold")).pack(anchor="w", padx=34, pady=(11, 5))
    body = tk.Text(dlg, wrap="word", height=6, bd=0, highlightthickness=1, highlightbackground=c["border"], bg=c["card"], fg=c["text"], insertbackground=c["text"], font=_font(13), padx=13, pady=12)
    body.pack(fill="both", expand=True, padx=34)
    footer = tk.Frame(dlg, bg=c["page"])
    footer.pack(fill="x", padx=34, pady=(7, 0))
    count = tk.Label(footer, text="0 个字符", bg=c["page"], fg=c["muted"], font=_font(11))
    count.pack(side="left")
    err = tk.Label(footer, text="", bg=c["page"], fg="#d14c51", font=_font(11))
    err.pack(side="right")
    body.bind("<KeyRelease>", lambda e: count.configure(text=f"{len(body.get('1.0', 'end-1c'))} 个字符"))
    ops = tk.Frame(dlg, bg=c["page"])
    ops.pack(fill="x", padx=34, pady=(7, 14))
    _button(ops, "加入并阅读", lambda: _submit_paste(app, dlg, title, body, err), bg=c["accent"], fg="white", font=_font(12, "bold"), pady=8).pack(side="right")
    _button(ops, "取消", dlg.destroy, bg=c["card"], fg=c["muted"], font=_font(12), pady=8).pack(side="right", padx=(0, 8))
    body.focus_set()
    app._paste_dialog = dlg


def _submit_paste(app, dlg, title_entry, body_widget, err):
    text = body_widget.get("1.0", "end-1c").strip()
    if not text:
        err.configure(text="正文不能为空，请粘贴要朗读的内容。")
        return
    title = title_entry.get().strip()
    if not title:
        title = next((line.strip() for line in text.splitlines() if line.strip()), "粘贴文本")[:40]
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:60] or "粘贴文本"
    from .storage import data_dir
    import time, uuid
    folder = os.path.join(data_dir(), "pasted")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{int(time.time())}-{uuid.uuid4().hex[:10]}-{safe}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(title + "\n\n" + text)
    dlg.destroy()
    app._import_single(path)


def _open_settings(app):
    existing = getattr(app, "_modern_settings", None)
    if existing and existing.winfo_exists():
        existing.lift()
        return
    c = DARK if app._modern_dark else LIGHT
    dlg = tk.Toplevel(app.root)
    dlg.title("设置")
    dlg.geometry("560x590")
    dlg.resizable(False, False)
    dlg.transient(app.root)
    dlg.configure(bg=c["page"])
    app._center_window(dlg)
    app._modern_settings = dlg
    tk.Label(dlg, text="设置", bg=c["page"], fg=c["text"], font=_font(24, "bold")).pack(anchor="w", padx=30, pady=(25, 17))
    panel = tk.Frame(dlg, bg=c["card"], highlightthickness=1, highlightbackground=c["border"])
    panel.pack(fill="both", expand=True, padx=30, pady=(0, 20))
    def row(label, widget):
        r = tk.Frame(panel, bg=c["card"]); r.pack(fill="x", padx=19, pady=8)
        tk.Label(r, text=label, bg=c["card"], fg=c["text"], width=14, anchor="w", font=_font(12)).pack(side="left")
        widget.pack(side="right")
    font = ttk.Combobox(panel, state="readonly", width=25, values=list(app.font_cb["values"]))
    font.set(app.settings.get("font_family", "微软雅黑"))
    font.bind("<<ComboboxSelected>>", lambda e: (app.font_cb.set(font.get()), app._on_font_change(e)))
    row("正文字体", font)
    paragraph = ttk.Combobox(panel, state="readonly", width=25, values=list(app.paragraph_cb["values"]))
    paragraph.current(max(0, min(2, int(app.settings.get("paragraph_mode", 1)) - 1)))
    paragraph.bind("<<ComboboxSelected>>", lambda e: (app.paragraph_cb.current(paragraph.current()), app._on_paragraph_mode(e)))
    row("段落空行", paragraph)
    from .constants import THEMES
    theme = ttk.Combobox(panel, state="readonly", width=25, values=list(THEMES.keys()))
    theme.set(app.settings.get("theme", "护眼"))
    theme.bind("<<ComboboxSelected>>", lambda e: (app.theme_cb.set(theme.get()), app._on_theme_change(e), setattr(app, "_modern_dark", theme.get() == "夜间"), app._apply_modern_palette()))
    row("书页配色", theme)
    voice = ttk.Combobox(panel, state="readonly", width=25, values=list(app.voice_cb["values"]))
    if app.voice_cb.get():
        voice.set(app.voice_cb.get())
    voice.bind("<<ComboboxSelected>>", lambda e: (app.voice_cb.current(voice.current()), app._on_voice_change(e)))
    row("朗读语音", voice)
    opacity = ttk.Scale(panel, from_=.65, to=1.0, length=190,
                        command=lambda value: app._set_floating_opacity(value, persist=False))
    opacity.set(float(app.settings.get("floating_reader_opacity", .92)))
    opacity.bind("<ButtonRelease-1>", lambda e: app._set_floating_opacity(opacity.get(), persist=True))
    row("悬浮窗透明度", opacity)
    app._floating_follow_var = tk.BooleanVar(value=bool(app.settings.get("floating_reader_follow_font", True)))
    follow = tk.Checkbutton(panel, text="跟随主阅读器", variable=app._floating_follow_var,
                            command=app._set_floating_follow_font, bg=c["card"], fg=c["text"],
                            activebackground=c["card"], selectcolor=c["card"], font=_font(11))
    row("悬浮窗字体", follow)
    row("悬浮窗背景", _button(panel, "切换浅色 / 米黄 / 深色", app._cycle_floating_background, bg=c["accent_soft"], fg=c["accent"], font=_font(11), pady=6))
    row("语音缓存", _button(panel, "管理整本缓存", app._open_cache_dialog, bg=c["accent_soft"], fg=c["accent"], font=_font(11), pady=6))
    row("全文搜索", _button(panel, "搜索当前书籍", app._open_search_dialog, bg=c["accent_soft"], fg=c["accent"], font=_font(11), pady=6))
    row("书签与划线", _button(panel, "打开书签面板", lambda: _show_bookmarks(app, dlg), bg=c["accent_soft"], fg=c["accent"], font=_font(11), pady=6))
    row("关于", _button(panel, "多多朗读信息", app._show_about, bg=c["accent_soft"], fg=c["accent"], font=_font(11), pady=6))
    _button(dlg, "完成", dlg.destroy, bg=c["accent"], fg="white", font=_font(12, "bold"), pady=8).pack(anchor="e", padx=30, pady=(0, 22))


def _show_bookmarks(app, settings_dialog):
    if not app.book:
        messagebox.showinfo("书签与划线", "请先从内容库选择一本书。", parent=settings_dialog)
        return
    settings_dialog.destroy()
    app._show_reader_page()
    if not app._chapter_panel_visible:
        app._toggle_toc()
    app._set_panel_mode("bookmark")


def _create_floating_reader(app):
    c = LIGHT
    win = tk.Toplevel(app.root)
    app._floating_reader = win
    win.overrideredirect(True)
    win.minsize(430, 238)
    win.configure(bg=c["sheet"], highlightthickness=1, highlightbackground=c["border"])
    sx, sy, sw, sh = _screen_bounds(win)
    geo = clamp_geometry(app.settings.get("floating_reader_geometry", ""), sw, sh, sx, sy)
    win.geometry(geo)
    opacity = app.settings.get("floating_reader_opacity", .92)
    try:
        opacity = max(.65, min(1.0, float(opacity)))
    except Exception:
        opacity = .92
    app.settings["floating_reader_opacity"] = opacity
    win.attributes("-alpha", opacity)
    win.attributes("-topmost", bool(app.settings.get("floating_reader_topmost", True)))
    title = tk.Frame(win, bg=c["sheet"], height=49)
    title.pack(fill="x")
    title.pack_propagate(False)
    app._floating_titlebar = title
    app._floating_dot = tk.Label(title, text="●", bg=c["sheet"], fg="#9ca2b3", font=_font(10))
    app._floating_dot.pack(side="left", padx=(14, 0), pady=13)
    app._floating_chapter = tk.Label(title, text="", bg=c["sheet"], fg=c["text"], font=_font(12, "bold"))
    app._floating_chapter.pack(side="left", padx=(5, 16), pady=13)
    app._floating_close = _button(title, "×", lambda: app._destroy_floating_reader(save=True), bg=c["card"], fg=c["text"], font=_font(18), pady=5)
    app._floating_close.pack(side="right", padx=(2, 10), pady=8)
    app._floating_pin = _button(title, "◆" if app.settings.get("floating_reader_topmost", True) else "◇", app._toggle_floating_topmost, bg=c["card"], fg=c["text"], font=_font(14), pady=5)
    app._floating_pin.pack(side="right", padx=2, pady=8)
    app._floating_theme = _button(title, "◐", app._cycle_floating_background, bg=c["card"], fg=c["text"], font=_font(15), pady=5)
    app._floating_theme.pack(side="right", padx=2, pady=8)
    app._floating_font_up = _button(title, "A+", lambda: app._change_floating_font(1), bg=c["card"], fg=c["text"], font=_font(10), pady=6)
    app._floating_font_up.pack(side="right", padx=2, pady=8)
    app._floating_font_down = _button(title, "A−", lambda: app._change_floating_font(-1), bg=c["card"], fg=c["text"], font=_font(10), pady=6)
    app._floating_font_down.pack(side="right", padx=2, pady=8)
    content = tk.Frame(win, bg=c["sheet"])
    content.pack(fill="both", expand=True, padx=19, pady=(3, 2))
    app._floating_content = content
    viewport = tk.Canvas(content, bg=c["sheet"], bd=0, highlightthickness=0)
    scroll = tk.Scrollbar(content, command=viewport.yview, width=8)
    viewport.configure(yscrollcommand=scroll.set)
    viewport.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    sentence_box = tk.Frame(viewport, bg=c["sheet"])
    sentence_window = viewport.create_window((0, 0), window=sentence_box, anchor="nw")
    sentence_box.bind("<Configure>", lambda e: viewport.configure(scrollregion=viewport.bbox("all")))
    viewport.bind("<Configure>", lambda e: viewport.itemconfigure(sentence_window, width=e.width))
    viewport.bind("<MouseWheel>", lambda e: viewport.yview_scroll(int(-e.delta / 120), "units"))
    app._floating_viewport = viewport
    app._floating_sentence_box = sentence_box
    app._floating_prev = tk.Label(sentence_box, text="", bg=c["sheet"], fg=c["muted"], anchor="w", justify="left", wraplength=490)
    app._floating_prev.pack(fill="x")
    app._floating_current = tk.Label(sentence_box, text="", bg=c["sheet"], fg=c["text"], anchor="w", justify="left", wraplength=500)
    app._floating_current.pack(fill="x", expand=True, pady=5)
    app._floating_next = tk.Label(sentence_box, text="", bg=c["sheet"], fg=c["muted"], anchor="w", justify="left", wraplength=490)
    app._floating_next.pack(fill="x")
    controls = tk.Frame(win, bg=c["sheet"], height=56)
    controls.pack(fill="x", side="bottom", padx=14, pady=(2, 9))
    controls.pack_propagate(False)
    app._floating_controls = controls
    app._floating_state = tk.Label(controls, text="准备就绪", bg=c["sheet"], fg=c["muted"], font=_font(10))
    app._floating_state.pack(side="left", padx=4)
    center = tk.Frame(controls, bg=c["sheet"])
    center.place(relx=.5, rely=.5, anchor="center")
    app._floating_prev_btn = _button(center, "│◀", lambda: app._step_sentence(-1), bg="#f1f2f8", fg=c["text"], font=_font(16), pady=6)
    app._floating_prev_btn.pack(side="left", padx=3)
    app._floating_play = _button(center, "▶", app._tts_toggle, bg=c["accent"], fg="white", font=_font(18), pady=7)
    app._floating_play.pack(side="left", padx=3)
    app._floating_next_btn = _button(center, "▶│", lambda: app._step_sentence(1), bg="#f1f2f8", fg=c["text"], font=_font(16), pady=6)
    app._floating_next_btn.pack(side="left", padx=3)
    app._floating_stop_btn = _button(center, "■", app._tts_stop, bg="#f1f2f8", fg=c["text"], font=_font(13), pady=7)
    app._floating_stop_btn.pack(side="left", padx=3)
    app._floating_progress = tk.Canvas(controls, width=78, height=8, bg=c["sheet"], bd=0, highlightthickness=0)
    app._floating_progress.pack(side="right", padx=(4, 20), pady=23)
    app._floating_bilingual = _button(controls, "中 / EN", lambda: messagebox.showinfo("双语显示", "当前内容无可靠译文，自动翻译不在本期范围内。", parent=win), bg="#f1f2f8", fg=c["muted"], font=_font(9), pady=5)
    app._floating_bilingual.pack(side="right", padx=3, pady=12)
    # Pack the fixed control bar before the expanding scroll viewport so the
    # minimum-height layout can never squeeze playback controls out of view.
    controls.pack_forget()
    content.pack_forget()
    controls.pack(fill="x", side="bottom", padx=14, pady=(2, 9))
    content.pack(fill="both", expand=True, side="top", padx=19, pady=(3, 2))
    handle = tk.Label(win, text="◢", bg=c["sheet"], fg=c["muted"], cursor="size_nw_se", font=_font(13))
    handle.place(relx=1, rely=1, anchor="se")
    app._floating_handle = handle
    app._float_drag = None
    app._float_resize = None
    for w in (title, app._floating_dot, app._floating_chapter):
        w.bind("<ButtonPress-1>", lambda e: _float_drag_start(app, e))
        w.bind("<B1-Motion>", lambda e: _float_drag_move(app, e))
        w.bind("<ButtonRelease-1>", lambda e: _float_drag_end(app, e))
    handle.bind("<ButtonPress-1>", lambda e: _float_resize_start(app, e))
    handle.bind("<B1-Motion>", lambda e: _float_resize_move(app, e))
    handle.bind("<ButtonRelease-1>", lambda e: _float_resize_end(app, e))
    win.bind("<space>", lambda e: (app._tts_toggle(), "break")[1])
    win.bind("<Escape>", lambda e: (app._destroy_floating_reader(save=True), "break")[1])
    win.bind("<Configure>", lambda e: _float_wrap(app, e))
    app._apply_floating_palette()
    app._update_floating_reader()
    app._sync_modern_tts_state("playing" if app.tts.is_playing() else ("paused" if app.tts.is_paused() else "stopped"))
    win.after_idle(lambda: _float_platform_setup(app))
    for btn in (app._floating_toolbar_btn, app._floating_player_btn):
        btn.configure(relief="sunken")


def _float_drag_start(app, e):
    win = app._floating_reader
    app._float_drag = (e.x_root, e.y_root, win.winfo_x(), win.winfo_y())
    try: win.grab_set_global()
    except Exception: pass


def _float_drag_move(app, e):
    if not app._float_drag: return
    sx, sy, ox, oy = app._float_drag
    win = app._floating_reader
    x, y = ox + e.x_root - sx, oy + e.y_root - sy
    bx, by, bw, bh = _screen_bounds(win)
    geo = clamp_geometry(f"{win.winfo_width()}x{win.winfo_height()}{x:+d}{y:+d}", bw, bh, bx, by)
    win.geometry(geo)


def _float_drag_end(app, e):
    app._float_drag = None
    try: app._floating_reader.grab_release()
    except Exception: pass
    app._save_floating_geometry()


def _float_resize_start(app, e):
    win = app._floating_reader
    app._float_resize = (e.x_root, e.y_root, win.winfo_width(), win.winfo_height(), win.winfo_x(), win.winfo_y())
    try: win.grab_set_global()
    except Exception: pass


def _float_resize_move(app, e):
    if not app._float_resize: return
    sx, sy, ow, oh, x, y = app._float_resize
    win = app._floating_reader
    w, h = max(430, ow + e.x_root - sx), max(238, oh + e.y_root - sy)
    bx, by, bw, bh = _screen_bounds(win)
    geo = clamp_geometry(f"{w}x{h}{x:+d}{y:+d}", bw, bh, bx, by)
    win.geometry(geo)


def _float_resize_end(app, e):
    app._float_resize = None
    try: app._floating_reader.grab_release()
    except Exception: pass
    app._save_floating_geometry()


def _float_wrap(app, e):
    try:
        w = max(320, app._floating_reader.winfo_width() - 54)
        app._floating_prev.configure(wraplength=w)
        app._floating_current.configure(wraplength=w)
        app._floating_next.configure(wraplength=w)
        total_w = app._floating_reader.winfo_width()
        if total_w < 700:
            app._floating_progress.pack_forget()
        elif not app._floating_progress.winfo_manager():
            app._floating_progress.pack(side="right", padx=(4, 20), pady=23)
        if total_w < 520:
            app._floating_bilingual.pack_forget()
        elif not app._floating_bilingual.winfo_manager():
            app._floating_bilingual.pack(side="right", padx=3, pady=12)
    except Exception:
        pass


def _float_platform_setup(app):
    """Detach the overlay from the main HWND and request native rounded corners."""
    try:
        import ctypes
        win = app._floating_reader
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        setter = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
        setter(hwnd, -8, 0)  # GWLP_HWNDPARENT: keep visible when root is minimized
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        if not getattr(app, "_floating_unmap_bound", False):
            app.root.bind("<Unmap>", lambda e: app.root.after(80, app._restore_floating_after_minimize), add="+")
            app._floating_unmap_bound = True
    except Exception:
        pass
