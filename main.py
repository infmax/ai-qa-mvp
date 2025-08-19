import sys
import anyio

from context import PlaywrightDriver
from parser import parse_test_case
from graph import build_graph
from models import ExecResult

DEFAULT_TEST = """
1. Дано: пользователь на главной. Что сделать: Открыть реестр уязвимостей. Результат: Реестр открыт.
2. Дано: Реестр открыт. Что сделать: Применить фильтры по критичности. Результат: Фильтры применены.
"""

def _print_step_result(step_idx: int, res: ExecResult):
    border = "=" * 60
    print(f"\n{border}")
    print(f"РЕЗУЛЬТАТ ШАГА #{step_idx}: {'OK' if res.ok else 'FAIL'}")
    print(f"URL: {res.url}")
    print(f"TITLE: {res.title}")
    if res.ok:
        print("Ошибок нет.")
    else:
        print("Ошибки:")
        for i, e in enumerate(res.errors, 1):
            msg = f"[{e.code}] {e.message}"
            if e.details:
                det = {k: (str(v)[:180] + "…") if isinstance(v, str) and len(str(v)) > 180 else v
                       for k, v in e.details.items()}
                msg += f" | details={det}"
            print(f"  {i}. {msg}")
    print(border)

async def run_test(test_text: str):
    steps = parse_test_case(test_text)
    if not steps:
        print("Не найдено ни одного шага. Проверь формат нумерованного списка.")
        return

    driver = PlaywrightDriver(headless=True)
    await driver.start()
    try:
        state = {
            "steps": steps,
            "current_idx": 0,
            "user_hints": None,
            "need_replan": False,
        }

        graph = build_graph(driver).compile()

        while state["current_idx"] < len(steps):
            # Один полный прогон: context -> plan -> validate -> (plan?) -> execute -> next
            state = await graph.ainvoke(state)
            res: ExecResult = state["exec_result"]
            current_step_number = int(steps[state["current_idx"] - 1]["id"])
            _print_step_result(current_step_number, res)

            if not res.ok:
                ans = input("Шаг завершился с ошибками. Продолжить к следующему шагу? [y/n]: ").strip().lower()
                if ans not in ("y", "yes", ""):
                    print("Остановлено по запросу пользователя.")
                    break

        print("\nТЕСТ ЗАВЕРШЁН.")
    finally:
        await driver.stop()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"Не удалось прочитать файл '{path}': {e}")
            sys.exit(1)
        anyio.run(run_test, text)
    else:
        anyio.run(run_test, DEFAULT_TEST)
