import argparse
import asyncio
import html
from pathlib import Path

import httpx

EXAMPLES = [
    {
        "name": "Real news (space)",
        "title": "SpaceX launches another batch of Starlink satellites",
        "text": (
            "SpaceX successfully launched a Falcon 9 rocket from Cape Canaveral, "
            "carrying another batch of Starlink satellites into orbit. "
            "The first stage booster landed on a drone ship in the ocean."
        ),
    },
    {
        "name": "Popular myths",
        "title": "Shocking facts scientists don't want you to know!!!",
        "text": (
            "The Great Wall of China is visible to the naked eye from the Moon. "
            "Humans use only 10 percent of their brains. "
            "According to anonymous sources, scientists have been hiding these facts for decades."
        ),
    },
    {
        "name": "Fabricated story",
        "title": "Sensation in Springfield",
        "text": (
            "Daisy Technologies of Springfield sold four million smart kettles in 2025. "
            "Company director Peter Kettleworth said the next goal is to enter "
            "the smart teapot market."
        ),
    },
]

VERDICT_TITLES = {
    "supported": "Supported",
    "refuted": "Refuted",
    "conflicting": "Conflicting",
    "unverifiable": "Unverifiable",
}

SOURCE_TYPE_TITLES = {
    "possible_primary": "possible primary source",
    "reprint": "reprint",
    "opinion": "opinion",
    "unknown": "type unknown",
}

STANCE_ICONS = {"supports": "✓", "refutes": "✕", "not_enough_info": "·"}

PAGE_STYLE = """
:root { --bg:#f6f7fb; --card:#fff; --text:#17203a; --muted:#5b6478; --border:#e3e7f0;
  --accent:#3b62e0; --chip:#eef1fa; --supported:#1f9d63; --refuted:#d64545;
  --conflicting:#dd8f1f; --unverifiable:#7a8496; --flag:#fdf5e4; --flag-border:#f0dfb6; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#12151d; --card:#1b1f2a; --text:#e8ebf3; --muted:#9aa3b5; --border:#2a3040;
    --accent:#5c7ff0; --chip:#232a3a; --supported:#34c184; --refuted:#ef6a6a;
    --conflicting:#e8a94a; --unverifiable:#8b95a8; --flag:#2a2517; --flag-border:#4a3f22; } }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 60px; background:var(--bg); color:var(--text);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { max-width:760px; margin:0 auto; }
h1 { font-size:26px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 24px; }
.tabs { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.tab { padding:8px 14px; border-radius:999px; border:1px solid var(--border);
  background:var(--card); color:var(--text); cursor:pointer; font-size:13px; }
.tab.active { background:var(--accent); border-color:var(--accent); color:#fff; }
.example { display:none; }
.example.active { display:block; }
.input-box { background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:14px 16px; margin-bottom:16px; }
.input-box .label { font-size:11px; text-transform:uppercase; letter-spacing:.6px;
  color:var(--muted); margin-bottom:6px; }
.input-box .headline { font-weight:700; margin-bottom:6px; }
.summary { background:var(--chip); border-radius:10px; padding:10px 14px; margin-bottom:12px; }
.flag { background:var(--flag); border:1px solid var(--flag-border); border-radius:10px;
  padding:8px 12px; margin-bottom:8px; font-size:13px; }
.claim { background:var(--card); border:1px solid var(--border); border-left:4px solid var(--unverifiable);
  border-radius:12px; padding:12px 16px; margin-bottom:12px; }
.claim.supported { border-left-color:var(--supported); }
.claim.refuted { border-left-color:var(--refuted); }
.claim.conflicting { border-left-color:var(--conflicting); }
.claim.unverifiable { border-left-color:var(--unverifiable); }
.badge-row { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; }
.badge { padding:3px 11px; border-radius:999px; font-size:12px; font-weight:700; color:#fff; }
.badge.supported { background:var(--supported); }
.badge.refuted { background:var(--refuted); }
.badge.conflicting { background:var(--conflicting); }
.badge.unverifiable { background:var(--unverifiable); }
.conf { font-size:12px; color:var(--muted); text-align:right; }
.claim-text { font-weight:600; margin:0 0 6px; }
.explanation { color:var(--muted); font-size:13px; margin:0 0 8px; }
details { border-top:1px solid var(--border); padding-top:8px; }
summary { cursor:pointer; color:var(--accent); font-size:13px; }
.source { display:flex; gap:8px; margin-top:8px; font-size:13px; }
.source .icon { font-weight:700; }
.icon.supports { color:var(--supported); }
.icon.refutes { color:var(--refuted); }
.icon.not_enough_info { color:var(--unverifiable); }
.source a { color:var(--accent); text-decoration:none; font-weight:600; }
.source .meta { color:var(--muted); }
footer { margin-top:32px; color:var(--muted); font-size:12px; }
footer a { color:var(--accent); }
"""

PAGE_SCRIPT = """
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".example").forEach((e) => e.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.target).classList.add("active");
  });
});
"""


def esc(value: str) -> str:
    return html.escape(value or "")


def render_claim(verdict: dict) -> str:
    label = verdict["label"]
    conf_parts = ["confidence: high" if verdict["confidence"] == "high" else "confidence: low"]
    if isinstance(verdict.get("historical_accuracy"), (int, float)):
        conf_parts.append(f"on benchmark: {round(verdict['historical_accuracy'] * 100)}%")
    sources = ""
    if verdict["evidence"]:
        rows = ""
        for item in verdict["evidence"]:
            source = item["source"]
            meta = [SOURCE_TYPE_TITLES.get(source["source_type"], source["source_type"])]
            if source.get("published_at"):
                meta.append(source["published_at"][:10])
            rows += (
                f'<div class="source"><span class="icon {item["stance"]}">'
                f'{STANCE_ICONS.get(item["stance"], "·")}</span>'
                f'<span><a href="{esc(source["url"])}" rel="noopener">{esc(source["domain"])}</a>'
                f'<span class="meta"> — {esc(", ".join(meta))}</span></span></div>'
            )
        sources = (
            f"<details><summary>Sources ({len(verdict['evidence'])})</summary>{rows}</details>"
        )
    return (
        f'<div class="claim {label}">'
        f'<div class="badge-row"><span class="badge {label}">{VERDICT_TITLES[label]}</span>'
        f'<span class="conf">{esc(" · ".join(conf_parts))}</span></div>'
        f'<p class="claim-text">{esc(verdict["claim"]["text"])}</p>'
        f'<p class="explanation">{esc(verdict["explanation"])}</p>'
        f"{sources}</div>"
    )


def render_example(index: int, example: dict, result: dict) -> tuple[str, str]:
    tab = (
        f'<button class="tab{" active" if index == 0 else ""}" data-target="example-{index}">'
        f"{esc(example['name'])}</button>"
    )
    flags = "".join(f'<div class="flag">❗ {esc(flag["detail"])}</div>' for flag in result["flags"])
    claims = "".join(render_claim(verdict) for verdict in result["claims"])
    body = (
        f'<div class="example{" active" if index == 0 else ""}" id="example-{index}">'
        f'<div class="input-box"><div class="label">Input text</div>'
        f'<div class="headline">{esc(example["title"])}</div>{esc(example["text"])}</div>'
        f'<div class="summary">{esc(result["summary"])}</div>'
        f"{flags}{claims}</div>"
    )
    return tab, body


async def build(backend: str, output: Path) -> None:
    tabs, bodies = [], []
    async with httpx.AsyncClient(timeout=600.0) as client:
        for index, example in enumerate(EXAMPLES):
            print(f"[{index + 1}/{len(EXAMPLES)}] {example['name']}…", flush=True)
            response = await client.post(
                f"{backend}/api/analyze",
                json={"text": example["text"], "title": example["title"]},
            )
            response.raise_for_status()
            tab, body = render_example(index, example, response.json())
            tabs.append(tab)
            bodies.append(body)
    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Veriscope — demo</title>"
        f"<style>{PAGE_STYLE}</style></head><body>"
        '<div class="wrap">'
        "<h1>Veriscope</h1>"
        '<p class="sub">A news fact-checking assistant: atomic claims, independent sources, '
        'an honest "cannot verify" instead of a fake truth percentage. '
        "Below are three real analyses computed by this pipeline locally (Qwen2.5-7B, CPU).</p>"
        f'<div class="tabs">{"".join(tabs)}</div>{"".join(bodies)}'
        "<footer>Code and calibration metrics: "
        '<a href="https://github.com/vakudo/veriscope">github.com/vakudo/veriscope</a></footer>'
        f"</div><script>{PAGE_SCRIPT}</script></body></html>"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"saved: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--output", default="docs/index.html")
    args = parser.parse_args()
    asyncio.run(build(args.backend, Path(args.output)))
