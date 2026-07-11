const DEFAULT_BACKEND = "http://localhost:8000";
const MAX_PAGE_CHARS = 8000;

const LANG = (
  (chrome.i18n && chrome.i18n.getUILanguage && chrome.i18n.getUILanguage()) ||
  navigator.language ||
  "en"
)
  .toLowerCase()
  .startsWith("ru")
  ? "ru"
  : "en";

const I18N = {
  ru: {
    locale: "ru-RU",
    tagline: "Проверка новостей по независимым источникам",
    settings_label: "Адрес бэкенда",
    settings_saved: "Сохранено",
    lead: "Открой новостную статью и запусти проверку: текст будет разложен на утверждения, каждое проверено по независимым источникам.",
    check_page: "Проверить страницу",
    tip: "Совет: выдели фрагмент текста и выбери «Проверить в Veriscope» в контекстном меню — проверка одного абзаца заметно быстрее.",
    history_title: "Недавние проверки",
    clear_history: "очистить",
    running_title: "Идёт проверка",
    elapsed_label: "Прошло:",
    running_note: "Можно закрыть попап — результат сохранится.",
    error_title: "Не удалось выполнить проверку",
    error_hint: "Проверь, что бэкенд запущен (uvicorn app.main:app) и адрес в настройках верен.",
    retry: "Попробовать снова",
    highlight: "Подсветить на странице",
    unhighlight: (n) => `Снять подсветку (${n})`,
    no_matches: "Совпадений на странице не нашлось",
    copy_md: "Копировать MD",
    copied: "Скопировано ✓",
    recheck: "Перепроверить заново",
    another: "Другая страница",
    took: (t) => `Проверка заняла ${t}`,
    stage_default: "Идёт проверка…",
    stage_sending: "Отправляю на проверку…",
    stage_extract: "Извлекаю текст статьи…",
    stage_claims: "Выделяю проверяемые утверждения…",
    stage_cached: "Беру готовый результат из кэша…",
    stage_claims_done: (n) => `Найдено утверждений: ${n}. Ищу источники…`,
    stage_claim_done: (d, t) => `Проверено ${d} из ${t}…`,
    error_no_text: "На этой странице не удалось прочитать текст",
    error_no_worker:
      "Фоновый обработчик не отвечает. Перезагрузи расширение: chrome://extensions → кнопка ↻ на карточке Veriscope.",
    benchmark: (p) => `на бенчмарке: ${p}%`,
    md_title_fallback: "Проверка новости",
    md_flags: "Признаки манипуляции",
    md_footer: "_Проверено Veriscope — ассистентом проверки фактов без фейковых процентов._",
    verdicts: {
      supported: "Подтверждается",
      refuted: "Опровергается",
      conflicting: "Противоречиво",
      unverifiable: "Не проверяется",
    },
    confidence: {
      high: "уверенность: высокая",
      low: "уверенность: низкая",
    },
    sourceTypes: {
      possible_primary: "возможный первоисточник",
      reprint: "перепечатка",
      opinion: "мнение",
      unknown: "тип не определён",
    },
  },
  en: {
    locale: "en-US",
    tagline: "News checking against independent sources",
    settings_label: "Backend address",
    settings_saved: "Saved",
    lead: "Open a news article and run a check: the text is split into claims, each verified against independent sources.",
    check_page: "Check this page",
    tip: "Tip: select a text fragment and pick “Check with Veriscope” in the context menu — checking one paragraph is much faster.",
    history_title: "Recent checks",
    clear_history: "clear",
    running_title: "Checking",
    elapsed_label: "Elapsed:",
    running_note: "You can close the popup — the result will be saved.",
    error_title: "The check failed",
    error_hint: "Make sure the backend is running (uvicorn app.main:app) and the address in settings is correct.",
    retry: "Try again",
    highlight: "Highlight on page",
    unhighlight: (n) => `Remove highlight (${n})`,
    no_matches: "No matches found on the page",
    copy_md: "Copy MD",
    copied: "Copied ✓",
    recheck: "Re-check",
    another: "Another page",
    took: (t) => `The check took ${t}`,
    stage_default: "Checking…",
    stage_sending: "Sending for analysis…",
    stage_extract: "Extracting article text…",
    stage_claims: "Extracting checkable claims…",
    stage_cached: "Serving a cached result…",
    stage_claims_done: (n) => `Claims found: ${n}. Searching for sources…`,
    stage_claim_done: (d, t) => `Checked ${d} of ${t}…`,
    error_no_text: "Could not read any text on this page",
    error_no_worker:
      "The background worker is not responding. Reload the extension: chrome://extensions → the ↻ button on the Veriscope card.",
    benchmark: (p) => `on benchmark: ${p}%`,
    md_title_fallback: "News check",
    md_flags: "Manipulation signals",
    md_footer: "_Checked by Veriscope — a fact-checking assistant without fake truth percentages._",
    verdicts: {
      supported: "Supported",
      refuted: "Refuted",
      conflicting: "Conflicting",
      unverifiable: "Unverifiable",
    },
    confidence: {
      high: "confidence: high",
      low: "confidence: low",
    },
    sourceTypes: {
      possible_primary: "possible primary source",
      reprint: "reprint",
      opinion: "opinion",
      unknown: "type unknown",
    },
  },
};

const T = I18N[LANG];

const STANCE_ICONS = {
  supports: "✓",
  refutes: "✕",
  not_enough_info: "·",
};

function stageTextFor(progress) {
  if (!progress) return T.stage_sending;
  if (progress.stage === "claims_done") return T.stage_claims_done(progress.total);
  if (progress.stage === "claim_done") return T.stage_claim_done(progress.done, progress.total);
  const key = `stage_${progress.stage}`;
  return typeof T[key] === "string" ? T[key] : T.stage_default;
}

function applyI18n() {
  for (const element of document.querySelectorAll("[data-i18n]")) {
    const value = T[element.dataset.i18n];
    if (typeof value === "string") {
      element.textContent = value;
    }
  }
}

const views = {
  idle: document.getElementById("idle-view"),
  running: document.getElementById("running-view"),
  error: document.getElementById("error-view"),
  result: document.getElementById("result-view"),
};

const checkButton = document.getElementById("check-page");
const retryButton = document.getElementById("retry");
const againButton = document.getElementById("again");
const recheckButton = document.getElementById("recheck");
const highlightButton = document.getElementById("highlight");
const copyMdButton = document.getElementById("copy-md");
const historyBlock = document.getElementById("history-block");
const historyList = document.getElementById("history-list");
const clearHistoryButton = document.getElementById("clear-history");
const stageTextEl = document.getElementById("stage-text");
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
let currentTabUrl = "";

function jobBelongsToCurrentTab(job) {
  return Boolean(job) && job.pageUrl === currentTabUrl;
}

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
    chip.append(dot, `${counts[label]} ${T.verdicts[label].toLowerCase()}`);
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
  const metaParts = [T.sourceTypes[item.source.source_type] || item.source.source_type];
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
  badge.textContent = T.verdicts[verdict.label] || verdict.label;
  const confidence = document.createElement("span");
  confidence.className = "confidence";
  const confidenceParts = [T.confidence[verdict.confidence] || ""];
  if (typeof verdict.historical_accuracy === "number") {
    confidenceParts.push(T.benchmark(Math.round(verdict.historical_accuracy * 100)));
  }
  confidence.textContent = confidenceParts.filter(Boolean).join(" · ");
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
    summary.textContent =
      LANG === "ru"
        ? `Источники (${verdict.evidence.length})`
        : `Sources (${verdict.evidence.length})`;
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
  metaEl.textContent = T.took(formatElapsed(job.startedAt, job.finishedAt));
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
    stageTextEl.textContent = stageTextFor(job.progress);
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

function formatHistoryMeta(entry) {
  const parts = [];
  if (entry.counts.supported) parts.push(`✓ ${entry.counts.supported}`);
  if (entry.counts.refuted) parts.push(`✕ ${entry.counts.refuted}`);
  if (entry.counts.conflicting) parts.push(`⚠ ${entry.counts.conflicting}`);
  if (entry.counts.unverifiable) parts.push(`? ${entry.counts.unverifiable}`);
  const date = new Date(entry.time);
  const stamp = date.toLocaleString(T.locale, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${parts.join(" · ")} — ${stamp}`;
}

async function renderHistory() {
  const { history } = await chrome.storage.local.get({ history: [] });
  historyBlock.hidden = history.length === 0;
  historyList.replaceChildren();
  for (const entry of history.slice(0, 8)) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "history-item";
    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = entry.title || entry.url;
    const meta = document.createElement("span");
    meta.className = "history-meta";
    meta.textContent = formatHistoryMeta(entry);
    item.append(title, meta);
    item.addEventListener("click", () => {
      if (entry.url) {
        chrome.tabs.create({ url: entry.url });
      }
    });
    historyList.append(item);
  }
}

function buildMarkdown(result) {
  const lines = [];
  lines.push(`# ${result.input_title || T.md_title_fallback}`);
  lines.push("");
  lines.push(result.summary);
  if (result.flags.length) {
    lines.push("");
    lines.push(`## ${T.md_flags}`);
    for (const flag of result.flags) {
      lines.push(`- ${flag.detail}`);
    }
  }
  for (const verdict of result.claims) {
    lines.push("");
    lines.push(`## ${T.verdicts[verdict.label] || verdict.label}: ${verdict.claim.text}`);
    lines.push("");
    lines.push(verdict.explanation);
    if (verdict.evidence.length) {
      lines.push("");
      for (const item of verdict.evidence) {
        const meta = [
          T.sourceTypes[item.source.source_type] || item.source.source_type,
          item.stance,
        ];
        if (item.source.published_at) {
          meta.push(item.source.published_at.slice(0, 10));
        }
        lines.push(`- [${item.source.domain}](${item.source.url}) (${meta.join(", ")})`);
      }
    }
  }
  lines.push("");
  lines.push(T.md_footer);
  return lines.join("\n");
}

function highlightOnPage(claims, titles) {
  const existing = document.querySelectorAll("mark[data-veriscope]");
  if (existing.length) {
    for (const el of existing) {
      const parent = el.parentNode;
      while (el.firstChild) parent.insertBefore(el.firstChild, el);
      parent.removeChild(el);
      parent.normalize();
    }
    return { removed: existing.length };
  }
  const colors = {
    supported: "rgba(46, 155, 87, 0.28)",
    refuted: "rgba(214, 69, 69, 0.32)",
    conflicting: "rgba(221, 143, 31, 0.32)",
    unverifiable: "rgba(127, 140, 141, 0.28)",
  };
  const tokenize = (value) => value.toLowerCase().match(/[a-zа-яё0-9]{4,}/g) || [];
  const root =
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.querySelector('[role="main"]') ||
    document.body;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const tag = node.parentElement ? node.parentElement.tagName : "";
    if (node.textContent.trim().length > 60 && !["SCRIPT", "STYLE", "NOSCRIPT"].includes(tag)) {
      nodes.push(node);
    }
  }
  let highlighted = 0;
  for (const claim of claims) {
    const claimWords = new Set(tokenize(claim.text));
    if (!claimWords.size) continue;
    let best = null;
    let bestScore = 0;
    for (const node of nodes) {
      let hits = 0;
      for (const word of tokenize(node.textContent)) {
        if (claimWords.has(word)) hits += 1;
      }
      const score = hits / claimWords.size;
      if (score > bestScore) {
        bestScore = score;
        best = node;
      }
    }
    if (!best || bestScore < 0.35) continue;
    const mark = document.createElement("mark");
    mark.dataset.veriscope = claim.label;
    mark.style.background = colors[claim.label] || colors.unverifiable;
    mark.style.borderRadius = "3px";
    mark.style.padding = "0 2px";
    mark.style.color = "inherit";
    mark.title = `Veriscope — ${titles[claim.label] || claim.label}. ${claim.explanation}`;
    best.parentNode.insertBefore(mark, best);
    mark.appendChild(best);
    highlighted += 1;
  }
  return { highlighted };
}

async function toggleHighlight(job) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const claims = job.result.claims.map((verdict) => ({
    text: verdict.claim.text,
    label: verdict.label,
    explanation: verdict.explanation,
  }));
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: highlightOnPage,
    args: [claims, T.verdicts],
  });
  const outcome = injection.result || {};
  if (outcome.removed) {
    highlightButton.textContent = T.highlight;
  } else if (outcome.highlighted > 0) {
    highlightButton.textContent = T.unhighlight(outcome.highlighted);
  } else {
    highlightButton.textContent = T.no_matches;
    setTimeout(() => {
      highlightButton.textContent = T.highlight;
    }, 2500);
  }
}

async function startCheck(force = false) {
  checkButton.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (maxChars) => {
        const candidates = ["article", "main", '[role="main"]', '[itemprop="articleBody"]'];
        let text = "";
        for (const selector of candidates) {
          const node = document.querySelector(selector);
          if (node && node.innerText && node.innerText.length > 500) {
            text = node.innerText;
            break;
          }
        }
        if (!text && document.body) {
          text = document.body.innerText;
        }
        return { title: document.title, text: text.slice(0, maxChars) };
      },
      args: [MAX_PAGE_CHARS],
    });
    const page = injection.result;
    if (!page || !page.text.trim()) {
      renderJob({
        status: "error",
        startedAt: Date.now(),
        message: T.error_no_text,
      });
      return;
    }
    currentTabUrl = tab.url || "";
    try {
      await chrome.runtime.sendMessage({
        type: "analyze",
        payload: { text: page.text, title: page.title, url: tab.url, force },
      });
    } catch (messageError) {
      renderJob({
        status: "error",
        startedAt: Date.now(),
        message: T.error_no_worker,
      });
      return;
    }
    renderJob({
      status: "running",
      startedAt: Date.now(),
      pageUrl: currentTabUrl,
      pageTitle: page.title,
    });
  } catch (error) {
    renderJob({ status: "error", startedAt: Date.now(), message: String(error) });
  } finally {
    checkButton.disabled = false;
  }
}

async function resetToIdle() {
  await chrome.storage.session.remove("job");
  chrome.runtime.sendMessage({ type: "clear-badge" }).catch(() => {});
  await renderHistory();
  renderJob(null);
}

checkButton.addEventListener("click", () => startCheck(false));
retryButton.addEventListener("click", () => startCheck(false));
recheckButton.addEventListener("click", () => startCheck(true));
againButton.addEventListener("click", resetToIdle);

highlightButton.addEventListener("click", async () => {
  const { job } = await chrome.storage.session.get("job");
  if (job && job.status === "done" && jobBelongsToCurrentTab(job)) {
    await toggleHighlight(job);
  }
});

copyMdButton.addEventListener("click", async () => {
  const { job } = await chrome.storage.session.get("job");
  if (!job || job.status !== "done") return;
  await navigator.clipboard.writeText(buildMarkdown(job.result));
  copyMdButton.textContent = T.copied;
  setTimeout(() => {
    copyMdButton.textContent = T.copy_md;
  }, 2000);
});

clearHistoryButton.addEventListener("click", async () => {
  await chrome.storage.local.set({ history: [] });
  await renderHistory();
});

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
    const job = changes.job.newValue;
    if (!job || jobBelongsToCurrentTab(job)) {
      renderJob(job);
    }
  }
});

(async () => {
  applyI18n();
  const { backendUrl } = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
  backendInput.value = backendUrl;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTabUrl = (tab && tab.url) || "";
  await renderHistory();
  const { job } = await chrome.storage.session.get("job");
  renderJob(jobBelongsToCurrentTab(job) ? job : null);
})();
