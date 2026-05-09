from __future__ import annotations

import argparse
import logging
import os
import sys

from core.analysis import collect_evidence
from core.models import format_size_bytes

logger = logging.getLogger(__name__)


def _format_evidence(evidence) -> list[str]:
    lines = [
        f'Firmware detected: {evidence.firmware_mode}',
        f"Live environment: {'yes' if evidence.live_environment else 'no'}",
        f'Distribution detected: {evidence.distribution}',
        f'Distribution family: {evidence.distribution_family.value}',
        f'Initramfs tool: {evidence.initramfs_tool}',
        f'Disks detected: {len(evidence.disks)}',
        f'Partitions detected: {len(evidence.partitions)}',
    ]
    if evidence.disks:
        lines.append('Disks:')
        lines.extend(f"  {disk.name} | {disk.model or 'unknown model'} | {format_size_bytes(disk.size_bytes)}" for disk in evidence.disks)
    if evidence.partitions:
        lines.append('Partitions:')
        lines.extend(
            f"  {part.name} | disk {part.disk_name or 'unknown'} | {part.fs_type or 'unknown fs'} | {part.mount_point or 'no mount'}"
            for part in evidence.partitions
        )
    if evidence.diagnostic_findings:
        lines.append('Diagnostics:')
        lines.extend(f'  [{finding.category}] {finding.description} ({finding.severity.value})' for finding in evidence.diagnostic_findings)
    if evidence.notes:
        lines.append('Notes:')
        lines.extend(f'  {note}' for note in evidence.notes)
    return lines


def _detect_graphics_backend() -> str:
    if os.environ.get('WAYLAND_DISPLAY'):
        return 'Wayland'
    if os.environ.get('DISPLAY'):
        return 'X11'
    return 'none'


def _validate_launcher_environment() -> None:
    logger.info('Boot Repair startup environment')
    logger.info(f"Current user: {os.getenv('USER', '<unknown>')} uid={os.getuid() if hasattr(os, 'getuid') else '<unknown>'}")
    logger.info(f"Graphical environment: DISPLAY={os.environ.get('DISPLAY', '<unset>')} WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '<unset>')} XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', '<unset>')}")
    logger.info(f"Detected graphics backend: {_detect_graphics_backend()}")

    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        logger.error('Application started as root, which is not supported for GUI startup')
        raise SystemExit('Boot Repair must be launched as a normal user, not root.')


def run_cli() -> int:
    evidence = collect_evidence()
    for line in _format_evidence(evidence):
        print(line)
    return 0


def run_gui() -> int:
    try:
        from gui.app import main as run_gui_main
    except ImportError as exc:
        print(f'GUI unavailable, falling back to CLI: {exc}', file=sys.stderr)
        return run_cli()

    try:
        return run_gui_main()
    except Exception as exc:
        print(f'GUI failed to start, falling back to CLI: {exc}', file=sys.stderr)
        return run_cli()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    _validate_launcher_environment()

    parser = argparse.ArgumentParser(description='Boot Repair Assistant')
    parser.add_argument('--cli', action='store_true', help='Run in command-line mode instead of using the GUI')
    args = parser.parse_args()

    backend = _detect_graphics_backend()
    logger.info(f"Target mode: {'CLI' if args.cli else 'GUI'} ({backend})")

    if args.cli or (not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')):
        return run_cli()
    return run_gui()


if __name__ == '__main__':
    raise SystemExit(main())
