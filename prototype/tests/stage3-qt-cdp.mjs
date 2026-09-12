import { writeFile } from "node:fs/promises";

const port = Number(process.env.DD_QA_CDP_PORT);
const bookTitle = process.env.DD_QA_BOOK_TITLE;
const searchTerm = process.env.DD_QA_SEARCH_TERM;
const screenshotPath = process.env.DD_QA_SCREENSHOT;

if (!port || !bookTitle || !searchTerm || !screenshotPath) {
  throw new Error("Missing DD_QA_* environment values");
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForTarget(timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let lastTargets = [];
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      lastTargets = targets;
      const page = targets.find((target) => (
        target.type === "page" && target.url?.includes("/prototype/dist/client/index.html")
      ));
      if (page?.webSocketDebuggerUrl) return page;
    } catch {
      // The Qt process may still be starting.
    }
    await sleep(100);
  }
  throw new Error(`Qt WebEngine CDP target did not appear: ${JSON.stringify(lastTargets.map((target) => ({
    type: target.type,
    title: target.title,
    url: target.url,
  })))}`);
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
    this.socket.close();
  }
}

function quote(value) {
  return JSON.stringify(value);
}

async function main() {
  let cdp;
  const connectDeadline = Date.now() + 15_000;
  while (!cdp && Date.now() < connectDeadline) {
    const target = await waitForTarget();
    const candidate = new CdpClient(target.webSocketDebuggerUrl);
    try {
      await candidate.connect();
      await candidate.call("Runtime.enable");
      await candidate.call("Log.enable");
      await candidate.call("Page.enable");
      cdp = candidate;
    } catch (error) {
      candidate.close();
      if (!String(error).includes("Target crashed")) throw error;
      await sleep(150);
    }
  }
  if (!cdp) throw new Error("Qt WebEngine CDP target did not become stable");
  await cdp.call("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 720,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.call("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      window.__qaPlaybackEvents = [];
      (() => {
        let current = window.QWebChannel;
        const wrap = (Original) => {
          if (!Original || Original.__ddQaWrapped) return Original;
          function Wrapped(transport, callback, converters) {
            return new Original(transport, (channel) => {
              window.__qaNativeBridge = channel.objects.ddBridge;
              if (!window.__qaPlaybackConnected) {
                window.__qaPlaybackConnected = true;
                channel.objects.ddBridge.readerPlaybackChanged.connect((raw) => {
                  try { window.__qaPlaybackEvents.push(JSON.parse(raw)); } catch {}
                });
              }
              callback(channel);
            }, converters);
          }
          Wrapped.__ddQaWrapped = true;
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
  await cdp.call("Page.reload", { ignoreCache: true });

  const evaluate = async (expression) => {
    const result = await cdp.call("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "Runtime.evaluate failed");
    }
    return result.result?.value;
  };

  const waitFor = async (expression, message, timeoutMs = 10_000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await sleep(100);
    }
    throw new Error(message);
  };

  const clickLabel = (label) => evaluate(`(() => {
    const node = [...document.querySelectorAll("button")].find((item) => item.getAttribute("aria-label") === ${quote(label)});
    if (!node) return false;
    node.click();
    return true;
  })()`);
  const clickText = (selector, text) => evaluate(`(() => {
    const node = [...document.querySelectorAll(${quote(selector)})].find((item) => item.innerText.includes(${quote(text)}));
    if (!node) return false;
    node.click();
    return true;
  })()`);

  await waitFor(
    `document.readyState === "complete" && document.body.innerText.includes(${quote(bookTitle)})`,
    "Real library card did not render",
  );
  const pageIdentity = await evaluate("({ title: document.title, url: location.href, text: document.body.innerText.slice(0, 500) })");

  if (!await clickText(".book-card", bookTitle)) throw new Error("Book card was not clickable");
  await waitFor(
    `document.querySelector(".native-reader") && document.body.innerText.includes("第一章 QA入口")`,
    "Native reader did not open",
  );

  if (!await clickText(".toc-list button", "第二章 QA导航")) throw new Error("Second chapter was not clickable");
  await waitFor(
    `document.querySelector(".reading-copy")?.innerText.includes(${quote(searchTerm)})`,
    "Second chapter content did not render",
  );

  if (!await clickLabel("书内搜索")) throw new Error("Search control was not clickable");
  await waitFor("Boolean(document.querySelector('input[placeholder=\"输入关键词后回车\"]'))", "Search field missing");
  await evaluate(`(() => {
    const input = document.querySelector('input[placeholder="输入关键词后回车"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, ${quote(searchTerm)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.form.requestSubmit();
    return true;
  })()`);
  await waitFor("document.querySelectorAll('.reader-side-result').length > 0", "Search result did not render");
  const searchResultCount = await evaluate("document.querySelectorAll('.reader-side-result').length");
  await evaluate("document.querySelector('.reader-side-result').click(); true");

  const fontBefore = Number(await evaluate("document.querySelector('.font-value').innerText"));
  if (!await clickLabel("放大字号")) throw new Error("Font-size control was not clickable");
  await waitFor(`Number(document.querySelector(".font-value").innerText) === ${fontBefore + 1}`, "Font size did not update");
  const fontAfter = Number(await evaluate("document.querySelector('.font-value').innerText"));

  if (!await clickLabel("播放")) throw new Error("Playback control was not clickable");
  await waitFor(
    "window.__qaPlaybackEvents.some((event) => ['sentenceStart', 'error', 'fallback'].includes(event.reason))",
    "No playback event reached QWebChannel",
    15_000,
  );
  await waitFor("Boolean(document.querySelector('.reading-copy mark'))", "Current sentence was not highlighted", 10_000);
  const highlightText = await evaluate("document.querySelector('.reading-copy mark')?.innerText || ''");
  const playbackEvents = await evaluate("window.__qaPlaybackEvents");
  const structuredFailure = playbackEvents.find((event) => event.reason === "error") || null;
  if (structuredFailure && !structuredFailure.error?.code) {
    throw new Error("Playback failure was not structured");
  }

  if (!await clickLabel("书签")) throw new Error("Bookmark panel was not clickable");
  await waitFor("Boolean(document.querySelector('.bookmark-current'))", "Current sentence bookmark action missing");
  await evaluate("document.querySelector('.bookmark-current').click(); true");
  await waitFor("document.querySelectorAll('.reader-bookmark').length > 0", "Bookmark did not persist");
  const bookmarkCount = await evaluate("document.querySelectorAll('.reader-bookmark').length");
  const consoleIssues = cdp.events.filter((event) => (
    event.method === "Runtime.exceptionThrown"
    || (event.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(event.params?.type))
    || (event.method === "Log.entryAdded" && ["error", "warning"].includes(event.params?.entry?.level))
  ));
  if (consoleIssues.length) {
    throw new Error(`Qt page emitted ${consoleIssues.length} console issue(s)`);
  }

  const screenshot = await cdp.call("Page.captureScreenshot", { format: "png", fromSurface: true });
  const screenshotBytes = Buffer.from(screenshot.data, "base64");
  await writeFile(screenshotPath, screenshotBytes);
  const screenshotSize = {
    width: screenshotBytes.readUInt32BE(16),
    height: screenshotBytes.readUInt32BE(20),
  };
  if (screenshotSize.width !== 1280 || screenshotSize.height !== 720) {
    throw new Error(`Unexpected screenshot size: ${screenshotSize.width}x${screenshotSize.height}`);
  }

  await clickLabel("停止朗读");
  await sleep(150);
  const closeSelector = '[...document.querySelectorAll("button")].find((item) => item.getAttribute("aria-label") === "关闭窗口")';
  if (!await evaluate(`Boolean(${closeSelector})`)) throw new Error("Close-window control was not clickable");
  cdp.socket.send(JSON.stringify({
    id: ++cdp.nextId,
    method: "Runtime.evaluate",
    params: { expression: `${closeSelector}.click()` },
  }));
  await sleep(150);
  cdp.close();

  process.stdout.write(`${JSON.stringify({
    pageIdentity,
    searchResultCount,
    fontBefore,
    fontAfter,
    highlightText,
    bookmarkCount,
    consoleIssues,
    playbackReasons: playbackEvents.map((event) => event.reason),
    structuredFailure: structuredFailure ? {
      reason: structuredFailure.reason,
      status: structuredFailure.status,
      code: structuredFailure.error?.code,
      retryable: structuredFailure.error?.retryable,
    } : null,
    screenshotPath,
    screenshotSize,
  }, null, 2)}\n`);
}

await main();
