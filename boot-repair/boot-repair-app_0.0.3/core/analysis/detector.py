"""Device detection and parsing.

This module handles detection of disks and partitions using multiple methods:
- Primary: pyudev for direct device enumeration
- Fallback: lsblk for JSON-based device listing
- Additional: blkid and findmnt for supplementary information
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Sequence
import json
import logging

logger = logging.getLogger(__name__)

from core.models import Disk, Partition
from core.privileged import sudo_command
from core.system import (
    CommandError,
    CommandNotFoundError,
    CommandTimeoutError,
    capture,
    detect_distribution_family,
    read_os_release,
    suggest_install_command,
)
from core.capabilities import pyudev_available, lsblk_json_available

from .utils import _device_name, _to_int, _to_bool, _normalize_mountpoints, _infer_disk_name


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


def _find_parent_disk_name(device: Any) -> str:
    current = getattr(device, 'parent', None)
    while current is not None:
        if getattr(current, 'subsystem', '') == 'block' and getattr(current, 'device_type', '').lower() == 'disk':
            if getattr(current, 'device_node', None):
                return str(current.device_node)
        current = getattr(current, 'parent', None)
    return ''
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


def detect_devices(
    command_runner: Callable[[Sequence[str]], str] = capture,
) -> tuple[tuple[Disk, ...], tuple[Partition, ...], tuple[str, ...]]:
    """Detect disks and partitions using available methods."""
    logger.info("Starting device detection")
    notes: list[str] = []
    disks = ()
    partitions = ()
    lsblk_success = False
    needs_sudo = False

    # Primary detection via pyudev
    if pyudev_available():
        try:
            pyudev_disks, pyudev_partitions, pyudev_notes = _detect_pyudev_devices()
            notes.extend(pyudev_notes)
            if pyudev_disks or pyudev_partitions:
                disks, partitions = pyudev_disks, pyudev_partitions
                logger.info(f"✓ pyudev detected {len(disks)} disks and {len(partitions)} partitions")
            else:
                notes.append('pyudev detected no block devices, falling back to lsblk')
                logger.warning('pyudev detected no block devices, falling back to lsblk')
        except Exception as exc:
            notes.append(f'pyudev detection failed: {exc}')
            logger.error('pyudev detection failed', exc_info=exc)
    else:
        notes.append('pyudev unavailable, will use lsblk fallback')
        logger.warning('pyudev unavailable, will use lsblk fallback')

    # Fallback to lsblk only when pyudev cannot provide block device data
    if not disks and not partitions:
        try:
            supported_columns = _detect_lsblk_columns(command_runner)
            lsblk_command = ('lsblk', '--json', '--bytes', '--output', ','.join(supported_columns))
            logger.info(f"Detected lsblk columns: {supported_columns}")
        except (CommandError, FileNotFoundError):
            lsblk_command = None
            notes.append('lsblk column detection failed, will use fallbacks')
            logger.warning('lsblk column detection failed')

        if lsblk_command:
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
                    os_release = read_os_release()
                    distribution_family = detect_distribution_family(os_release)
                    if isinstance(exc, CommandNotFoundError) or isinstance(exc, FileNotFoundError):
                        notes.append(suggest_install_command(lsblk_command, distribution_family))

    # If lsblk failed due to permissions, try with sudo
    if not disks and not partitions and not lsblk_success and needs_sudo:
        logger.info("Retrying lsblk with sudo")
        try:
            supported_columns = _detect_lsblk_columns(command_runner)
            lsblk_command = ('sudo', '-E', 'lsblk', '--json', '--bytes', '--output', ','.join(supported_columns))
            lsblk_payload = command_runner(lsblk_command)
            logger.debug(f"lsblk with sudo raw payload: {lsblk_payload[:1000]}...")
            disks, partitions, lsblk_notes = _parse_lsblk(lsblk_payload)
            notes.extend(lsblk_notes)
            lsblk_success = True
            notes.append('lsblk succeeded with elevated privileges')
            logger.info(f"lsblk with sudo successful: {len(disks)} disks, {len(partitions)} partitions")
        except (CommandError, FileNotFoundError) as exc:
            notes.append(f'lsblk with sudo also failed: {exc}')
            logger.error(f'lsblk with sudo failed: {exc}')

    logger.info(f"Device detection complete: {len(disks)} disks, {len(partitions)} partitions")
    return disks, partitions, tuple(notes)