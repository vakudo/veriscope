import json
from pathlib import Path


def load_calibration(path: str, min_samples: int = 20) -> dict[str, float]:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    accuracy: dict[str, float] = {}
    for label, stats in raw.items():
        if not isinstance(stats, dict):
            continue
        total = stats.get("total", 0)
        if isinstance(total, int) and total >= min_samples:
            accuracy[label] = round(stats.get("correct", 0) / total, 3)
    return accuracy
