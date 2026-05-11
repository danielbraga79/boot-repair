"""Boot and filesystem diagnostics.

This module performs various diagnostic checks on the system to identify
potential boot issues, including EFI configuration, boot partition integrity,
fstab correctness, and filesystem corruption indicators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence
import logging

logger = logging.getLogger(__name__)

from core.models import DiagnosticCategory, DiagnosticFinding, Disk, Partition, RiskLevel
from core.system import CommandError, CommandNotFoundError, CommandTimeoutError, capture

from .partition_checks import detect_partition_table_issues
from .filesystem_checks import inspect_filesystem
from .utils import _parse_mounts


def _detect_btrfs_layout(
    partitions: tuple[Partition, ...],
    fstab_entries: tuple[str, ...],
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    for entry in fstab_entries:
        fields = entry.split()
        if len(fields) < 3:
            continue
        device_spec, mount_point, fs_type = fields[0], fields[1], fields[2].lower()
        options = fields[3] if len(fields) > 3 else ''
        if fs_type == 'btrfs':
            if 'subvol=' in options or 'subvolid=' in options:
                findings.append(
                    DiagnosticFinding(
                        DiagnosticCategory.BTRFS_LAYOUT_ERROR,
                        f'btrfs mount at {mount_point} uses subvolume options: {options}',
                        severity=RiskLevel.MEDIUM,
                        evidence=device_spec,
                    )
                )
            else:
                findings.append(
                    DiagnosticFinding(
                        DiagnosticCategory.BTRFS_LAYOUT_ERROR,
                        f'btrfs mount at {mount_point} is missing explicit subvolume selection',
                        severity=RiskLevel.MEDIUM,
                        evidence=options,
                    )
                )
    return tuple(findings)


def _detect_boot_partition_issues(
    partitions: tuple[Partition, ...],
    runner: Callable[[Sequence[str]], str],
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    
    # Check for /boot partition
    boot_partition = None
    efi_partition = None
    for partition in partitions:
        if partition.mount_point == '/boot':
            boot_partition = partition
        elif partition.mount_point == '/boot/efi':
            efi_partition = partition
    
    # Check /boot partition
    if boot_partition:
        try:
            # Check if /boot has essential files
            output = runner(('find', boot_partition.mount_point, '-maxdepth', '1', '-name', 'vmlinuz-*', '-o', '-name', 'initramfs-*', '-o', '-name', 'initrd-*'))
            if not output.strip():
                findings.append(
                    DiagnosticFinding(
                        DiagnosticCategory.BOOT_PARTITION_FORMATTED,
                        f'/boot partition ({boot_partition.name}) appears to be empty or missing kernel/initramfs files',
                        severity=RiskLevel.CRITICAL,
                        evidence=f'no vmlinuz, initramfs, or initrd files found in {boot_partition.mount_point}',
                    )
                )
        except (CommandError, FileNotFoundError):
            pass
    
    # Check EFI partition
    if efi_partition:
        try:
            # Check for EFI directory and bootloader files
            efi_dir_exists = runner(('test', '-d', f'{efi_partition.mount_point}/EFI'))
            if efi_dir_exists.strip():
                # Check for common bootloader files
                bootloader_files = runner(('find', f'{efi_partition.mount_point}/EFI', '-name', 'grubx64.efi', '-o', '-name', 'BOOTX64.EFI', '-o', '-name', 'systemd-bootx64.efi'))
                if not bootloader_files.strip():
                    findings.append(
                        DiagnosticFinding(
                            DiagnosticCategory.BOOT_PARTITION_FORMATTED,
                            f'EFI partition ({efi_partition.name}) exists but is missing bootloader files',
                            severity=RiskLevel.CRITICAL,
                            evidence=f'EFI directory exists at {efi_partition.mount_point}/EFI but no bootloader files found',
                        )
                    )
            else:
                findings.append(
                    DiagnosticFinding(
                        DiagnosticCategory.BOOT_PARTITION_FORMATTED,
                        f'EFI partition ({efi_partition.name}) is missing EFI directory',
                        severity=RiskLevel.CRITICAL,
                        evidence=f'no EFI directory found at {efi_partition.mount_point}/EFI',
                    )
                )
        except (CommandError, FileNotFoundError):
            pass
    
    return tuple(findings)


def _detect_fstab_issues(
    fstab_entries: tuple[str, ...],
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    
    # Check if fstab exists and has entries
    if not fstab_entries:
        findings.append(
            DiagnosticFinding(
                DiagnosticCategory.FSTAB_MISSING,
                '/etc/fstab is missing or empty',
                severity=RiskLevel.CRITICAL,
                evidence='no fstab entries detected',
            )
        )
    
    return tuple(findings)


def collect_optional_diagnostics(
    disks: tuple[Disk, ...],
    partitions: tuple[Partition, ...],
    fstab_entries: tuple[str, ...],
    firmware_mode: str,
    runner: Callable[[Sequence[str]], str] = capture,
    blkid_entries: tuple[str, ...] = (),
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    findings.extend(detect_partition_table_issues(disks, runner))
    mount_entries = _parse_mounts()
    for partition in partitions:
        findings.extend(inspect_filesystem(partition, mount_entries, runner))
    return tuple(findings)


def collect_optional_diagnostics(
    disks: tuple[Disk, ...],
    partitions: tuple[Partition, ...],
    fstab_entries: tuple[str, ...],
    firmware_mode: str,
    runner: Callable[[Sequence[str]], str] = capture,
    blkid_entries: tuple[str, ...] = (),
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    findings.extend(detect_partition_table_issues(disks, runner))
    mount_entries = _parse_mounts()
    for partition in partitions:
        findings.extend(inspect_filesystem(partition, mount_entries, runner))
    return tuple(findings)


def _detect_efi_evidence(
    partitions: tuple[Partition, ...],
    fstab_entries: tuple[str, ...],
    blkid_entries: tuple[str, ...],
    mount_entries: tuple[tuple[str, str, bool], ...],
) -> bool:
    """Check multiple sources for EFI System Partition evidence."""
    
    # Check partitions from lsblk/pyudev/blkid
    for partition in partitions:
        lower_fs = partition.fs_type.lower()
        lower_label = partition.label.lower()
        lower_flags = partition.flags.lower()
        if lower_fs in {'vfat', 'fat', 'fat32'}:
            if partition.mount_point in {'/boot/efi', '/efi', '/boot'}:
                return True
            if partition.bootable or 'esp' in lower_flags or 'boot' in lower_flags:
                return True
            if 'efi' in lower_label or 'esp' in lower_label:
                return True
    
    # Check fstab for EFI mount points
    for entry in fstab_entries:
        fields = entry.split()
        if len(fields) >= 3:
            mount_point = fields[1]
            fs_type = fields[2].lower()
            if fs_type in {'vfat', 'fat', 'fat32'} and mount_point in {'/boot/efi', '/efi', '/boot'}:
                return True
    
    # Check blkid for FAT filesystems that might be EFI
    for entry in blkid_entries:
        lower_entry = entry.lower()
        if 'type="vfat"' in lower_entry or 'type="fat"' in lower_entry or 'type="fat32"' in lower_entry:
            if 'partlabel="efi"' in lower_entry or 'partlabel="esp"' in lower_entry or 'label="efi"' in lower_entry:
                return True
            # Look for common EFI mount points in mounts
            for device, mount_point, _ in mount_entries:
                if mount_point in {'/boot/efi', '/efi', '/boot'} and device in entry:
                    return True
    
    # Check /proc/mounts for EFI mounts
    for device, mount_point, _ in mount_entries:
        if mount_point in {'/boot/efi', '/efi', '/boot'}:
            # Check if it's a FAT filesystem by looking at device in blkid
            for entry in blkid_entries:
                if device in entry and ('TYPE="vfat"' in entry or 'TYPE="fat"' in entry or 'TYPE="fat32"' in entry):
                    return True
    
    return False


def collect_diagnostics(
    disks: tuple[Disk, ...],
    partitions: tuple[Partition, ...],
    fstab_entries: tuple[str, ...],
    firmware_mode: str,
    runner: Callable[[Sequence[str]], str],
    blkid_entries: tuple[str, ...] = (),
    run_optional_diagnostics: bool = True,
) -> tuple[DiagnosticFinding, ...]:
    findings: list[DiagnosticFinding] = []
    findings.extend(_detect_btrfs_layout(partitions, fstab_entries))
    
    mount_entries = _parse_mounts()
    
    # Enhanced EFI detection
    if firmware_mode.lower() == 'uefi':
        efi_evidence = _detect_efi_evidence(partitions, fstab_entries, blkid_entries, mount_entries)
        if not efi_evidence:
            findings.append(
                DiagnosticFinding(
                    DiagnosticCategory.EFI_MISSING,
                    'UEFI boot mode detected but no EFI System Partition evidence found',
                    severity=RiskLevel.HIGH,
                    evidence='checked partitions, fstab, blkid, and mounts for EFI indicators',
                )
            )
    
    findings.extend(_detect_boot_partition_issues(partitions, runner))
    findings.extend(_detect_fstab_issues(fstab_entries))

    if run_optional_diagnostics:
        try:
            findings = tuple(findings) + collect_optional_diagnostics(
                disks,
                partitions,
                fstab_entries,
                firmware_mode,
                runner,
                blkid_entries,
            )
        except Exception as exc:
            logger.warning(
                'Optional diagnostics skipped due to internal error: %s',
                exc,
                exc_info=exc,
            )
    return tuple(findings)