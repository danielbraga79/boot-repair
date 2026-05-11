from __future__ import annotations

from typing import Any
import logging

logger = logging.getLogger(__name__)

from .analysis.evidence_builder import collect_evidence


def analyze_system(**kwargs: Any) -> Any:
    return collect_evidence(**kwargs)from __future__ import annotations

from typing import Any
import logging

logger = logging.getLogger(__name__)

from .analysis.evidence_builder import collect_evidence


def analyze_system(**kwargs: Any) -> Any:
    return collect_evidence(**kwargs)
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}
    return False


def _normalize_mountpoints(mountpoints: Any) -> str:
    """Normalize mountpoints field to a single mount point string."""
    if isinstance(mountpoints, list):
        # Take the first non-null mount point
        for mp in mountpoints:
            if mp:
                return str(mp).strip()
        return ''
    elif isinstance(mountpoints, str):
        return mountpoints.strip()
    return ''


def _get_udev_string(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace').strip()
    return str(value).strip()


def _get_udev_property(device: Any, key: str) -> str:
    return _get_udev_string(device.properties.get(key, '')) if hasattr(device, 'properties') else ''


def _get_udev_attribute(device: Any, key: str) -> str:
    try:
        if hasattr(device, 'attributes'):
            value = device.attributes.get(key)
            return _get_udev_string(value)
    except OSError:
        pass
    return ''


def _is_physical_block_disk(device: Any) -> bool:
    if getattr(device, 'device_type', '').lower() != 'disk':
        return False
    name = str(getattr(device, 'sys_name', '') or '')
    if name.startswith(('loop', 'ram', 'dm-', 'sr', 'md', 'zram', 'fd')):
        return False
    return True


def _is_standard_partition(device: Any) -> bool:
    if getattr(device, 'device_type', '').lower() != 'partition':
        return False
    name = str(getattr(device, 'device_node', '') or '')
    if name.startswith(('/dev/loop', '/dev/ram', '/dev/dm-', '/dev/ram', '/dev/loop')):
        return False
    return True


def _infer_disk_name(device: str) -> str:
    if not device.startswith('/dev/'):
        return ''
    if device.startswith('/dev/nvme') and 'p' in device:
        return device.rsplit('p', 1)[0]
    return device.rstrip('0123456789')


def _find_parent_disk_name(device: Any) -> str:
    current = getattr(device, 'parent', None)
    while current is not None:
        if getattr(current, 'subsystem', '') == 'block' and getattr(current, 'device_type', '').lower() == 'disk':
            if getattr(current, 'device_node', None):
                return str(current.device_node)
        current = getattr(current, 'parent', None)
    return ''


def _pyudev_disk_transport(device: Any) -> str:
    transport = _get_udev_property(device, 'ID_BUS') or _get_udev_property(device, 'ID_PATH')
    if transport:
        return transport.lower()
    sys_name = str(getattr(device, 'sys_name', '') or '')
    if sys_name.startswith('nvme'):
        return 'nvme'
    if sys_name.startswith(('sd', 'hd', 'mmcblk')):
        return 'sata'
    return ''


def _parse_pyudev_device(device: Any) -> tuple[Disk | None, Partition | None]:
    device_node = getattr(device, 'device_node', None)
    if not device_node:
        return None, None
    device_node = str(device_node).strip()
    kind = str(getattr(device, 'device_type', '') or _get_udev_property(device, 'DEVTYPE')).strip().lower()
    if kind == 'disk':
        if not _is_physical_block_disk(device):
            return None, None
        size = 0
        size_value = _get_udev_attribute(device, 'size')
        if size_value.isdigit():
            size = int(size_value) * 512
        disk = Disk(
            name=device_node,
            size_bytes=size,
            model=_get_udev_property(device, 'ID_MODEL') or _get_udev_property(device, 'ID_MODEL_ENC'),
            serial=_get_udev_property(device, 'ID_SERIAL_SHORT') or _get_udev_property(device, 'ID_SERIAL'),
            removable=_to_bool(_get_udev_attribute(device, 'removable')),
            transport=_pyudev_disk_transport(device),
            path=device_node,
        )
        return disk, None
    if kind == 'partition':
        size = 0
        size_value = _get_udev_attribute(device, 'size')
        if size_value.isdigit():
            size = int(size_value) * 512
        disk_name = _find_parent_disk_name(device) or _infer_disk_name(device_node)
        raw_flags = _get_udev_property(device, 'ID_PART_ENTRY_FLAGS') or _get_udev_property(device, 'PARTFLAGS')
        partition = Partition(
            name=device_node,
            disk_name=disk_name,
            size_bytes=size,
            fs_type=_get_udev_property(device, 'ID_FS_TYPE'),
            mount_point='',
            uuid=_get_udev_property(device, 'ID_FS_UUID'),
            bootable='boot' in raw_flags.lower().split() if raw_flags else False,
            label=_get_udev_property(device, 'ID_FS_LABEL') or _get_udev_property(device, 'ID_PART_ENTRY_NAME'),
            partuuid=_get_udev_property(device, 'ID_PART_ENTRY_UUID') or _get_udev_property(device, 'PARTUUID') or _get_udev_property(device, 'ID_PART_TABLE_UUID'),
            flags=raw_flags,
        )
        return None, partition
    return None, None


def _detect_pyudev_devices() -> tuple[tuple[Disk, ...], tuple[Partition, ...], tuple[str, ...]]:
    notes: list[str] = []
    try:
        pyudev = importlib.import_module('pyudev')
    except ImportError as exc:
        raise

    try:
        context = pyudev.Context()
    except Exception as exc:
        raise RuntimeError(f'pyudev context initialization failed: {exc}') from exc

    disks: dict[str, Disk] = {}
    partitions: list[Partition] = []
    for device in context.list_devices(subsystem='block'):
        disk, partition = _parse_pyudev_device(device)
        if disk is not None:
            disks[disk.name] = disk
        if partition is not None:
            partitions.append(partition)
            if partition.disk_name and partition.disk_name not in disks:
                disks[partition.disk_name] = Disk(name=partition.disk_name, size_bytes=0, path=partition.disk_name)

    notes.append(f'pyudev detected {len(disks)} disks and {len(partitions)} partitions')
    return tuple(disks.values()), tuple(partitions), tuple(notes)


def _parse_entry(
    entry: dict[str, Any],
    disks: list[Disk],
    partitions: list[Partition],
    parent_disk: str = '',
) -> None:
    name = str(entry.get('name', '')).strip()
    if not name:
        logger.debug("Entry has no name, skipping")
        return

    dev_name = _device_name(name)
    kind = str(entry.get('type', '')).strip().lower()
    size = _to_int(entry.get('size'))
    model = str(entry.get('model', '') or '')
    serial = str(entry.get('serial', '') or '')
    removable = _to_bool(entry.get('rm'))

    logger.debug(f"Processing {kind}: {dev_name} (size: {size})")

    if kind == 'disk':
        disk = Disk(name=dev_name, size_bytes=size, model=model, serial=serial, removable=removable)
        disks.append(disk)
        logger.debug(f"Added disk: {disk}")
        for child in entry.get('children', []) or []:
            if isinstance(child, dict):
                _parse_entry(child, disks, partitions, dev_name)
        return

    if kind == 'part':
        # Handle both 'mountpoint' (legacy) and 'mountpoints' (current)
        mount_point = _normalize_mountpoints(entry.get('mountpoints') or entry.get('mountpoint'))
        
        partition = Partition(
            name=dev_name,
            disk_name=parent_disk or str(entry.get('pkname', '') or ''),
            size_bytes=size,
            fs_type=str(entry.get('fstype', '') or ''),
            mount_point=mount_point,
            uuid=str(entry.get('uuid', '') or ''),
            bootable=_to_bool(entry.get('boot')),
            label=str(entry.get('label', '') or entry.get('partlabel', '') or ''),
            partuuid=str(entry.get('partuuid', '') or entry.get('PARTUUID', '') or ''),
            flags=str(entry.get('partflags', '') or ''),
        )
        partitions.append(partition)
        logger.debug(f"Added partition: {partition}")

    for child in entry.get('children', []) or []:
        if isinstance(child, dict):
            _parse_entry(child, disks, partitions, parent_disk or str(entry.get('pkname', '') or ''))


def _detect_lsblk_columns(command_runner: Callable[[Sequence[str]], str]) -> tuple[str, ...]:
    """Detect supported lsblk columns dynamically."""
    # Start with minimal safe columns that are widely supported
    base_columns = ['NAME', 'SIZE', 'TYPE', 'FSTYPE', 'MOUNTPOINT', 'UUID', 'PKNAME']
    optional_columns = ['MODEL', 'SERIAL', 'RM', 'BOOT', 'PARTUUID', 'PARTLABEL', 'PARTFLAGS']
    
    supported = list(base_columns)
    
    # Test each optional column
    for col in optional_columns:
        test_columns = ','.join(supported + [col])
        try:
            command_runner(('lsblk', '--json', '--bytes', '--output', test_columns))
            supported.append(col)
        except (CommandError, FileNotFoundError):
            continue
    
    return tuple(supported)


def _parse_blk_entries(blkid_payload: str) -> tuple[tuple[Disk, ...], tuple[Partition, ...]]:
    """Parse blkid output to extract basic device information."""
    disks: list[Disk] = []
    partitions: list[Partition] = []
    
    for line in blkid_payload.splitlines():
        line = line.strip()
        if not line:
            continue
        
        # blkid output format: DEVICE=UUID=TYPE=etc.
        parts = dict()
        for pair in line.split():
            if '=' in pair:
                key, value = pair.split('=', 1)
                parts[key] = value.strip('"')
        
        device = parts.get('DEVNAME', '')
        if not device:
            continue
        
        uuid = parts.get('UUID', '')
        fs_type = parts.get('TYPE', '')
        
        # Determine if it's a disk or partition based on naming
        if device.endswith(('1', '2', '3', '4', '5', '6', '7', '8', '9')) or 'p' in device[-2:]:
            # Likely a partition
            disk_name = device.rstrip('0123456789').rstrip('p')
            if disk_name != device:
                partitions.append(Partition(
                    name=device,
                    disk_name=f'/dev/{disk_name}',
                    size_bytes=0,  # blkid doesn't provide size
                    fs_type=fs_type,
                    uuid=uuid,
                    label=parts.get('LABEL', ''),
                    partuuid=parts.get('PARTUUID', ''),
                ))
        else:
            # Likely a disk
            disks.append(Disk(
                name=device,
                size_bytes=0,  # blkid doesn't provide size
            ))
    
    return tuple(disks), tuple(partitions)


def _parse_findmnt_entries(findmnt_payload: str) -> tuple[Partition, ...]:
    """Parse findmnt output to extract mount information."""
    partitions: list[Partition] = []
    
    for line in findmnt_payload.splitlines():
        line = line.strip()
        if not line or line.startswith('TARGET'):
            continue
        
        fields = line.split()
        if len(fields) < 3:
            continue
        
        mount_point = fields[0]
        fs_type = fields[1] if len(fields) > 1 else ''
        device = fields[2] if len(fields) > 2 else ''
        
        if device and device.startswith('/dev/'):
            partitions.append(Partition(
                name=device,
                disk_name='',  # findmnt doesn't provide disk info
                size_bytes=0,
                fs_type=fs_type,
                mount_point=mount_point,
            ))
    
    return tuple(partitions)


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


def _parse_lsblk(payload: str) -> tuple[tuple[Disk, ...], tuple[Partition, ...], tuple[str, ...]]:
    logger.debug("Starting lsblk payload parsing")
    notes: list[str] = []
    disks: list[Disk] = []
    partitions: list[Partition] = []

    if not payload.strip():
        notes.append('lsblk returned an empty payload')
        logger.warning('lsblk returned empty payload')
        return tuple(disks), tuple(partitions), tuple(notes)

    try:
        data = json.loads(payload)
        logger.debug("lsblk JSON parsed successfully")
    except json.JSONDecodeError as exc:
        notes.append(f'could not parse lsblk json: {exc}')
        logger.error(f'lsblk JSON parsing failed: {exc}')
        logger.debug(f'Raw payload that failed: {payload[:2000]}')
        return tuple(disks), tuple(partitions), tuple(notes)

    entries = data.get('blockdevices', []) if isinstance(data, dict) else []
    if not entries:
        notes.append('lsblk json does not contain blockdevices')
        logger.warning('lsblk JSON does not contain blockdevices')
        return tuple(disks), tuple(partitions), tuple(notes)
    
    logger.debug(f"Found {len(entries)} block devices in lsblk output")
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            _parse_entry(entry, disks, partitions)

    # Don't treat absence of disks/partitions as critical failure
    # They might be detected by other sources
    if not disks:
        notes.append('no disks detected from lsblk (may be available from other sources)')
        logger.info('No disks detected from lsblk')
    else:
        logger.info(f"lsblk detected {len(disks)} disks")
    if not partitions:
        notes.append('no partitions detected from lsblk (may be available from other sources)')
        logger.info('No partitions detected from lsblk')
    else:
        logger.info(f"lsblk detected {len(partitions)} partitions")

    return tuple(disks), tuple(partitions), tuple(notes)


def _read_fstab(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()

    lines: list[str] = []
    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if line and not line.startswith('#'):
            lines.append(line)
    return tuple(lines)


def _firmware_mode() -> str:
    return 'uefi' if Path('/sys/firmware/efi').exists() else 'bios'


def _live_environment() -> bool:
    markers = (Path('/run/live'), Path('/run/archiso'), Path('/cdrom'), Path('/isodevice'))
    if any(marker.exists() for marker in markers):
        return True
    try:
        cmdline = Path('/proc/cmdline').read_text(encoding='utf-8', errors='replace').lower()
    except OSError:
        return False
    return any(token in cmdline for token in ('boot=live', 'toram', 'casper'))


def _parse_mounts() -> tuple[tuple[str, str, bool], ...]:
    entries: list[tuple[str, str, bool]] = []
    try:
        content = Path('/proc/mounts').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ()
    for raw_line in content.splitlines():
        fields = raw_line.split()
        if len(fields) < 4:
            continue
        device = fields[0]
        mount_point = fields[1]
        options = fields[3].split(',')
        entries.append((device, mount_point, 'ro' in options))
    return tuple(entries)


def _detect_partition_table_issues(
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


def _inspect_filesystem(
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
    findings.extend(_detect_partition_table_issues(disks, runner))
    mount_entries = _parse_mounts()
    for partition in partitions:
        findings.extend(_inspect_filesystem(partition, mount_entries, runner))
    return tuple(findings)


def _collect_diagnostics(
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


def collect_evidence(
    *,
    fstab_path: Path | str = Path('/etc/fstab'),
    lsblk_command: tuple[str, ...] | None = None,
    blkid_command: tuple[str, ...] = ('blkid', '-o', 'export'),
    command_runner: Callable[[Sequence[str]], str] = capture,
    run_optional_diagnostics: bool = False,
) -> AnalysisEvidence:
    logger.info("====== EVIDENCE COLLECTION STARTED ======")
    logger.info("CRITICAL PHASE: Core disk/partition detection")
    notes: list[str] = []
    os_release = read_os_release()
    distribution = detect_distribution(os_release)
    distribution_family = detect_distribution_family(os_release)
    logger.info(f"Detected distribution: {distribution} (family: {distribution_family})")

    disks = ()
    partitions = ()
    lsblk_success = False
    needs_sudo = False

    # Primary detection via pyudev
    try:
        pyudev_disks, pyudev_partitions, pyudev_notes = _detect_pyudev_devices()
        notes.extend(pyudev_notes)
        if pyudev_disks or pyudev_partitions:
            disks, partitions = pyudev_disks, pyudev_partitions
            logger.info(f"✓ CRITICAL: pyudev detected {len(disks)} disks and {len(partitions)} partitions")
        else:
            notes.append('pyudev detected no block devices, falling back to lsblk')
            logger.warning('pyudev detected no block devices, falling back to lsblk')
    except ImportError as exc:
        notes.append(f'pyudev unavailable: {exc}')
        logger.warning('pyudev unavailable, will use lsblk fallback')
    except Exception as exc:
        notes.append(f'pyudev detection failed: {exc}')
        logger.error('pyudev detection failed', exc_info=exc)

    # Fallback to lsblk only when pyudev cannot provide block device data
    if (not disks and not partitions) and lsblk_command is None:
        try:
            supported_columns = _detect_lsblk_columns(command_runner)
            lsblk_command = ('lsblk', '--json', '--bytes', '--output', ','.join(supported_columns))
            logger.info(f"Detected lsblk columns: {supported_columns}")
        except (CommandError, FileNotFoundError):
            lsblk_command = None
            notes.append('lsblk column detection failed, will use fallbacks')
            logger.warning('lsblk column detection failed')

    if (not disks and not partitions) and lsblk_command:
        logger.info(f"Attempting lsblk command: {' '.join(lsblk_command)}")
        try:
            lsblk_payload = command_runner(lsblk_command)
            logger.debug(f"lsblk raw payload: {lsblk_payload[:1000]}...")
            disks, partitions, lsblk_notes = _parse_lsblk(lsblk_payload)
            notes.extend(lsblk_notes)
            lsblk_success = True
            logger.info(f"lsblk parsing successful: {len(disks)} disks, {len(partitions)} partitions")
        except (CommandError, FileNotFoundError) as exc:
            error_msg = str(exc).lower()
            stderr_msg = ''
            if isinstance(exc, CommandError) and hasattr(exc, 'result'):
                stderr_msg = getattr(exc.result, 'stderr', '') or ''
            stderr_msg = stderr_msg.lower()
            if (
                'permission denied' in error_msg
                or 'access denied' in error_msg
                or 'operation not permitted' in error_msg
                or 'permission denied' in stderr_msg
                or 'access denied' in stderr_msg
                or 'operation not permitted' in stderr_msg
            ):
                needs_sudo = True
                notes.append('lsblk requires elevated privileges, will try with sudo')
                logger.warning('lsblk failed due to permissions, will try with sudo')
            else:
                notes.append(f'lsblk unavailable: {exc}')
                logger.error(f'lsblk failed: {exc}')
                if isinstance(exc, CommandNotFoundError) or isinstance(exc, FileNotFoundError):
                    notes.append(suggest_install_command(lsblk_command, distribution_family))

    # If lsblk failed due to permissions, try with sudo
    if (not disks and not partitions) and not lsblk_success and needs_sudo and lsblk_command:
        logger.info("Retrying lsblk with sudo")
        try:
            sudo_lsblk_command = ('sudo', '-E', *lsblk_command)
            lsblk_payload = command_runner(sudo_lsblk_command)
            logger.debug(f"lsblk with sudo raw payload: {lsblk_payload[:1000]}...")
            disks, partitions, lsblk_notes = _parse_lsblk(lsblk_payload)
            notes.extend(lsblk_notes)
            lsblk_success = True
            notes.append('lsblk succeeded with elevated privileges')
            logger.info(f"lsblk with sudo successful: {len(disks)} disks, {len(partitions)} partitions")
        except (CommandError, FileNotFoundError) as exc:
            notes.append(f'lsblk with sudo also failed: {exc}')
            logger.error(f'lsblk with sudo failed: {exc}')

    # Fallback sources even if lsblk succeeded, to enrich data
    logger.info("Collecting fallback data from blkid and findmnt")
    blkid_disks = ()
    blkid_partitions = ()
    blkid_payload: str | None = None
    try:
        blkid_payload = command_runner(blkid_command)
        logger.debug(f"blkid raw payload: {blkid_payload[:500]}...")
        blkid_disks, blkid_partitions = _parse_blk_entries(blkid_payload)
        logger.info(f"blkid parsing: {len(blkid_disks)} disks, {len(blkid_partitions)} partitions")
    except (CommandError, FileNotFoundError) as exc:
        notes.append(f'blkid unavailable: {exc}')
        logger.warning(f'blkid failed: {exc}')
        if isinstance(exc, CommandNotFoundError) or isinstance(exc, FileNotFoundError):
            notes.append(suggest_install_command(blkid_command, distribution_family))

    # Try findmnt for mount information
    findmnt_partitions = ()
    try:
        findmnt_payload = command_runner(('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'))
        logger.debug(f"findmnt raw payload: {findmnt_payload[:500]}...")
        findmnt_partitions = _parse_findmnt_entries(findmnt_payload)
        logger.info(f"findmnt parsing: {len(findmnt_partitions)} partitions")
    except (CommandError, FileNotFoundError):
        notes.append('findmnt unavailable, using /proc/mounts fallback')
        logger.warning('findmnt failed, using /proc/mounts fallback')

    proc_mount_entries = _parse_mounts()
    proc_mount_partitions: list[Partition] = []
    if not findmnt_partitions and proc_mount_entries:
        notes.append('using /proc/mounts fallback for mount information')
        logger.info('Using /proc/mounts fallback for mount information')
        for device, mount_point, _ in proc_mount_entries:
            if device.startswith('/dev/'):
                proc_mount_partitions.append(Partition(
                    name=device,
                    disk_name=_infer_disk_name(device),
                    size_bytes=0,
                    fs_type='',
                    mount_point=mount_point,
                ))

    # Merge information from all sources
    logger.info("Merging device information from all sources")
    disks, partitions = _merge_device_info(disks, partitions, blkid_disks, blkid_partitions)
    # Add mount info from findmnt or /proc/mounts fallback
    if findmnt_partitions or proc_mount_partitions:
        disks, partitions = _merge_device_info(disks, partitions, (), tuple(findmnt_partitions) + tuple(proc_mount_partitions))
    
    logger.info(f"After merge: {len(disks)} disks, {len(partitions)} partitions")

    blkid_entries = ()
    if blkid_disks or blkid_partitions:
        try:
            blkid_payload = command_runner(blkid_command)
            blkid_entries = tuple(line.strip() for line in blkid_payload.splitlines() if line.strip())
        except (CommandError, FileNotFoundError):
            blkid_entries = ()

    fstab_entries = _read_fstab(Path(fstab_path))
    if not fstab_entries:
        notes.append('fstab has no active entries or could not be read')
        logger.warning('fstab is empty or unreadable')

    firmware_mode = _firmware_mode()
    logger.info(f"Detected firmware mode: {firmware_mode}")
    
    logger.info("====== CRITICAL DETECTION PHASE COMPLETE ======")
    logger.info(f"Core detection result: {len(disks)} disks, {len(partitions)} partitions")
    
    diagnostic_findings: tuple[DiagnosticFinding, ...] = ()
    if run_optional_diagnostics:
        logger.info("====== OPTIONAL DIAGNOSTICS PHASE STARTING ======")
    try:
        diagnostic_findings = _collect_diagnostics(
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

    mount_graph = _resolve_mount_graph(fstab_entries, _parse_mounts())
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

    evidence = AnalysisEvidence(
        disks=disks,
        partitions=partitions,
        blkid_entries=blkid_entries,
        fstab_entries=fstab_entries,
        firmware_mode=firmware_mode,
        live_environment=_live_environment(),
        distribution=distribution,
        distribution_family=distribution_family,
        initramfs_tool=detect_initramfs_tool(),
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
    
    return evidence


def analyze_system(**kwargs: Any) -> AnalysisEvidence:
    return collect_evidence(**kwargs)
