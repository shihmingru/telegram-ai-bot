"""Safe, dependency-free workflow primitives for the Telegram agent.

Workflows are declarative JSON-like steps. Arbitrary Python, shell commands,
URLs, and dynamic imports are deliberately not executable workflow actions.
External mutations must be routed through the application's approval system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


MAX_STEPS = 20
MAX_RETRIES = 3
MAX_TEXT = 10_000


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    action: str
    params: dict[str, Any]
    retries: int = 0
    requires_approval: bool = False


def validate_workflow(raw: Any, allowed_actions: set[str]) -> list[WorkflowStep]:
    """Validate a bounded declarative workflow without executing it."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Workflow must be a non-empty list of steps.")
    if len(raw) > MAX_STEPS:
        raise ValueError(f"Workflow exceeds the {MAX_STEPS}-step limit.")
    steps: list[WorkflowStep] = []
    names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Step {index} must be an object.")
        name = str(item.get("name", f"step_{index}")).strip()
        action = str(item.get("action", "")).strip()
        params = item.get("params", {})
        retries = item.get("retries", 0)
        approval = item.get("requires_approval", False)
        if not name or len(name) > 80 or name in names:
            raise ValueError(f"Step {index} has an invalid or duplicate name.")
        if action not in allowed_actions:
            raise ValueError(f"Step {name}: action is not in the allowlist.")
        if not isinstance(params, dict):
            raise ValueError(f"Step {name}: params must be an object.")
        if len(str(params)) > MAX_TEXT:
            raise ValueError(f"Step {name}: params are too large.")
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= MAX_RETRIES:
            raise ValueError(f"Step {name}: retries must be between 0 and {MAX_RETRIES}.")
        if not isinstance(approval, bool):
            raise ValueError(f"Step {name}: requires_approval must be boolean.")
        names.add(name)
        steps.append(WorkflowStep(name, action, params, retries, approval))
    return steps


def run_workflow(
    steps: list[WorkflowStep],
    handlers: dict[str, Callable[[dict[str, Any]], Any]],
    *,
    approve: Callable[[WorkflowStep], bool] | None = None,
) -> dict[str, Any]:
    """Run allowlisted actions sequentially, with bounded retries and fail-fast errors."""
    results: list[dict[str, Any]] = []
    for step in steps:
        if step.requires_approval and not (approve and approve(step)):
            return {
                "status": "approval_required",
                "completed": results,
                "pending_step": step.name,
                "message": "Workflow paused because this step requires explicit approval.",
            }
        handler = handlers.get(step.action)
        if handler is None:
            return {
                "status": "failed",
                "completed": results,
                "failed_step": step.name,
                "error": "No registered handler for this allowlisted action.",
            }
        last_error = "Action failed."
        for attempt in range(step.retries + 1):
            try:
                value = handler(dict(step.params))
                results.append({"step": step.name, "status": "completed", "result": value})
                break
            except Exception as error:
                last_error = type(error).__name__
                if attempt == step.retries:
                    return {
                        "status": "failed",
                        "completed": results,
                        "failed_step": step.name,
                        "attempts": attempt + 1,
                        "error": last_error,
                    }
    return {"status": "completed", "completed": results}


def workflow_summary(steps: list[WorkflowStep]) -> dict[str, Any]:
    """Return a safe plan preview; never implies that actions were executed."""
    return {
        "step_count": len(steps),
        "steps": [
            {
                "name": step.name,
                "action": step.action,
                "retries": step.retries,
                "requires_approval": step.requires_approval,
            }
            for step in steps
        ],
        "execution": "not_run",
    }
