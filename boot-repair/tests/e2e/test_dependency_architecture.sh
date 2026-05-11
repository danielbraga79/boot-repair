#!/bin/bash

#############################################################################
# test_dependency_architecture.sh - Comprehensive dependency tests
#
# This test suite validates the refactored dependency architecture:
# - PRIORITY 1: Native distro packages
# - PRIORITY 2: Virtual environment fallback
# - PEP 668 compliance
# - Import validation
#############################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DEPS_SCRIPT="${PROJECT_ROOT}/install-deps.sh"
TEST_VENV_DIR="${PROJECT_ROOT}/.test_venv"

TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

#############################################################################
# Test utilities
#############################################################################

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

print_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

print_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

print_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
    ((TESTS_SKIPPED++))
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

cleanup_test_venv() {
    if [[ -d "${TEST_VENV_DIR}" ]]; then
        rm -rf "${TEST_VENV_DIR}"
    fi
}

#############################################################################
# Test Suite 1: Script integrity
#############################################################################

test_script_exists_and_executable() {
    print_test "install-deps.sh exists and is executable"
    
    if [[ ! -f "${INSTALL_DEPS_SCRIPT}" ]]; then
        print_fail "Script not found: ${INSTALL_DEPS_SCRIPT}"
        return 1
    fi
    
    if [[ ! -x "${INSTALL_DEPS_SCRIPT}" ]]; then
        chmod +x "${INSTALL_DEPS_SCRIPT}"
    fi
    
    print_pass "Script exists and is executable"
    return 0
}

test_script_syntax() {
    print_test "Bash script syntax validation"
    
    if ! bash -n "${INSTALL_DEPS_SCRIPT}" 2>/dev/null; then
        print_fail "Script has syntax errors"
        return 1
    fi
    
    print_pass "Script has valid bash syntax"
    return 0
}

test_required_functions() {
    print_test "Required functions are defined"
    
    local required_functions=(
        "detect_distribution"
        "check_python_module"
        "install_system_packages"
        "install_native_python_packages"
        "create_or_reuse_venv"
        "install_python_modules_in_venv"
        "validate_python_environment"
    )
    
    local missing=()
    for func in "${required_functions[@]}"; do
        if ! grep -q "^${func}()" "${INSTALL_DEPS_SCRIPT}"; then
            missing+=("$func")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        print_fail "Missing functions: ${missing[*]}"
        return 1
    fi
    
    print_pass "All required functions are defined"
    return 0
}

#############################################################################
# Test Suite 2: Distribution detection
#############################################################################

test_distribution_detection() {
    print_test "Distribution detection capability"
    
    local test_script=$(mktemp)
    cat > "$test_script" << 'EOF'
source "$1"
distro=$(detect_distribution)
if [[ -z "$distro" ]]; then
    exit 1
fi
echo "$distro"
EOF
    
    local detected
    if ! detected=$(bash "$test_script" "${INSTALL_DEPS_SCRIPT}" 2>/dev/null); then
        rm -f "$test_script"
        print_fail "Distribution detection failed"
        return 1
    fi
    
    if [[ ! "$detected" =~ ^(arch|debian)$ ]]; then
        rm -f "$test_script"
        print_fail "Unknown distribution detected: $detected"
        return 1
    fi
    
    rm -f "$test_script"
    print_pass "Distribution detected: $detected"
    return 0
}

#############################################################################
# Test Suite 3: Module checking
#############################################################################

test_module_check_function() {
    print_test "check_python_module function works correctly"
    
    # Create a temporary wrapper to test the function
    local test_script=$(mktemp)
    cat > "$test_script" << 'EOF'
source "$1"
# Test with a module that should exist
if check_python_module python3 sys; then
    exit 0
else
    exit 1
fi
EOF
    
    if ! bash "$test_script" "${INSTALL_DEPS_SCRIPT}"; then
        rm -f "$test_script"
        print_fail "Failed to detect existing module"
        return 1
    fi
    
    # Test with a module that shouldn't exist
    cat > "$test_script" << 'EOF'
source "$1"
# Test with a module that shouldn't exist
if check_python_module python3 nonexistent_module_xyz_12345; then
    exit 1
else
    exit 0
fi
EOF
    
    if ! bash "$test_script" "${INSTALL_DEPS_SCRIPT}"; then
        rm -f "$test_script"
        print_fail "False positive for non-existent module"
        return 1
    fi
    
    rm -f "$test_script"
    print_pass "Module checking works correctly"
    return 0
}

#############################################################################
# Test Suite 4: Venv creation and reuse
#############################################################################

test_venv_creation() {
    print_test "Virtual environment creation"
    
    cleanup_test_venv
    
    # Create a test venv
    if ! python3 -m venv "${TEST_VENV_DIR}" 2>/dev/null; then
        print_skip "venv module not available"
        cleanup_test_venv
        return 0
    fi
    
    if [[ ! -x "${TEST_VENV_DIR}/bin/python" ]]; then
        print_fail "Venv Python not executable"
        cleanup_test_venv
        return 1
    fi
    
    print_pass "Virtual environment can be created"
    cleanup_test_venv
    return 0
}

test_venv_python_import() {
    print_test "Virtual environment Python can import modules"
    
    cleanup_test_venv
    
    if ! python3 -m venv "${TEST_VENV_DIR}" 2>/dev/null; then
        print_skip "venv module not available"
        cleanup_test_venv
        return 0
    fi
    
    if ! "${TEST_VENV_DIR}/bin/python" -c "import sys" 2>/dev/null; then
        print_fail "Venv Python cannot import modules"
        cleanup_test_venv
        return 1
    fi
    
    print_pass "Venv Python can import modules"
    cleanup_test_venv
    return 0
}

test_venv_pip_install() {
    print_test "Virtual environment pip can install packages"
    
    cleanup_test_venv
    
    if ! python3 -m venv "${TEST_VENV_DIR}" 2>/dev/null; then
        print_skip "venv module not available"
        cleanup_test_venv
        return 0
    fi
    
    # Try to install a small package (like six which is lightweight)
    if ! "${TEST_VENV_DIR}/bin/pip" install --quiet six 2>/dev/null; then
        print_fail "Cannot install packages in venv via pip"
        cleanup_test_venv
        return 1
    fi
    
    # Verify installation
    if ! "${TEST_VENV_DIR}/bin/python" -c "import six" 2>/dev/null; then
        print_fail "Installed package not available in venv"
        cleanup_test_venv
        return 1
    fi
    
    print_pass "Virtual environment pip installation works"
    cleanup_test_venv
    return 0
}

#############################################################################
# Test Suite 5: Architecture validation
#############################################################################

test_no_global_pip_install() {
    print_test "Script does not use global 'pip install'"
    
    # Exclude comments and VENV_PYTHON pip installs
    if grep -E "^\s*pip\s+install\s|^[^#]*\s+pip\s+install\s" "${INSTALL_DEPS_SCRIPT}" | \
       grep -v "VENV_PYTHON" | grep -v ".venv" | grep -v "^\s*#"; then
        print_fail "Found global pip install command"
        return 1
    fi
    
    print_pass "Script never uses global pip install"
    return 0
}

test_no_break_system_packages() {
    print_test "Script does not use --break-system-packages flag"
    
    # Exclude comments
    if grep -E "^\s*[^#]*--break-system-packages" "${INSTALL_DEPS_SCRIPT}" | grep -v "^\s*#"; then
        print_fail "Found --break-system-packages flag"
        return 1
    fi
    
    print_pass "Script avoids --break-system-packages"
    return 0
}

test_priority_1_native_packages() {
    print_test "PRIORITY 1 native packages are attempted first"
    
    # Check that native package installation comes before venv
    local native_line=$(grep -n "install_native_python_packages" "${INSTALL_DEPS_SCRIPT}" | head -1 | cut -d: -f1)
    local venv_line=$(grep -n "create_or_reuse_venv" "${INSTALL_DEPS_SCRIPT}" | head -1 | cut -d: -f1)
    
    if [[ $native_line -gt $venv_line ]]; then
        print_fail "Native packages should be attempted before venv"
        return 1
    fi
    
    print_pass "PRIORITY 1 native packages are attempted first"
    return 0
}

test_venv_fallback_exists() {
    print_test "PRIORITY 2 venv fallback is implemented"
    
    if ! grep -q "create_or_reuse_venv" "${INSTALL_DEPS_SCRIPT}"; then
        print_fail "Venv fallback not implemented"
        return 1
    fi
    
    print_pass "PRIORITY 2 venv fallback exists"
    return 0
}

test_import_validation() {
    print_test "Import validation is used for verification"
    
    if ! grep -q "check_python_module" "${INSTALL_DEPS_SCRIPT}"; then
        print_fail "Import validation not used"
        return 1
    fi
    
    # Ensure it's not validating by package name
    if grep -q "dpkg-query.*customtkinter" "${INSTALL_DEPS_SCRIPT}" || \
       grep -q "pacman.*customtkinter[^-]" "${INSTALL_DEPS_SCRIPT}"; then
        print_fail "Package name validation still present"
        return 1
    fi
    
    print_pass "Import validation is properly implemented"
    return 0
}

#############################################################################
# Test Suite 6: Error handling
#############################################################################

test_error_handling() {
    print_test "Script handles errors gracefully"
    
    # Try running with invalid distro
    local output
    if output=$(bash "${INSTALL_DEPS_SCRIPT}" invalid_distro 2>&1); then
        print_fail "Script should fail for invalid distribution"
        return 1
    fi
    
    if ! echo "$output" | grep -qi "error\|failed\|unsupported"; then
        print_fail "Error message not informative"
        return 1
    fi
    
    print_pass "Error handling works correctly"
    return 0
}

#############################################################################
# Test Suite 7: Integration tests
#############################################################################

test_boot_repair_compatibility() {
    print_test "boot-repair.sh calls install-deps.sh correctly"
    
    if [[ ! -f "${PROJECT_ROOT}/boot-repair.sh" ]]; then
        print_skip "boot-repair.sh not found"
        return 0
    fi
    
    if ! grep -q 'INSTALL_DEPS_SCRIPT.*install-deps.sh' "${PROJECT_ROOT}/boot-repair.sh"; then
        print_fail "boot-repair.sh should reference install-deps.sh"
        return 1
    fi
    
    if ! grep -q 'VENV_DIR.*\.venv' "${PROJECT_ROOT}/boot-repair.sh"; then
        print_fail "boot-repair.sh should reference .venv"
        return 1
    fi
    
    print_pass "boot-repair.sh properly calls install-deps.sh"
    return 0
}

test_main_app_location() {
    print_test "Main application location is properly referenced"
    
    if [[ ! -d "${PROJECT_ROOT}/boot-repair-app_0.0.3" ]]; then
        print_fail "Application directory not found"
        return 1
    fi
    
    if [[ ! -f "${PROJECT_ROOT}/boot-repair-app_0.0.3/main.py" ]]; then
        print_fail "main.py not found in application directory"
        return 1
    fi
    
    print_pass "Application structure is correct"
    return 0
}

#############################################################################
# Main test execution
#############################################################################

run_all_tests() {
    print_header "Boot Repair - Dependency Architecture Tests"
    print_info "Validating PEP 668 compatibility and refactored architecture"
    
    local test_functions=(
        test_script_exists_and_executable
        test_script_syntax
        test_required_functions
        test_distribution_detection
        test_module_check_function
        test_venv_creation
        test_venv_python_import
        test_venv_pip_install
        test_no_global_pip_install
        test_no_break_system_packages
        test_priority_1_native_packages
        test_venv_fallback_exists
        test_import_validation
        test_error_handling
        test_boot_repair_compatibility
        test_main_app_location
    )
    
    for test_func in "${test_functions[@]}"; do
        if ! $test_func; then
            # Just log failure, continue with other tests
            :
        fi
    done
    
    # Print summary
    print_header "Test Summary"
    echo -e "${GREEN}Passed: ${TESTS_PASSED}${NC}"
    echo -e "${RED}Failed: ${TESTS_FAILED}${NC}"
    echo -e "${YELLOW}Skipped: ${TESTS_SKIPPED}${NC}"
    echo ""
    
    if [[ ${TESTS_FAILED} -eq 0 ]]; then
        echo -e "${GREEN}✅ All tests passed!${NC}"
        return 0
    else
        echo -e "${RED}❌ Some tests failed!${NC}"
        return 1
    fi
}

# Cleanup on exit
trap cleanup_test_venv EXIT

run_all_tests
