const DEFAULT_BACKEND = "http://localhost:8000";
const KEEPALIVE_INTERVAL_MS = 20000;
const REQUEST_TIMEOUT_MS = 600000;
const HISTORY_LIMIT = 20;

const UI_RU = (
  (chrome.i18n && chrome.i18n.getUILanguage && chrome.i18n.getUILanguage()) ||
  ""
)
  .toLowerCase()
  .startsWith("ru");

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

function setBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color: color || "#7a8496" });
  chrome.action.setBadgeText({ text: text || "" });
}

async function saveHistoryEntry(pageUrl, pageTitle, result, elapsedMs) {
  const counts = { supported: 0, refuted: 0, conflicting: 0, unverifiable: 0 };
  for (const verdict of result.claims) {
    counts[verdict.label] = (counts[verdict.label] || 0) + 1;
  }
  const entry = {
    url: pageUrl,
    title: pageTitle || result.input_title || pageUrl,
    time: Date.now(),
    elapsedMs,
    total: result.claims.length,
    counts,
  };
  const { history } = await chrome.storage.local.get({ history: [] });
  const filtered = history.filter((item) => item.url !== pageUrl);
  filtered.unshift(entry);
  await chrome.storage.local.set({ history: filtered.slice(0, HISTORY_LIMIT) });
}

async function readStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const line = chunk.split("\n").find((part) => part.startsWith("data: "));
      if (!line) continue;
      await onEvent(JSON.parse(line.slice(6)));
    }
  }
}

async function runAnalysis(payload) {
  const startedAt = Date.now();
  const pageUrl = payload.url || "";
  const pageTitle = payload.title || "";
  startKeepalive();
  setBadge("…", "#3b62e0");
  const baseJob = { status: "running", startedAt, pageUrl, pageTitle };
  await setJob({ ...baseJob, progress: null });
  try {
    const { backendUrl } = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
    const request = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    };
    let finalEvent = null;
    const response = await fetch(`${backendUrl}/api/analyze/stream`, request);
    if (response.ok && response.body) {
      await readStream(response, async (event) => {
        if (event.stage === "done" || event.stage === "error") {
          finalEvent = event;
          return;
        }
        await setJob({ ...baseJob, progress: event });
      });
    } else {
      const fallback = await fetch(`${backendUrl}/api/analyze`, request);
      if (!fallback.ok) {
        throw new Error(`HTTP ${fallback.status}`);
      }
      finalEvent = { stage: "done", result: await fallback.json() };
    }
    if (!finalEvent) {
      throw new Error("stream ended without result");
    }
    if (finalEvent.stage === "error") {
      throw new Error(finalEvent.detail || "backend error");
    }
    const result = finalEvent.result;
    const finishedAt = Date.now();
    await setJob({ status: "done", startedAt, finishedAt, pageUrl, pageTitle, result });
    const refuted = result.claims.filter(
      (verdict) => verdict.label === "refuted" || verdict.label === "conflicting"
    ).length;
    setBadge(refuted > 0 ? String(refuted) : "✓", refuted > 0 ? "#d64545" : "#1f9d63");
    await saveHistoryEntry(pageUrl, pageTitle, result, finishedAt - startedAt);
  } catch (error) {
    setBadge("!", "#d64545");
    await setJob({
      status: "error",
      startedAt,
      finishedAt: Date.now(),
      pageUrl,
      pageTitle,
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
  if (message && message.type === "clear-badge") {
    setBadge("");
  }
  return false;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "veriscope-check-selection",
      title: UI_RU ? "Проверить в Veriscope" : "Check with Veriscope",
      contexts: ["selection"],
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== "veriscope-check-selection" || !info.selectionText) {
    return;
  }
  runAnalysis({
    text: info.selectionText,
    title: tab && tab.title ? tab.title : "выделенный фрагмент",
    url: (tab && tab.url) || "",
  });
});
