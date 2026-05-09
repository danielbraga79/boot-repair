from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from core.models import DistributionFamily


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(f"command failed with return code {result.returncode}: {' '.join(result.command)}")


class CommandTimeoutError(TimeoutError):
    def __init__(self, command: Sequence[str], timeout: int) -> None:
        self.command = tuple(command)
        self.timeout = timeout
        super().__init__(f"command timed out after {timeout}s: {' '.join(self.command)}")


class CommandNotFoundError(FileNotFoundError):
    def __init__(self, command: Sequence[str]) -> None:
        self.command = tuple(command)
        super().__init__(f"command not found: {' '.join(self.command)}")


def read_os_release(path: Path | str = Path('/etc/os-release')) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        content = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return result

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        value = value.strip().strip('"').strip("'")
        result[key] = value
    return result


def detect_distribution(os_release: dict[str, str] | None = None) -> str:
    os_release = os_release or read_os_release()
    identity = os_release.get('ID', '').lower()
    like = os_release.get('ID_LIKE', '').lower().split()

    if identity in ARCH_LIKE or any(item in ARCH_LIKE for item in like):
        return identity or 'arch'
    if identity in DEBIAN_LIKE or any(item in DEBIAN_LIKE for item in like):
        if identity in {'linuxmint', 'pop', 'elementary'}:
            return 'ubuntu'
        return identity or 'debian'
    if identity:
        return identity
    return 'unknown'


def detect_initramfs_tool() -> str:
    if shutil.which('mkinitcpio') is not None:
        return 'mkinitcpio'
    if shutil.which('dracut') is not None:
        return 'dracut'
    if shutil.which('update-initramfs') is not None:
        return 'update-initramfs'
    return 'unknown'


ARCH_LIKE = {'arch', 'archlinux', 'manjaro', 'cachyos', 'endeavouros'}
DEBIAN_LIKE = {'debian', 'ubuntu', 'linuxmint', 'pop', 'elementary', 'kali'}

COMMAND_PACKAGE_HINTS: dict[str, dict[DistributionFamily, str]] = {
    'lsblk': {
        DistributionFamily.DEBIAN: 'sudo apt install util-linux',
        DistributionFamily.ARCH: 'sudo pacman -S util-linux',
        DistributionFamily.UNKNOWN: 'install the util-linux package for your distribution',
    },
    'blkid': {
        DistributionFamily.DEBIAN: 'sudo apt install util-linux',
        DistributionFamily.ARCH: 'sudo pacman -S util-linux',
        DistributionFamily.UNKNOWN: 'install the util-linux package for your distribution',
    },
    'parted': {
        DistributionFamily.DEBIAN: 'sudo apt install parted',
        DistributionFamily.ARCH: 'sudo pacman -S parted',
        DistributionFamily.UNKNOWN: 'install parted for your distribution',
    },
    'fdisk': {
        DistributionFamily.DEBIAN: 'sudo apt install util-linux',
        DistributionFamily.ARCH: 'sudo pacman -S util-linux',
        DistributionFamily.UNKNOWN: 'install the util-linux package for your distribution',
    },
    'fsck.ext4': {
        DistributionFamily.DEBIAN: 'sudo apt install e2fsprogs',
        DistributionFamily.ARCH: 'sudo pacman -S e2fsprogs',
        DistributionFamily.UNKNOWN: 'install the ext4 filesystem utilities for your distribution',
    },
    'xfs_repair': {
        DistributionFamily.DEBIAN: 'sudo apt install xfsprogs',
        DistributionFamily.ARCH: 'sudo pacman -S xfsprogs',
        DistributionFamily.UNKNOWN: 'install the xfsprogs package for your distribution',
    },
    'btrfs': {
        DistributionFamily.DEBIAN: 'sudo apt install btrfs-progs',
        DistributionFamily.ARCH: 'sudo pacman -S btrfs-progs',
        DistributionFamily.UNKNOWN: 'install the btrfs-progs package for your distribution',
    },
    'fsck.fat': {
        DistributionFamily.DEBIAN: 'sudo apt install dosfstools',
        DistributionFamily.ARCH: 'sudo pacman -S dosfstools',
        DistributionFamily.UNKNOWN: 'install dosfstools for your distribution',
    },
}


def detect_distribution_family(os_release: dict[str, str] | None = None) -> DistributionFamily:
    os_release = os_release or read_os_release()
    identity = os_release.get('ID', '').lower()
    like = os_release.get('ID_LIKE', '').lower().split()
    if identity in ARCH_LIKE or any(item in ARCH_LIKE for item in like):
        return DistributionFamily.ARCH
    if identity in DEBIAN_LIKE or any(item in DEBIAN_LIKE for item in like):
        return DistributionFamily.DEBIAN
    return DistributionFamily.UNKNOWN


def _extract_tool_name(command: Sequence[str]) -> str:
    parts = [str(part).strip() for part in command if str(part).strip()]
    if not parts:
        return ''
    if parts[0] == 'sudo':
        for part in parts[1:]:
            if not part.startswith('-'):
                return Path(part).name
        return ''
    return Path(parts[0]).name


def suggest_install_command(command: Sequence[str], distribution_family: DistributionFamily) -> str:
    tool = _extract_tool_name(command)
    hint = COMMAND_PACKAGE_HINTS.get(tool, {}).get(distribution_family, '')
    if hint:
        return hint
    return f"Install the package that provides {tool or 'command'} for your distribution."


def _normalize_command(command: Sequence[str]) -> tuple[str, ...]:
    parts = tuple(str(part) for part in command)
    if not parts:
        raise ValueError('command must not be empty')
    if any(not part.strip() for part in parts):
        raise ValueError('command parts must not be empty')
    return parts


def run(
    command: Sequence[str],
    *,
    timeout: int = 30,
    cwd: str = '',
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    argv = _normalize_command(command)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd or None,
            env=dict(env) if env is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(argv, timeout) from exc
    except FileNotFoundError as exc:
        raise CommandNotFoundError(argv) from exc

    result = CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)
    if check and result.returncode != 0:
        raise CommandError(result)
    return result


def run_root(
    command: Sequence[str],
    *,
    timeout: int = 30,
    cwd: str = '',
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    from .privileged import run_privileged

    return run_privileged(command, timeout=timeout, cwd=cwd, env=env, check=check)


def capture(
    command: Sequence[str],
    *,
    timeout: int = 30,
    cwd: str = '',
    env: Mapping[str, str] | None = None,
) -> str:
    return run(command, timeout=timeout, cwd=cwd, env=env, check=True).stdout
