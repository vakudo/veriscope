const DEFAULT_BACKEND = "http://localhost:8000";
const KEEPALIVE_INTERVAL_MS = 20000;
const REQUEST_TIMEOUT_MS = 600000;

let keepaliveTimer = null;

function startKeepalive() {
  if (keepaliveTimer !== null) return;
  keepaliveTimer = setInterval(() => {
    chrome.runtime.getPlatformInfo(() => {});
  }, KEEPALIVE_INTERVAL_MS);
}

function stopKeepalive() {
  if (keepaliveTimer !== null) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}

async function setJob(job) {
  await chrome.storage.session.set({ job });
}

async function runAnalysis(payload) {
  const startedAt = Date.now();
  const pageUrl = payload.url || "";
  startKeepalive();
  await setJob({ status: "running", startedAt, pageUrl, pageTitle: payload.title || "" });
  try {
    const { backendUrl } = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
    const response = await fetch(`${backendUrl}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    await setJob({ status: "done", startedAt, finishedAt: Date.now(), pageUrl, result });
  } catch (error) {
    await setJob({
      status: "error",
      startedAt,
      finishedAt: Date.now(),
      pageUrl,
      message: error && error.message ? error.message : String(error),
    });
  } finally {
    stopKeepalive();
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "analyze") {
    runAnalysis(message.payload);
  }
  return false;
});
