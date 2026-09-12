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

const EMPTY_IMPORT_STATE = {
  status: "idle",
  jobId: "",
  completed: 0,
  total: 0,
  succeeded: 0,
  failed: 0,
  message: "",
  tone: "info",
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

function Library({
  books,
  error,
  loading,
  openBook,
  openPaste,
  selectFiles,
  showUnavailable,
  capabilities,
  readerEnabled,
  importState,
  cancelImport,
  openAfterImportBookId,
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleBooks = normalizedQuery
    ? books.filter((book) => book.title.toLocaleLowerCase().includes(normalizedQuery))
    : books;
  const importing = ["selecting", "confirming", "processing", "cancelling"].includes(importState.status);
  return (
    <section className="library-page">
      <div className="library-heading">
        <div><p className="eyebrow">我的内容</p><h1>内容库</h1><p className="subtle">让文字成为可以随时聆听的陪伴。</p></div>
        <label className="search-field"><MagnifyingGlass /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索书籍或文章" /></label>
      </div>
      <div className="import-grid">
        <button className="import-card primary" aria-disabled={!capabilities.pasteImport || importing} onClick={capabilities.pasteImport && !importing ? openPaste : undefined}><span className="import-icon"><Article weight="fill" /></span><span><strong>粘贴文本</strong><small>快速开始一段朗读</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled="true" onClick={() => showUnavailable("网页正文提取将在后续版本支持，当前不会发起网页抓取或创建空内容。") }><span className="import-icon blue"><LinkSimple weight="bold" /></span><span><strong>网页链接</strong><small>后续支持 · 当前不抓取网页</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled="true" onClick={() => showUnavailable("音频导入与语音转写暂未支持，现有朗读功能不会被当作音频转写使用。") }><span className="import-icon violet"><Headphones weight="fill" /></span><span><strong>播客 / 音频</strong><small>暂未支持 · 不会创建音频内容</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled={!capabilities.fileImport || importing} onClick={capabilities.fileImport && !importing ? selectFiles : undefined}><span className="import-icon mint"><FileArrowUp weight="fill" /></span><span><strong>导入文件</strong><small>TXT、EPUB、DOCX、PDF</small></span><CaretRight /></button>
      </div>
      {error ? <div className="library-error" role="alert">{error}</div> : null}
      {importState.message ? <div className={`import-notice ${importState.tone || "info"}`} role="status">{importState.message}</div> : null}
      {["processing", "cancelling"].includes(importState.status) ? (
        <div className="import-progress" aria-label="导入进度">
          <div><strong>{importState.status === "cancelling" ? "正在取消导入…" : "正在导入内容…"}</strong><span>{importState.completed} / {importState.total}</span></div>
          <progress value={importState.completed} max={Math.max(1, importState.total)} />
          <button className="secondary-button" onClick={cancelImport} disabled={importState.status === "cancelling"}>取消导入</button>
        </div>
      ) : null}
      <div className="section-title"><div><h2>最近阅读</h2><span>{visibleBooks.length} 项内容</span></div><button className="quiet-button"><List /> 列表</button></div>
      <div className="book-grid">
        {visibleBooks.map((book) => (
          <button key={book.id} className={`book-card ${book.id === openAfterImportBookId ? "just-imported" : ""}`} aria-disabled={!readerEnabled} onClick={() => openBook(book)}>
            <div className="cover-wrap"><img src={book.coverUrl} alt="" /><span className="format-badge">{book.format || "TXT"}</span><span className="resume-pill"><Play weight="fill" /> 继续</span></div>
            <strong>{book.title}</strong><small>{book.currentChapterTitle || book.author || "尚未开始阅读"}</small><div className="book-progress"><span style={{ width: `${book.progressPercent}%` }} /></div><em>{book.progressPercent}%</em>
          </button>
        ))}
        {loading ? <div className="library-loading">正在读取内容库…</div> : null}
        {!loading && visibleBooks.length === 0 ? (
          <div className="library-empty">
            <strong>{books.length === 0 ? "内容库还是空的" : "没有匹配的内容"}</strong>
            <span>{books.length === 0 ? "导入文件或粘贴文本即可开始朗读" : "换个关键词，或清空搜索后查看全部内容"}</span>
            {books.length > 0 ? <button className="secondary-button" onClick={() => setQuery("")}>清空搜索</button> : null}
          </div>
        ) : null}
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

function PasteModal({ onClose, onImport, demoMode }) {
  const [title, setTitle] = useState(demoMode ? "运气的成分" : "");
  const [text, setText] = useState(demoMode ? "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。" : "");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const submit = async () => {
    if (!text.trim()) {
      setSubmitError("正文不能为空，请粘贴要朗读的内容。");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    const error = await onImport({ title, text });
    if (error) {
      setSubmitError(error);
      setSubmitting(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !submitting && onClose()}><div className="paste-modal" role="dialog" aria-modal="true" aria-labelledby="paste-title"><div className="modal-header"><div><span className="modal-icon"><Article weight="fill" /></span><div><h2 id="paste-title">粘贴文本</h2><p>将一段文字快速加入内容库</p></div></div><IconButton label="关闭" onClick={submitting ? undefined : onClose}><X /></IconButton></div><label className="field-label">标题<input value={title} onChange={(event) => setTitle(event.target.value)} disabled={submitting} placeholder="可选，留空将使用正文首行" /></label><label className="field-label">正文<textarea value={text} onChange={(event) => setText(event.target.value)} disabled={submitting} placeholder="粘贴要朗读的正文" /></label><div className="modal-footer"><span>{text.length} 个字符</span>{submitError ? <span className="modal-error" role="alert">{submitError}</span> : null}<div><button className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button className="primary-button" onClick={submit} disabled={submitting}>{submitting ? "正在加入…" : "加入并阅读"}</button></div></div></div></div>
  );
}

function ImportConfirmationModal({ selection, onClose, onStart }) {
  const [confirmLargeFiles, setConfirmLargeFiles] = useState(false);
  const [duplicateMode, setDuplicateMode] = useState("cancel");
  const supportedCount = selection.items.filter((item) => item.supported).length;
  return (
    <div className="modal-backdrop"><div className="paste-modal import-confirmation" role="dialog" aria-modal="true" aria-labelledby="import-confirm-title">
      <div className="modal-header"><div><span className="modal-icon"><FileArrowUp weight="fill" /></span><div><h2 id="import-confirm-title">确认导入</h2><p>已选择 {selection.total} 个文件，其中 {supportedCount} 个格式受支持</p></div></div><IconButton label="关闭" onClick={onClose}><X /></IconButton></div>
      <div className="selection-list">{selection.items.map((item) => <div key={item.itemId} className={!item.supported ? "unsupported" : ""}><strong>{item.name}</strong><span>{item.format || "未知格式"}{item.large ? " · 大文件" : ""}{item.duplicate.exists ? ` · 已存在「${item.duplicate.title}」` : ""}{!item.supported ? " · 不支持" : ""}</span></div>)}</div>
      {selection.largeFileCount > 0 ? <label className="confirmation-row"><input type="checkbox" checked={confirmLargeFiles} onChange={(event) => setConfirmLargeFiles(event.target.checked)} />我确认导入 {selection.largeFileCount} 个大文件</label> : null}
      {selection.duplicateCount > 0 ? <label className="field-label">重复内容处理<select value={duplicateMode} onChange={(event) => setDuplicateMode(event.target.value)}><option value="cancel">跳过重复内容</option><option value="overwrite">覆盖并沿用已有解析</option><option value="reparse">重新预处理文本</option></select></label> : null}
      <div className="confirmation-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={supportedCount === 0 || (selection.largeFileCount > 0 && !confirmLargeFiles)} onClick={() => onStart({ selectionId: selection.selectionId, confirmLargeFiles, duplicateMode })}>开始导入</button></div>
    </div></div>
  );
}

export function App() {
  const qaMode = new URLSearchParams(window.location.search).get("qa");
  const qaFloating = qaMode === "floating";
  const qaEmptyLibrary = qaMode === "empty-library";
  const nativeTransportAvailable = Boolean(window.qt?.webChannelTransport);
  const demoQaFloating = qaFloating && !nativeTransportAvailable;
  const connectionRef = useRef(null);
  const [page, setPage] = useState(demoQaFloating ? "reader" : "library");
  const [books, setBooks] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [bridgeError, setBridgeError] = useState("");
  const [bridgeMode, setBridgeMode] = useState(nativeTransportAvailable ? "native" : "demo");
  const [windowControls, setWindowControls] = useState(EMPTY_CONTROLS);
  const [capabilities, setCapabilities] = useState(EMPTY_CAPABILITIES);
  const [importState, setImportState] = useState(() => ({ ...EMPTY_IMPORT_STATE }));
  const [importSelection, setImportSelection] = useState(null);
  const [openAfterImportBookId, setOpenAfterImportBookId] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [floating, setFloating] = useState(demoQaFloating);
  const [playing, setPlaying] = useState(demoQaFloating);
  const [bilingual, setBilingual] = useState(false);
  const [fontSize, setFontSize] = useState(21);

  useEffect(() => {
    let active = true;
    const readBridgeMessage = (raw) => {
      try {
        return JSON.parse(raw).message || "桌面操作失败。";
      } catch {
        return "桌面操作失败。";
      }
    };
    const attachConnection = (connected) => {
      if (!active) {
        connected.dispose();
        return;
      }
      connectionRef.current?.dispose();
      connectionRef.current = connected;
      setBridgeMode(connected.mode);
      setBooks(connected.mode === "demo" && qaEmptyLibrary ? [] : connected.initialState.data.library.books);
      setCapabilities(connected.initialState.data.capabilities);
      setWindowControls(connected.controls);
      connected.onBridgeError((raw) => {
        if (active) setBridgeError(readBridgeMessage(raw));
      });
      connected.onImportProgress((event) => {
        if (!active) return;
        setImportState((previous) => previous.jobId && previous.jobId !== event.jobId ? previous : {
          ...previous,
          status: "processing",
          jobId: event.jobId,
          completed: event.completed,
          total: event.total,
          succeeded: event.succeeded,
          failed: event.failed,
          message: event.error?.message || `正在处理「${event.item.name}」`,
          tone: event.error ? "warning" : "info",
        });
      });
      connected.onImportFinished(async (event) => {
        if (!active) return;
        const firstFailure = event.results.find((item) => item.status === "failed")?.error?.message;
        const succeeded = event.succeeded > 0;
        const partial = succeeded && event.failed > 0;
        const message = event.state === "cancelled"
          ? `导入已取消，已处理 ${event.processed} / ${event.total} 项。`
          : partial
            ? `已导入 ${event.succeeded} 项，${event.failed} 项失败。${firstFailure ? ` ${firstFailure}` : ""}`
            : succeeded
              ? `已成功导入 ${event.succeeded} 项；真实阅读器将在阶段 3 接入。`
              : firstFailure || "导入失败，内容库未新增可用内容。";
        setImportState({
          status: event.state === "cancelled" ? "cancelled" : partial ? "partial" : succeeded ? "succeeded" : "failed",
          jobId: event.jobId,
          completed: event.processed,
          total: event.total,
          succeeded: event.succeeded,
          failed: event.failed,
          message,
          tone: event.state === "cancelled" ? "info" : partial ? "warning" : succeeded ? "success" : "error",
        });
        setPasteOpen(false);
        setImportSelection(null);
        setOpenAfterImportBookId(event.openAfterImportBookId);
        setPage("library");
        if (connected.mode === "demo") {
          setBooks([...connected.initialState.data.library.books]);
          return;
        }
        try {
          attachConnection(await connectBridge());
        } catch (error) {
          if (active) setBridgeError(error.message || "导入完成，但内容库刷新失败。");
        }
      });
      setLibraryLoading(false);
    };
    connectBridge().then(attachConnection).catch((error) => {
      if (!active) return;
      const failedConnection = error.connection;
      if (failedConnection) attachConnection(failedConnection);
      setBooks(error.initialData?.library?.books || []);
      setCapabilities(error.initialData?.capabilities || EMPTY_CAPABILITIES);
      setBridgeError(error.message || "无法连接桌面程序。");
      setLibraryLoading(false);
    });
    return () => {
      active = false;
      connectionRef.current?.dispose();
      connectionRef.current = null;
    };
  }, []);

  const selectFiles = async () => {
    const connection = connectionRef.current;
    if (!connection) return;
    setImportState({ ...EMPTY_IMPORT_STATE, status: "selecting", message: "正在选择文件…" });
    try {
      const response = await connection.imports.selectFiles();
      if (response.data.cancelled) {
        setImportState({ ...EMPTY_IMPORT_STATE });
        return;
      }
      setImportSelection(response.data);
      setImportState({ ...EMPTY_IMPORT_STATE, status: "confirming" });
    } catch (error) {
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message: error.message || "无法选择导入文件。", tone: "error" });
    }
  };
  const startFileImport = async (input) => {
    const connection = connectionRef.current;
    if (!connection || !importSelection) return;
    setImportSelection(null);
    setImportState({ ...EMPTY_IMPORT_STATE, status: "processing", total: importSelection.total, message: "导入任务正在排队…" });
    try {
      const response = await connection.imports.startFileImport(input);
      setImportState((previous) => ({ ...previous, jobId: response.data.jobId }));
    } catch (error) {
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message: error.message || "无法开始文件导入。", tone: "error" });
    }
  };
  const startPasteImport = async (input) => {
    const connection = connectionRef.current;
    if (!connection) return "桌面通信尚未就绪。";
    setImportState({ ...EMPTY_IMPORT_STATE, status: "processing", total: 1, message: "正在加入粘贴内容…" });
    try {
      const response = await connection.imports.startPasteImport(input);
      setImportState((previous) => ({ ...previous, jobId: response.data.jobId }));
      return "";
    } catch (error) {
      const message = error.message || "无法加入粘贴内容。";
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message, tone: "error" });
      return message;
    }
  };
  const cancelImport = async () => {
    const connection = connectionRef.current;
    if (!connection || !importState.jobId) return;
    setImportState((previous) => ({ ...previous, status: "cancelling", message: "正在取消导入…" }));
    try {
      const response = await connection.imports.cancelImport(importState.jobId);
      if (!response.data.cancelRequested) {
        setImportState((previous) => ({ ...previous, status: "processing", message: "当前导入任务无法取消。", tone: "warning" }));
      }
    } catch (error) {
      setImportState((previous) => ({ ...previous, status: "processing", message: error.message || "取消导入失败。", tone: "error" }));
    }
  };
  const openBook = (book) => {
    if (bridgeMode === "demo") {
      setPage("reader");
      setPasteOpen(false);
      return;
    }
    setOpenAfterImportBookId(book.id);
    setImportState({ ...EMPTY_IMPORT_STATE, status: "ready", message: `「${book.title}」已就绪；真实阅读器将在阶段 3 接入。`, tone: "info" });
    setPage("library");
  };
  const showUnavailable = (message) => setImportState({ ...EMPTY_IMPORT_STATE, status: "unavailable", message, tone: "info" });
  const desktopMode = bridgeMode === "native" || nativeTransportAvailable;
  const readerEnabled = bridgeMode === "demo" || capabilities.reader;
  const effectiveCapabilities = bridgeMode === "demo"
    ? { fileImport: true, pasteImport: true, webImport: true, audioImport: true }
    : capabilities;
  return (
    <div className={`prototype-stage ${desktopMode ? "desktop-host" : ""}`}>{desktopMode ? <WindowResizeHandles controls={windowControls} /> : null}<div className="mac-window"><MacTitlebar controls={windowControls} desktopMode={desktopMode} /><div className="app-body"><Rail page={page} setPage={setPage} readerEnabled={readerEnabled} audioEnabled={bridgeMode === "demo" || capabilities.audioImport} /><main className="content-area">{page === "reader" && bridgeMode === "demo" ? <Reader setPage={setPage} fontSize={fontSize} setFontSize={setFontSize} playing={playing} setPlaying={setPlaying} floating={floating} setFloating={setFloating} /> : <Library books={books} error={bridgeError} loading={libraryLoading} openBook={openBook} openPaste={() => setPasteOpen(true)} selectFiles={selectFiles} showUnavailable={showUnavailable} capabilities={effectiveCapabilities} readerEnabled={readerEnabled} importState={importState} cancelImport={cancelImport} openAfterImportBookId={openAfterImportBookId} />}</main></div></div>{floating && <FloatingReader playing={playing} setPlaying={setPlaying} onClose={() => setFloating(false)} bilingual={bilingual} setBilingual={setBilingual} />}{pasteOpen && <PasteModal onClose={() => setPasteOpen(false)} onImport={startPasteImport} demoMode={bridgeMode === "demo"} />}{importSelection && <ImportConfirmationModal selection={importSelection} onClose={() => { setImportSelection(null); setImportState({ ...EMPTY_IMPORT_STATE }); }} onStart={startFileImport} />}</div>
  );
}
