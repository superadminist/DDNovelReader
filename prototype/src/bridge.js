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
  let payload;
  try {
    payload = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new BridgeProtocolError("桌面通信返回了无法解析的数据。", "BRIDGE_INVALID_JSON");
  }

  if (!payload || payload.schemaVersion !== SCHEMA_VERSION) {
    throw new BridgeProtocolError("桌面程序与界面版本不兼容，请更新后重试。", "SCHEMA_MISMATCH");
  }
  const books = payload?.data?.library?.books;
  const capabilities = payload?.data?.capabilities;
  const validBooks = Array.isArray(books) && books.every((book) => (
    book
    && Object.entries(BOOK_FIELDS).every(([field, type]) => typeof book[field] === type)
    && (book.lastReadAt === null || typeof book.lastReadAt === "number")
  ));
  const validCapabilities = capabilities
    && CAPABILITY_KEYS.every((key) => typeof capabilities[key] === "boolean");
  if (
    typeof payload.ok !== "boolean"
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

function invokeWithResult(nativeBridge, method) {
  return new Promise((resolve, reject) => {
    if (typeof nativeBridge?.[method] !== "function") {
      reject(new BridgeProtocolError("桌面通信接口不完整。", "BRIDGE_METHOD_MISSING"));
      return;
    }
    try {
      nativeBridge[method]((result) => resolve(result));
    } catch {
      reject(new BridgeProtocolError("桌面通信调用失败。", "BRIDGE_CALL_FAILED"));
    }
  });
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
  return {
    mode: "native",
    initialState,
    controls: nativeControls(nativeBridge),
    onBridgeError(callback) {
      signalSubscription(nativeBridge.bridgeError, callback, subscriptions);
    },
    onWindowStateChanged(callback) {
      signalSubscription(nativeBridge.windowStateChanged, callback, subscriptions);
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

export async function connectBridge(environment = {}) {
  const browserWindow = environment.window ?? (typeof window === "undefined" ? undefined : window);
  const browserDocument = environment.document ?? (typeof document === "undefined" ? undefined : document);

  if (!browserWindow?.qt?.webChannelTransport) {
    return {
      mode: "demo",
      initialState: createDemoInitialState(),
      controls: NOOP_CONTROLS,
      onBridgeError() {},
      onWindowStateChanged() {},
      dispose() {},
    };
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
