"""Environment capabilities detection.

This module provides functions to detect the availability of various tools
and libraries that the boot-repair application can use. This allows the
application to adapt its behavior based on what's available in the environment.
"""

import importlib
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

from core.system import CommandError, CommandNotFoundError, capture


def _check_command(command: str, runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if a command is available and executable."""
    try:
        runner((command, '--version'))
        return True
    except (CommandError, CommandNotFoundError, FileNotFoundError):
        return False


def pyudev_available() -> bool:
    """Check if pyudev library is available."""
    try:
        importlib.import_module('pyudev')
        return True
    except ImportError:
        return False


def lsblk_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if lsblk is available."""
    return _check_command('lsblk', runner)


def lsblk_json_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if lsblk supports JSON output."""
    if not lsblk_available(runner):
        return False
    try:
        output = runner(('lsblk', '--json', '--help'))
        return '--json' in output.lower()
    except (CommandError, CommandNotFoundError, FileNotFoundError):
        return False


def parted_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if parted is available."""
    return _check_command('parted', runner)


def efibootmgr_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if efibootmgr is available."""
    return _check_command('efibootmgr', runner)


def grub_install_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if grub-install is available."""
    return _check_command('grub-install', runner)


def mkinitcpio_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if mkinitcpio is available."""
    return _check_command('mkinitcpio', runner)


def dracut_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if dracut is available."""
    return _check_command('dracut', runner)


def update_initramfs_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if update-initramfs is available."""
    return _check_command('update-initramfs', runner)


def blkid_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if blkid is available."""
    return _check_command('blkid', runner)


def findmnt_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if findmnt is available."""
    return _check_command('findmnt', runner)


def fsck_ext4_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if fsck.ext4 is available."""
    return _check_command('fsck.ext4', runner)


def xfs_repair_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if xfs_repair is available."""
    return _check_command('xfs_repair', runner)


def btrfs_check_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if btrfs check is available."""
    return _check_command('btrfs', runner)


def fsck_fat_available(runner: Callable[[tuple[str, ...]], str] = capture) -> bool:
    """Check if fsck.fat is available."""
    return _check_command('fsck.fat', runner)


def get_capabilities(runner: Callable[[tuple[str, ...]], str] = capture) -> dict[str, bool]:
    """Get a dictionary of all detected capabilities."""
    return {
        'pyudev': pyudev_available(),
        'lsblk': lsblk_available(runner),
        'lsblk_json': lsblk_json_available(runner),
        'parted': parted_available(runner),
        'efibootmgr': efibootmgr_available(runner),
        'grub_install': grub_install_available(runner),
        'mkinitcpio': mkinitcpio_available(runner),
        'dracut': dracut_available(runner),
        'update_initramfs': update_initramfs_available(runner),
        'blkid': blkid_available(runner),
        'findmnt': findmnt_available(runner),
        'fsck_ext4': fsck_ext4_available(runner),
        'xfs_repair': xfs_repair_available(runner),
        'btrfs_check': btrfs_check_available(runner),
        'fsck_fat': fsck_fat_available(runner),
    }