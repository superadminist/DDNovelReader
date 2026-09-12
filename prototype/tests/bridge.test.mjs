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

function nativeEnvironment(response) {
  const calls = [];
  const nativeBridge = {
    bridgeError: signal(),
    windowStateChanged: signal(),
    getInitialState(callback) { callback(JSON.stringify(response)); },
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
