const DEFAULT_BACKEND = "http://localhost:8000";
const MAX_PAGE_CHARS = 12000;

const VERDICT_TITLES = {
  supported: "Подтверждается",
  refuted: "Опровергается",
  conflicting: "Противоречиво",
  unverifiable: "Не проверяется",
};

const CONFIDENCE_TITLES = {
  high: "уверенность: высокая",
  low: "уверенность: низкая",
};

const SOURCE_TYPE_TITLES = {
  possible_primary: "возможный первоисточник",
  reprint: "перепечатка",
  opinion: "мнение",
  unknown: "тип не определён",
};

const STANCE_ICONS = {
  supports: "✓",
  refutes: "✕",
  not_enough_info: "·",
};

const views = {
  idle: document.getElementById("idle-view"),
  running: document.getElementById("running-view"),
  error: document.getElementById("error-view"),
  result: document.getElementById("result-view"),
};

const checkButton = document.getElementById("check-page");
const retryButton = document.getElementById("retry");
const againButton = document.getElementById("again");
const elapsedEl = document.getElementById("elapsed");
const runningPageEl = document.getElementById("running-page");
const errorMessageEl = document.getElementById("error-message");
const summaryChipsEl = document.getElementById("summary-chips");
const summaryTextEl = document.getElementById("summary-text");
const flagsEl = document.getElementById("flags");
const claimsEl = document.getElementById("claims");
const metaEl = document.getElementById("meta");
const settingsPanel = document.getElementById("settings-panel");
const settingsToggle = document.getElementById("settings-toggle");
const backendInput = document.getElementById("backend-url");
const saveSettingsButton = document.getElementById("save-settings");
const settingsNote = document.getElementById("settings-note");

let timerId = null;

function showView(name) {
  for (const [key, element] of Object.entries(views)) {
    element.hidden = key !== name;
  }
}

function formatElapsed(startedAt, finishedAt) {
  const seconds = Math.max(0, Math.floor(((finishedAt || Date.now()) - startedAt) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function startTimer(startedAt) {
  stopTimer();
  elapsedEl.textContent = formatElapsed(startedAt);
  timerId = setInterval(() => {
    elapsedEl.textContent = formatElapsed(startedAt);
  }, 1000);
}

function stopTimer() {
  if (timerId !== null) {
    clearInterval(timerId);
    timerId = null;
  }
}

function renderChips(claims) {
  summaryChipsEl.replaceChildren();
  const counts = {};
  for (const verdict of claims) {
    counts[verdict.label] = (counts[verdict.label] || 0) + 1;
  }
  for (const label of ["supported", "refuted", "conflicting", "unverifiable"]) {
    if (!counts[label]) continue;
    const chip = document.createElement("span");
    chip.className = "chip";
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = `var(--${label})`;
    chip.append(dot, `${counts[label]} ${VERDICT_TITLES[label].toLowerCase()}`);
    summaryChipsEl.append(chip);
  }
}

function renderSource(item) {
  const row = document.createElement("div");
  row.className = "source";
  const icon = document.createElement("span");
  icon.className = `stance-icon ${item.stance}`;
  icon.textContent = STANCE_ICONS[item.stance] || "·";
  const content = document.createElement("span");
  const link = document.createElement("a");
  link.href = item.source.url;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = item.source.domain;
  const metaParts = [SOURCE_TYPE_TITLES[item.source.source_type] || item.source.source_type];
  if (item.source.published_at) {
    metaParts.push(item.source.published_at.slice(0, 10));
  }
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = ` — ${metaParts.join(", ")}`;
  content.append(link, meta);
  if (item.rationale) {
    const rationale = document.createElement("span");
    rationale.className = "rationale";
    rationale.textContent = item.rationale;
    content.append(rationale);
  }
  row.append(icon, content);
  return row;
}

function renderClaim(verdict) {
  const card = document.createElement("div");
  card.className = `claim ${verdict.label}`;
  const badgeRow = document.createElement("div");
  badgeRow.className = "badge-row";
  const badge = document.createElement("span");
  badge.className = `badge ${verdict.label}`;
  badge.textContent = VERDICT_TITLES[verdict.label] || verdict.label;
  const confidence = document.createElement("span");
  confidence.className = "confidence";
  confidence.textContent = CONFIDENCE_TITLES[verdict.confidence] || "";
  badgeRow.append(badge, confidence);
  const text = document.createElement("p");
  text.className = "claim-text";
  text.textContent = verdict.claim.text;
  const explanation = document.createElement("p");
  explanation.className = "explanation";
  explanation.textContent = verdict.explanation;
  card.append(badgeRow, text, explanation);
  if (verdict.evidence.length > 0) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `Источники (${verdict.evidence.length})`;
    details.append(summary);
    for (const item of verdict.evidence) {
      details.append(renderSource(item));
    }
    card.append(details);
  }
  return card;
}

function renderResult(job) {
  const result = job.result;
  renderChips(result.claims);
  summaryTextEl.textContent = result.summary;
  flagsEl.replaceChildren();
  for (const flag of result.flags) {
    const box = document.createElement("div");
    box.className = "flag";
    box.append("❗", ` ${flag.detail}`);
    flagsEl.append(box);
  }
  claimsEl.replaceChildren();
  for (const verdict of result.claims) {
    claimsEl.append(renderClaim(verdict));
  }
  metaEl.textContent = `Проверка заняла ${formatElapsed(job.startedAt, job.finishedAt)}`;
  showView("result");
}

function renderJob(job) {
  stopTimer();
  if (!job) {
    showView("idle");
    return;
  }
  if (job.status === "running") {
    runningPageEl.textContent = job.pageTitle ? `: ${job.pageTitle}` : "";
    startTimer(job.startedAt);
    showView("running");
    return;
  }
  if (job.status === "error") {
    errorMessageEl.textContent = job.message || "";
    showView("error");
    return;
  }
  if (job.status === "done") {
    renderResult(job);
    return;
  }
  showView("idle");
}

async function startCheck() {
  checkButton.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (maxChars) => ({
        title: document.title,
        text: document.body ? document.body.innerText.slice(0, maxChars) : "",
      }),
      args: [MAX_PAGE_CHARS],
    });
    const page = injection.result;
    if (!page || !page.text.trim()) {
      renderJob({
        status: "error",
        startedAt: Date.now(),
        message: "На этой странице не удалось прочитать текст",
      });
      return;
    }
    try {
      await chrome.runtime.sendMessage({
        type: "analyze",
        payload: { text: page.text, title: page.title },
      });
    } catch (messageError) {
      renderJob({
        status: "error",
        startedAt: Date.now(),
        message:
          "Фоновый обработчик не отвечает. Перезагрузи расширение: chrome://extensions → кнопка ↻ на карточке Veriscope.",
      });
      return;
    }
    renderJob({ status: "running", startedAt: Date.now(), pageTitle: page.title });
  } catch (error) {
    renderJob({ status: "error", startedAt: Date.now(), message: String(error) });
  } finally {
    checkButton.disabled = false;
  }
}

async function resetToIdle() {
  await chrome.storage.session.remove("job");
  renderJob(null);
}

checkButton.addEventListener("click", startCheck);
retryButton.addEventListener("click", startCheck);
againButton.addEventListener("click", resetToIdle);

settingsToggle.addEventListener("click", () => {
  settingsPanel.hidden = !settingsPanel.hidden;
  settingsNote.hidden = true;
});

saveSettingsButton.addEventListener("click", async () => {
  const value = backendInput.value.trim() || DEFAULT_BACKEND;
  await chrome.storage.sync.set({ backendUrl: value });
  backendInput.value = value;
  settingsNote.hidden = false;
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.job) {
    renderJob(changes.job.newValue);
  }
});

(async () => {
  const { backendUrl } = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
  backendInput.value = backendUrl;
  const { job } = await chrome.storage.session.get("job");
  renderJob(job);
})();
