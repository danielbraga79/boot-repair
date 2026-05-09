#!/bin/bash

#############################################################################
# boot-repair.sh - Main launcher for boot-repair application
#
# This script serves as the operational bootstrap layer only.
# It is responsible for:
#   - Detecting the Linux distribution
#   - Validating essential dependencies
#   - Installing missing dependencies
#   - Requesting sudo authentication
#   - Launching the Python application
#
# All business logic remains in Python (main.py)
#############################################################################

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DEPS_SCRIPT="${SCRIPT_DIR}/install-deps.sh"
MAIN_APP="${SCRIPT_DIR}/boot-repair-app_0.0.3/main.py"
VENV_DIR="${SCRIPT_DIR}/.venv"
APP_NAME="Boot Repair"

#############################################################################
# Functions
#############################################################################

# Print functions
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

# Detect Linux distribution
detect_distribution() {
    if [[ ! -f /etc/os-release ]]; then
        print_error "Cannot detect distribution: /etc/os-release not found"
        return 1
    fi
    
    # Source the os-release file
    # shellcheck source=/dev/null
    source /etc/os-release
    
    # Normalize to common IDs
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
            print_info "Supported distributions: Arch, CachyOS, EndeavourOS, Manjaro, Debian, Ubuntu, Linux Mint, Pop!_OS, elementary OS, Zorin OS"
            return 1
            ;;
    esac
}

# Check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Verify essential tools are available
verify_tools() {
    local missing_tools=()
    
    print_info "Verifying essential tools..."
    
    if ! command_exists python3; then
        missing_tools+=("python3")
    fi
    
    if ! command_exists sudo; then
        missing_tools+=("sudo")
    fi
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        print_error "Missing essential tools: ${missing_tools[*]}"
        print_info "Please install these tools manually before running Boot Repair"
        return 1
    fi
    
    print_success "All essential tools are available"
    return 0
}

# Verify application entry point
verify_app() {
    if [[ ! -f "${MAIN_APP}" ]]; then
        print_error "Application entry point not found: ${MAIN_APP}"
        print_info "Make sure you're running this script from the project root directory"
        return 1
    fi
    
    print_info "Application entry point verified: ${MAIN_APP}"
    return 0
}

# Request and validate sudo authentication
request_sudo_auth() {
    print_info "Requesting sudo authentication..."
    print_info "(This is required to access disk and boot information)"
    
    # Use sudo with -v to validate/update credentials
    # The -v flag updates the sudo timestamp without running a command
    if ! sudo -v; then
        print_error "Sudo authentication failed or was canceled by user"
        return 1
    fi
    
    print_success "Sudo authentication successful"
    return 0
}

# Install dependencies if needed
install_dependencies() {
    local distro="$1"
    
    # Make sure install-deps.sh is executable
    if [[ ! -f "${INSTALL_DEPS_SCRIPT}" ]]; then
        print_error "Dependency installer not found: ${INSTALL_DEPS_SCRIPT}"
        return 1
    fi
    
    if [[ ! -x "${INSTALL_DEPS_SCRIPT}" ]]; then
        chmod +x "${INSTALL_DEPS_SCRIPT}"
    fi
    
    print_info "Installing/verifying dependencies for ${distro} distribution..."
    
    # Run the dependency installer with the detected distribution
    # The installer will:
    # 1. Try native distro packages first (PRIORITY 1)
    # 2. Create .venv if needed (PRIORITY 2)
    # 3. Validate all imports
    if "${INSTALL_DEPS_SCRIPT}" "${distro}"; then
        print_success "Dependencies installation/verification completed"
        return 0
    else
        print_error "Dependency installation/verification failed"
        return 1
    fi
}

# Resolve which Python interpreter should launch the app
resolve_python_interpreter() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
    else
        command -v python3
    fi
}

# Launch the Python application
launch_app() {
    print_info "Launching ${APP_NAME}..."

    cd "${SCRIPT_DIR}"

    local python_exec
    python_exec="$(resolve_python_interpreter)"
    if [[ -z "${python_exec}" ]]; then
        print_error "Python interpreter not found"
        return 1
    fi

    print_info "Using interpreter: ${python_exec}"
    exec "${python_exec}" "${MAIN_APP}" "$@"
}

#############################################################################
# Main Execution
#############################################################################

main() {
    print_info "Starting ${APP_NAME} bootstrap..."
    print_info "Current user: $(id -un) uid=$(id -u)"
    print_info "Graphical environment: DISPLAY=${DISPLAY:-<unset>} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>} XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-<unset>}"

    if [[ $(id -u) -eq 0 ]]; then
        print_error "boot-repair.sh must not be executed as root. Launch the application as a normal user."
        return 1
    fi
    
    # Step 1: Verify essential tools
    if ! verify_tools; then
        return 1
    fi
    
    # Step 2: Verify application entry point
    if ! verify_app; then
        return 1
    fi
    
    # Step 3: Detect distribution
    print_info "Detecting Linux distribution..."
    local distro
    if ! distro=$(detect_distribution); then
        return 1
    fi
    print_success "Distribution detected: ${distro}"
    
    # Step 4: Install dependencies if needed
    if ! install_dependencies "${distro}"; then
        return 1
    fi
    
    # Step 5: Cache sudo credentials when running from an interactive terminal.
    # This does not elevate the GUI process, it only refreshes sudo credentials.
    if [[ -t 0 ]]; then
        if ! request_sudo_auth; then
            print_warning "Continuing without cached sudo credentials. Privileged operations will prompt when needed."
        fi
    else
        print_info "No interactive terminal detected; skipping sudo credential prefetch"
    fi
    
    # Step 6: Launch the application
    print_info "All checks passed - launching application..."
    launch_app "$@"
}

# Run main with all arguments when executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
