import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Article,
  BookOpen,
  Books,
  CaretLeft,
  CaretRight,
  CornersOut,
  FileArrowUp,
  GearSix,
  Headphones,
  LinkSimple,
  List,
  MagnifyingGlass,
  Minus,
  Moon,
  Pause,
  Play,
  Plus,
  PushPin,
  SidebarSimple,
  SpeakerHigh,
  TextAa,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { connectBridge } from "./bridge.js";

const EMPTY_CONTROLS = {
  minimizeWindow() {},
  toggleMaximizeWindow() {},
  closeWindow() {},
  startWindowMove() {},
  startWindowResize() {},
};

const EMPTY_CAPABILITIES = {
  fileImport: false,
  pasteImport: false,
  webImport: false,
  audioImport: false,
  reader: false,
  tts: false,
  floatingReader: false,
};

const chapters = [
  "序言：为什么要重新理解运气",
  "第一章　财富与选择",
  "第二章　时间的复利",
  "第三章　幸运的结构",
  "第四章　长期主义",
  "第五章　保持在场",
  "第六章　运气的成分",
  "第七章　创造自己的机会",
  "结语：做一个清醒的乐观者",
];

const paragraphs = [
  "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。",
  "财富并不只是一串数字，它更像一种选择权：你能决定把时间留给谁，也能决定拒绝什么。",
  "创造财富的法则，往往只是代表了财富创造的方式；真正重要的是理解自己愿意用什么交换，又不愿失去什么。",
  "如果你想赚100万美元，就不得不接受一段长期而安静的积累。可是不难想象，把人生压缩到三四年，承受较大的压力，通常会让判断变得狭窄。",
  "所以，运气不是等待。它来自持续行动、开放连接，以及在机会出现时仍然保持准备。",
];

function IconButton({ label, children, active = false, onClick, className = "" }) {
  return (
    <button className={`icon-button ${active ? "active" : ""} ${className}`} aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}

function Rail({ page, setPage, readerEnabled, audioEnabled }) {
  return (
    <aside className="rail">
      <div className="brand-mark"><BookOpen weight="fill" /></div>
      <nav aria-label="主导航">
        <IconButton label="内容库" active={page === "library"} onClick={() => setPage("library")}><Books weight={page === "library" ? "fill" : "regular"} /></IconButton>
        <IconButton label="阅读器" active={page === "reader"} onClick={readerEnabled ? () => setPage("reader") : undefined}><Article weight={page === "reader" ? "fill" : "regular"} /></IconButton>
        <IconButton label="音频内容" className={!audioEnabled ? "disabled" : ""}><Headphones /></IconButton>
      </nav>
      <div className="rail-bottom">
        <IconButton label="深色模式"><Moon /></IconButton>
        <IconButton label="设置"><GearSix /></IconButton>
      </div>
    </aside>
  );
}

function MacTitlebar({ controls, desktopMode }) {
  const startMove = (event) => {
    if (!desktopMode || event.button !== 0 || event.target.closest("button, input")) return;
    controls.startWindowMove();
  };
  const toggleMaximize = (event) => {
    if (!desktopMode || event.target.closest("button, input")) return;
    controls.toggleMaximizeWindow();
  };
  return (
    <header className="mac-titlebar" onPointerDown={startMove} onDoubleClick={toggleMaximize}>
      <div className="traffic-lights">
        <button className="traffic red" aria-label="关闭窗口" title="关闭窗口" onClick={controls.closeWindow} />
        <button className="traffic yellow" aria-label="最小化窗口" title="最小化窗口" onClick={controls.minimizeWindow} />
        <button className="traffic green" aria-label="最大化或还原窗口" title="最大化或还原窗口" onClick={controls.toggleMaximizeWindow} />
      </div>
      <div className="app-title">多多朗读</div>
      <div className="titlebar-actions"><IconButton label="搜索"><MagnifyingGlass /></IconButton><div className="avatar">D</div></div>
    </header>
  );
}

function Library({ books, error, loading, openBook, openPaste, capabilities, readerEnabled }) {
  const [query, setQuery] = useState("");
  const visibleBooks = books.filter((book) => book.title.includes(query));
  return (
    <section className="library-page">
      <div className="library-heading">
        <div><p className="eyebrow">我的内容</p><h1>内容库</h1><p className="subtle">让文字成为可以随时聆听的陪伴。</p></div>
        <label className="search-field"><MagnifyingGlass /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索书籍或文章" /></label>
      </div>
      <div className="import-grid">
        <button className="import-card primary" aria-disabled={!capabilities.pasteImport} onClick={capabilities.pasteImport ? openPaste : undefined}><span className="import-icon"><Article weight="fill" /></span><span><strong>粘贴文本</strong><small>快速开始一段朗读</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled={!capabilities.webImport}><span className="import-icon blue"><LinkSimple weight="bold" /></span><span><strong>网页链接</strong><small>提取干净文章正文</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled={!capabilities.audioImport}><span className="import-icon violet"><Headphones weight="fill" /></span><span><strong>播客 / 音频</strong><small>导入并整理音频内容</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled={!capabilities.fileImport}><span className="import-icon mint"><FileArrowUp weight="fill" /></span><span><strong>导入文件</strong><small>TXT、EPUB、DOCX、PDF</small></span><CaretRight /></button>
      </div>
      {error ? <div className="library-error" role="alert">{error}</div> : null}
      <div className="section-title"><div><h2>最近阅读</h2><span>{visibleBooks.length} 项内容</span></div><button className="quiet-button"><List /> 列表</button></div>
      <div className="book-grid">
        {visibleBooks.map((book) => (
          <button key={book.id} className="book-card" aria-disabled={!readerEnabled} onClick={readerEnabled ? () => openBook(book) : undefined}>
            <div className="cover-wrap"><img src={book.coverUrl} alt="" /><span className="format-badge">{book.format || "TXT"}</span><span className="resume-pill"><Play weight="fill" /> 继续</span></div>
            <strong>{book.title}</strong><small>{book.currentChapterTitle || book.author || "尚未开始阅读"}</small><div className="book-progress"><span style={{ width: `${book.progressPercent}%` }} /></div><em>{book.progressPercent}%</em>
          </button>
        ))}
        {loading ? <div className="library-loading">正在读取内容库…</div> : null}
      </div>
    </section>
  );
}

const WINDOW_EDGES = ["top", "right", "bottom", "left", "topRight", "bottomRight", "bottomLeft", "topLeft"];

function WindowResizeHandles({ controls }) {
  return WINDOW_EDGES.map((edge) => (
    <div
      key={edge}
      className={`window-resize-handle ${edge}`}
      aria-hidden="true"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        controls.startWindowResize(edge);
      }}
    />
  ));
}

function ReaderToolbar({ onBack, fontSize, setFontSize, floating, setFloating }) {
  return (
    <div className="reader-toolbar">
      <div className="toolbar-group"><IconButton label="返回内容库" onClick={onBack}><ArrowLeft /></IconButton><IconButton label="显示或隐藏目录"><SidebarSimple /></IconButton><span className="toolbar-title">财富自由之路</span></div>
      <div className="toolbar-group toolbar-center"><IconButton label="缩小字号" onClick={() => setFontSize(Math.max(17, fontSize - 1))}><Minus /></IconButton><span className="font-value">{fontSize}</span><IconButton label="放大字号" onClick={() => setFontSize(Math.min(28, fontSize + 1))}><Plus /></IconButton><IconButton label="阅读排版"><TextAa /></IconButton></div>
      <div className="toolbar-group"><button className={`floating-toggle ${floating ? "on" : ""}`} onClick={() => setFloating(!floating)}><CornersOut /> 悬浮朗读</button><IconButton label="更多设置"><GearSix /></IconButton></div>
    </div>
  );
}

function Player({ playing, setPlaying, setFloating }) {
  const [progress, setProgress] = useState(43);
  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => setProgress((value) => (value >= 100 ? 0 : value + 0.3)), 180);
    return () => window.clearInterval(timer);
  }, [playing]);
  return (
    <div className="player-bar">
      <div className="player-copy"><strong>第六章　运气的成分</strong><small>正在朗读第 18 段</small></div>
      <div className="player-controls"><IconButton label="上一句"><CaretLeft weight="bold" /></IconButton><button className="play-button" aria-label={playing ? "暂停" : "播放"} onClick={() => setPlaying(!playing)}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button><IconButton label="下一句"><CaretRight weight="bold" /></IconButton></div>
      <div className="player-slider"><span>08:24</span><input type="range" min="0" max="100" value={progress} onChange={(event) => setProgress(Number(event.target.value))} /><span>19:42</span></div>
      <div className="player-tools"><button className="speed">1.0×</button><IconButton label="音量"><SpeakerHigh /></IconButton><IconButton label="打开悬浮朗读" onClick={() => setFloating(true)}><CornersOut /></IconButton></div>
    </div>
  );
}

function Reader({ setPage, fontSize, setFontSize, playing, setPlaying, floating, setFloating }) {
  const [chapter, setChapter] = useState(6);
  return (
    <section className="reader-page">
      <ReaderToolbar onBack={() => setPage("library")} fontSize={fontSize} setFontSize={setFontSize} floating={floating} setFloating={setFloating} />
      <div className="reader-layout">
        <aside className="toc-panel"><div className="toc-title"><span>目录</span><small>9 章</small></div><div className="toc-list">{chapters.map((item, index) => <button key={item} className={chapter === index ? "selected" : ""} onClick={() => setChapter(index)}><span>{String(index + 1).padStart(2, "0")}</span>{item}</button>)}</div><div className="toc-footer"><UploadSimple /> 已同步阅读进度</div></aside>
        <article className="reading-sheet" style={{ "--reading-size": `${fontSize}px` }}><p className="chapter-index">CHAPTER 06</p><h1>运气的成分</h1><div className="title-rule" /><div className="reading-copy">{paragraphs.map((paragraph, index) => <p key={paragraph} className={index === 0 ? "speaking" : ""}>{paragraph}</p>)}</div><div className="page-count">126 / 298</div></article>
      </div>
      <Player playing={playing} setPlaying={setPlaying} setFloating={setFloating} />
    </section>
  );
}

function FloatingReader({ playing, setPlaying, onClose, bilingual, setBilingual }) {
  const dragRef = useRef(null);
  const resizeRef = useRef(null);
  const initialWidth = Math.min(560, window.innerWidth - 96);
  const [position, setPosition] = useState({ x: Math.max(24, window.innerWidth - initialWidth - 120), y: 90 });
  const [size, setSize] = useState({ width: initialWidth, height: 270 });
  const startDrag = (event) => {
    if (event.target.closest("button, input")) return;
    dragRef.current = { x: event.clientX, y: event.clientY, left: position.x, top: position.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const drag = (event) => {
    if (!dragRef.current) return;
    setPosition({ x: Math.max(8, dragRef.current.left + event.clientX - dragRef.current.x), y: Math.max(8, dragRef.current.top + event.clientY - dragRef.current.y) });
  };
  const startResize = (event) => {
    event.stopPropagation();
    resizeRef.current = { x: event.clientX, y: event.clientY, width: size.width, height: size.height };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const resize = (event) => {
    if (!resizeRef.current) return;
    const maxWidth = Math.max(370, window.innerWidth - position.x - 10);
    const maxHeight = Math.max(238, window.innerHeight - position.y - 10);
    setSize({
      width: Math.min(maxWidth, Math.max(370, resizeRef.current.width + event.clientX - resizeRef.current.x)),
      height: Math.min(maxHeight, Math.max(238, resizeRef.current.height + event.clientY - resizeRef.current.y)),
    });
  };
  return (
    <div className="floating-reader" style={{ left: position.x, top: position.y, width: size.width, height: size.height }}>
      <div className="floating-dragbar" onPointerDown={startDrag} onPointerMove={drag} onPointerUp={() => { dragRef.current = null; }}>
        <div><span className="live-dot" /> 第六章　运气的成分</div><div className="floating-window-actions"><IconButton label="固定在最前"><PushPin /></IconButton><IconButton label="关闭悬浮窗" onClick={onClose}><X /></IconButton></div>
      </div>
      <div className="floating-content"><p className="context-line">创造财富的法则，往往只是代表了财富创造的方式。</p><p className="current-line">每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。</p>{bilingual && <p className="translation">Three million dollars a year feels enormous to most people, yet barely registers to others.</p>}<p className="next-line">300万美元算什么？</p></div>
      <div className="floating-controls"><div className="control-cluster"><IconButton label="上一句"><CaretLeft weight="fill" /></IconButton><button className="floating-play" aria-label={playing ? "暂停" : "播放"} onClick={() => setPlaying(!playing)}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button><IconButton label="下一句"><CaretRight weight="fill" /></IconButton></div><div className="mini-progress"><span /></div><div className="control-cluster"><button className={`language-toggle ${bilingual ? "on" : ""}`} onClick={() => setBilingual(!bilingual)}>中 / EN</button><IconButton label="缩小文字"><Minus /></IconButton><IconButton label="放大文字"><Plus /></IconButton></div></div>
      <span className="resize-hint">拖动缩放</span>
      <button
        className="resize-handle"
        aria-label="拖动缩放悬浮窗"
        title="拖动缩放悬浮窗"
        onPointerDown={startResize}
        onPointerMove={resize}
        onPointerUp={() => { resizeRef.current = null; }}
        onPointerCancel={() => { resizeRef.current = null; }}
      >
        <CornersOut />
      </button>
    </div>
  );
}

function PasteModal({ onClose, onImport }) {
  const [text, setText] = useState("每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。");
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="paste-modal" role="dialog" aria-modal="true" aria-labelledby="paste-title"><div className="modal-header"><div><span className="modal-icon"><Article weight="fill" /></span><div><h2 id="paste-title">粘贴文本</h2><p>将一段文字快速加入内容库</p></div></div><IconButton label="关闭" onClick={onClose}><X /></IconButton></div><label className="field-label">标题<input defaultValue="运气的成分" /></label><label className="field-label">正文<textarea value={text} onChange={(event) => setText(event.target.value)} /></label><div className="modal-footer"><span>{text.length} 个字符</span><div><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" onClick={onImport}>加入并阅读</button></div></div></div></div>
  );
}

export function App() {
  const qaFloating = new URLSearchParams(window.location.search).get("qa") === "floating";
  const nativeTransportAvailable = Boolean(window.qt?.webChannelTransport);
  const demoQaFloating = qaFloating && !nativeTransportAvailable;
  const [page, setPage] = useState(demoQaFloating ? "reader" : "library");
  const [books, setBooks] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [bridgeError, setBridgeError] = useState("");
  const [bridgeMode, setBridgeMode] = useState(nativeTransportAvailable ? "native" : "demo");
  const [windowControls, setWindowControls] = useState(EMPTY_CONTROLS);
  const [capabilities, setCapabilities] = useState(EMPTY_CAPABILITIES);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [floating, setFloating] = useState(demoQaFloating);
  const [playing, setPlaying] = useState(demoQaFloating);
  const [bilingual, setBilingual] = useState(false);
  const [fontSize, setFontSize] = useState(21);
  const openReader = () => { setPage("reader"); setPasteOpen(false); };
  useEffect(() => {
    let active = true;
    let connection;
    connectBridge()
      .then((connected) => {
        if (!active) return;
        connection = connected;
        setBridgeMode(connected.mode);
        setBooks(connected.initialState.data.library.books);
        setCapabilities(connected.initialState.data.capabilities);
        setWindowControls(connected.controls);
        connected.onBridgeError((raw) => {
          if (!active) return;
          try {
            setBridgeError(JSON.parse(raw).message || "桌面操作失败。");
          } catch {
            setBridgeError("桌面操作失败。");
          }
        });
        setLibraryLoading(false);
      })
      .catch((error) => {
        if (!active) return;
        const failedConnection = error.connection;
        connection = failedConnection;
        if (failedConnection) {
          setBridgeMode(failedConnection.mode);
          setWindowControls(failedConnection.controls);
          failedConnection.onBridgeError((raw) => {
            if (!active) return;
            try {
              setBridgeError(JSON.parse(raw).message || "桌面操作失败。");
            } catch {
              setBridgeError("桌面操作失败。");
            }
          });
        }
        setBooks(error.initialData?.library?.books || []);
        setCapabilities(error.initialData?.capabilities || EMPTY_CAPABILITIES);
        setBridgeError(error.message || "无法连接桌面程序。");
        setLibraryLoading(false);
      });
    return () => {
      active = false;
      connection?.dispose();
    };
  }, []);
  const desktopMode = bridgeMode === "native" || nativeTransportAvailable;
  const readerEnabled = bridgeMode === "demo" || capabilities.reader;
  const effectiveCapabilities = bridgeMode === "demo"
    ? { fileImport: true, pasteImport: true, webImport: true, audioImport: true }
    : capabilities;
  return (
    <div className={`prototype-stage ${desktopMode ? "desktop-host" : ""}`}>{desktopMode ? <WindowResizeHandles controls={windowControls} /> : null}<div className="mac-window"><MacTitlebar controls={windowControls} desktopMode={desktopMode} /><div className="app-body"><Rail page={page} setPage={setPage} readerEnabled={readerEnabled} audioEnabled={bridgeMode === "demo" || capabilities.audioImport} /><main className="content-area">{page === "library" ? <Library books={books} error={bridgeError} loading={libraryLoading} openBook={openReader} openPaste={() => setPasteOpen(true)} capabilities={effectiveCapabilities} readerEnabled={readerEnabled} /> : <Reader setPage={setPage} fontSize={fontSize} setFontSize={setFontSize} playing={playing} setPlaying={setPlaying} floating={floating} setFloating={setFloating} />}</main></div></div>{floating && <FloatingReader playing={playing} setPlaying={setPlaying} onClose={() => setFloating(false)} bilingual={bilingual} setBilingual={setBilingual} />}{pasteOpen && <PasteModal onClose={() => setPasteOpen(false)} onImport={openReader} />}</div>
  );
}
