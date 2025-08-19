from __future__ import annotations
import os, json, textwrap
from typing import Dict, Any, List
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from openai import OpenAI
from pydantic import ValidationError

from models import StepPlan, Instruction, Target, Selector

# === Конфиг модели ===
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY не задан в окружении")
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


# === Утилиты усечения контекста ===
def _truncate(s: str, max_chars: int) -> str:
    if s is None:
        return ""
    if len(s) <= max_chars:
        return s
    head = s[: max_chars // 2]
    tail = s[-max_chars // 2 :]
    return f"{head}\n...TRUNCATED...\n{tail}"


def _shrink_inventory(
    inv: List[Dict[str, Any]], max_items: int = 120
) -> List[Dict[str, Any]]:
    if not inv:
        return []
    out = []
    for e in inv[:max_items]:
        out.append(
            {
                "tag": e.get("tag"),
                "text": (e.get("text") or "")[:120],
                "id": e.get("id"),
                "role": e.get("role"),
                "testid": e.get("testid"),
                "placeholder": (
                    (e.get("placeholder") or "")[:80] if e.get("placeholder") else None
                ),
                "label": (e.get("label") or "")[:80] if e.get("label") else None,
                "cssCandidates": (e.get("cssCandidates") or [])[:3],
            }
        )
    return out


# === Системные правила для LLM (строго) ===
SYSTEM_INSTR = """Ты — планировщик шагов автотеста Playwright.
Выдавай ТОЛЬКО JSON по следующему контракту (без пояснений и Markdown).

Ограничения и правила:
- Действия (action): navigate | click | fill | waitForSelector | waitForURL | assertVisible | assertText
- Типы селекторов: testid | role | label | placeholder | text | css | id
- НЕЛЬЗЯ использовать xpath; svg игнорируй полностью (во входном HTML уже вырезано).
- Отдавай 1–3 альтернативных селектора (alternatives) на важные действия (click, fill).
- Приоритет селекторов: testid > role > label/placeholder > id > text > css.
- Для классов с хэш-суффиксами генерируй css только вида [class^="stable_part"] или [class*="stable_part"].
- Для navigate используй wait: { "for": "domcontentloaded" } по умолчанию.
- В expects формируй проверки из секции 'Результат' (urlIncludes, elementVisible, assertText).
- Соблюдай JSON-схему: StepPlan { stepId, title, instructions[], expects[], hintsFromUser? }.

Вывод — строго валидный JSON одного StepPlan и ничего больше.
"""


def _build_user_prompt(
    step_id: str,
    step_title: str,
    action: str,
    result: str,
    url: str,
    title: str,
    body_html: str,
    dom_inventory: List[Dict[str, Any]],
    hints: Dict[str, Any] | None,
) -> str:
    inv_json = json.dumps(_shrink_inventory(dom_inventory), ensure_ascii=False)
    hints_json = json.dumps(hints or {}, ensure_ascii=False)
    body_short = _truncate(body_html, 40000)

    return f"""
    ЧТО СДЕЛАТЬ: {action or ""}
    РЕЗУЛЬТАТ: {result or ""}

    ТЕКУЩЕЕ СОСТОЯНИЕ:
    - URL: {url}
    - TITLE: {title}
    - BODY_HTML (без svg, усечён): <<<HTML_START>>>
{body_short}
<<<HTML_END>>>

    DOM-ИНВЕНТАРЬ (усечён):
    {inv_json}

    ПОДСКАЗКИ ПОЛЬЗОВАТЕЛЯ (если есть):
    {hints_json}

    Требуется сгенерировать JSON StepPlan для шага:
    - stepId: "{step_id}"
    - title: "{_truncate(step_title, 120)}"
    """


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1.2, min=1, max=8),
    retry=retry_if_exception_type(Exception),
)
def _call_llm(messages: List[Dict[str, str]]) -> str:
    client = _get_client()
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},  # просим чистый JSON
    )
    return resp.choices[0].message.content or "{}"


def _pydantic_load_or_repair(
    raw: str, fallback_title: str, step_id: str, hints: Dict[str, Any] | None
) -> StepPlan:
    try:
        data = json.loads(raw)
    except Exception:
        return StepPlan(
            stepId=step_id,
            title=fallback_title,
            instructions=[],
            expects=[],
            hintsFromUser=hints,
        )
    try:
        return StepPlan.model_validate(data)
    except ValidationError:
        data.setdefault("stepId", step_id)
        data.setdefault("title", fallback_title)
        data.setdefault("instructions", [])
        data.setdefault("expects", [])
        try:
            return StepPlan.model_validate(data)
        except ValidationError:
            return StepPlan(
                stepId=step_id,
                title=fallback_title,
                instructions=[],
                expects=[],
                hintsFromUser=hints,
            )


def plan_step_llm(
    step_id: str,
    step_title: str,
    action: str,
    result: str,
    url: str,
    title: str,
    body_html: str,
    dom_inventory: list,
    hints: Dict[str, Any] | None = None,
) -> StepPlan:
    user_prompt = _build_user_prompt(
        step_id, step_title, action, result, url, title, body_html, dom_inventory, hints
    )

    messages = [
        {"role": "system", "content": SYSTEM_INSTR},
        {"role": "user", "content": user_prompt},
    ]

    raw = _call_llm(messages)
    plan = _pydantic_load_or_repair(raw, step_title, step_id, hints)

    # Гарантированно применим подсказки локально (на случай игнора моделью)
    if hints:
        if isinstance(hints.get("prepend_instructions"), list):
            prepend = []
            for raw_ins in hints["prepend_instructions"]:
                try:
                    prepend.append(Instruction(**raw_ins))
                except Exception:
                    pass
            plan.instructions = prepend + plan.instructions

        so = hints.get("selector_override")
        if isinstance(so, dict):
            idx = so.get("instructionIndex", 0)
            sel = so.get("selector")
            if (
                isinstance(idx, int)
                and 0 <= idx < len(plan.instructions)
                and isinstance(sel, dict)
            ):
                try:
                    if plan.instructions[idx].target:
                        plan.instructions[idx].target.selector = Selector(**sel)
                    else:
                        plan.instructions[idx].target = Target(
                            selector=Selector(**sel), alternatives=[]
                        )
                except Exception:
                    pass

    return plan
