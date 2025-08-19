import json
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict, Any, Optional

from context import PlaywrightDriver
from dom_tools import build_dom_inventory
from planner import plan_step_llm
from executor import execute_step
from models import StepPlan, ExecResult

class TestState(TypedDict, total=False):
    steps: List[Dict[str, Any]]
    current_idx: int
    last_snapshot: Dict[str, Any]
    inventory: List[Dict[str, Any]]
    plan: StepPlan
    exec_result: ExecResult
    user_hints: Optional[Dict[str, Any]]
    need_replan: bool

async def node_context(state: TestState, driver: PlaywrightDriver) -> TestState:
    # Снимаем снапшот текущей страницы и строим инвентарь DOM
    snap = await driver.snapshot()
    inv = build_dom_inventory(snap["bodyHtml"] or "")
    state["last_snapshot"] = snap
    state["inventory"] = inv
    return state

async def node_plan(state: TestState, driver: PlaywrightDriver) -> TestState:
    step = state["steps"][state["current_idx"]]
    snap = state["last_snapshot"]
    plan = plan_step_llm(
        step_id=step["id"],
        step_title=step["raw"][:80],
        dane=step["dano"],
        action=step["do"],
        result=step["result"],
        url=snap["url"],
        title=snap["title"],
        body_html=snap["bodyHtml"],
        dom_inventory=state["inventory"],
        hints=state.get("user_hints"),
    )
    state["plan"] = plan
    state["need_replan"] = False
    return state

def _print_plan_for_cli(plan: StepPlan):
    print("\n--- Предпросмотр шага ---")
    print(f"Шаг {plan.stepId}: {plan.title}")
    print("Инструкции:")
    for i, ins in enumerate(plan.instructions):
        line = f"  {i}. action={ins.action}"
        if ins.url:
            line += f" url={ins.url}"
        if ins.target:
            t = ins.target.selector
            line += f" target=({t.type}='{t.value}')"
            if ins.target.alternatives:
                line += f" alts=[{', '.join(f'{a.type}:{a.value}' for a in ins.target.alternatives[:2])}...]"
        if ins.value is not None:
            line += f" value={ins.value!r}"
        print(line)
    if plan.expects:
        print("Ожидания:")
        for e in plan.expects:
            if e.selector:
                print(f"  - {e.kind} selector({e.selector.type}='{e.selector.value}') value={e.value}")
            else:
                print(f"  - {e.kind} value={e.value}")
    print("-------------------------")

def _collect_hints_from_cli() -> Optional[Dict[str, Any]]:
    print("\nХотите указать верный селектор или поправить последовательность?")
    print("Введите подсказки в JSON или нажмите Enter, чтобы пропустить.")
    print("Примеры:")
    print('  {"selector_override": {"instructionIndex": 1, "selector": {"type":"css","value":"[class^=\\"btn_primary\\"]"}}}')
    print('  {"prepend_instructions": [{"action":"click","target":{"selector":{"type":"text","value":"Меню"}}}]}')
    raw = input("> ").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"Не получилось разобрать JSON: {e}")
        return None

async def node_validate(state: TestState) -> TestState:
    plan = state["plan"]
    _print_plan_for_cli(plan)
    ans = input("Одобрить этот шаг? [y/n]: ").strip().lower()
    if ans in ("y", "yes", ""):
        state["need_replan"] = False
        return state
    # Отклонён → соберём hints и вернёмся на планирование
    hints = _collect_hints_from_cli()
    if hints:
        state["user_hints"] = hints
    else:
        state["user_hints"] = {"note": "user_rejected_without_hints"}
    state["need_replan"] = True
    return state

async def node_execute(state: TestState, driver: PlaywrightDriver) -> TestState:
    result = await execute_step(driver, state["plan"])
    state["exec_result"] = result
    # Обновим контекст после исполнения (для следующего шага)
    new_snap = {"url": result.url, "title": result.title, "bodyHtml": result.bodyHtml or ""}
    state["last_snapshot"] = new_snap
    state["inventory"] = build_dom_inventory(new_snap["bodyHtml"])
    return state

async def node_next(state: TestState) -> TestState:
    state["current_idx"] += 1
    return state

def build_graph(driver: PlaywrightDriver):
    g = StateGraph(TestState)

    g.add_node("context", lambda s: node_context(s, driver))
    g.add_node("plan",     lambda s: node_plan(s, driver))
    g.add_node("validate", node_validate)
    g.add_node("execute",  lambda s: node_execute(s, driver))
    g.add_node("next",     node_next)

    g.set_entry_point("context")
    g.add_edge("context", "plan")

    # Условная развилка из validate: либо повторное планирование, либо исполнение
    def _should_replan(state: TestState) -> str:
        return "plan" if state.get("need_replan") else "execute"

    g.add_conditional_edges("validate", _should_replan, {"plan": "plan", "execute": "execute"})
    g.add_edge("execute", "next")
    g.add_edge("next", END)
    return g
