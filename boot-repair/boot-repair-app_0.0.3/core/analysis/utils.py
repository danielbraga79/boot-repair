"""Common utility functions for analysis modules.

This module contains shared helper functions used across the analysis
submodules, including data type conversions, device name normalization,
and mount information parsing.
"""

from pathlib import Path
from typing import Any


def _device_name(name: str) -> str:
    value = str(name).strip()
    return value if value.startswith('/dev/') else f'/dev/{value}'


def _to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, str):
        # Handle comma decimal separator (e.g., "223,6G")
        value = value.replace(',', '.')
        # Remove size suffixes and convert to bytes
        value = value.upper()
        if value.endswith('G'):
            try:
                return int(float(value[:-1]) * 1_000_000_000)
            except ValueError:
                return default
        elif value.endswith('M'):
            try:
                return int(float(value[:-1]) * 1_000_000)
            except ValueError:
                return default
        elif value.endswith('K'):
            try:
                return int(float(value[:-1]) * 1_000)
            except ValueError:
                return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
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


def _infer_disk_name(device: str) -> str:
    if not device.startswith('/dev/'):
        return ''
    if device.startswith('/dev/nvme'):
        if 'p' in device:
            return device.rsplit('p', 1)[0]
        return device
    return device.rstrip('0123456789')


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