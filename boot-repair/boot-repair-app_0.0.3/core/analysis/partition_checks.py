from typing import Callable, Sequence
import logging

logger = logging.getLogger(__name__)

from core.models import DiagnosticCategory, DiagnosticFinding, Disk, RiskLevel
from core.system import CommandError, CommandNotFoundError, CommandTimeoutError, capture


def detect_partition_table_issues(
    disks: Sequence[Disk],
    runner: Callable[[Sequence[str]], str],
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    for disk in disks:
        for command in (('parted', '-m', disk.name, 'print'), ('fdisk', '-l', disk.name)):
            timeout = 5 if command[0] == 'parted' else 10
            try:
                output = runner(command, timeout=timeout)
            except CommandTimeoutError as exc:
                logger.warning(
                    'Skipping optional partition table diagnostics for %s using %s: timeout %s',
                    disk.name,
                    command[0],
                    timeout,
                )
                continue
            except (CommandError, CommandNotFoundError, FileNotFoundError, TimeoutError) as exc:
                output = ''
                if isinstance(exc, CommandError) and getattr(exc, 'result', None) is not None:
                    output = getattr(exc.result, 'stdout', '') or getattr(exc.result, 'stderr', '')
                logger.warning(
                    'Skipping optional partition table diagnostics for %s using %s: %s',
                    disk.name,
                    command[0],
                    exc,
                )
                if not output:
                    continue
            except Exception as exc:
                logger.warning(
                    'Unexpected error during partition table diagnostics for %s using %s: %s',
                    disk.name,
                    command[0],
                    exc,
                )
                continue
            lowered = output.lower()
            if 'error:' in lowered or 'failed' in lowered or 'unrecognised disk label' in lowered or 'invalid partition table' in lowered:
                findings.append(
                    DiagnosticFinding(
                        DiagnosticCategory.PARTITION_TABLE_DAMAGE,
                        f'partition table inconsistency detected on {disk.name}',
                        severity=RiskLevel.CRITICAL if 'invalid partition table' in lowered else RiskLevel.HIGH,
                        evidence=output.strip()[:1024],
                    )
                )
    return tuple(findings)