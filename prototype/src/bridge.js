export const SCHEMA_VERSION = 1;

const DEMO_BOOKS = [
  { id: "demo-1", title: "高效能人士的七个习惯", author: "", format: "EPUB", progressPercent: 36, chapterIndex: 2, chapterCount: 12, currentChapterTitle: "第 3 章 · 要事第一", lastReadAt: null, totalChars: 0, coverUrl: "covers/mountains.png" },
  { id: "demo-2", title: "创意是一种习惯", author: "", format: "EPUB", progressPercent: 68, chapterIndex: 7, chapterCount: 10, currentChapterTitle: "第 8 章 · 保持好奇", lastReadAt: null, totalChars: 0, coverUrl: "covers/creative.png" },
  { id: "demo-3", title: "财富自由之路", author: "", format: "EPUB", progressPercent: 52, chapterIndex: 5, chapterCount: 9, currentChapterTitle: "第 6 章 · 运气的成分", lastReadAt: null, totalChars: 0, coverUrl: "covers/money.png" },
  { id: "demo-4", title: "星火", author: "", format: "EPUB", progressPercent: 12, chapterIndex: 0, chapterCount: 8, currentChapterTitle: "序章 · 启程", lastReadAt: null, totalChars: 0, coverUrl: "covers/library.png" },
];

const EMPTY_DATA = {
  library: { books: [], total: 0 },
  window: { isMaximized: false },
  capabilities: {
    fileImport: false,
    pasteImport: false,
    webImport: false,
    audioImport: false,
    reader: false,
    tts: false,
    floatingReader: false,
  },
};

const CAPABILITY_KEYS = Object.keys(EMPTY_DATA.capabilities);
const BOOK_FIELDS = {
  id: "string",
  title: "string",
  author: "string",
  format: "string",
  progressPercent: "number",
  chapterIndex: "number",
  chapterCount: "number",
  currentChapterTitle: "string",
  totalChars: "number",
  coverUrl: "string",
};

const DUPLICATE_MODES = new Set(["cancel", "overwrite", "reparse"]);

function validBridgeError(error) {
  return error === null || Boolean(
    error
    && typeof error.code === "string"
    && typeof error.message === "string"
    && typeof error.retryable === "boolean",
  );
}

function validBook(book) {
  return Boolean(
    book
    && Object.entries(BOOK_FIELDS).every(([field, type]) => typeof book[field] === type)
    && (book.lastReadAt === null || typeof book.lastReadAt === "number"),
  );
}

function parseJsonPayload(raw, invalidMessage) {
  try {
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new BridgeProtocolError(invalidMessage, "BRIDGE_INVALID_JSON");
  }
}

function parseBridgeResponse(raw, validateData) {
  const payload = parseJsonPayload(raw, "桌面通信返回了无法解析的数据。");
  if (!payload || payload.schemaVersion !== SCHEMA_VERSION) {
    throw new BridgeProtocolError("桌面程序与界面版本不兼容，请更新后重试。", "SCHEMA_MISMATCH");
  }
  if (
    typeof payload.ok !== "boolean"
    || !validBridgeError(payload.error)
    || !validateData(payload.data)
  ) {
    throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
  }
  if (!payload.ok) {
    throw new BridgeProtocolError(
      payload.error?.message || "桌面操作失败。",
      payload.error?.code || "BRIDGE_REQUEST_FAILED",
    );
  }
  return payload;
}

const NOOP_CONTROLS = Object.freeze({
  minimizeWindow() {},
  toggleMaximizeWindow() {},
  closeWindow() {},
  startWindowMove() {},
  startWindowResize() {},
});

export class BridgeProtocolError extends Error {
  constructor(message, code = "BRIDGE_PROTOCOL_ERROR", initialData = EMPTY_DATA) {
    super(message);
    this.name = "BridgeProtocolError";
    this.code = code;
    this.initialData = initialData;
  }
}

export function createDemoInitialState() {
  return {
    schemaVersion: SCHEMA_VERSION,
    ok: true,
    data: {
      ...EMPTY_DATA,
      library: { books: DEMO_BOOKS.map((book) => ({ ...book })), total: DEMO_BOOKS.length },
    },
    error: null,
  };
}

export function parseInitialState(raw) {
  const payload = parseJsonPayload(raw, "桌面通信返回了无法解析的数据。");

  if (!payload || payload.schemaVersion !== SCHEMA_VERSION) {
    throw new BridgeProtocolError("桌面程序与界面版本不兼容，请更新后重试。", "SCHEMA_MISMATCH");
  }
  const books = payload?.data?.library?.books;
  const capabilities = payload?.data?.capabilities;
  const validBooks = Array.isArray(books) && books.every(validBook);
  const validCapabilities = capabilities
    && CAPABILITY_KEYS.every((key) => typeof capabilities[key] === "boolean");
  if (
    typeof payload.ok !== "boolean"
    || !validBridgeError(payload.error)
    || !validBooks
    || typeof payload.data.library.total !== "number"
    || typeof payload.data?.window?.isMaximized !== "boolean"
    || !validCapabilities
  ) {
    throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
  }
  if (!payload.ok) {
    throw new BridgeProtocolError(
      payload.error?.message || "桌面程序暂时无法读取内容库。",
      payload.error?.code || "BRIDGE_REQUEST_FAILED",
      payload.data,
    );
  }
  return payload;
}

function nonNegativeNumber(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function validImportSelection(data) {
  return Boolean(
    data
    && typeof data.cancelled === "boolean"
    && typeof data.selectionId === "string"
    && nonNegativeNumber(data.total)
    && nonNegativeNumber(data.duplicateCount)
    && nonNegativeNumber(data.largeFileCount)
    && Array.isArray(data.items)
    && data.items.length === data.total
    && data.items.every((item) => (
      item
      && typeof item.itemId === "string"
      && typeof item.name === "string"
      && typeof item.format === "string"
      && nonNegativeNumber(item.sizeBytes)
      && typeof item.supported === "boolean"
      && typeof item.large === "boolean"
      && item.duplicate
      && typeof item.duplicate.exists === "boolean"
      && typeof item.duplicate.bookId === "string"
      && typeof item.duplicate.title === "string"
    )),
  );
}

function validImportStart(data) {
  return Boolean(data && typeof data.jobId === "string" && data.jobId && data.state === "queued");
}

function validImportCancel(data) {
  return Boolean(data && typeof data.jobId === "string" && typeof data.cancelRequested === "boolean");
}

function validImportProgress(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.jobId === "string"
    && event.phase === "item"
    && nonNegativeNumber(event.completed)
    && nonNegativeNumber(event.total)
    && nonNegativeNumber(event.succeeded)
    && nonNegativeNumber(event.failed)
    && event.item
    && nonNegativeNumber(event.item.index)
    && typeof event.item.name === "string"
    && ["running", "succeeded", "failed"].includes(event.item.status)
    && typeof event.item.bookId === "string"
    && validBridgeError(event.error),
  );
}

function validImportFinished(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.jobId === "string"
    && ["completed", "cancelled"].includes(event.state)
    && nonNegativeNumber(event.total)
    && nonNegativeNumber(event.processed)
    && nonNegativeNumber(event.succeeded)
    && nonNegativeNumber(event.failed)
    && typeof event.lastImportedBookId === "string"
    && typeof event.openAfterImportBookId === "string"
    && Array.isArray(event.results)
    && event.results.every((item) => (
      item
      && typeof item.name === "string"
      && ["succeeded", "failed"].includes(item.status)
      && typeof item.bookId === "string"
      && validBridgeError(item.error)
    )),
  );
}

function parseImportEvent(raw, validate, message) {
  const event = parseJsonPayload(raw, message);
  if (!validate(event)) {
    throw new BridgeProtocolError(message, "BRIDGE_INVALID_PAYLOAD");
  }
  return event;
}

function loadQWebChannel(browserWindow, browserDocument) {
  if (typeof browserWindow.QWebChannel === "function") return Promise.resolve();
  if (!browserDocument) {
    return Promise.reject(new BridgeProtocolError("无法加载桌面通信组件。", "QWEBCHANNEL_UNAVAILABLE"));
  }

  const existing = browserDocument.querySelector('script[data-dd-qwebchannel="true"]');
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", () => reject(new BridgeProtocolError("桌面通信组件加载失败。", "QWEBCHANNEL_LOAD_FAILED")), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    const script = browserDocument.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.dataset.ddQwebchannel = "true";
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", () => reject(new BridgeProtocolError("桌面通信组件加载失败。", "QWEBCHANNEL_LOAD_FAILED")), { once: true });
    browserDocument.head.appendChild(script);
  });
}

function createNativeChannel(browserWindow) {
  return new Promise((resolve, reject) => {
    try {
      new browserWindow.QWebChannel(browserWindow.qt.webChannelTransport, (channel) => resolve(channel));
    } catch {
      reject(new BridgeProtocolError("无法连接桌面程序。", "QWEBCHANNEL_CONNECT_FAILED"));
    }
  });
}

function invokeWithResult(nativeBridge, method, args = []) {
  return new Promise((resolve, reject) => {
    if (typeof nativeBridge?.[method] !== "function") {
      reject(new BridgeProtocolError("桌面通信接口不完整。", "BRIDGE_METHOD_MISSING"));
      return;
    }
    try {
      nativeBridge[method](...args, (result) => resolve(result));
    } catch {
      reject(new BridgeProtocolError("桌面通信调用失败。", "BRIDGE_CALL_FAILED"));
    }
  });
}

function nativeImports(nativeBridge) {
  return {
    async selectFiles() {
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "selectImportFiles"),
        validImportSelection,
      );
    },
    async startFileImport(input) {
      if (
        !input
        || typeof input.selectionId !== "string"
        || typeof input.confirmLargeFiles !== "boolean"
        || !DUPLICATE_MODES.has(input.duplicateMode)
      ) {
        throw new BridgeProtocolError("文件导入参数无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "startFileImport", [JSON.stringify(input)]),
        validImportStart,
      );
    },
    async startPasteImport(input) {
      if (!input || typeof input.title !== "string" || typeof input.text !== "string") {
        throw new BridgeProtocolError("粘贴文本参数无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "startPasteImport", [JSON.stringify(input)]),
        validImportStart,
      );
    },
    async cancelImport(jobId) {
      if (typeof jobId !== "string" || !jobId) {
        throw new BridgeProtocolError("导入任务编号无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "cancelImport", [jobId]),
        validImportCancel,
      );
    },
  };
}

function nativeControls(nativeBridge) {
  return {
    minimizeWindow: () => nativeBridge.minimizeWindow(),
    toggleMaximizeWindow: () => nativeBridge.toggleMaximizeWindow(),
    closeWindow: () => nativeBridge.closeWindow(),
    startWindowMove: () => nativeBridge.startWindowMove(),
    startWindowResize: (edge) => nativeBridge.startWindowResize(edge),
  };
}

function createNativeConnection(nativeBridge, initialState) {
  const subscriptions = [];
  const bridgeErrorCallbacks = new Set();
  const reportProtocolError = (error) => {
    const payload = JSON.stringify({
      schemaVersion: SCHEMA_VERSION,
      code: error.code || "BRIDGE_PROTOCOL_ERROR",
      message: error.message || "桌面通信事件无效。",
      retryable: false,
    });
    bridgeErrorCallbacks.forEach((callback) => callback(payload));
  };
  return {
    mode: "native",
    initialState,
    controls: nativeControls(nativeBridge),
    imports: nativeImports(nativeBridge),
    onBridgeError(callback) {
      bridgeErrorCallbacks.add(callback);
      signalSubscription(nativeBridge.bridgeError, callback, subscriptions);
      subscriptions.push(() => bridgeErrorCallbacks.delete(callback));
    },
    onWindowStateChanged(callback) {
      signalSubscription(nativeBridge.windowStateChanged, callback, subscriptions);
    },
    onImportProgress(callback) {
      signalSubscription(nativeBridge.importProgress, (raw) => {
        try {
          callback(parseImportEvent(raw, validImportProgress, "导入进度数据无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onImportFinished(callback) {
      signalSubscription(nativeBridge.importFinished, (raw) => {
        try {
          callback(parseImportEvent(raw, validImportFinished, "导入结果数据无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    dispose() {
      subscriptions.splice(0).forEach((disconnect) => disconnect());
    },
  };
}

function signalSubscription(signal, callback, subscriptions) {
  if (!signal || typeof signal.connect !== "function") return;
  signal.connect(callback);
  subscriptions.push(() => {
    if (typeof signal.disconnect === "function") signal.disconnect(callback);
  });
}

function createDemoConnection() {
  const initialState = createDemoInitialState();
  const progressCallbacks = new Set();
  const finishedCallbacks = new Set();
  const jobs = new Map();
  let jobSequence = 0;

  const emit = (callbacks, payload) => callbacks.forEach((callback) => callback(payload));
  const response = (data) => ({ schemaVersion: SCHEMA_VERSION, ok: true, data, error: null });
  const addDemoBook = (name, format, title = "") => {
    const id = `demo-import-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const cleanTitle = title.trim() || name.replace(/\.[^.]+$/, "") || "粘贴文本";
    const book = {
      id,
      title: cleanTitle,
      author: "",
      format: format.toUpperCase(),
      progressPercent: 0,
      chapterIndex: 0,
      chapterCount: 1,
      currentChapterTitle: "尚未开始阅读",
      lastReadAt: Date.now() / 1000,
      totalChars: 0,
      coverUrl: "covers/library.png",
    };
    initialState.data.library.books = [book, ...initialState.data.library.books];
    initialState.data.library.total = initialState.data.library.books.length;
    return book;
  };
  const startJob = (items) => {
    const jobId = `demo-job-${++jobSequence}`;
    const job = { cancelled: false, timer: null };
    jobs.set(jobId, job);
    let completed = 0;
    let succeeded = 0;
    let failed = 0;
    const results = [];

    const finish = (state = "completed") => {
      const successful = results.filter((item) => item.status === "succeeded");
      const lastImportedBookId = successful.at(-1)?.bookId || "";
      emit(finishedCallbacks, {
        schemaVersion: SCHEMA_VERSION,
        jobId,
        state,
        total: items.length,
        processed: completed,
        succeeded,
        failed,
        lastImportedBookId,
        openAfterImportBookId: lastImportedBookId,
        results,
      });
      jobs.delete(jobId);
    };

    const processNext = () => {
      if (job.cancelled) {
        finish("cancelled");
        return;
      }
      const item = items[completed];
      if (!item) {
        finish();
        return;
      }
      let result;
      if (item.error) {
        failed += 1;
        result = { name: item.name, status: "failed", bookId: "", error: item.error };
      } else {
        const book = addDemoBook(item.name, item.format, item.title);
        succeeded += 1;
        result = { name: item.name, status: "succeeded", bookId: book.id, error: null };
      }
      completed += 1;
      results.push(result);
      emit(progressCallbacks, {
        schemaVersion: SCHEMA_VERSION,
        jobId,
        phase: "item",
        completed,
        total: items.length,
        succeeded,
        failed,
        item: {
          index: completed - 1,
          name: item.name,
          status: result.status,
          bookId: result.bookId,
        },
        error: result.error,
      });
      job.timer = setTimeout(processNext, 120);
    };

    job.timer = setTimeout(processNext, 80);
    return response({ jobId, state: "queued" });
  };

  return {
    mode: "demo",
    initialState,
    controls: NOOP_CONTROLS,
    imports: {
      async selectFiles() {
        const items = [
          { itemId: "demo-new", name: "演示新书.txt", format: "TXT", sizeBytes: 2048, supported: true, large: false, duplicate: { exists: false, bookId: "", title: "" } },
          { itemId: "demo-duplicate", name: "财富自由之路.epub", format: "EPUB", sizeBytes: 4096, supported: true, large: false, duplicate: { exists: true, bookId: "demo-3", title: "财富自由之路" } },
          { itemId: "demo-large", name: "长篇演示.txt", format: "TXT", sizeBytes: 30 * 1024 * 1024, supported: true, large: true, duplicate: { exists: false, bookId: "", title: "" } },
        ];
        return response({ cancelled: false, selectionId: "demo-selection", total: items.length, duplicateCount: 1, largeFileCount: 1, items });
      },
      async startFileImport(input) {
        if (!input?.confirmLargeFiles) {
          throw new BridgeProtocolError("请先确认导入大文件。", "LARGE_FILE_CONFIRMATION_REQUIRED");
        }
        const duplicateError = input.duplicateMode === "cancel"
          ? { code: "DUPLICATE_SKIPPED", message: "已跳过书架中的重复内容。", retryable: false }
          : null;
        return startJob([
          { name: "演示新书.txt", format: "TXT" },
          { name: "财富自由之路.epub", format: "EPUB", error: duplicateError },
          { name: "长篇演示.txt", format: "TXT" },
        ]);
      },
      async startPasteImport(input) {
        const text = input?.text?.trim();
        if (!text) {
          throw new BridgeProtocolError("正文不能为空，请粘贴要朗读的内容。", "PASTE_TEXT_EMPTY");
        }
        const title = input.title?.trim() || text.split(/\r?\n/).find((line) => line.trim())?.trim().slice(0, 40) || "粘贴文本";
        return startJob([{ name: `${title}.txt`, format: "TXT", title }]);
      },
      async cancelImport(jobId) {
        const job = jobs.get(jobId);
        if (job) job.cancelled = true;
        return response({ jobId, cancelRequested: Boolean(job) });
      },
    },
    onBridgeError() {},
    onWindowStateChanged() {},
    onImportProgress(callback) { progressCallbacks.add(callback); },
    onImportFinished(callback) { finishedCallbacks.add(callback); },
    dispose() {
      jobs.forEach((job) => clearTimeout(job.timer));
      jobs.clear();
      progressCallbacks.clear();
      finishedCallbacks.clear();
    },
  };
}

export async function connectBridge(environment = {}) {
  const browserWindow = environment.window ?? (typeof window === "undefined" ? undefined : window);
  const browserDocument = environment.document ?? (typeof document === "undefined" ? undefined : document);

  if (!browserWindow?.qt?.webChannelTransport) {
    return createDemoConnection();
  }

  await loadQWebChannel(browserWindow, browserDocument);
  const channel = await createNativeChannel(browserWindow);
  const nativeBridge = channel.objects?.ddBridge;
  if (!nativeBridge) {
    throw new BridgeProtocolError("桌面通信对象不存在。", "BRIDGE_OBJECT_MISSING");
  }

  try {
    const initialState = parseInitialState(await invokeWithResult(nativeBridge, "getInitialState"));
    return createNativeConnection(nativeBridge, initialState);
  } catch (error) {
    if (error instanceof BridgeProtocolError) {
      error.connection = createNativeConnection(nativeBridge, {
        schemaVersion: SCHEMA_VERSION,
        ok: false,
        data: error.initialData,
        error: { code: error.code, message: error.message, retryable: false },
      });
    }
    throw error;
  }
}
