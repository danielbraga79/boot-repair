from typing import Callable, Sequence
import logging

logger = logging.getLogger(__name__)

from core.models import DiagnosticCategory, DiagnosticFinding, Partition, RiskLevel
from core.system import CommandError, CommandNotFoundError, CommandTimeoutError, capture


def inspect_filesystem(
    partition: Partition,
    mount_entries: tuple[tuple[str, str, bool], ...],
    runner: Callable[[Sequence[str]], str],
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    device = partition.name
    lower_type = partition.fs_type.lower()
    mounted = any(entry for entry in mount_entries if entry[0] == device)
    if mounted:
        ro_forced = any(entry[2] for entry in mount_entries if entry[0] == device)
        if ro_forced:
            findings.append(
                DiagnosticFinding(
                    DiagnosticCategory.FS_CORRUPTION,
                    f'{device} is currently mounted read-only',
                    severity=RiskLevel.MEDIUM,
                    evidence='read-only mount detected via /proc/mounts',
                )
            )
    if lower_type in {'ext4', 'ext3', 'ext2'}:
        command = ('fsck.ext4', '-n', device)
    elif lower_type == 'xfs':
        command = ('xfs_repair', '-n', device)
    elif lower_type == 'btrfs':
        command = ('btrfs', 'check', '--readonly', device)
    elif lower_type in {'vfat', 'fat', 'fat32'}:
        command = ('fsck.fat', '-n', device)
    else:
        return tuple(findings)
    try:
        output = runner(command, timeout=15)
    except CommandTimeoutError as exc:
        logger.warning(
            'Filesystem inspection timeout for %s using %s: %s',
            device,
            command[0],
            exc,
        )
        return tuple(findings)
    except (CommandError, FileNotFoundError, TimeoutError) as exc:
        logger.warning(
            'Filesystem inspection failed for %s using %s: %s',
            device,
            command[0],
            exc,
        )
        return tuple(findings)
    except Exception as exc:
        logger.warning(
            'Unexpected error during filesystem inspection for %s: %s',
            device,
            exc,
        )
        return tuple(findings)
    lowered = output.lower()
    if 'invalid superblock' in lowered or 'bad superblock' in lowered or 'superblock failed' in lowered:
        findings.append(
            DiagnosticFinding(
                DiagnosticCategory.FS_CORRUPTION,
                f'{device} has an invalid superblock',
                severity=RiskLevel.CRITICAL,
                evidence=output.strip()[:1024],
            )
        )
    if 'journal' in lowered and ('error' in lowered or 'inconsistent' in lowered or 'corrupt' in lowered):
        findings.append(
            DiagnosticFinding(
                DiagnosticCategory.FS_CORRUPTION,
                f'{device} shows journal inconsistency',
                severity=RiskLevel.HIGH,
                evidence=output.strip()[:1024],
            )
        )
    if 'metadata' in lowered and ('corrupt' in lowered or 'inconsistent' in lowered or 'error' in lowered):
        findings.append(
            DiagnosticFinding(
                DiagnosticCategory.FS_CORRUPTION,
                f'{device} shows metadata corruption indicators',
                severity=RiskLevel.HIGH,
                evidence=output.strip()[:1024],
            )
        )
    return tuple(findings)