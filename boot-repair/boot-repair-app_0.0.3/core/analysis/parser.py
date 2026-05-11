from typing import Callable, Sequence
import logging

logger = logging.getLogger(__name__)

from core.models import Disk, Partition
from core.system import CommandError, CommandNotFoundError, capture


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


def parse_fallback_sources(
    blkid_command: tuple[str, ...] = ('blkid', '-o', 'export'),
    command_runner: Callable[[Sequence[str]], str] = capture,
) -> tuple[tuple[Disk, ...], tuple[Partition, ...], tuple[Partition, ...], tuple[str, ...]]:
    """Parse fallback sources like blkid and findmnt for additional device information."""
    logger.info("Parsing fallback sources")
    notes: list[str] = []
    
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

    # Try findmnt for mount information
    findmnt_partitions: tuple[Partition, ...] = ()
    try:
        findmnt_payload = command_runner(('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'))
        logger.debug(f"findmnt raw payload: {findmnt_payload[:500]}...")
        findmnt_partitions = _parse_findmnt_entries(findmnt_payload)
        logger.info(f"findmnt parsing: {len(findmnt_partitions)} partitions")
    except (CommandError, FileNotFoundError):
        notes.append('findmnt unavailable, using /proc/mounts fallback')
        logger.warning('findmnt failed, using /proc/mounts fallback')

    return blkid_disks, blkid_partitions, findmnt_partitions, tuple(notes)