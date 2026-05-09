#!/bin/bash

#############################################################################
# install-deps.sh - Dependency installer for boot-repair
#
# ARCHITECTURE:
# 1. PRIORITY 1: Use native distro packages when available
# 2. PRIORITY 2: If no native package, create local .venv and install via pip
# 3. NEVER: Use global pip install or --break-system-packages
#
# This ensures compatibility with PEP 668 while maintaining portability
# across Arch, CachyOS, Debian, Ubuntu, and Mint distributions.
#############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

# System packages required for all distributions
ARCH_SYSTEM_PACKAGES=(python3 tk util-linux efibootmgr dosfstools)
DEBIAN_SYSTEM_PACKAGES=(python3 python3-venv python3-tk util-linux efibootmgr dosfstools)

# Native Python packages (PRIORITY 1) - distro-specific mapping
declare -A ARCH_NATIVE_PYTHON_PACKAGES=(
    [customtkinter]="python-customtkinter"
    [darkdetect]="python-darkdetect"
)

declare -A DEBIAN_NATIVE_PYTHON_PACKAGES=(
    [customtkinter]="python3-customtkinter"
    [darkdetect]="python3-darkdetect"
)

# List of Python modules this app requires
PYTHON_MODULES=(customtkinter darkdetect)

PYTHON_MODULES=(customtkinter darkdetect)

#############################################################################
# Print helpers
#############################################################################

print_error() {
    echo "❌ ERROR: $*" >&2
}

print_warning() {
    echo "⚠️  WARNING: $*" >&2
}

print_info() {
    echo "ℹ️  INFO: $*"
}

print_success() {
    echo "✅ SUCCESS: $*"
}

#############################################################################
# Distribution detection
#############################################################################

detect_distribution() {
    if [[ ! -f /etc/os-release ]]; then
        print_error "Cannot detect distribution: /etc/os-release not found"
        return 1
    fi
    
    source /etc/os-release
    
    case "${ID:-}" in
        arch|cachyos|endeavouros|manjaro)
            echo "arch"
            return 0
            ;;
        debian|ubuntu|linuxmint|mint|pop|elementary|zorin)
            echo "debian"
            return 0
            ;;
        *)
            print_error "Unsupported distribution: ${ID:-unknown}"
            return 1
            ;;
    esac
}

#############################################################################
# Utility helpers
#############################################################################

check_python_module() {
    local interpreter="$1"
    local module="$2"
    "${interpreter}" -c "import ${module}" >/dev/null 2>&1
}

is_package_installed_arch() {
    pacman -Q "$1" >/dev/null 2>&1
}

is_package_available_arch() {
    pacman -Si "$1" >/dev/null 2>&1
}

is_package_installed_debian() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}

is_package_available_debian() {
    apt-cache show "$1" >/dev/null 2>&1
}

get_native_package_candidate() {
    local distro="$1"
    local module="$2"
    
    if [[ "$distro" == "arch" ]]; then
        echo "${ARCH_NATIVE_PYTHON_PACKAGES[$module]:-}"
    else
        echo "${DEBIAN_NATIVE_PYTHON_PACKAGES[$module]:-}"
    fi
}

get_native_package_candidate() {
    local distro="$1"
    local module="$2"
    
    if [[ "$distro" == "arch" ]]; then
        echo "${ARCH_NATIVE_PYTHON_PACKAGES[$module]:-}"
    else
        echo "${DEBIAN_NATIVE_PYTHON_PACKAGES[$module]:-}"
    fi
}

#############################################################################
# PRIORITY 1: System packages (required for all functionality)
#############################################################################

install_system_packages() {
    local distro="$1"
    local packages=()
    local pkg
    local missing=()

    if [[ "$distro" == "arch" ]]; then
        packages=("${ARCH_SYSTEM_PACKAGES[@]}")
    else
        packages=("${DEBIAN_SYSTEM_PACKAGES[@]}")
    fi

    for pkg in "${packages[@]}"; do
        if [[ "$distro" == "arch" ]]; then
            if ! is_package_installed_arch "$pkg"; then
                missing+=("$pkg")
            fi
        else
            if ! is_package_installed_debian "$pkg"; then
                missing+=("$pkg")
            fi
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        print_success "All system packages already installed"
        return 0
    fi

    print_info "Installing missing system packages: ${missing[*]}"
    
    if [[ "$distro" == "arch" ]]; then
        if ! sudo pacman -S --noconfirm --needed "${missing[@]}"; then
            print_error "Failed to install Arch/CachyOS system packages"
            return 1
        fi
    else
        if ! sudo apt update; then
            print_error "Failed to update apt cache"
            return 1
        fi
        if ! sudo apt install -y "${missing[@]}"; then
            print_error "Failed to install Debian/Ubuntu system packages"
            return 1
        fi
    fi

    print_success "System packages installed successfully"
    return 0
}

#############################################################################
# PRIORITY 1: Native Python packages (when available)
#############################################################################

install_native_python_packages() {
    local distro="$1"
    local module
    local candidate
    local installed_any=0

    print_info "Checking for native Python packages (PRIORITY 1)..."

    for module in "${PYTHON_MODULES[@]}"; do
        # Skip if module already available in system python3
        if check_python_module python3 "$module"; then
            print_info "  ✓ ${module} already available in system python3"
            continue
        fi

        candidate="$(get_native_package_candidate "$distro" "$module")"
        
        if [[ -z "$candidate" ]]; then
            print_info "  - ${module}: no native package available"
            continue
        fi

        if [[ "$distro" == "arch" ]]; then
            if is_package_installed_arch "$candidate"; then
                print_info "  ✓ ${candidate} already installed"
                continue
            fi
            
            if is_package_available_arch "$candidate"; then
                print_info "  Installing ${candidate}..."
                if ! sudo pacman -S --noconfirm --needed "$candidate"; then
                    print_warning "  Could not install ${candidate}"
                    continue
                fi
                installed_any=1
            else
                print_info "  - ${candidate} not available in Arch repos"
            fi
        else
            if is_package_installed_debian "$candidate"; then
                print_info "  ✓ ${candidate} already installed"
                continue
            fi
            
            if is_package_available_debian "$candidate"; then
                print_info "  Installing ${candidate}..."
                if ! sudo apt update >/dev/null 2>&1; then
                    print_warning "  Failed to update apt cache"
                    continue
                fi
                if ! sudo apt install -y "$candidate"; then
                    print_warning "  Could not install ${candidate}"
                    continue
                fi
                installed_any=1
            else
                print_info "  - ${candidate} not available in Debian repos"
            fi
        fi
    done

    return 0
}

#############################################################################
# PRIORITY 2: Virtual environment setup and pip installation
#############################################################################

create_or_reuse_venv() {
    if [[ -x "${VENV_PYTHON}" ]]; then
        print_info "Reusing existing Python virtual environment: ${VENV_DIR}"
        return 0
    fi

    print_info "Creating local Python virtual environment (PRIORITY 2)..."
    
    if ! python3 -m venv "${VENV_DIR}"; then
        print_error "Failed to create virtual environment at ${VENV_DIR}"
        return 1
    fi

    print_info "Upgrading pip in virtual environment..."
    if ! "${VENV_PYTHON}" -m pip install --quiet --upgrade pip; then
        print_error "Failed to upgrade pip in virtual environment"
        return 1
    fi

    print_success "Virtual environment created successfully: ${VENV_DIR}"
    return 0
}

detect_missing_python_modules() {
    local interpreter="$1"
    local module
    
    for module in "${PYTHON_MODULES[@]}"; do
        if ! check_python_module "$interpreter" "$module"; then
            printf '%s\n' "$module"
        fi
    done
}

install_python_modules_in_venv() {
    local missing=()
    local module
    
    mapfile -t missing < <(detect_missing_python_modules "${VENV_PYTHON}")
    
    if [[ ${#missing[@]} -eq 0 ]]; then
        print_info "All Python modules already installed in venv"
        return 0
    fi

    print_info "Installing Python modules in venv: ${missing[*]}"
    
    if ! "${VENV_PYTHON}" -m pip install --quiet "${missing[@]}"; then
        print_error "Failed to install Python modules in venv"
        return 1
    fi

    print_success "Python modules installed in venv successfully"
    return 0
}

#############################################################################
# Validation
#############################################################################

validate_python_environment() {
    local interpreter="$1"
    local failed=()
    local module

    if ! command -v "${interpreter}" >/dev/null 2>&1; then
        print_error "Python interpreter not available: ${interpreter}"
        return 1
    fi

    for module in "${PYTHON_MODULES[@]}"; do
        if ! check_python_module "$interpreter" "$module"; then
            failed+=("${module}")
        fi
    done

    if [[ ${#failed[@]} -gt 0 ]]; then
        print_error "Failed to verify Python dependencies:"
        for module in "${failed[@]}"; do
            print_error "  - ${module} could not be imported"
        done
        return 1
    fi

    print_success "All Python environments validated successfully"
    return 0
}

#############################################################################
# Main orchestration
#############################################################################

main() {
    local distro="$1"

    print_info "======================================="
    print_info "Boot Repair - Dependency Installation"
    print_info "======================================="
    print_info "Distribution: ${distro}"

    # Validate distribution parameter
    if [[ ! "$distro" =~ ^(arch|debian)$ ]]; then
        print_error "Invalid distribution: ${distro}"
        print_info "Supported distributions: arch, debian"
        return 1
    fi

    # Step 1: Install system packages
    print_info ""
    print_info "Step 1/4: Installing system packages..."
    if ! install_system_packages "$distro"; then
        return 1
    fi

    # Step 2: Try native Python packages first
    print_info ""
    print_info "Step 2/4: Attempting native Python packages..."
    install_native_python_packages "$distro" || true

    # Step 3: Check if we need venv
    print_info ""
    print_info "Step 3/4: Checking Python environment..."
    
    local missing_in_system=()
    mapfile -t missing_in_system < <(detect_missing_python_modules python3)
    
    if [[ ${#missing_in_system[@]} -eq 0 ]]; then
        print_success "All Python modules available in system python3"
        print_info "Validating system Python environment..."
        if validate_python_environment python3; then
            print_info ""
            print_success "Dependency installation completed!"
            print_info "Python interpreter to use: python3"
            return 0
        else
            return 1
        fi
    else
        print_info "Missing modules in system python3: ${missing_in_system[*]}"
        print_info "Creating virtual environment and installing via pip..."
        
        if ! create_or_reuse_venv; then
            return 1
        fi
        
        if ! install_python_modules_in_venv; then
            return 1
        fi
        
        # Step 4: Final validation for venv
        print_info ""
        print_info "Step 4/4: Final validation..."
        
        if validate_python_environment "${VENV_PYTHON}"; then
            print_info ""
            print_success "Dependency installation completed!"
            print_info "Python interpreter to use: ${VENV_PYTHON}"
            return 0
        else
            return 1
        fi
    fi
}

#############################################################################
# Script execution
#############################################################################

# Only execute if not being sourced (allow testing and direct calling)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -eq 0 ]]; then
        # Auto-detect distribution
        if ! distro=$(detect_distribution); then
            print_error "Could not auto-detect distribution"
            exit 1
        fi
    else
        distro="$1"
    fi

    if ! main "$distro"; then
        print_error "Dependency installation failed"
        exit 1
    fi
fi
