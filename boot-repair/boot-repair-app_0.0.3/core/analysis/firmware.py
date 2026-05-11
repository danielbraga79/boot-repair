from pathlib import Path


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


def detect_firmware_and_environment() -> tuple[str, bool]:
    """Detect firmware mode and live environment status."""
    firmware_mode = _firmware_mode()
    live_environment = _live_environment()
    return firmware_mode, live_environment