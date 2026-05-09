from __future__ import annotations

from dataclasses import dataclass

from core.models import RepairAction, RepairPlan
from core.system import CommandError, CommandResult, CommandTimeoutError, run_root


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    action: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    success: bool
    applied_actions: tuple[ExecutionStep, ...]
    failed_action: str = ''
    rollback_steps: tuple[ExecutionStep, ...] = ()
    notes: tuple[str, ...] = ()


class ExecutionError(RuntimeError):
    ...


def _execute_action(action: RepairAction, *, timeout: int, runner) -> ExecutionStep:
    result: CommandResult = runner(action.command, timeout=timeout, check=True, cwd=action.cwd)
    return ExecutionStep(
        action=action.label,
        command=result.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def execute_repair_plan(plan: RepairPlan, *, timeout: int = 600, runner=run_root) -> ExecutionReport:
    validation = plan.validate()
    if not validation.approved:
        raise ExecutionError('; '.join(validation.issues))

    applied: list[ExecutionStep] = []
    rollback_steps: list[ExecutionStep] = []
    notes: list[str] = []

    try:
        for action in plan.actions:
            applied.append(_execute_action(action, timeout=timeout, runner=runner))
        return ExecutionReport(success=True, applied_actions=tuple(applied), rollback_steps=tuple(rollback_steps), notes=tuple(notes))
    except (CommandError, CommandTimeoutError, OSError, ValueError) as exc:
        failed_action = action.label if 'action' in locals() else ''
        notes.append(f'execution failed: {exc}')
        if failed_action:
            notes.append(f'failed action: {failed_action}')

        for rollback_action in plan.rollback:
            try:
                rollback_steps.append(_execute_action(rollback_action, timeout=timeout, runner=runner))
            except (CommandError, CommandTimeoutError, OSError, ValueError) as rollback_exc:
                notes.append(f'rollback failed for {rollback_action.label}: {rollback_exc}')

        return ExecutionReport(
            success=False,
            applied_actions=tuple(applied),
            failed_action=failed_action,
            rollback_steps=tuple(rollback_steps),
            notes=tuple(notes),
        )
