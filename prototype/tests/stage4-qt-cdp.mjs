import { spawnSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const port = Number(process.env.DD_QA_CDP_PORT);
const hostPid = Number(process.env.DD_QA_HOST_PID);
const bookTitle = process.env.DD_QA_BOOK_TITLE;
const longMarker = process.env.DD_QA_LONG_MARKER;
const screenshotDir = process.env.DD_QA_SCREENSHOT_DIR;
const checkpointPath = process.env.DD_QA_CHECKPOINT;
const phase = process.env.DD_QA_STAGE4_PHASE;
const scaleFactor = Number(process.env.DD_QA_SCALE_FACTOR || "1");
const python = process.env.DD_QA_PYTHON;
const windowProbe = process.env.DD_QA_WINDOW_PROBE;

if (!port || !hostPid || !bookTitle || !longMarker || !screenshotDir || !checkpointPath || !python || !windowProbe) {
  throw new Error("Missing required DD_QA_* environment values");
}
if (!["primary", "restore", "dpi"].includes(phase)) {
  throw new Error(`Unknown DD_QA_STAGE4_PHASE: ${phase}`);
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const quote = (value) => JSON.stringify(value);

async function targets() {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  return response.json();
}

function isAppTarget(target) {
  return target.type === "page" && target.url?.includes("/prototype/dist/client/index.html");
}

async function waitForTarget(predicate, message, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let lastTargets = [];
  while (Date.now() < deadline) {
    try {
      lastTargets = await targets();
      const target = lastTargets.find(predicate);
      if (target?.webSocketDebuggerUrl) return target;
    } catch {
      // The Qt host may still be starting.
    }
    await sleep(100);
  }
  throw new Error(`${message}: ${JSON.stringify(lastTargets.map(({ type, title, url }) => ({ type, title, url })))}`);
}

async function waitForTargetCount(expected, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let count = -1;
  while (Date.now() < deadline) {
    try {
      count = (await targets()).filter(isAppTarget).length;
      if (count === expected) return;
    } catch {
      // Closing a target briefly interrupts /json/list.
    }
    await sleep(100);
  }
  throw new Error(`Expected ${expected} app CDP target(s), saw ${count}`);
}

class CdpClient {
  constructor(url) {
    this.nextId = 0;
    this.pending = new Map();
    this.events = [];
    this.socket = new WebSocket(url);
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (message) => {
      const payload = JSON.parse(message.data);
      if (!payload.id) {
        this.events.push(payload);
        return;
      }
      const pending = this.pending.get(payload.id);
      if (!pending) return;
      this.pending.delete(payload.id);
      if (payload.error) pending.reject(new Error(`${pending.method}: ${payload.error.message}`));
      else pending.resolve(payload.result || {});
    });
  }

  call(method, params = {}, timeoutMs = 10_000) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (this.socket.readyState < WebSocket.CLOSING) this.socket.close();
  }
}

async function attach(target) {
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const refreshed = (await targets()).find((item) => item.id === target.id) || target;
    const client = new CdpClient(refreshed.webSocketDebuggerUrl);
    client.targetId = refreshed.id;
    try {
      await client.connect();
      await client.call("Runtime.enable");
      await client.call("Log.enable");
      await client.call("Page.enable");
      return client;
    } catch (error) {
      lastError = error;
      client.close();
      if (attempt < 2) await sleep(350);
    }
  }
  throw new Error(`Unable to initialize CDP target ${target.id}: ${lastError?.message || "unknown error"}`);
}

async function evaluate(client, expression) {
  const result = await client.call("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
    throw new Error(detail || "Runtime.evaluate failed");
  }
  return result.result?.value;
}

async function waitFor(client, expression, message, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(client, expression)) return;
    await sleep(100);
  }
  throw new Error(message);
}

async function clickLabel(client, labels) {
  const requested = Array.isArray(labels) ? labels : [labels];
  return evaluate(client, `(() => {
    const labels = ${JSON.stringify(requested)};
    const node = [...document.querySelectorAll("button, [role=button], input[aria-label]")]
      .find((item) => labels.includes(item.getAttribute("aria-label")));
    if (!node) return "";
    node.click();
    return node.getAttribute("aria-label") || node.innerText;
  })()`);
}

async function clickText(client, selector, text) {
  return evaluate(client, `(() => {
    const node = [...document.querySelectorAll(${quote(selector)})]
      .find((item) => item.innerText.includes(${quote(text)}));
    if (!node) return false;
    node.click();
    return true;
  })()`);
}

async function capture(client, filename) {
  const result = await client.call("Page.captureScreenshot", { format: "png", fromSurface: true });
  const bytes = Buffer.from(result.data, "base64");
  const path = join(screenshotDir, filename);
  await writeFile(path, bytes);
  return {
    path,
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

function consoleIssues(client) {
  return client.events.filter((event) => (
    event.method === "Runtime.exceptionThrown"
    || (event.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(event.params?.type))
    || (event.method === "Log.entryAdded" && ["error", "warning"].includes(event.params?.entry?.level))
  ));
}

function probe(action = "snapshot", args = []) {
  const result = spawnSync(python, [windowProbe, action, String(hostPid), ...args], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error(`window probe ${action} failed: ${result.stderr || result.stdout}`);
  }
  return JSON.parse(result.stdout);
}

function roleWindow(snapshot, role) {
  const item = snapshot.windows.find((window) => window.role === role);
  if (!item) throw new Error(`Missing ${role} top-level window: ${JSON.stringify(snapshot.windows)}`);
  return item;
}

function fitsMonitor(rect, monitors) {
  return monitors.some(({ work }) => (
    rect.left >= work.left
    && rect.top >= work.top
    && rect.right <= work.right
    && rect.bottom <= work.bottom
  ));
}

async function checkpoint() {
  try {
    return JSON.parse(await readFile(checkpointPath, "utf8"));
  } catch {
    return {};
  }
}

async function saveCheckpoint(patch) {
  await writeFile(checkpointPath, `${JSON.stringify({ ...(await checkpoint()), ...patch }, null, 2)}\n`, "utf8");
}

async function nativeCall(main, method, argument) {
  const argumentsSource = argument === undefined ? "done" : `${quote(argument)}, done`;
  const raw = await evaluate(main, `new Promise((resolve, reject) => {
    const bridge = window.__qaNativeBridge;
    if (!bridge || typeof bridge[${quote(method)}] !== "function") {
      reject(new Error("Missing native slot: " + ${quote(method)}));
      return;
    }
    const done = (value) => resolve(value);
    bridge[${quote(method)}](${argumentsSource});
  })`);
  if (raw === undefined || raw === null || raw === "") return null;
  const response = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (response?.ok === false) throw new Error(`${method}: ${response.error?.code}: ${response.error?.message}`);
  return response;
}

async function floatingState(main) {
  const response = await nativeCall(main, "getFloatingReaderState");
  if (!response?.data) throw new Error("getFloatingReaderState returned no data");
  return response.data;
}

async function waitForFloatingState(main, predicate, message, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let state;
  while (Date.now() < deadline) {
    state = await floatingState(main);
    if (predicate(state)) return state;
    await sleep(100);
  }
  throw new Error(`${message}: ${JSON.stringify(state)}`);
}

async function connectMain() {
  const target = await waitForTarget(
    (item) => isAppTarget(item) && !item.url.includes("surface=floating"),
    "Main Qt WebEngine target did not appear",
  );
  const main = await attach(target);
  await main.call("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      window.__qaPlaybackEvents = [];
      window.__qaFloatingEvents = [];
      window.__qaReaderEvents = [];
      (() => {
        let current = window.QWebChannel;
        const wrap = (Original) => {
          if (!Original || Original.__ddQaStage4Wrapped) return Original;
          function Wrapped(transport, callback, converters) {
            return new Original(transport, (channel) => {
              const bridge = channel.objects.ddBridge;
              window.__qaNativeBridge = bridge;
              if (!window.__qaStage4SignalsConnected) {
                window.__qaStage4SignalsConnected = true;
                bridge.readerPlaybackChanged.connect((raw) => {
                  try { window.__qaPlaybackEvents.push(JSON.parse(raw)); } catch {}
                });
                bridge.readerOpened.connect((raw) => {
                  try { window.__qaReaderEvents.push(JSON.parse(raw)); } catch {}
                });
                if (bridge.floatingReaderChanged?.connect) {
                  bridge.floatingReaderChanged.connect((raw) => {
                    try { window.__qaFloatingEvents.push(JSON.parse(raw)); } catch {}
                  });
                }
              }
              callback(channel);
            }, converters);
          }
          Wrapped.__ddQaStage4Wrapped = true;
          return Wrapped;
        };
        Object.defineProperty(window, "QWebChannel", {
          configurable: true,
          get() { return current; },
          set(value) { current = wrap(value); },
        });
        if (current) current = wrap(current);
      })();
    `,
  });
  await main.call("Page.reload", { ignoreCache: true });
  await waitFor(
    main,
    `document.readyState === "complete" && document.body.innerText.includes(${quote(bookTitle)}) && Boolean(window.__qaNativeBridge)`,
    "Real library or QWebChannel bridge did not become ready",
    15_000,
  );
  const initial = await nativeCall(main, "getInitialState");
  if (initial?.data?.capabilities?.floatingReader !== true) {
    throw new Error("Stage-4 implementation unavailable: capabilities.floatingReader is not true");
  }
  return main;
}

async function openReader(main) {
  // Give the persisted auto-open intent time to move the library into its
  // opening state before deciding whether a manual card click is needed.
  await sleep(800);
  const readerInProgress = await evaluate(main, "Boolean(document.querySelector('.reader-page'))");
  if (!readerInProgress && !await clickText(main, ".book-card", bookTitle)) throw new Error("Fixture book card was not clickable");
  await waitFor(main, "Boolean(document.querySelector('.native-reader'))", "Native reader did not open");
  await waitFor(main, "window.__qaReaderEvents.length > 0", "readerOpened event was not observed");
  const opened = await evaluate(main, "window.__qaReaderEvents.at(-1)");
  if (!opened?.data?.sessionId || !opened?.data?.book?.id) {
    throw new Error(`readerOpened did not identify the active session: ${JSON.stringify(opened)}`);
  }
  return opened.data;
}

async function showFloating(main) {
  const used = await clickLabel(main, "打开悬浮朗读");
  if (!used) throw new Error("Native reader has no 打开悬浮朗读 control");
  const target = await waitForTarget(
    (item) => isAppTarget(item) && item.url.includes("surface=floating"),
    "Independent floating-reader CDP target did not appear",
  );
  await waitForTargetCount(2);
  const floating = await attach(target);
  await waitFor(
    floating,
    `Boolean(document.querySelector('[data-testid="native-floating-reader"], .native-floating-surface'))`,
    "Native floating-reader surface did not render",
    15_000,
  );
  return floating;
}

async function assertSurfaceFits(floating) {
  const layout = await evaluate(floating, `(() => {
    const root = document.querySelector('[data-testid="native-floating-reader"], .native-floating-surface');
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      if (getComputedStyle(node).visibility === 'hidden') return null;
      const value = node.getBoundingClientRect();
      return { left: value.left, top: value.top, right: value.right, bottom: value.bottom, width: value.width, height: value.height };
    };
    const overlaps = (first, second) => Boolean(first && second && first.left < second.right - 1 && first.right > second.left + 1 && first.top < second.bottom - 1 && first.bottom > second.top + 1);
    const regions = { header: rect('.floating-dragbar'), content: rect('.floating-content'), error: rect('.floating-error'), footer: rect('.floating-controls'), current: rect('[data-sentence-role="current"]') };
    const controls = [...document.querySelectorAll("button, input")].filter((node) => getComputedStyle(node).visibility !== 'hidden').map((node) => {
      const rect = node.getBoundingClientRect();
      return { label: node.getAttribute("aria-label") || node.innerText, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    });
    return {
      innerWidth,
      innerHeight,
      devicePixelRatio,
      screenAvailWidth: screen.availWidth,
      screenAvailHeight: screen.availHeight,
      documentWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
      root: root ? { width: root.scrollWidth, height: root.scrollHeight } : null,
      contextMode: root?.dataset.contextMode || '',
      contentScrollable: document.querySelector('.floating-content')?.scrollHeight > document.querySelector('.floating-content')?.clientHeight + 1,
      regionOverlap: overlaps(regions.header, regions.content) || overlaps(regions.content, regions.error) || overlaps(regions.content, regions.footer) || overlaps(regions.error, regions.footer),
      regions,
      clippedControls: controls.filter((rect) => rect.left < -1 || rect.top < -1 || rect.right > innerWidth + 1 || rect.bottom > innerHeight + 1),
    };
  })()`);
  if (!layout.root || layout.documentWidth > layout.innerWidth + 1 || layout.documentHeight > layout.innerHeight + 1) {
    throw new Error(`Floating layout overflow: ${JSON.stringify(layout)}`);
  }
  if (layout.clippedControls.length) throw new Error(`Floating controls clipped: ${JSON.stringify(layout.clippedControls)}`);
  if (layout.regionOverlap) throw new Error(`Floating regions overlap: ${JSON.stringify(layout.regions)}`);
  return layout;
}

async function closeMain(main) {
  const canClose = await evaluate(main, "typeof window.__qaNativeBridge?.closeWindow === 'function'");
  if (!canClose) throw new Error("Missing closeWindow slot");
  main.socket.send(JSON.stringify({
    id: ++main.nextId,
    method: "Runtime.evaluate",
    params: { expression: "window.__qaNativeBridge.closeWindow()" },
  }));
  await sleep(200);
  main.close();
}

async function openAndBind() {
  const main = await connectMain();
  const opened = await openReader(main);
  const floating = await showFloating(main);
  const state = await floatingState(main);
  if (state.sessionId !== opened.sessionId || state.bookId !== opened.book.id) {
    throw new Error(`Floating session mismatch: ${JSON.stringify({ opened: { sessionId: opened.sessionId, bookId: opened.book.id }, state })}`);
  }
  return { main, floating, opened, state };
}

async function primaryScenario() {
  let { main, floating, opened, state } = await openAndBind();
  const evidence = {};
  const initialWindowSnapshot = probe();
  if (initialWindowSnapshot.windows.filter((item) => ["main", "floating"].includes(item.role)).length !== 2) {
    throw new Error(`Expected two real top-level Qt windows: ${JSON.stringify(initialWindowSnapshot)}`);
  }
  const initialFloatingWindow = roleWindow(initialWindowSnapshot, "floating");
  const initialMainWindow = roleWindow(initialWindowSnapshot, "main");
  if (!initialFloatingWindow.visible || initialFloatingWindow.minimized) throw new Error("Floating top-level window is not visible");
  if (!initialFloatingWindow.toolWindow || initialMainWindow.toolWindow) throw new Error("Floating window taskbar/tool-window flags are incorrect");
  if (initialMainWindow.layeredWindow || !initialFloatingWindow.layeredWindow) {
    throw new Error(`Main and floating composition paths are not isolated: ${JSON.stringify({ main: initialMainWindow, floating: initialFloatingWindow })}`);
  }
  if (initialMainWindow.windowRegionType !== "complex" || initialFloatingWindow.windowRegionType !== "none") {
    throw new Error(`Windows 10 corner regions are not isolated: ${JSON.stringify({ main: initialMainWindow, floating: initialFloatingWindow })}`);
  }
  if (!initialFloatingWindow.topmost || state.settings.topmost !== true) throw new Error("Floating window is not topmost by default");
  await waitFor(
    floating,
    `document.querySelector('[data-sentence-role="current"]')?.innerText.includes(${quote(longMarker)})`,
    "Long current sentence did not render in floating window",
  );
  evidence.longSentence = await capture(floating, "stage4-long-sentence.png");
  await floating.call("Input.dispatchMouseEvent", { type: "mouseMoved", x: -12, y: -12 });
  await sleep(240);
  const focusedLayout = await evaluate(floating, `(() => {
    const root = document.querySelector('.native-floating-surface');
    const header = document.querySelector('.floating-dragbar');
    const footer = document.querySelector('.floating-controls');
    const content = document.querySelector('.floating-content');
    return {
      hovered: root.matches(':hover'),
      contextMode: root.dataset.contextMode,
      previousDisplay: getComputedStyle(document.querySelector('[data-sentence-role="previous"]')).display,
      nextDisplay: getComputedStyle(document.querySelector('[data-sentence-role="next"]')).display,
      headerVisibility: getComputedStyle(header).visibility,
      footerVisibility: getComputedStyle(footer).visibility,
      headerHeight: header.getBoundingClientRect().height,
      footerHeight: footer.getBoundingClientRect().height,
      contentHeight: content.getBoundingClientRect().height,
    };
  })()`);
  if (focusedLayout.hovered || focusedLayout.headerVisibility !== "hidden" || focusedLayout.footerVisibility !== "hidden"
      || focusedLayout.headerHeight > 1 || focusedLayout.footerHeight > 1
      || focusedLayout.contextMode !== "all" || focusedLayout.previousDisplay === "none" || focusedLayout.nextDisplay === "none") {
    throw new Error(`Floating chrome did not collapse after pointer leave: ${JSON.stringify(focusedLayout)}`);
  }
  evidence.contentFocus = await capture(floating, "stage4-content-focus.png");
  const floatingViewport = await evaluate(floating, "({ width: innerWidth, height: innerHeight })");
  await floating.call("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: Math.round(floatingViewport.width / 2),
    y: Math.round(floatingViewport.height / 2),
  });
  const hoverLayout = await evaluate(floating, `new Promise((resolve) => setTimeout(() => {
    const root = document.querySelector('.native-floating-surface');
    const header = document.querySelector('.floating-dragbar');
    const footer = document.querySelector('.floating-controls');
    resolve({
      hovered: root.matches(':hover'),
      contextMode: root.dataset.contextMode,
      previousDisplay: getComputedStyle(document.querySelector('[data-sentence-role="previous"]')).display,
      nextDisplay: getComputedStyle(document.querySelector('[data-sentence-role="next"]')).display,
      headerVisibility: getComputedStyle(header).visibility,
      footerVisibility: getComputedStyle(footer).visibility,
      headerHeight: header.getBoundingClientRect().height,
      footerHeight: footer.getBoundingClientRect().height,
    });
  }, 240))`);
  if (!hoverLayout.hovered || hoverLayout.headerVisibility !== "visible" || hoverLayout.footerVisibility !== "visible"
      || hoverLayout.headerHeight < 40 || hoverLayout.footerHeight < 50
      || hoverLayout.previousDisplay !== "none" || hoverLayout.nextDisplay !== "none") {
    throw new Error(`Floating chrome did not expand on hover: ${JSON.stringify(hoverLayout)}`);
  }
  evidence.default = await capture(floating, "stage4-hover-controls.png");
  evidence.mainNormal = await capture(main, "stage4-main-normal.png");
  const normalWindowStyle = await evaluate(main, `(() => {
    const node = document.querySelector('.mac-window');
    const rect = node.getBoundingClientRect();
    return { radius: getComputedStyle(node).borderRadius, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, innerWidth, innerHeight };
  })()`);
  if (normalWindowStyle.radius !== "22px"
      || Math.abs(normalWindowStyle.left - 1) > .75 || Math.abs(normalWindowStyle.top - 1) > .75
      || Math.abs(normalWindowStyle.right - (normalWindowStyle.innerWidth - 1)) > .75
      || Math.abs(normalWindowStyle.bottom - (normalWindowStyle.innerHeight - 1)) > .75) {
    throw new Error(`Main normal-state corner surface is incorrect: ${JSON.stringify(normalWindowStyle)}`);
  }
  const floatingWindowStyle = await evaluate(floating, `(() => {
    const node = document.querySelector('.native-floating-surface');
    const rect = node.getBoundingClientRect();
    return { radius: getComputedStyle(node).borderRadius, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, innerWidth, innerHeight };
  })()`);
  if (floatingWindowStyle.radius !== "30px"
      || Math.abs(floatingWindowStyle.left - 2) > .75 || Math.abs(floatingWindowStyle.top - 2) > .75
      || Math.abs(floatingWindowStyle.right - (floatingWindowStyle.innerWidth - 2)) > .75
      || Math.abs(floatingWindowStyle.bottom - (floatingWindowStyle.innerHeight - 2)) > .75) {
    throw new Error(`Floating corner surface is incorrect: ${JSON.stringify(floatingWindowStyle)}`);
  }
  if (!await clickLabel(main, "最大化窗口")) throw new Error("Main maximize control missing");
  await waitFor(main, "document.querySelector('.prototype-stage')?.dataset.windowMode === 'maximized'", "Main maximize state did not reach the frontend");
  const maximizedRadius = await evaluate(main, "getComputedStyle(document.querySelector('.mac-window')).borderRadius");
  if (maximizedRadius !== "0px") throw new Error(`Main maximized radius was not cleared: ${maximizedRadius}`);
  if (roleWindow(probe(), "main").windowRegionType !== "none") throw new Error("Maximized main window retained its rounded native region");
  evidence.mainMaximized = await capture(main, "stage4-main-maximized.png");
  if (!await clickLabel(main, "还原窗口")) throw new Error("Main restore control missing");
  await waitFor(main, "document.querySelector('.prototype-stage')?.dataset.windowMode === 'normal'", "Main normal state did not restore");
  await sleep(180);
  if (roleWindow(probe(), "main").windowRegionType !== "complex") throw new Error("Restored main window did not regain its rounded native region");
  const defaultLayout = await assertSurfaceFits(floating);

  if (!await clickLabel(floating, "播放")) throw new Error("Floating playback button missing");
  await waitFor(main, "window.__qaPlaybackEvents.some((event) => ['playing', 'error'].includes(event.playback?.status))", "Playback produced neither a playing state nor a structured backend error", 15_000);
  await waitFor(main, "Boolean(document.querySelector('.reading-copy mark')) || window.__qaPlaybackEvents.some((event) => event.playback?.status === 'error')", "Main reader did not highlight floating playback sentence", 10_000);
  await waitFor(floating, `document.querySelector('[data-sentence-role="current"]')?.innerText.includes(${quote(longMarker)})`, "Floating current sentence diverged from main playback");
  const playbackState = await floatingState(main);
  const highlighted = await evaluate(main, "document.querySelector('.reading-copy mark')?.innerText || ''");
  const floatingCurrent = await evaluate(floating, "document.querySelector('[data-sentence-role=\"current\"]')?.innerText || ''");
  const sharedOffsets = playbackState.playback.sentence?.chapterIndex === playbackState.context.current?.chapterIndex
    && playbackState.playback.sentence?.startOffset === playbackState.context.current?.startOffset;
  const playbackEvents = await evaluate(main, "window.__qaPlaybackEvents");
  const backendFailure = playbackState.playback.status === "error"
    ? playbackEvents.find((event) => event.reason === "error") || null
    : null;
  if (playbackState.playback.status === "error") {
    if (!backendFailure?.error?.code || !floatingCurrent) throw new Error(`TTS backend failure was not structured: ${JSON.stringify(backendFailure)}`);
  } else if (playbackState.playback.status !== "playing" || !highlighted || !floatingCurrent || !floatingCurrent.startsWith(highlighted) || !sharedOffsets) {
    throw new Error(`Main/floating playback state diverged: ${JSON.stringify({ highlighted, floatingCurrent, playback: playbackState.playback })}`);
  }

  if (!await clickLabel(main, "最小化窗口")) throw new Error("Main minimize control missing");
  await sleep(500);
  const minimized = probe();
  if (roleWindow(minimized, "main").visible) throw new Error("Main Qt window did not hide to the system tray");
  const visibleWhileMinimized = roleWindow(minimized, "floating");
  if (!visibleWhileMinimized.visible || visibleWhileMinimized.minimized) throw new Error("Floating window disappeared with minimized main window");
  evidence.mainMinimized = await capture(floating, "stage4-main-minimized.png");
  probe("restore", ["--role", "main"]);
  await sleep(400);

  const targetsBeforeDuplicate = (await targets()).filter(isAppTarget).length;
  const duplicate = await nativeCall(main, "showFloatingReader");
  await sleep(300);
  const targetsAfterDuplicate = (await targets()).filter(isAppTarget).length;
  if (targetsBeforeDuplicate !== 2 || targetsAfterDuplicate !== 2 || duplicate?.data?.visible !== true) {
    throw new Error(`Repeated show created another floating instance: ${targetsBeforeDuplicate} -> ${targetsAfterDuplicate}`);
  }

  const floatingEventCountBeforeClose = await evaluate(main, "window.__qaFloatingEvents.length");
  if (!await clickLabel(floating, "关闭悬浮窗")) throw new Error("Floating close control missing");
  await waitFor(
    main,
    `window.__qaFloatingEvents.slice(${floatingEventCountBeforeClose}).some((event) => event.state?.visible === false)`,
    "Floating close state event was not observed",
  );
  await sleep(300);
  const closeTransition = await evaluate(main, `(() => {
    const events = window.__qaFloatingEvents;
    const closeIndex = events.findIndex((event, index) => index >= ${floatingEventCountBeforeClose} && event.state?.visible === false);
    const closed = events[closeIndex]?.state;
    const visible = events.slice(0, closeIndex).reverse().find((event) => event.state?.visible === true)?.state;
    return { closed, visible };
  })()`);
  if (!closeTransition.closed || !closeTransition.visible
      || JSON.stringify(closeTransition.closed.playback) !== JSON.stringify(closeTransition.visible.playback)
      || closeTransition.closed.sessionId !== closeTransition.visible.sessionId
      || closeTransition.closed.bookId !== closeTransition.visible.bookId) {
    throw new Error(`Floating close mutated the shared playback snapshot: ${JSON.stringify(closeTransition)}`);
  }
  state = await floatingState(main);
  if (state.visible !== false || state.sessionId !== opened.sessionId || state.bookId !== opened.book.id) {
    throw new Error(`Closing floating window stopped or reset playback: ${JSON.stringify(state.playback)}`);
  }
  const hiddenWindow = probe().windows.find((item) => item.title.includes("悬浮朗读"));
  if (!hiddenWindow || hiddenWindow.visible) throw new Error("Floating close did not hide the native top-level window");
  await waitForTargetCount(2);

  await nativeCall(main, "showFloatingReader");
  const secondTarget = await waitForTarget(
    (item) => isAppTarget(item) && item.url.includes("surface=floating"),
    "Floating reader did not reopen",
  );
  await waitForTargetCount(2);
  if (secondTarget.id !== floating.targetId) {
    throw new Error(`Repeated show replaced the floating target instead of reusing one instance: ${floating.targetId} -> ${secondTarget.id}`);
  }
  await waitFor(floating, "Boolean(document.querySelector('[data-testid=\"native-floating-reader\"], .native-floating-surface'))", "Reopened floating UI missing");
  state = await floatingState(main);
  if (state.playback.status === "playing") {
    if (!await clickLabel(floating, "暂停")) throw new Error("Reopened floating playback did not share playing state");
    await waitFor(main, "window.__qaPlaybackEvents.some((event) => event.playback?.status === 'paused')", "Pause state did not reach main window");
  }
  if (!await clickLabel(floating, "下一句")) throw new Error("Floating next-sentence control missing");
  await waitFor(
    floating,
    `!document.querySelector('[data-sentence-role="current"]')?.innerText.includes(${quote(longMarker)})`,
    "Next-sentence command did not update floating context",
  );
  state = await floatingState(main);
  if (!state.context.previous || !state.context.current || !state.context.next) {
    throw new Error(`Floating reader did not expose three-sentence context: ${JSON.stringify(state.context)}`);
  }
  const renderedContext = await evaluate(floating, `({
    previous: document.querySelector('[data-sentence-role="previous"]')?.innerText || '',
    current: document.querySelector('[data-sentence-role="current"]')?.innerText || '',
    next: document.querySelector('[data-sentence-role="next"]')?.innerText || '',
  })`);
  if (!renderedContext.previous || !renderedContext.current || !renderedContext.next) {
    throw new Error(`Three-sentence UI is incomplete: ${JSON.stringify(renderedContext)}`);
  }

  const settingsBefore = state.settings;
  if (!await clickLabel(floating, "取消置顶")) throw new Error("Topmost toggle missing");
  await sleep(250);
  state = await floatingState(main);
  if (state.settings.topmost !== false || roleWindow(probe(), "floating").topmost) throw new Error("Topmost=false did not reach the native window");
  if (!await clickLabel(floating, "置顶悬浮窗")) throw new Error("Topmost restore control missing");
  await waitForFloatingState(main, (value) => value.settings.topmost === true, "Topmost setting did not restore");
  await sleep(150);
  const wheelDispatched = await evaluate(floating, `(() => {
    const node = document.querySelector('.floating-content');
    if (!node) return false;
    node.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, bubbles: true, cancelable: true }));
    return true;
  })()`);
  if (!wheelDispatched) throw new Error("Floating wheel target missing");
  await waitForFloatingState(main, (value) => value.settings.fontSize > settingsBefore.fontSize && value.settings.followReaderFont === false, "Floating font size did not increase or leave follow mode");
  await sleep(150);
  const opacityChanged = await evaluate(floating, `(() => {
    const node = document.querySelector('input[aria-label="悬浮窗背景透明度"]');
    if (!node) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(node, '0');
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!opacityChanged) throw new Error("Floating background-opacity slider missing");
  await waitForFloatingState(main, (value) => value.settings.backgroundOpacity === 0, "Floating background opacity did not reach zero");
  evidence.transparent = await capture(floating, "stage4-transparent-background.png");
  if (!await clickLabel(main, "更多设置")) throw new Error("Settings center control missing");
  const voiceCatalog = await evaluate(main, `(() => ({
    edge: document.querySelectorAll('.speech-settings optgroup[label^="Edge"] option').length,
    local: document.querySelectorAll('.speech-settings optgroup[label^="本地"] option').length,
    hasRate: Boolean(document.querySelector('.speech-settings input[min="80"][max="400"]')),
    hasGap: Boolean(document.querySelector('.speech-settings input[min="0"][max="1"]')),
  }))()`);
  if (voiceCatalog.edge < 9 || voiceCatalog.local < 1 || !voiceCatalog.hasRate || !voiceCatalog.hasGap) throw new Error(`Settings voice/speech controls incomplete: ${JSON.stringify(voiceCatalog)}`);
  const backgroundLabel = settingsBefore.background === "sepia" ? "深色" : "米黄";
  if (!await clickText(main, ".floating-settings-section button", backgroundLabel)) throw new Error("Floating background setting missing");
  await waitForFloatingState(main, (value) => value.settings.background !== settingsBefore.background, "Floating background did not change");
  const hoverContextChanged = await evaluate(main, `(() => {
    const label = [...document.querySelectorAll('.floating-settings-section label')]
      .find((item) => item.textContent.includes('鼠标移开时显示上一段和下一段'));
    const node = label?.querySelector('input[type="checkbox"]');
    if (!node) return false;
    node.click();
    return true;
  })()`);
  if (!hoverContextChanged) throw new Error("Idle-context setting missing");
  await waitForFloatingState(main, (value) => value.settings.hoverDisplayEnabled === false, "Idle-context setting did not toggle");
  const followChanged = await evaluate(main, `(() => {
    const label = [...document.querySelectorAll('.floating-settings-section label')]
      .find((item) => item.textContent.includes('跟随主阅读器字号'));
    const node = label?.querySelector('input[type="checkbox"]');
    if (!node) return false;
    node.click();
    return true;
  })()`);
  if (!followChanged) throw new Error("Follow-reader-font setting missing");
  await waitForFloatingState(main, (value) => value.settings.followReaderFont === true, "Follow-reader-font setting did not toggle");
  await nativeCall(main, "updateFloatingReaderSettings", JSON.stringify({ patch: { textColor: "#123ABC" } }));
  if (!await clickLabel(main, "关闭设置")) throw new Error("Settings center did not close");
  await sleep(150);
  await floating.call("Input.dispatchMouseEvent", { type: "mouseMoved", x: -12, y: -12 });
  const disabledIdleLayout = await evaluate(floating, `new Promise((resolve) => setTimeout(() => {
    const root = document.querySelector('.native-floating-surface');
    const header = document.querySelector('.floating-dragbar');
    const footer = document.querySelector('.floating-controls');
    resolve({
      hovered: root.matches(':hover'),
      previousDisplay: getComputedStyle(document.querySelector('[data-sentence-role="previous"]')).display,
      nextDisplay: getComputedStyle(document.querySelector('[data-sentence-role="next"]')).display,
      headerVisibility: getComputedStyle(header).visibility,
      footerVisibility: getComputedStyle(footer).visibility,
      headerHeight: header.getBoundingClientRect().height,
      footerHeight: footer.getBoundingClientRect().height,
    });
  }, 240))`);
  if (disabledIdleLayout.hovered || disabledIdleLayout.headerVisibility !== "hidden" || disabledIdleLayout.footerVisibility !== "hidden"
      || disabledIdleLayout.headerHeight > 1 || disabledIdleLayout.footerHeight > 1
      || disabledIdleLayout.previousDisplay !== "none" || disabledIdleLayout.nextDisplay !== "none") {
    throw new Error(`Disabled idle-context mode affected collapsed chrome or exposed context: ${JSON.stringify(disabledIdleLayout)}`);
  }
  evidence.disabledIdle = await capture(floating, "stage4-disabled-idle-current-only.png");
  await floating.call("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: Math.round(floatingViewport.width / 2),
    y: Math.round(floatingViewport.height / 2),
  });
  const disabledHoverLayout = await evaluate(floating, `new Promise((resolve) => setTimeout(() => {
    const root = document.querySelector('.native-floating-surface');
    const header = document.querySelector('.floating-dragbar');
    const footer = document.querySelector('.floating-controls');
    resolve({
      hovered: root.matches(':hover'),
      previousDisplay: getComputedStyle(document.querySelector('[data-sentence-role="previous"]')).display,
      nextDisplay: getComputedStyle(document.querySelector('[data-sentence-role="next"]')).display,
      headerVisibility: getComputedStyle(header).visibility,
      footerVisibility: getComputedStyle(footer).visibility,
      headerHeight: header.getBoundingClientRect().height,
      footerHeight: footer.getBoundingClientRect().height,
    });
  }, 240))`);
  if (!disabledHoverLayout.hovered || disabledHoverLayout.headerVisibility !== "visible" || disabledHoverLayout.footerVisibility !== "visible"
      || disabledHoverLayout.headerHeight < 40 || disabledHoverLayout.footerHeight < 50
      || disabledHoverLayout.previousDisplay !== "none" || disabledHoverLayout.nextDisplay !== "none") {
    throw new Error(`Disabled idle-context mode affected hover chrome: ${JSON.stringify(disabledHoverLayout)}`);
  }
  evidence.disabledHover = await capture(floating, "stage4-disabled-hover-controls.png");
  if (!await clickLabel(floating, "显示双语")) throw new Error("Bilingual control missing");
  state = await waitForFloatingState(main, (value) => value.settings.bilingual === true, "Bilingual setting did not toggle");
  if (state.settings.topmost !== true || !roleWindow(probe(), "floating").topmost) throw new Error("Topmost=true did not reach the native window");
  if (state.settings.fontSize !== opened.settings.fontSize) throw new Error("Follow-reader-font did not restore the main reader size");
  if (state.settings.background === settingsBefore.background) throw new Error("Floating background did not change");
  if (state.settings.backgroundOpacity !== 0) throw new Error("Floating background opacity did not reach zero");
  if (state.settings.textColor !== "#123ABC") throw new Error("Floating text color did not persist");
  if (state.settings.followReaderFont !== true) throw new Error("Follow-reader-font setting did not restore");
  if (state.settings.hoverDisplayEnabled !== false) throw new Error("Idle-context setting did not persist");
  if (state.settings.bilingual !== true) throw new Error("Bilingual setting did not toggle");

  const beforeMove = roleWindow(probe(), "floating").rect;
  const dragPoint = await evaluate(floating, `(() => {
    const rect = document.querySelector('.floating-dragbar').getBoundingClientRect();
    return { x: rect.left + Math.min(100, rect.width / 3), y: rect.top + rect.height / 2 };
  })()`);
  probe("drag", [
    "--role", "floating",
    "--from-x", String(Math.round(dragPoint.x)),
    "--from-y", String(Math.round(dragPoint.y)),
    "--dx", "72",
    "--dy", "38",
  ]);
  await sleep(400);
  const afterMove = roleWindow(probe(), "floating").rect;
  if (beforeMove.left === afterMove.left && beforeMove.top === afterMove.top) throw new Error("System startWindowMove path did not move the native floating window");

  const beforeResize = afterMove;
  const resizePoint = await evaluate(floating, `(() => {
    const node = document.querySelector('.window-resize-handle.bottomRight');
    const rect = node.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  let afterResize = beforeResize;
  // Native system-resize begins only when the pointer-down lands inside the
  // small WebEngine handle.  Try a few points progressively farther inside
  // the handle so a fractional device-pixel rounding does not make this gate
  // flaky; every attempt still has to resize the real top-level window.
  for (const inset of [0, -3, -6]) {
    probe("drag", [
      "--role", "floating",
      "--from-x", String(Math.round(resizePoint.x + inset)),
      "--from-y", String(Math.round(resizePoint.y + inset)),
      "--dx", "90",
      "--dy", "60",
    ]);
    await sleep(400);
    afterResize = roleWindow(probe(), "floating").rect;
    if (beforeResize.width !== afterResize.width || beforeResize.height !== afterResize.height) break;
  }
  if (beforeResize.width === afterResize.width && beforeResize.height === afterResize.height) throw new Error("System startWindowResize path did not resize the native floating window");

  const screen = probe().monitors.find((item) => item.primary) || probe().monitors[0];
  const safeX = screen.work.left + 80;
  const safeY = screen.work.top + 80;
  await nativeCall(main, "updateFloatingReaderSettings", JSON.stringify({ patch: { followReaderFont: false, backgroundOpacity: 0.75 } }));
  const layoutCases = [
    { width: 360, height: 220, fontSize: 40, name: "360x220-font40" },
    { width: 448, height: 273, fontSize: 22, name: "448x273-font22" },
    { width: 560, height: 300, fontSize: 14, name: "560x300-font14" },
  ];
  evidence.layouts = [];
  for (const item of layoutCases) {
    await nativeCall(main, "updateFloatingReaderSettings", JSON.stringify({ patch: { fontSize: item.fontSize } }));
    probe("place", ["--role", "floating", "--x", String(safeX), "--y", String(safeY), "--width", String(item.width), "--height", String(item.height)]);
    await sleep(450);
    const layout = await assertSurfaceFits(floating);
    if (!layout.regions.current || layout.regions.current.height <= 0) throw new Error(`Current sentence disappeared for ${item.name}`);
    const screenshot = await capture(floating, `stage4-${item.name}.png`);
    evidence.layouts.push({ ...item, contextMode: layout.contextMode, contentScrollable: layout.contentScrollable, screenshot });
  }
  evidence.minimum = evidence.layouts[0].screenshot;

  const largeWidth = Math.min(920, screen.work.width - 120);
  const largeHeight = Math.min(620, screen.work.height - 120);
  probe("place", ["--role", "floating", "--x", String(safeX), "--y", String(safeY), "--width", String(largeWidth), "--height", String(largeHeight)]);
  await sleep(400);
  await assertSurfaceFits(floating);
  evidence.maximum = await capture(floating, "stage4-maximum.png");

  probe("place", [
    "--role", "floating",
    "--x", String(screen.work.right + 500),
    "--y", String(screen.work.bottom + 500),
    "--width", "560",
    "--height", "300",
  ]);
  await sleep(700);
  const clampedSnapshot = probe();
  const clampedWindow = roleWindow(clampedSnapshot, "floating");
  if (!fitsMonitor(clampedWindow.rect, clampedSnapshot.monitors)) {
    throw new Error(`Floating geometry escaped all screen work areas: ${JSON.stringify(clampedSnapshot)}`);
  }

  const persistedWidth = Math.min(640, screen.work.width - 180);
  const persistedHeight = Math.min(360, screen.work.height - 180);
  probe("place", ["--role", "floating", "--x", String(safeX), "--y", String(safeY), "--width", String(persistedWidth), "--height", String(persistedHeight)]);
  await sleep(700);
  state = await floatingState(main);
  if (!state.settings.geometry) throw new Error("Floating geometry was not exposed after native move/resize");
  await assertSurfaceFits(floating);

  const issues = [...consoleIssues(main), ...consoleIssues(floating)];
  if (issues.length) throw new Error(`Stage-4 pages emitted ${issues.length} console issue(s): ${JSON.stringify(issues)}`);
  await saveCheckpoint({
    bookId: opened.book.id,
    sessionId: opened.sessionId,
    persistedGeometry: state.settings.geometry,
    monitorCount: clampedSnapshot.monitors.length,
    primaryScaleFactor: scaleFactor,
    primaryDevicePixelRatio: defaultLayout.devicePixelRatio,
    ttsBackendFailure: backendFailure ? { code: backendFailure.error.code, message: backendFailure.error.message } : null,
    evidence,
  });
  if (!await clickLabel(floating, "关闭悬浮窗")) throw new Error("Final floating close control missing");
  await sleep(250);
  await closeMain(main);
  return { state, evidence, monitorCount: clampedSnapshot.monitors.length };
}

async function restoreScenario() {
  const expected = await checkpoint();
  const { main, floating, opened } = await openAndBind();
  const state = await floatingState(main);
  if (state.settings.geometry !== expected.persistedGeometry) {
    throw new Error(`Floating geometry was not restored: ${expected.persistedGeometry} -> ${state.settings.geometry}`);
  }
  const snapshot = probe();
  if (!fitsMonitor(roleWindow(snapshot, "floating").rect, snapshot.monitors)) throw new Error("Restored floating window is outside available screens");
  const layout = await assertSurfaceFits(floating);
  const restoredScreenshot = await capture(floating, "stage4-restored.png");
  const issues = [...consoleIssues(main), ...consoleIssues(floating)];
  if (issues.length) throw new Error(`Restored stage-4 pages emitted ${issues.length} console issue(s)`);
  await saveCheckpoint({
    bookId: opened.book.id,
    restoredGeometry: state.settings.geometry,
    restoredScreenshot,
    restoredLayout: layout,
  });
  await clickLabel(floating, "关闭悬浮窗");
  await sleep(250);
  await closeMain(main);
  return state;
}

async function dpiScenario() {
  const { main, floating, opened, state } = await openAndBind();
  const layout = await assertSurfaceFits(floating);
  const expected = await checkpoint();
  const expectedRatio = expected.primaryDevicePixelRatio * scaleFactor / expected.primaryScaleFactor;
  if (!Number.isFinite(expectedRatio) || Math.abs(layout.devicePixelRatio - expectedRatio) > 0.2) {
    throw new Error(`Unexpected devicePixelRatio at QT_SCALE_FACTOR=${scaleFactor}: ${layout.devicePixelRatio}, expected about ${expectedRatio}`);
  }
  const token = String(scaleFactor).replace(".", "_");
  const screenshot = await capture(floating, `stage4-dpi-${token}.png`);
  const snapshot = probe();
  if (layout.innerWidth > layout.screenAvailWidth || layout.innerHeight > layout.screenAvailHeight) {
    throw new Error(`DPI ${scaleFactor} floating viewport exceeds Qt/Chromium available screen: ${JSON.stringify(layout)}`);
  }
  const issues = [...consoleIssues(main), ...consoleIssues(floating)];
  if (issues.length) throw new Error(`DPI ${scaleFactor} pages emitted ${issues.length} console issue(s)`);
  const current = expected;
  await saveCheckpoint({
    bookId: opened.book.id,
    dpi: [...(current.dpi || []), {
      scaleFactor,
      layout,
      screenshot,
      geometry: state.settings.geometry,
      nativeWindowRect: roleWindow(snapshot, "floating").rect,
    }],
  });
  await clickLabel(floating, "关闭悬浮窗");
  await sleep(250);
  await closeMain(main);
  return { layout, screenshot };
}

let result;
if (phase === "primary") result = await primaryScenario();
else if (phase === "restore") result = await restoreScenario();
else result = await dpiScenario();
process.stdout.write(`${JSON.stringify({ phase, scaleFactor, result }, null, 2)}\n`);
