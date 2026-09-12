import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeProtocolError,
  SCHEMA_VERSION,
  connectBridge,
  createDemoInitialState,
} from "../src/bridge.js";


function signal() {
  const callbacks = new Set();
  return {
    connect(callback) { callbacks.add(callback); },
    disconnect(callback) { callbacks.delete(callback); },
    emit(payload) { callbacks.forEach((callback) => callback(payload)); },
    get size() { return callbacks.size; },
  };
}

function envelope(data, ok = true, error = null) {
  return { schemaVersion: SCHEMA_VERSION, ok, data, error };
}

function stage2State() {
  const response = createDemoInitialState();
  response.data.library = { books: [], total: 0 };
  response.data.capabilities = {
    fileImport: true,
    pasteImport: true,
    webImport: false,
    audioImport: false,
    reader: false,
    tts: false,
    floatingReader: false,
  };
  return response;
}

function cancelledSelection() {
  return envelope({
    cancelled: true,
    selectionId: "",
    total: 0,
    duplicateCount: 0,
    largeFileCount: 0,
    items: [],
  });
}

function selectedTxt() {
  return envelope({
    cancelled: false,
    selectionId: "selection-1",
    total: 1,
    duplicateCount: 0,
    largeFileCount: 0,
    items: [{
      itemId: "item-1",
      name: "阶段2测试.txt",
      format: "TXT",
      sizeBytes: 31,
      supported: true,
      large: false,
      duplicate: { exists: false, bookId: "", title: "" },
    }],
  });
}

function nativeEnvironment(overrides = {}) {
  const calls = [];
  const nativeBridge = {
    bridgeError: signal(),
    windowStateChanged: signal(),
    importProgress: signal(),
    importFinished: signal(),
    getInitialState(callback) { callback(JSON.stringify(stage2State())); },
    minimizeWindow() {},
    toggleMaximizeWindow() {},
    closeWindow() {},
    startWindowMove() {},
    startWindowResize() {},
    selectImportFiles(callback) {
      calls.push(["selectImportFiles"]);
      callback(JSON.stringify(selectedTxt()));
    },
    startFileImport(input, callback) {
      calls.push(["startFileImport", input]);
      callback(JSON.stringify(envelope({ jobId: "job-file", state: "queued" })));
    },
    startPasteImport(input, callback) {
      calls.push(["startPasteImport", input]);
      callback(JSON.stringify(envelope({ jobId: "job-paste", state: "queued" })));
    },
    cancelImport(jobId, callback) {
      calls.push(["cancelImport", jobId]);
      callback(JSON.stringify(envelope({ jobId, cancelRequested: true })));
    },
    ...overrides,
  };
  const browserWindow = {
    qt: { webChannelTransport: {} },
    QWebChannel: class {
      constructor(_transport, ready) { ready({ objects: { ddBridge: nativeBridge } }); }
    },
  };
  return { browserWindow, nativeBridge, calls };
}

async function connectionFor(env = nativeEnvironment()) {
  return { connection: await connectBridge({ window: env.browserWindow, document: null }), env };
}

function requireImports(connection) {
  assert.ok(connection.imports, "Stage-2 connection.imports is missing");
  return connection.imports;
}

function requireImportSubscriptions(connection) {
  assert.equal(typeof connection.onImportProgress, "function", "onImportProgress is missing");
  assert.equal(typeof connection.onImportFinished, "function", "onImportFinished is missing");
}

test("stage-2 capabilities expose imports but keep reader and later phases disabled", async () => {
  const { connection } = await connectionFor();
  assert.deepEqual(connection.initialState.data.capabilities, {
    fileImport: true,
    pasteImport: true,
    webImport: false,
    audioImport: false,
    reader: false,
    tts: false,
    floatingReader: false,
  });
  assert.equal(typeof connection.imports?.selectFiles, "function");
  assert.equal(typeof connection.imports?.startFileImport, "function");
  assert.equal(typeof connection.imports?.startPasteImport, "function");
  assert.equal(typeof connection.imports?.cancelImport, "function");
});

test("native import controls validate responses and delegate frozen request shapes", async () => {
  const { connection, env } = await connectionFor();
  const imports = requireImports(connection);
  const selection = await imports.selectFiles();
  const fileStart = await imports.startFileImport({
    selectionId: selection.data.selectionId,
    confirmLargeFiles: true,
    duplicateMode: "cancel",
  });
  const pasteStart = await imports.startPasteImport({
    title: "标题",
    text: "真实正文。",
  });
  const cancel = await imports.cancelImport(fileStart.data.jobId);

  assert.equal(selection.ok, true);
  assert.equal(selection.data.items[0].name, "阶段2测试.txt");
  assert.equal(JSON.stringify(selection).includes("C:\\"), false);
  assert.equal(Object.hasOwn(selection.data.items[0], "path"), false);
  assert.equal(fileStart.data.jobId, "job-file");
  assert.equal(pasteStart.data.jobId, "job-paste");
  assert.equal(cancel.data.cancelRequested, true);
  assert.deepEqual(env.calls, [
    ["selectImportFiles"],
    ["startFileImport", { selectionId: "selection-1", confirmLargeFiles: true, duplicateMode: "cancel" }],
    ["startPasteImport", { title: "标题", text: "真实正文。" }],
    ["cancelImport", "job-file"],
  ]);
});

test("selection cancellation remains a successful zero-item result", async () => {
  const env = nativeEnvironment({
    selectImportFiles(callback) { callback(JSON.stringify(cancelledSelection())); },
  });
  const { connection } = await connectionFor(env);
  const response = await requireImports(connection).selectFiles();
  assert.deepEqual(response, cancelledSelection());
});

test("progress and partial-failure events are parsed, preserve open intent, and never enable reader", async () => {
  const { connection, env } = await connectionFor();
  const progress = [];
  const finished = [];
  requireImportSubscriptions(connection);
  connection.onImportProgress((event) => progress.push(event));
  connection.onImportFinished((event) => finished.push(event));

  env.nativeBridge.importProgress.emit(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    jobId: "job-file",
    phase: "item",
    completed: 1,
    total: 2,
    succeeded: 1,
    failed: 0,
    item: { index: 0, name: "成功.txt", status: "succeeded", bookId: "book-ok" },
    error: null,
  }));
  env.nativeBridge.importFinished.emit(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    jobId: "job-file",
    state: "completed",
    total: 2,
    processed: 2,
    succeeded: 1,
    failed: 1,
    lastImportedBookId: "book-ok",
    openAfterImportBookId: "book-ok",
    results: [
      { name: "成功.txt", status: "succeeded", bookId: "book-ok", error: null },
      {
        name: "损坏.epub",
        status: "failed",
        bookId: "",
        error: { code: "IMPORT_PARSE_FAILED", message: "文件无法解析", retryable: false },
      },
    ],
  }));

  assert.equal(progress.length, 1);
  assert.equal(progress[0].item.bookId, "book-ok");
  assert.equal(finished.length, 1);
  assert.equal(finished[0].openAfterImportBookId, "book-ok");
  assert.equal(finished[0].succeeded, 1);
  assert.equal(finished[0].failed, 1);
  assert.equal(connection.initialState.data.capabilities.reader, false);
  assert.equal(Object.hasOwn(finished[0], "content"), false);
  assert.equal(Object.hasOwn(finished[0], "chapters"), false);
});

test("cancelled job event is observable without fabricating an open target", async () => {
  const { connection, env } = await connectionFor();
  const finished = [];
  requireImportSubscriptions(connection);
  connection.onImportFinished((event) => finished.push(event));
  env.nativeBridge.importFinished.emit(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    jobId: "job-cancelled",
    state: "cancelled",
    total: 2,
    processed: 0,
    succeeded: 0,
    failed: 0,
    lastImportedBookId: "",
    openAfterImportBookId: "",
    results: [],
  }));
  assert.equal(finished.length, 1);
  assert.equal(finished[0].state, "cancelled");
  assert.equal(finished[0].openAfterImportBookId, "");
});

test("malformed import response is rejected before application code receives it", async () => {
  const env = nativeEnvironment({
    selectImportFiles(callback) {
      callback(JSON.stringify({ ...selectedTxt(), schemaVersion: 2 }));
    },
  });
  const { connection } = await connectionFor(env);
  const imports = requireImports(connection);
  await assert.rejects(
    imports.selectFiles(),
    (error) => error instanceof BridgeProtocolError && error.code === "SCHEMA_MISMATCH",
  );
});

test("malformed import events fail closed and are not delivered to subscribers", async () => {
  const { connection, env } = await connectionFor();
  const progress = [];
  const finished = [];
  requireImportSubscriptions(connection);
  connection.onImportProgress((event) => progress.push(event));
  connection.onImportFinished((event) => finished.push(event));

  env.nativeBridge.importProgress.emit('{"schemaVersion":1,"jobId":"job","phase":"wrong"}');
  env.nativeBridge.importFinished.emit('{"schemaVersion":2,"jobId":"job","state":"completed"}');

  assert.deepEqual(progress, []);
  assert.deepEqual(finished, []);
});

test("disposing the connection removes both import subscriptions", async () => {
  const { connection, env } = await connectionFor();
  requireImportSubscriptions(connection);
  connection.onImportProgress(() => {});
  connection.onImportFinished(() => {});
  assert.equal(env.nativeBridge.importProgress.size, 1);
  assert.equal(env.nativeBridge.importFinished.size, 1);
  connection.dispose();
  assert.equal(env.nativeBridge.importProgress.size, 0);
  assert.equal(env.nativeBridge.importFinished.size, 0);
});

test("browser demo import provider stays isolated from the native persistence path", async () => {
  const native = nativeEnvironment();
  const nativeConnection = await connectBridge({ window: native.browserWindow, document: null });
  const demoConnection = await connectBridge({ window: {}, document: null });

  assert.equal(nativeConnection.mode, "native");
  assert.equal(demoConnection.mode, "demo");
  const demoImports = requireImports(demoConnection);
  assert.notEqual(demoImports, requireImports(nativeConnection));

  const response = await demoImports.startPasteImport({ title: "预览", text: "正文" });
  assert.equal(response.schemaVersion, SCHEMA_VERSION);
  assert.equal(typeof response.ok, "boolean");
  assert.deepEqual(native.calls, []);
  assert.deepEqual(nativeConnection.initialState.data.library, { books: [], total: 0 });
});
