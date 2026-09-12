import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeProtocolError,
  SCHEMA_VERSION,
  connectBridge,
  createDemoInitialState,
  parseInitialState,
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

function readerFixture() {
  const position = { chapterIndex: 0, charOffset: 0, progressPercent: 0 };
  const playback = { status: "idle", position, sentence: null, requestedBackend: "sapi", activeBackend: null, fallbackActive: false };
  const window = { sessionId: "reader-session", bookId: "book-1", chapterIndex: 0, chapterTitle: "第一章", chapterCharCount: 4, anchorOffset: 0, windowStartOffset: 0, windowEndOffset: 4, hasBefore: false, hasAfter: false, blocks: [{ id: "0:0:4", startOffset: 0, endOffset: 4, text: "真实正文", startsParagraph: true, endsParagraph: true }] };
  const settings = { fontFamily: "微软雅黑", fontSize: 17, lineSpacing: 1.5, paragraphMode: 1, firstLineIndent: true, ttsRate: 200, ttsVoiceId: "voice-1", volume: 100, sentenceGapSeconds: 0.1 };
  return { sessionId: "reader-session", book: { id: "book-1", title: "真实书籍", author: "作者", format: "TXT", totalChars: 4, chapters: [{ index: 0, title: "第一章", charCount: 4 }] }, position, window, settings, playback, bookmarkCount: 0 };
}

function nativeEnvironment(response) {
  const calls = [];
  const ok = (data) => JSON.stringify({ schemaVersion: SCHEMA_VERSION, ok: true, data, error: null });
  const nativeBridge = {
    bridgeError: signal(),
    windowStateChanged: signal(),
    importProgress: signal(),
    importFinished: signal(),
    readerOpened: signal(),
    readerSearchFinished: signal(),
    readerPlaybackChanged: signal(),
    getInitialState(callback) { callback(JSON.stringify(response)); },
    selectImportFiles(callback) {
      calls.push(["selectImportFiles"]);
      callback(ok({
        cancelled: false,
        selectionId: "selection-1",
        total: 1,
        duplicateCount: 0,
        largeFileCount: 0,
        items: [{
          itemId: "item-1",
          name: "novel.txt",
          format: "TXT",
          sizeBytes: 12,
          supported: true,
          large: false,
          duplicate: { exists: false, bookId: "", title: "" },
        }],
      }));
    },
    startFileImport(input, callback) {
      calls.push(["startFileImport", input]);
      callback(ok({ jobId: "job-file", state: "queued" }));
    },
    startPasteImport(input, callback) {
      calls.push(["startPasteImport", input]);
      callback(ok({ jobId: "job-paste", state: "queued" }));
    },
    cancelImport(jobId, callback) {
      calls.push(["cancelImport", jobId]);
      callback(ok({ jobId, cancelRequested: true }));
    },
    openReaderBook(bookId, callback) { calls.push(["openReaderBook", bookId]); callback(ok({ requestId: "reader-request", bookId, state: "loading" })); },
    getReaderWindow(input, callback) { calls.push(["getReaderWindow", input]); callback(ok(readerFixture().window)); },
    navigateReader(input, callback) { calls.push(["navigateReader", input]); const fixture = readerFixture(); callback(ok({ position: fixture.position, window: fixture.window, playback: fixture.playback })); },
    updateReaderPosition(input, callback) { calls.push(["updateReaderPosition", input]); callback(ok({ updated: true, position: readerFixture().position })); },
    searchReader(input, callback) { calls.push(["searchReader", input]); callback(ok({ requestId: "search-request", state: "searching" })); },
    listReaderBookmarks(input, callback) { calls.push(["listReaderBookmarks", input]); callback(ok({ total: 0, nextCursor: "", items: [] })); },
    addReaderBookmark(input, callback) { calls.push(["addReaderBookmark", input]); callback(ok({ id: "bookmark-1", chapterIndex: 0, chapterTitle: "第一章", startOffset: 0, endOffset: 2, text: "真实", note: "重点", createdAt: 1 })); },
    removeReaderBookmark(input, callback) { calls.push(["removeReaderBookmark", input]); callback(ok({ bookmarkId: "bookmark-1", removed: true })); },
    controlReaderPlayback(input, callback) { calls.push(["controlReaderPlayback", input]); callback(ok({ commandId: "command-1", accepted: true })); },
    updateReaderSettings(input, callback) { calls.push(["updateReaderSettings", input]); callback(ok({ ...readerFixture().settings, ...JSON.parse(input).patch })); },
    minimizeWindow() { calls.push(["minimizeWindow"]); },
    toggleMaximizeWindow() { calls.push(["toggleMaximizeWindow"]); },
    closeWindow() { calls.push(["closeWindow"]); },
    startWindowMove() { calls.push(["startWindowMove"]); },
    startWindowResize(edge) { calls.push(["startWindowResize", edge]); },
  };
  const browserWindow = {
    qt: { webChannelTransport: {} },
    QWebChannel: class {
      constructor(_transport, ready) { ready({ objects: { ddBridge: nativeBridge } }); }
    },
  };
  return { browserWindow, nativeBridge, calls };
}

test("browser preview uses the versioned demo provider", async () => {
  const connection = await connectBridge({ window: {}, document: null });
  assert.equal(connection.mode, "demo");
  assert.equal(connection.initialState.schemaVersion, SCHEMA_VERSION);
  assert.equal(connection.initialState.data.library.total, 4);
});

test("demo paste import stays isolated and emits the frozen event contract", async () => {
  const connection = await connectBridge({ window: {}, document: null });
  const finished = new Promise((resolve) => connection.onImportFinished(resolve));
  const start = await connection.imports.startPasteImport({ title: "浏览器演示导入", text: "真实提交内容" });
  const event = await finished;

  assert.equal(start.data.state, "queued");
  assert.equal(event.jobId, start.data.jobId);
  assert.equal(event.succeeded, 1);
  assert.ok(event.openAfterImportBookId.startsWith("demo-import-"));
  assert.equal(connection.initialState.data.library.books[0].title, "浏览器演示导入");
  assert.equal(connection.initialState.data.library.total, 5);
  connection.dispose();
});

test("native provider validates schema and delegates window controls", async () => {
  const response = createDemoInitialState();
  response.data.library = { books: [], total: 0 };
  const env = nativeEnvironment(response);

  const connection = await connectBridge({ window: env.browserWindow, document: null });
  connection.controls.minimizeWindow();
  connection.controls.toggleMaximizeWindow();
  connection.controls.startWindowMove();
  connection.controls.startWindowResize("topLeft");
  connection.controls.closeWindow();

  assert.equal(connection.mode, "native");
  assert.deepEqual(env.calls, [
    ["minimizeWindow"],
    ["toggleMaximizeWindow"],
    ["startWindowMove"],
    ["startWindowResize", "topLeft"],
    ["closeWindow"],
  ]);
});

test("native import controls use the frozen slot names and serialize inputs", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });

  const selection = await connection.imports.selectFiles();
  const fileStart = await connection.imports.startFileImport({
    selectionId: selection.data.selectionId,
    confirmLargeFiles: true,
    duplicateMode: "overwrite",
  });
  const pasteStart = await connection.imports.startPasteImport({ title: "标题", text: "正文" });
  const cancelled = await connection.imports.cancelImport(fileStart.data.jobId);

  assert.equal(selection.data.items[0].name, "novel.txt");
  assert.equal(pasteStart.data.jobId, "job-paste");
  assert.equal(cancelled.data.cancelRequested, true);
  assert.deepEqual(env.calls, [
    ["selectImportFiles"],
    ["startFileImport", JSON.stringify({ selectionId: "selection-1", confirmLargeFiles: true, duplicateMode: "overwrite" })],
    ["startPasteImport", JSON.stringify({ title: "标题", text: "正文" })],
    ["cancelImport", "job-file"],
  ]);
});

test("native reader controls use the frozen slots and serialize complex inputs", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const sessionId = "reader-session";

  await connection.reader.openBook("book-1");
  await connection.reader.getWindow({ sessionId, chapterIndex: 0, anchorOffset: 0 });
  await connection.reader.navigate({ sessionId, target: { kind: "percent", percent: 42 } });
  await connection.reader.updatePosition({ sessionId, chapterIndex: 0, charOffset: 2 });
  await connection.reader.search({ sessionId, query: "真实", cursor: "" });
  await connection.reader.listBookmarks({ sessionId, cursor: "" });
  await connection.reader.addBookmark({ sessionId, chapterIndex: 0, startOffset: 0, endOffset: 2, note: "重点" });
  await connection.reader.removeBookmark({ sessionId, bookmarkId: "bookmark-1" });
  await connection.reader.controlPlayback({ sessionId, command: "play" });
  await connection.reader.updateSettings({ sessionId, patch: { fontSize: 22, paragraphMode: 2 } });

  assert.deepEqual(env.calls, [
    ["openReaderBook", "book-1"],
    ["getReaderWindow", JSON.stringify({ sessionId, chapterIndex: 0, anchorOffset: 0 })],
    ["navigateReader", JSON.stringify({ sessionId, target: { kind: "percent", percent: 42 } })],
    ["updateReaderPosition", JSON.stringify({ sessionId, chapterIndex: 0, charOffset: 2 })],
    ["searchReader", JSON.stringify({ sessionId, query: "真实", cursor: "" })],
    ["listReaderBookmarks", JSON.stringify({ sessionId, cursor: "" })],
    ["addReaderBookmark", JSON.stringify({ sessionId, chapterIndex: 0, startOffset: 0, endOffset: 2, note: "重点" })],
    ["removeReaderBookmark", JSON.stringify({ sessionId, bookmarkId: "bookmark-1" })],
    ["controlReaderPlayback", JSON.stringify({ sessionId, command: "play" })],
    ["updateReaderSettings", JSON.stringify({ sessionId, patch: { fontSize: 22, paragraphMode: 2 } })],
  ]);
});

test("native reader events are parsed, bounded and disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const opened = [];
  const searches = [];
  const playback = [];
  const errors = [];
  connection.onReaderOpened((event) => opened.push(event));
  connection.onReaderSearchFinished((event) => searches.push(event));
  connection.onReaderPlaybackChanged((event) => playback.push(event));
  connection.onBridgeError((raw) => errors.push(JSON.parse(raw)));

  env.nativeBridge.readerOpened.emit(JSON.stringify({ schemaVersion: 1, requestId: "reader-request", bookId: "book-1", ok: true, data: readerFixture(), error: null }));
  env.nativeBridge.readerSearchFinished.emit(JSON.stringify({ schemaVersion: 1, requestId: "search-request", sessionId: "reader-session", ok: true, data: { query: "真实", total: 1, nextCursor: "", results: [{ id: "result-1", chapterIndex: 0, chapterTitle: "第一章", startOffset: 0, endOffset: 2, excerptStartOffset: 0, excerpt: "真实正文" }] }, error: null }));
  env.nativeBridge.readerPlaybackChanged.emit(JSON.stringify({ schemaVersion: 1, sessionId: "reader-session", bookId: "book-1", sequence: 1, commandId: "command-1", reason: "sentenceStart", playback: { ...readerFixture().playback, status: "playing", activeBackend: "sapi", sentence: { chapterIndex: 0, startOffset: 0, endOffset: 2, text: "真实" } }, error: null }));
  const oversized = readerFixture();
  oversized.window.blocks = Array.from({ length: 121 }, (_, index) => ({ id: `0:${index}:${index + 1}`, startOffset: index, endOffset: index + 1, text: "字", startsParagraph: true, endsParagraph: true }));
  env.nativeBridge.readerOpened.emit(JSON.stringify({ schemaVersion: 1, requestId: "oversized", bookId: "book-1", ok: true, data: oversized, error: null }));

  assert.equal(opened.length, 1);
  assert.equal(searches[0].data.results[0].startOffset, 0);
  assert.equal(playback[0].playback.sentence.endOffset, 2);
  assert.equal(errors.at(-1).code, "BRIDGE_INVALID_PAYLOAD");
  connection.dispose();
  assert.equal(env.nativeBridge.readerOpened.size, 0);
  assert.equal(env.nativeBridge.readerSearchFinished.size, 0);
  assert.equal(env.nativeBridge.readerPlaybackChanged.size, 0);
});

test("native import events are parsed and all subscriptions are disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const progress = [];
  const finished = [];
  connection.onImportProgress((event) => progress.push(event));
  connection.onImportFinished((event) => finished.push(event));

  env.nativeBridge.importProgress.emit(JSON.stringify({
    schemaVersion: 1,
    jobId: "job-1",
    phase: "item",
    completed: 1,
    total: 1,
    succeeded: 1,
    failed: 0,
    item: { index: 0, name: "novel.txt", status: "succeeded", bookId: "book-1" },
    error: null,
  }));
  env.nativeBridge.importFinished.emit(JSON.stringify({
    schemaVersion: 1,
    jobId: "job-1",
    state: "completed",
    total: 1,
    processed: 1,
    succeeded: 1,
    failed: 0,
    lastImportedBookId: "book-1",
    openAfterImportBookId: "book-1",
    results: [{ name: "novel.txt", status: "succeeded", bookId: "book-1", error: null }],
  }));

  assert.equal(progress[0].item.bookId, "book-1");
  assert.equal(finished[0].openAfterImportBookId, "book-1");
  assert.equal(env.nativeBridge.importProgress.size, 1);
  assert.equal(env.nativeBridge.importFinished.size, 1);
  connection.dispose();
  assert.equal(env.nativeBridge.importProgress.size, 0);
  assert.equal(env.nativeBridge.importFinished.size, 0);
});

test("malformed import events surface a bridge error without reaching React", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const errors = [];
  const progress = [];
  connection.onBridgeError((payload) => errors.push(JSON.parse(payload)));
  connection.onImportProgress((event) => progress.push(event));

  env.nativeBridge.importProgress.emit('{"schemaVersion":1,"jobId":"broken"}');

  assert.equal(progress.length, 0);
  assert.equal(errors[0].code, "BRIDGE_INVALID_PAYLOAD");
  assert.equal(errors[0].message, "导入进度数据无效。");
});

test("native errors are observable and subscriptions are disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const received = [];
  connection.onBridgeError((payload) => received.push(payload));
  env.nativeBridge.bridgeError.emit('{"message":"failed"}');
  assert.deepEqual(received, ['{"message":"failed"}']);
  assert.equal(env.nativeBridge.bridgeError.size, 1);
  connection.dispose();
  assert.equal(env.nativeBridge.bridgeError.size, 0);
});

test("schema mismatch and backend failure never fall back to demo data", async () => {
  assert.throws(
    () => parseInitialState({ ...createDemoInitialState(), schemaVersion: 2 }),
    (error) => error instanceof BridgeProtocolError && error.code === "SCHEMA_MISMATCH",
  );

  const failed = createDemoInitialState();
  failed.ok = false;
  failed.data.library = { books: [], total: 0 };
  failed.error = { code: "LIBRARY_INVALID", message: "书架损坏", retryable: false };
  const env = nativeEnvironment(failed);
  await assert.rejects(
    connectBridge({ window: env.browserWindow, document: null }),
    (error) => {
      assert.equal(error.code, "LIBRARY_INVALID");
      assert.equal(error.initialData.library.total, 0);
      assert.equal(error.connection.mode, "native");
      error.connection.controls.closeWindow();
      error.connection.controls.startWindowMove();
      assert.deepEqual(env.calls, [["closeWindow"], ["startWindowMove"]]);
      return true;
    },
  );
});

test("incomplete schema v1 data is rejected before React receives it", () => {
  const missingCapabilities = createDemoInitialState();
  delete missingCapabilities.data.capabilities;
  assert.throws(
    () => parseInitialState(missingCapabilities),
    (error) => error.code === "BRIDGE_INVALID_PAYLOAD",
  );

  const invalidBook = createDemoInitialState();
  invalidBook.data.library.books[0].title = null;
  assert.throws(
    () => parseInitialState(invalidBook),
    (error) => error.code === "BRIDGE_INVALID_PAYLOAD",
  );
});
