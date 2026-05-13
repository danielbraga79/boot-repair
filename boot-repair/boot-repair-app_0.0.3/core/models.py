from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class RiskLevel(str, Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


class DistributionFamily(str, Enum):
    DEBIAN = 'debian'
    ARCH = 'arch'
    UNKNOWN = 'unknown'


class OperationMode(str, Enum):
    SAFE = 'safe'
    ADVANCED = 'advanced'


class DiagnosticCategory(str, Enum):
    BOOTLOADER_FAILURE = 'BOOTLOADER_FAILURE'
    EFI_MISSING = 'EFI_MISSING'
    FS_CORRUPTION = 'FS_CORRUPTION'
    PARTITION_TABLE_DAMAGE = 'PARTITION_TABLE_DAMAGE'
    INITRAMFS_FAILURE = 'INITRAMFS_FAILURE'
    BTRFS_LAYOUT_ERROR = 'BTRFS_LAYOUT_ERROR'
    MULTI_DISK_MISMATCH = 'MULTI_DISK_MISMATCH'
    BOOT_PARTITION_FORMATTED = 'BOOT_PARTITION_FORMATTED'
    FSTAB_MISSING = 'FSTAB_MISSING'


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    category: DiagnosticCategory
    description: str
    severity: RiskLevel = RiskLevel.MEDIUM
    evidence: str = ''


@dataclass(frozen=True, slots=True)
class Disk:
    name: str
    size_bytes: int
    model: str = ''
    serial: str = ''
    removable: bool = False
    transport: str = ''
    path: str = ''


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    disk_name: str
    size_bytes: int
    fs_type: str = ''
    mount_point: str = ''
    uuid: str = ''
    bootable: bool = False
    label: str = ''
    partuuid: str = ''
    flags: str = ''


@dataclass(frozen=True, slots=True)
class AnalysisEvidence:
    disks: tuple[Disk, ...] = ()
    partitions: tuple[Partition, ...] = ()
    blkid_entries: tuple[str, ...] = ()
    fstab_entries: tuple[str, ...] = ()
    firmware_mode: str = 'unknown'
    distribution: str = 'unknown'
    distribution_family: DistributionFamily = DistributionFamily.UNKNOWN
    live_environment: bool = False
    initramfs_tool: str = 'unknown'
    windows_present: bool = False
    diagnostic_findings: tuple[DiagnosticFinding, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairSelection:
    root_partition: str = ''
    efi_system_partition: str = ''
    firmware_mode: str = ''
    dual_boot_windows: bool = False
    operation_mode: OperationMode = OperationMode.SAFE
    confirmed: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairContext:
    disks: tuple[Disk, ...] = ()
    partitions: tuple[Partition, ...] = ()
    firmware_mode: str = 'unknown'
    live_environment: bool = False
    distribution: str = 'unknown'
    initramfs_tool: str = 'unknown'
    windows_present: bool = False
    evidence: tuple[str, ...] = ()
    root_partition: str = ''
    root_disk_name: str = ''
    efi_system_partition: str = ''
    dual_boot_windows: bool = False
    operation_mode: OperationMode = OperationMode.SAFE
    confirmed: bool = False
    distribution_family: DistributionFamily = DistributionFamily.UNKNOWN
    diagnostic_findings: tuple[DiagnosticFinding, ...] = ()
    notes: tuple[str, ...] = ()


def format_size_bytes(size_bytes: int) -> str:
    """Format size in bytes to human-readable format (MB, GB, TB)."""
    if size_bytes >= 1_000_000_000_000:  # TB
        return f"{size_bytes / 1_000_000_000_000:.1f} TB"
    elif size_bytes >= 1_000_000_000:  # GB
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    elif size_bytes >= 1_000_000:  # MB
        return f"{size_bytes / 1_000_000:.1f} MB"
    else:
        return f"{size_bytes} B"


@dataclass(frozen=True, slots=True)
class Risk:
    description: str
    level: RiskLevel
    mitigation: str = ''
    params: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    approved: bool
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairAction:
    label: str
    command: tuple[str, ...]
    requires_root: bool
    description: str = ''
    cwd: str = ''


@dataclass(frozen=True, slots=True)
class RepairPlan:
    title: str
    actions: tuple[RepairAction, ...]
    justifications: tuple[str, ...]
    risks: tuple[Risk, ...]
    preconditions: tuple[str, ...]
    rollback: tuple[RepairAction, ...]
    confidence: float
    trace: tuple[str, ...] = ()

    def validate(self) -> ValidationResult:
        issues: list[str] = []
        warnings: list[str] = []

        if not self.title.strip():
            issues.append('repair plan title is empty')
        if not self.actions:
            issues.append('repair plan has no actions')
        if not self.rollback:
            warnings.append('repair plan has no rollback steps')
        if not (0.0 <= self.confidence <= 1.0):
            issues.append('confidence must be between 0.0 and 1.0')
        if not self.justifications:
            warnings.append('repair plan has no justifications')
        if not self.preconditions:
            warnings.append('repair plan has no preconditions')
        if not self.trace:
            warnings.append('repair plan has no trace')

        for action in self.actions:
            if not action.label.strip():
                issues.append('an action label is empty')
            if not action.command:
                issues.append(f"action '{action.label}' has no command")
            if any(not part.strip() for part in action.command):
                issues.append(f"action '{action.label}' contains an empty command part")

        for action in self.rollback:
            if not action.label.strip():
                issues.append('a rollback action label is empty')
            if not action.command:
                issues.append(f"rollback action '{action.label}' has no command")
            if any(not part.strip() for part in action.command):
                issues.append(f"rollback action '{action.label}' contains an empty command part")

        return ValidationResult(approved=not issues, issues=tuple(issues), warnings=tuple(warnings))
