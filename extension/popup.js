const DEFAULT_BACKEND = "http://localhost:8000";

const VERDICT_TITLES = {
  supported: "Подтверждается",
  refuted: "Опровергается",
  conflicting: "Противоречивые данные",
  unverifiable: "Не удалось проверить",
};

const SOURCE_TYPE_TITLES = {
  possible_primary: "возможный первоисточник",
  reprint: "перепечатка",
  opinion: "мнение",
  unknown: "тип не определён",
};

const checkButton = document.getElementById("check-page");
const statusBox = document.getElementById("status");
const resultBox = document.getElementById("result");
const backendInput = document.getElementById("backend-url");
const saveButton = document.getElementById("save-settings");

async function getBackendUrl() {
  const stored = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
  return stored.backendUrl || DEFAULT_BACKEND;
}

function setStatus(text, isError = false) {
  statusBox.hidden = !text;
  statusBox.textContent = text || "";
  statusBox.classList.toggle("error", isError);
}

function grabPageContent() {
  return {
    title: document.title,
    text: document.body ? document.body.innerText.slice(0, 20000) : "",
  };
}

async function readActivePage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: grabPageContent,
  });
  return injection.result;
}

function renderSource(item) {
  const row = document.createElement("div");
  row.className = "source";
  const link = document.createElement("a");
  link.href = item.source.url;
  link.target = "_blank";
  link.textContent = item.source.domain;
  const meta = document.createElement("span");
  const parts = [SOURCE_TYPE_TITLES[item.source.source_type] || item.source.source_type];
  if (item.source.published_at) {
    parts.push(item.source.published_at.slice(0, 10));
  }
  parts.push(item.stance);
  meta.className = "meta";
  meta.textContent = ` (${parts.join(", ")})`;
  row.append("• ", link, meta);
  return row;
}

function renderResult(result) {
  resultBox.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "summary";
  summary.textContent = result.summary;
  resultBox.append(summary);
  for (const flag of result.flags) {
    const flagBox = document.createElement("div");
    flagBox.className = "flag";
    flagBox.textContent = `❗ ${flag.detail}`;
    resultBox.append(flagBox);
  }
  for (const verdict of result.claims) {
    const card = document.createElement("div");
    card.className = "claim";
    const badge = document.createElement("span");
    badge.className = `badge ${verdict.label}`;
    badge.textContent = VERDICT_TITLES[verdict.label] || verdict.label;
    const text = document.createElement("div");
    text.className = "text";
    text.textContent = verdict.claim.text;
    const explanation = document.createElement("div");
    explanation.className = "explanation";
    explanation.textContent = verdict.explanation;
    card.append(badge, text, explanation);
    for (const item of verdict.evidence.slice(0, 3)) {
      card.append(renderSource(item));
    }
    resultBox.append(card);
  }
  resultBox.hidden = false;
}

checkButton.addEventListener("click", async () => {
  checkButton.disabled = true;
  resultBox.hidden = true;
  setStatus("Читаю страницу и проверяю утверждения — это может занять пару минут…");
  try {
    const page = await readActivePage();
    if (!page || !page.text.trim()) {
      throw new Error("empty page");
    }
    const backend = await getBackendUrl();
    const response = await fetch(`${backend}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: page.text, title: page.title }),
    });
    if (!response.ok) {
      throw new Error(`backend responded with ${response.status}`);
    }
    renderResult(await response.json());
    setStatus("");
  } catch (error) {
    setStatus("Не удалось проверить страницу. Убедитесь, что бэкенд запущен и адрес верен.", true);
  } finally {
    checkButton.disabled = false;
  }
});

saveButton.addEventListener("click", async () => {
  await chrome.storage.sync.set({ backendUrl: backendInput.value.trim() || DEFAULT_BACKEND });
  setStatus("Настройки сохранены");
});

getBackendUrl().then((url) => {
  backendInput.value = url;
});
