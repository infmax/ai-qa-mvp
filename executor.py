import traceback
from models import StepPlan, ExecResult, ExecError

async def execute_step(driver, plan: StepPlan) -> ExecResult:
    res = ExecResult(ok=True)
    try:
        for ins in plan.instructions:
            if ins.action == "navigate" and ins.url:
                await driver.page.goto(ins.url)
            elif ins.action == "click" and ins.target:
                await driver.page.click(ins.target.selector.value)
            elif ins.action == "fill" and ins.target:
                await driver.page.fill(ins.target.selector.value, ins.value or "")
            elif ins.action == "waitForSelector" and ins.target:
                await driver.page.wait_for_selector(ins.target.selector.value)
            elif ins.action == "assertVisible" and ins.target:
                el = await driver.page.wait_for_selector(ins.target.selector.value)
                if not el:
                    raise Exception(f"Element not visible: {ins.target.selector.value}")
        snap = await driver.snapshot()
        res.url, res.title, res.bodyHtml = snap["url"], snap["title"], snap["bodyHtml"]
    except Exception as e:
        res.ok = False
        res.errors.append(ExecError(code="runtime", message=str(e), details={"trace": traceback.format_exc()}))
    return res
