#!/bin/bash

#############################################################################
# collect-debug.sh - Diagnostic information collector
#
# This script collects a complete diagnostic snapshot for debugging purposes.
# It gathers information from various system sources and saves it to a 
# timestamped file.
#
# Generated file format: debug-report-YYYYMMDD-HHMMSS.txt
#############################################################################

set -euo pipefail

# Configuration
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
DEBUG_FILE="debug-report-${TIMESTAMP}.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

#############################################################################
# Functions
#############################################################################

# Print functions
print_error() {
    echo "❌ ERROR: $*" >&2
}

print_info() {
    echo "ℹ️  INFO: $*"
}

print_success() {
    echo "✅ SUCCESS: $*"
}

# Add section header to debug file
add_section_header() {
    local title="$1"
    {
        echo ""
        echo "==============================================================================="
        echo "$title"
        echo "==============================================================================="
    } >> "${DEBUG_FILE}"
}

# Run a command and append output to debug file
run_command_and_log() {
    local description="$1"
    shift
    local cmd=("$@")
    
    add_section_header "$description"
    
    print_info "Collecting: $description"
    
    if "${cmd[@]}" >> "${DEBUG_FILE}" 2>&1; then
        return 0
    else
        # Even if command fails, we try to capture the output
        return 0
    fi
}

# Collect system information
collect_system_info() {
    print_info "Collecting system information..."
    add_section_header "SYSTEM INFORMATION"
    
    {
        echo "Timestamp: $(date)"
        echo "Hostname: $(hostname)"
        echo "Kernel: $(uname -a)"
        echo "Uptime: $(uptime)"
    } >> "${DEBUG_FILE}"
}

# Collect distribution information
collect_distro_info() {
    print_info "Collecting distribution information..."
    
    if [[ -f /etc/os-release ]]; then
        run_command_and_log "DISTRIBUTION INFO (/etc/os-release)" cat /etc/os-release
    fi
    
    if command -v lsb_release >/dev/null 2>&1; then
        run_command_and_log "LSB RELEASE" lsb_release -a
    fi
}

# Collect locale information
collect_locale_info() {
    print_info "Collecting locale information..."
    run_command_and_log "LOCALE SETTINGS" locale
}

# Collect Python information
collect_python_info() {
    print_info "Collecting Python information..."
    add_section_header "PYTHON INFORMATION"
    
    {
        echo "Python 3 version:"
        python3 --version || echo "ERROR: python3 not found"
        echo ""
        echo "Python 3 executable:"
        which python3 || echo "ERROR: python3 not in PATH"
        echo ""
        echo "Python 3 path:"
        python3 -c "import sys; print('\\n'.join(sys.path))" || echo "ERROR: Could not get sys.path"
    } >> "${DEBUG_FILE}" 2>&1
}

# Collect block device information
collect_block_devices() {
    print_info "Collecting block device information..."
    
    if command -v lsblk >/dev/null 2>&1; then
        run_command_and_log "LSBLK OUTPUT (JSON)" lsblk --json --bytes
    fi
    
    if command -v blkid >/dev/null 2>&1; then
        run_command_and_log "BLKID OUTPUT" sudo blkid || run_command_and_log "BLKID OUTPUT (without sudo)" blkid
    fi
}

# Collect mount information
collect_mount_info() {
    print_info "Collecting mount information..."
    
    if command -v findmnt >/dev/null 2>&1; then
        run_command_and_log "FINDMNT OUTPUT (JSON)" findmnt --json
    fi
    
    if [[ -f /etc/fstab ]]; then
        run_command_and_log "FSTAB CONTENTS" cat /etc/fstab
    fi
    
    run_command_and_log "MOUNTED FILESYSTEMS (/proc/mounts)" cat /proc/mounts
}

# Collect EFI/boot information
collect_boot_info() {
    print_info "Collecting boot information..."
    
    if command -v efibootmgr >/dev/null 2>&1; then
        run_command_and_log "EFIBOOTMGR OUTPUT" sudo efibootmgr -v || run_command_and_log "EFIBOOTMGR OUTPUT (without sudo)" efibootmgr -v
    fi
    
    if [[ -d /sys/firmware/efi ]]; then
        run_command_and_log "EFI DIRECTORY EXISTS" ls -la /sys/firmware/efi/
    fi
    
    if [[ -f /proc/cmdline ]]; then
        run_command_and_log "KERNEL COMMAND LINE (/proc/cmdline)" cat /proc/cmdline
    fi
}

# Collect storage partition information
collect_partition_info() {
    print_info "Collecting partition information..."
    
    run_command_and_log "DISK USAGE (/dev)" ls -la /dev/ | grep -E "^b|^c"
    
    run_command_and_log "PARTED LIST" sudo parted -l || true
}

# Collect network information
collect_network_info() {
    print_info "Collecting network information..."
    
    if command -v ip >/dev/null 2>&1; then
        run_command_and_log "IP ADDRESS INFO" ip address show
    fi
    
    if command -v nmcli >/dev/null 2>&1; then
        run_command_and_log "NETWORKMANAGER INFO" nmcli device || true
    fi
}

# Collect kernel/dmesg information
collect_kernel_info() {
    print_info "Collecting kernel information..."
    
    run_command_and_log "KERNEL MESSAGES (last 100 lines)" dmesg | tail -100 || true
}

# Collect package manager information
collect_package_info() {
    print_info "Collecting package manager information..."
    
    if command -v pacman >/dev/null 2>&1; then
        run_command_and_log "PACMAN MIRRORS" pacman -S --noconfirm -d pacman 2>&1 | head -20 || true
        run_command_and_log "PACMAN PACKAGES" pacman -Q || true
    fi
    
    if command -v apt >/dev/null 2>&1; then
        run_command_and_log "APT SOURCES" cat /etc/apt/sources.list || true
        run_command_and_log "APT PACKAGES (partial)" dpkg -l | head -50 || true
    fi
}

# Collect application-specific information
collect_app_info() {
    print_info "Collecting application information..."
    add_section_header "APPLICATION INFORMATION"
    
    local app_dir="${SCRIPT_DIR}/boot-repair-app_0.0.3"
    
    {
        echo "Application Directory: ${app_dir}"
        echo "Application Exists: $(test -d "$app_dir" && echo 'YES' || echo 'NO')"
        echo ""
    } >> "${DEBUG_FILE}"
    
    if [[ -d "${app_dir}" ]]; then
        {
            echo "Directory Contents:"
            ls -la "${app_dir}/"
            echo ""
            echo "Core Module Contents:"
            ls -la "${app_dir}/core/"
            echo ""
            echo "GUI Module Contents:"
            ls -la "${app_dir}/gui/"
            echo ""
        } >> "${DEBUG_FILE}"
    fi
}

# Create final report summary
create_summary() {
    add_section_header "COLLECTION SUMMARY"
    
    {
        echo "Debug report generated: $(date)"
        echo "Report file: ${DEBUG_FILE}"
        echo "Collection completed successfully"
    } >> "${DEBUG_FILE}"
}

#############################################################################
# Main Execution
#############################################################################

main() {
    print_info "Starting diagnostic information collection..."
    print_info "Output file: ${DEBUG_FILE}"
    
    # Create empty file
    > "${DEBUG_FILE}"
    
    # Collect information
    collect_system_info
    collect_distro_info
    collect_locale_info
    collect_python_info
    collect_block_devices
    collect_mount_info
    collect_boot_info
    collect_partition_info
    collect_network_info
    collect_kernel_info
    collect_package_info
    collect_app_info
    
    # Create summary
    create_summary
    
    # Calculate file size
    local file_size
    file_size=$(du -h "${DEBUG_FILE}" | cut -f1)
    
    print_success "Diagnostic information collected successfully"
    print_info "Report file: ${DEBUG_FILE}"
    print_info "Report size: ${file_size}"
    print_info "Review the report and attach it when reporting issues"
}

# Run main
main "$@"
