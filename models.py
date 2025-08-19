from __future__ import annotations
from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field

SelectorType = Literal["testid","role","label","placeholder","text","css","id"]
WaitForType = Literal["domcontentloaded","networkidle"]
ActionType = Literal[
    "navigate","click","fill",
    "waitForSelector","waitForURL",
    "assertVisible","assertText"
]

class Selector(BaseModel):
    type: SelectorType
    value: str

class Target(BaseModel):
    selector: Selector
    alternatives: List[Selector] = Field(default_factory=list)

class WaitSpec(BaseModel):
    for_: WaitForType = Field(alias="for")
    timeoutMs: int = 10000

class Instruction(BaseModel):
    action: ActionType
    url: Optional[str] = None
    target: Optional[Target] = None
    value: Optional[str] = None
    masking: Optional[bool] = False
    wait: Optional[WaitSpec] = None
    waitAfter: Optional[WaitSpec] = None

class Expectation(BaseModel):
    kind: Literal["urlIncludes","elementVisible","assertText"]
    value: Optional[str] = None
    selector: Optional[Selector] = None

class StepPlan(BaseModel):
    stepId: str
    title: str
    instructions: List[Instruction]
    expects: List[Expectation] = Field(default_factory=list)
    hintsFromUser: Optional[Dict[str, Any]] = None

class ExecError(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

class ExecResult(BaseModel):
    ok: bool
    errors: List[ExecError] = Field(default_factory=list)
    url: Optional[str] = None
    title: Optional[str] = None
    bodyHtml: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
