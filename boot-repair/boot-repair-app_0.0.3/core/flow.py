from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

from core.analysis import AnalysisEvidence, collect_evidence
from core.execution import ExecutionReport, execute_repair_plan
from core.models import DiagnosticCategory, Disk, Partition, RepairContext, RepairPlan, RepairSelection, ValidationResult
from core.planning import build_repair_plan, validate_plan


class FlowError(RuntimeError):
    ...


class FlowStateError(FlowError):
    ...


class FlowValidationError(FlowError):
    ...


class FlowStage(str, Enum):
    DETECT = 'detect'
    ANALYZE = 'analyze'
    VALIDATE = 'validate'
    PLAN = 'plan'
    EXECUTE = 'execute'
    COMPLETE = 'complete'


@dataclass(slots=True)
class FlowState:
    stage: FlowStage = FlowStage.DETECT
    evidence: AnalysisEvidence | None = None
    context: RepairContext | None = None
    validation: ValidationResult | None = None
    plan: RepairPlan | None = None
    report: ExecutionReport | None = None
    history: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def advance(self, stage: FlowStage, entry: str) -> None:
        self.stage = stage
        self.history = self.history + (entry,)


def _normalize(text: str) -> str:
    return ' '.join(text.strip().split())


def _device_name(value: str) -> str:
    normalized = _normalize(value)
    if not normalized:
        return ''
    return normalized if normalized.startswith('/dev/') else f'/dev/{normalized}'


def _find_partition(partitions: Sequence[Partition], device_name: str) -> Partition | None:
    normalized = _device_name(device_name)
    if not normalized:
        return None
    for partition in partitions:
        if partition.name == normalized:
            return partition
    return None


def _find_disk(disks: Sequence[Disk], device_name: str) -> Disk | None:
    normalized = _device_name(device_name)
    if not normalized:
        return None
    for disk in disks:
        if disk.name == normalized:
            return disk
    return None


class BootRepairFlow:
    def __init__(
        self,
        selection: RepairSelection | None = None,
        *,
        detector: Callable[[], AnalysisEvidence] = collect_evidence,
        planner: Callable[[RepairContext], RepairPlan] = build_repair_plan,
        executor: Callable[[RepairPlan], ExecutionReport] = execute_repair_plan,
    ) -> None:
        self.selection = selection or RepairSelection()
        self._detector = detector
        self._planner = planner
        self._executor = executor
        self.state = FlowState()

    def set_selection(self, selection: RepairSelection) -> None:
        if self.state.stage not in {FlowStage.DETECT, FlowStage.ANALYZE}:
            raise FlowStateError('selection cannot be changed after planning has started')
        self.selection = selection
        self.state.notes = self.state.notes + ('selection updated',)

    def detect(self) -> AnalysisEvidence:
        if self.state.stage != FlowStage.DETECT:
            raise FlowStateError('detect can only run first')
        logger.info("Starting detection phase")
        evidence = self._detector()
        logger.info(f"Detection complete: {len(evidence.disks)} disks, {len(evidence.partitions)} partitions")
        logger.debug(f"Evidence notes: {evidence.notes}")
        self.state.evidence = evidence
        self.state.advance(FlowStage.ANALYZE, 'detect')
        return evidence

    def analyze(self) -> AnalysisEvidence:
        if self.state.stage != FlowStage.ANALYZE:
            raise FlowStateError('analyze requires detected evidence')
        if self.state.evidence is None:
            raise FlowStateError('no evidence available for analysis')
        logger.info("Starting analysis phase")
        evidence = self.state.evidence
        logger.info(f"Analysis complete: processing {len(evidence.disks)} disks, {len(evidence.partitions)} partitions")
        self.state.advance(FlowStage.ANALYZE, 'analyze')
        return evidence

    def _build_context(self) -> tuple[RepairContext, tuple[str, ...], tuple[str, ...]]:
        if self.state.evidence is None:
            raise FlowStateError('analysis evidence is missing')

        evidence = self.state.evidence
        selection = self.selection
        issues: list[str] = []
        warnings: list[str] = list(selection.notes)

        detected_mode = _normalize(evidence.firmware_mode).lower() or 'unknown'
        selected_mode = _normalize(selection.firmware_mode).lower()
        firmware_mode = detected_mode
        if selected_mode and selected_mode != detected_mode:
            warnings.append('selected firmware mode differs from detected firmware mode')

        if not selection.confirmed:
            issues.append('user confirmation is required')

        root_partition = _device_name(selection.root_partition)
        if not root_partition:
            issues.append('a root partition must be selected')
        root_entry = _find_partition(evidence.partitions, root_partition)
        if root_partition and root_entry is None:
            issues.append('selected root partition does not appear in analysis results')
        if root_entry is not None and not root_entry.fs_type.strip():
            warnings.append('selected root partition has no detected filesystem type')

        root_disk_name = root_entry.disk_name if root_entry is not None else ''
        if root_disk_name and not _find_disk(evidence.disks, root_disk_name):
            warnings.append('root partition disk was not detected separately')

        efi_system_partition = _device_name(selection.efi_system_partition)
        efi_entry = _find_partition(evidence.partitions, efi_system_partition) if efi_system_partition else None
        if firmware_mode == 'uefi':
            if not efi_system_partition:
                issues.append('UEFI mode requires an EFI System Partition')
            elif efi_entry is None:
                issues.append('selected EFI System Partition does not appear in analysis results')
            else:
                if root_entry is not None and efi_entry.disk_name and root_entry.disk_name and efi_entry.disk_name != root_entry.disk_name:
                    warnings.append('root and EFI partitions are on different disks; cross-disk UEFI boot setup detected')
                if efi_entry.fs_type.lower() not in {'vfat', 'fat', 'fat32'} and not efi_entry.bootable:
                    warnings.append('selected EFI partition does not present a typical ESP filesystem or boot flag')
        elif efi_system_partition:
            warnings.append('EFI System Partition was provided but firmware mode is not UEFI')

        if not evidence.live_environment:
            warnings.append('the current environment is not detected as live')

        if root_entry is not None and root_entry.uuid:
            root_uuid = root_entry.uuid
            if not any(root_uuid in line for line in evidence.fstab_entries):
                warnings.append('root partition UUID not referenced in /etc/fstab; verify root topology manually')

        if any(finding.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE for finding in evidence.diagnostic_findings):
            warnings.append('partition table damage was detected; use the plan diagnostics before applying bootloader repair')
        if any(finding.category == DiagnosticCategory.FS_CORRUPTION for finding in evidence.diagnostic_findings):
            warnings.append('filesystem corruption was detected; the repair plan includes non-destructive diagnostics')
        if any(finding.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR for finding in evidence.diagnostic_findings):
            warnings.append('btrfs subvolume layout was detected; verify subvolume mount options in /etc/fstab')

        context = RepairContext(
            disks=evidence.disks,
            partitions=evidence.partitions,
            firmware_mode=firmware_mode,
            live_environment=evidence.live_environment,
            distribution=evidence.distribution,
            distribution_family=evidence.distribution_family,
            initramfs_tool=evidence.initramfs_tool,
            evidence=evidence.blkid_entries + evidence.fstab_entries + evidence.notes,
            root_partition=root_partition,
            root_disk_name=root_disk_name,
            efi_system_partition=efi_system_partition,
            confirmed=selection.confirmed and not issues,
            diagnostic_findings=evidence.diagnostic_findings,
            notes=tuple(warnings + issues),
        )
        return context, tuple(issues), tuple(warnings)

    def validate(self) -> ValidationResult:
        if self.state.stage != FlowStage.ANALYZE:
            raise FlowStateError('validate requires analyzed evidence')

        context, issues, warnings = self._build_context()
        validation = ValidationResult(approved=not issues, issues=issues, warnings=warnings)
        self.state.context = context
        self.state.validation = validation
        if not validation.approved:
            raise FlowValidationError('; '.join(validation.issues) if validation.issues else 'validation failed')
        self.state.advance(FlowStage.VALIDATE, 'validate')
        return validation

    def plan(self) -> RepairPlan:
        if self.state.stage != FlowStage.VALIDATE:
            raise FlowStateError('plan requires successful validation')
        if self.state.context is None:
            raise FlowStateError('validation context is missing')

        repair_plan = self._planner(self.state.context)
        plan_validation = validate_plan(repair_plan)
        self.state.validation = plan_validation
        if not plan_validation.approved:
            raise FlowValidationError('; '.join(plan_validation.issues))
        self.state.plan = repair_plan
        self.state.advance(FlowStage.PLAN, 'plan')
        return repair_plan

    def execute(self) -> ExecutionReport:
        if self.state.stage != FlowStage.PLAN:
            raise FlowStateError('execute requires a planned repair')
        if self.state.plan is None:
            raise FlowStateError('repair plan is missing')

        report = self._executor(self.state.plan)
        self.state.report = report
        self.state.advance(FlowStage.COMPLETE, 'execute')
        return report
