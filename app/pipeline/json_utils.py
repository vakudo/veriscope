import json
import re

FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_value(text: str):
    fenced = FENCE_PATTERN.search(text)
    if fenced:
        text = fenced.group(1)
    candidates = []
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start != -1:
            candidates.append((start, closer))
    for start, closer in sorted(candidates):
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
