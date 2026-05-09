# boot-repair

A portable Linux boot repair assistant for Debian/Ubuntu/Arch/CachyOS families.

## Features

- Detects disks, partitions, firmware mode, distribution family, and initramfs tool
- Collects diagnostics for partition tables, filesystems, Btrfs subvolumes, and EFI boot layout
- Builds safe bootloader repair plans with UEFI/Bios and cross-disk awareness
- Provides CLI fallback when the GUI is unavailable or `DISPLAY` is missing
- Offers package hints for missing recovery utilities on supported distributions

## Quick Start

The easiest way to run boot-repair is using the provided launcher script:

```bash
chmod +x *.sh
./boot-repair.sh
```

This script will:
1. Detect your Linux distribution
2. Verify essential dependencies
3. Install missing packages automatically
4. Request sudo authentication
5. Launch the boot-repair application

## Requirements

- Python 3.11 or later
- `sudo` access for repair actions
- Command-line tools: `lsblk`, `blkid`, `findmnt`, `efibootmgr`, `dosfstools`
- Optional GUI support with `tkinter`
- Python packages: `customtkinter`, `darkdetect` (installed automatically)

## Supported Distributions

### Arch Linux Family
- Arch Linux
- CachyOS
- EndeavourOS
- Manjaro

### Debian Family
- Debian
- Ubuntu
- Linux Mint
- Pop!_OS
- elementary OS
- Zorin OS

## Usage

### Recommended: Using the Launcher Script

```bash
./boot-repair.sh
```

The launcher script handles all bootstrap operations and launches the application.

### Alternative: Direct Python Execution

If you prefer to run the application directly:

```bash
python3 boot-repair-app_0.0.3/main.py
```

For CLI mode (no GUI):

```bash
python3 boot-repair-app_0.0.3/main.py --cli
```

## Shell Scripts

### boot-repair.sh

**Main launcher and bootstrap script**

Performs the following operations:
- Detects your Linux distribution via `/etc/os-release`
- Validates essential tools (`python3`, `sudo`)
- Verifies application integrity
- Checks and installs missing dependencies
- Requests sudo authentication
- Launches the Python application with preserved arguments

Usage:
```bash
./boot-repair.sh [options passed to main.py]
```

### install-deps.sh

**Dependency installation script**

Automatically installs required packages for your distribution:
- **Arch/CachyOS/EndeavourOS**: Uses `pacman`
- **Debian/Ubuntu/Mint**: Uses `apt`

The script only installs missing packages - it will not reinstall already-installed dependencies.

Usage (normally called automatically by boot-repair.sh):
```bash
./install-deps.sh <distro>
# <distro> can be: arch or debian
```

### collect-debug.sh

**Diagnostic collection script**

Generates a comprehensive diagnostic report for troubleshooting issues.

Collects:
- System information (kernel, hostname, uptime)
- Distribution details
- Python environment
- Block devices (lsblk, blkid)
- Mount information (findmnt, /proc/mounts)
- EFI/Boot configuration
- Locale settings
- Network configuration
- Kernel messages

The report is saved as `debug-report-YYYYMMDD-HHMMSS.txt` in the current directory.

Usage:
```bash
./collect-debug.sh
```

## Architecture

### Python Application Stack

The core boot-repair application is written in Python for portability and maintainability:

- **core/analysis.py**: Disk and partition detection, system inspection
- **core/system.py**: System command execution, privilege management
- **core/planning.py**: Repair plan generation
- **core/execution.py**: Repair execution (when authorized)
- **core/models.py**: Data structures for devices, partitions, and plans
- **core/flow.py**: Workflow orchestration
- **gui/app.py**: Tkinter-based graphical interface
- **gui/screens.py**: Screen definitions and navigation

### Shell Script Bootstrap Layer

The shell scripts provide:
- Operational bootstrap (no business logic)
- Environment preparation and validation
- Dependency management
- Diagnostic collection

This separation ensures:
- Core repair logic is portable across all Linux distributions
- Shell scripts only handle environment-specific setup
- Easy testing and maintenance
- No business logic in shell code

## Development

### Running Tests

```bash
cd boot-repair-app_0.0.3
python3 -m unittest discover -s tests -p 'test_*.py'
```

### Checking Code

```bash
# Validate Python syntax
python3 -m py_compile boot-repair-app_0.0.3/**/*.py

# Validate shell syntax
bash -n *.sh
```

## Troubleshooting

### Dependencies Failed to Install

If dependency installation fails, you can manually install required packages:

**Arch Linux Family (Arch, CachyOS, EndeavourOS, Manjaro):**
```bash
sudo pacman -S python3 tk util-linux efibootmgr dosfstools python-pyudev
```

**Debian Family (Debian, Ubuntu, Linux Mint, Pop!_OS, elementary OS, Zorin OS):**
```bash
sudo apt install python3 python3-tk util-linux efibootmgr dosfstools python3-pyudev
```

### Collect Diagnostic Information

If you encounter issues, run the diagnostic script to gather system information:

```bash
./collect-debug.sh
```

This creates a debug report that can help identify issues with system configuration or compatibility.

### No GUI Available

The application can run in CLI mode when a graphical environment is not available:

```bash
python3 boot-repair-app_0.0.3/main.py --cli
```

## Notes

This tool is designed for diagnostic and planning purposes. Review generated plans carefully before applying repairs on real systems. Always back up important data first.

All business logic including disk analysis, repair planning, and decision-making is implemented in Python. Shell scripts serve only as a bootstrap layer for environment preparation and application launching.
