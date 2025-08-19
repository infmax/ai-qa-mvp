import re
from typing import List, Dict

STEP_RE = re.compile(r"^\s*(\d+)\.\s*(.+)$", re.MULTILINE)


def parse_test_case(text: str) -> List[Dict]:
    matches = STEP_RE.findall(text)
    steps = []
    for num, body in matches:
        action = extract_section(
            body, ["ЧТО СДЕЛАТЬ", "Что сделать", "ДЕЙСТВИЕ", "Действие"]
        )
        result = extract_section(
            body, ["РЕЗУЛЬТАТ", "Результат", "ОЖИДАНИЕ", "Ожидание"]
        )
        steps.append(
            {"id": num.strip(), "do": action, "result": result, "raw": body.strip()}
        )
    return steps


def extract_section(text: str, keys) -> str:
    pattern = r"(?:" + "|".join(re.escape(k) for k in keys) + r")\s*:?\s*"
    parts = re.split(pattern, text)
    if len(parts) == 1:
        return ""
    tail = parts[1]
    next_split = re.split(
        r"(?:ЧТО СДЕЛАТЬ|Что сделать|ДЕЙСТВИЕ|Действие|РЕЗУЛЬТАТ|Результат|ОЖИДАНИЕ|Ожидание)\s*:?\s*",
        tail,
    )
    return next_split[0].strip()
