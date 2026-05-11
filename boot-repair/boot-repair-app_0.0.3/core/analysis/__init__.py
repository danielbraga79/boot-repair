# Analysis module for boot repair

import importlib

from core.models import AnalysisEvidence
from .evidence_builder import _parse_mounts, collect_evidence as _collect_evidence
from .diagnostics import collect_optional_diagnostics, _detect_boot_partition_issues, _detect_fstab_issues
from .detector import _detect_lsblk_columns


def collect_evidence(*, fstab_path=None, lsblk_command=None, blkid_command=('blkid', '-o', 'export'), command_runner=None, run_optional_diagnostics=False):
    return _collect_evidence(
        fstab_path=fstab_path,
        lsblk_command=lsblk_command,
        blkid_command=blkid_command,
        command_runner=command_runner,
        run_optional_diagnostics=run_optional_diagnostics,
        parse_mounts=_parse_mounts,
    )


analyze_system = collect_evidence

__all__ = [
    'AnalysisEvidence',
    'collect_evidence',
    'collect_optional_diagnostics',
    'analyze_system',
    '_parse_mounts',
    '_detect_boot_partition_issues',
    '_detect_fstab_issues',
    '_detect_lsblk_columns',
]
