"""Evidence collection and analysis orchestration.

This module coordinates the collection of system evidence from multiple sources,
merging device information and running diagnostics to provide a comprehensive
view of the system's boot configuration.

Evidence is cached temporarily to improve performance and reduce latency.
"""

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Sequence
import logging

logger = logging.getLogger(__name__)

from core.models import AnalysisEvidence, DiagnosticFinding, Disk, Partition
from core.system import capture, detect_distribution, detect_distribution_family, detect_initramfs_tool, read_os_release

from .detector import detect_devices
from .parser import parse_fallback_sources
from .diagnostics import collect_diagnostics
from .firmware import detect_firmware_and_environment
from .utils import _parse_mounts, _infer_disk_name

# Cache settings
CACHE_FILE = Path('/tmp/boot-repair-evidence-cache.json')
CACHE_TTL_SECONDS = 30  # Short TTL for safety


def _load_cached_evidence() -> AnalysisEvidence | None:
    """Load evidence from cache if valid."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        if time.time() - data.get('timestamp', 0) > CACHE_TTL_SECONDS:
            logger.debug('Cache expired')
            return None
        # Reconstruct AnalysisEvidence from dict
        return AnalysisEvidence(
            disks=tuple(Disk(**d) for d in data['disks']),
            partitions=tuple(Partition(**p) for p in data['partitions']),
            blkid_entries=tuple(data['blkid_entries']),
            fstab_entries=tuple(data['fstab_entries']),
            firmware_mode=data['firmware_mode'],
            live_environment=data['live_environment'],
            distribution=data['distribution'],
            distribution_family=data['distribution_family'],
            initramfs_tool=data['initramfs_tool'],
            diagnostic_findings=tuple(DiagnosticFinding(**f) for f in data['diagnostic_findings']),
            notes=tuple(data['notes']),
        )
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        logger.debug(f'Failed to load cache: {exc}')
        return None


def _save_cached_evidence(evidence: AnalysisEvidence) -> None:
    """Save evidence to cache."""
    try:
        data = {
            'timestamp': time.time(),
            'disks': [asdict(d) for d in evidence.disks],
            'partitions': [asdict(p) for p in evidence.partitions],
            'blkid_entries': list(evidence.blkid_entries),
            'fstab_entries': list(evidence.fstab_entries),
            'firmware_mode': evidence.firmware_mode,
            'live_environment': evidence.live_environment,
            'distribution': evidence.distribution,
            'distribution_family': evidence.distribution_family,
            'initramfs_tool': evidence.initramfs_tool,
            'diagnostic_findings': [asdict(f) for f in evidence.diagnostic_findings],
            'notes': list(evidence.notes),
            'windows_present': evidence.windows_present,
        }
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
        logger.debug('Evidence cached')
    except OSError as exc:
        logger.debug(f'Failed to save cache: {exc}')


def _read_fstab(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()

    lines: list[str] = []
    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if line and not line.startswith('#'):
            lines.append(line)
    return tuple(lines)


def _resolve_mount_graph(
    fstab_entries: tuple[str, ...],
    mount_entries: tuple[tuple[str, str, bool], ...],
) -> tuple[str, ...]:
    lines: list[str] = []
    for device, mount_point, ro in mount_entries:
        lines.append(f'{mount_point} mounted from {device}{" (ro)" if ro else ""}')
    for entry in fstab_entries:
        fields = entry.split()
        if len(fields) < 3:
            continue
        lines.append(f'{fields[1]} configured from {fields[0]} as {fields[2]}')
    return tuple(lines)


def _resolve_mount_graph(
    fstab_entries: tuple[str, ...],
    mount_entries: tuple[tuple[str, str, bool], ...],
) -> tuple[str, ...]:
    lines: list[str] = []
    for device, mount_point, ro in mount_entries:
        lines.append(f'{mount_point} mounted from {device}{" (ro)" if ro else ""}')
    for entry in fstab_entries:
        fields = entry.split()
        if len(fields) < 3:
            continue
        lines.append(f'{fields[1]} configured from {fields[0]} as {fields[2]}')
    return tuple(lines)


def _merge_device_info(
    primary_disks: tuple[Disk, ...],
    primary_partitions: tuple[Partition, ...],
    fallback_disks: tuple[Disk, ...],
    fallback_partitions: tuple[Partition, ...],
) -> tuple[tuple[Disk, ...], tuple[Partition, ...]]:
    """Merge device information from multiple sources."""
    # Start with primary source
    disk_lookup = {d.name: d for d in primary_disks}
    part_lookup = {p.name: p for p in primary_partitions}
    
    # Add disks from fallback if not present
    for fb_disk in fallback_disks:
        if fb_disk.name not in disk_lookup:
            disk_lookup[fb_disk.name] = fb_disk
        else:
            # Merge disk info, preferring non-zero values
            existing = disk_lookup[fb_disk.name]
            merged = Disk(
                name=existing.name,
                size_bytes=existing.size_bytes or fb_disk.size_bytes,
                model=existing.model or fb_disk.model,
                serial=existing.serial or fb_disk.serial,
                removable=existing.removable or fb_disk.removable,
                transport=existing.transport or fb_disk.transport,
                path=existing.path or fb_disk.path,
            )
            disk_lookup[fb_disk.name] = merged
    
    # Add/merge partitions from fallback
    for fb_part in fallback_partitions:
        if fb_part.name not in part_lookup:
            disk_name = fb_part.disk_name or _infer_disk_name(fb_part.name)
            part_lookup[fb_part.name] = Partition(
                name=fb_part.name,
                disk_name=disk_name,
                size_bytes=fb_part.size_bytes,
                fs_type=fb_part.fs_type,
                mount_point=fb_part.mount_point,
                uuid=fb_part.uuid,
                bootable=fb_part.bootable,
                label=fb_part.label,
                partuuid=fb_part.partuuid,
                flags=fb_part.flags,
            )
        else:
            # Merge partition info, preferring non-empty values
            existing = part_lookup[fb_part.name]
            merged = Partition(
                name=existing.name,
                disk_name=existing.disk_name or fb_part.disk_name or _infer_disk_name(fb_part.name),
                size_bytes=existing.size_bytes or fb_part.size_bytes,
                fs_type=existing.fs_type or fb_part.fs_type,
                mount_point=existing.mount_point or fb_part.mount_point,
                uuid=existing.uuid or fb_part.uuid,
                bootable=existing.bootable or fb_part.bootable,
                label=existing.label or fb_part.label,
                partuuid=existing.partuuid or fb_part.partuuid,
                flags=existing.flags or fb_part.flags,
            )
            part_lookup[fb_part.name] = merged

    # Ensure we have at least minimal disk records for known partition owners
    for partition in part_lookup.values():
        if partition.disk_name and partition.disk_name not in disk_lookup:
            disk_lookup[partition.disk_name] = Disk(name=partition.disk_name, size_bytes=0)

    return tuple(disk_lookup.values()), tuple(part_lookup.values())


def _detect_windows_evidence(
    partitions: tuple[Partition, ...],
    blkid_entries: tuple[str, ...],
    mount_entries: tuple[tuple[str, str, bool], ...],
    runner: Callable[[Sequence[str]], str],
) -> bool:
    """Detect evidence of Windows installation on the target system."""
    lower_labels = {partition.label.strip().lower() for partition in partitions if partition.label}
    if any(partition.fs_type.lower() == 'ntfs' for partition in partitions if partition.fs_type):
        return True
    if any('windows' in label or 'microsoft' in label for label in lower_labels):
        return True
    for entry in blkid_entries:
        lower_entry = entry.lower()
        if 'type="ntfs"' in lower_entry or 'type="fuseblk"' in lower_entry:
            return True
    for partition in partitions:
        if partition.mount_point and partition.mount_point.startswith('/'):
            try:
                output = runner(('test', '-f', f'{partition.mount_point}/EFI/Microsoft/Boot/bootmgfw.efi'))
                if output.strip() == '':
                    return True
            except Exception:
                pass
    try:
        efibootmgr_output = runner(('efibootmgr', '-v'))
        if 'windows boot manager' in efibootmgr_output.lower() or 'bootmgfw.efi' in efibootmgr_output.lower():
            return True
    except Exception:
        pass
    return False


def collect_evidence(
    *,
    fstab_path: Path | str = Path('/etc/fstab'),
    lsblk_command: tuple[str, ...] | None = None,
    blkid_command: tuple[str, ...] = ('blkid', '-o', 'export'),
    command_runner: Callable[[Sequence[str]], str] = capture,
    run_optional_diagnostics: bool = False,
    parse_mounts: Callable[[], tuple[tuple[str, str, bool], ...]] | None = None,
    use_cache: bool = True,
) -> AnalysisEvidence:
    if parse_mounts is None:
        parse_mounts = _parse_mounts

    # Check cache first
    if use_cache:
        cached = _load_cached_evidence()
        if cached is not None:
            logger.info('Using cached evidence')
            return cached

    logger.info("====== EVIDENCE COLLECTION STARTED ======")
    logger.info("CRITICAL PHASE: Core disk/partition detection")
    notes: list[str] = []
    os_release = read_os_release()
    distribution = detect_distribution(os_release)
    distribution_family = detect_distribution_family(os_release)
    logger.info(f"Detected distribution: {distribution} (family: {distribution_family})")

    # Detect firmware and environment
    firmware_mode, live_environment = detect_firmware_and_environment()
    logger.info(f"Detected firmware mode: {firmware_mode}")

    # Primary device detection
    disks, partitions, detection_notes = detect_devices(command_runner)
    notes.extend(detection_notes)

    # Fallback sources
    logger.info("Collecting fallback data from blkid and findmnt")
    blkid_disks, blkid_partitions, findmnt_partitions, fallback_notes = parse_fallback_sources(blkid_command, command_runner)
    notes.extend(fallback_notes)

    proc_mount_partitions: list[Partition] = []
    if not findmnt_partitions:
        for device, mount_point, _ in parse_mounts():
            if device.startswith('/dev/'):
                proc_mount_partitions.append(Partition(
                    name=device,
                    disk_name=_infer_disk_name(device),
                    size_bytes=0,
                    fs_type='',
                    mount_point=mount_point,
                ))
        if proc_mount_partitions:
            notes.append('using /proc/mounts fallback for mount information')
            logger.info('Using /proc/mounts fallback for mount information')

    # Merge information from all sources
    logger.info("Merging device information from all sources")
    disks, partitions = _merge_device_info(disks, partitions, blkid_disks, blkid_partitions + findmnt_partitions + tuple(proc_mount_partitions))
    
    logger.info(f"After merge: {len(disks)} disks, {len(partitions)} partitions")

    blkid_entries = ()
    if blkid_disks or blkid_partitions:
        try:
            blkid_payload = command_runner(blkid_command)
            blkid_entries = tuple(line.strip() for line in blkid_payload.splitlines() if line.strip())
        except Exception:
            blkid_entries = ()

    fstab_entries = _read_fstab(Path(fstab_path))
    if not fstab_entries:
        notes.append('fstab has no active entries or could not be read')
        logger.warning('fstab is empty or unreadable')

    logger.info("====== CRITICAL DETECTION PHASE COMPLETE ======")
    logger.info(f"Core detection result: {len(disks)} disks, {len(partitions)} partitions")
    
    diagnostic_findings: tuple[DiagnosticFinding, ...] = ()
    if run_optional_diagnostics:
        logger.info("====== OPTIONAL DIAGNOSTICS PHASE STARTING ======")
    try:
        diagnostic_findings = collect_diagnostics(
            disks,
            partitions,
            fstab_entries,
            firmware_mode,
            command_runner,
            blkid_entries,
            run_optional_diagnostics=run_optional_diagnostics,
        )
    except Exception as exc:
        notes.append('optional diagnostics failed to complete')
        logger.warning('Optional diagnostics failed during evidence collection, continuing without them: %s', exc, exc_info=exc)

    mount_graph = _resolve_mount_graph(fstab_entries, parse_mounts())
    if mount_graph:
        notes.extend(mount_graph)

    # Add summary notes about detection
    if disks:
        notes.append(f'detected {len(disks)} disk(s)')
        logger.info(f"Final result: {len(disks)} disks detected")
    else:
        notes.append('no disks detected from any source')
        logger.warning('No disks detected from any source')
    if partitions:
        notes.append(f'detected {len(partitions)} partition(s)')
        logger.info(f"Final result: {len(partitions)} partitions detected")
    else:
        notes.append('no partitions detected from any source')
        logger.warning('No partitions detected from any source')

    windows_present = _detect_windows_evidence(partitions, blkid_entries, _parse_mounts(), command_runner)
    if windows_present:
        notes.append('Windows installation evidence detected')

    evidence = AnalysisEvidence(
        disks=disks,
        partitions=partitions,
        blkid_entries=blkid_entries,
        fstab_entries=fstab_entries,
        firmware_mode=firmware_mode,
        live_environment=live_environment,
        distribution=distribution,
        distribution_family=distribution_family,
        initramfs_tool=detect_initramfs_tool(),
        windows_present=windows_present,
        diagnostic_findings=diagnostic_findings,
        notes=tuple(notes),
    )
    
    logger.info(f"====== EVIDENCE COLLECTION COMPLETE ======")
    logger.info(f"Final: {len(evidence.disks)} disks, {len(evidence.partitions)} partitions detected")
    
    if evidence.disks or evidence.partitions:
        logger.info("✓ Sufficient evidence for GUI initialization")
    else:
        logger.warning("✗ No disks or partitions detected")
    
    if diagnostic_findings:
        logger.info(f"Optional diagnostics found {len(diagnostic_findings)} issue(s)")
    
    # Cache the evidence
    if use_cache:
        _save_cached_evidence(evidence)
    
    return evidence