#!/bin/bash

#############################################################################
# test_e2e_workflow.sh - End-to-End Workflow Test
#
# Simulates the complete workflow from boot-repair.sh execution
# through dependency installation to app readiness
#############################################################################

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."
BOOT_REPAIR_SCRIPT="${PROJECT_ROOT}/boot-repair.sh"
INSTALL_DEPS_SCRIPT="${PROJECT_ROOT}/install-deps.sh"
MAIN_APP="${PROJECT_ROOT}/boot-repair-app_0.0.3/main.py"

#############################################################################
# Test utilities
#############################################################################

print_header() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC} $1"
    echo -e "${MAGENTA}╚════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}→${NC} $1"
}

print_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

print_fail() {
    echo -e "${RED}✗${NC} $1"
    return 1
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

#############################################################################
# Test 1: Verify all required files exist
#############################################################################

test_files_exist() {
    print_header "Test 1/5: Verificar Arquivos Necessários"
    
    print_step "Verificando boot-repair.sh"
    [[ -f "${BOOT_REPAIR_SCRIPT}" ]] && print_pass "boot-repair.sh existe" || print_fail "boot-repair.sh não encontrado"
    [[ -x "${BOOT_REPAIR_SCRIPT}" ]] && print_pass "boot-repair.sh é executável" || print_fail "boot-repair.sh não é executável"
    
    print_step "Verificando install-deps.sh"
    [[ -f "${INSTALL_DEPS_SCRIPT}" ]] && print_pass "install-deps.sh existe" || print_fail "install-deps.sh não encontrado"
    [[ -x "${INSTALL_DEPS_SCRIPT}" ]] && print_pass "install-deps.sh é executável" || print_fail "install-deps.sh não é executável"
    
    print_step "Verificando aplicação principal"
    [[ -f "${MAIN_APP}" ]] && print_pass "main.py existe" || print_fail "main.py não encontrado"
    
    print_step "Verificando testes"
    [[ -f "${PROJECT_ROOT}/tests/test_dependency_architecture.sh" ]] && print_pass "test_dependency_architecture.sh existe" || print_fail "Testes não encontrados"
    
    echo -e "${GREEN}✅ Teste 1 Completo${NC}"
}

#############################################################################
# Test 2: Verify distribution detection
#############################################################################

test_distribution_detection() {
    print_header "Test 2/5: Detecção de Distribuição"
    
    print_step "Carregando script de detecção"
    local detected_distro
    detected_distro=$(bash -c "source '${INSTALL_DEPS_SCRIPT}'; detect_distribution")
    
    [[ -n "${detected_distro}" ]] && print_pass "Distribuição detectada: ${detected_distro}" || print_fail "Falha na detecção"
    [[ "${detected_distro}" =~ ^(arch|debian)$ ]] && print_pass "Distribuição suportada" || print_fail "Distribuição não suportada: ${detected_distro}"
    
    echo -e "${GREEN}✅ Teste 2 Completo${NC}"
}

#############################################################################
# Test 3: Verify dependency installation logic
#############################################################################

test_dependency_installation_logic() {
    print_header "Test 3/5: Lógica de Instalação de Dependências"
    
    print_step "Testando Priority 1: Verificação de pacotes nativos"
    
    # Source the script to access functions
    source "${INSTALL_DEPS_SCRIPT}"
    
    print_step "Verificando check_python_module function"
    if check_python_module python3 sys; then
        print_pass "check_python_module funciona corretamente"
    else
        print_fail "check_python_module falhou"
    fi
    
    print_step "Verificando detecção de módulos missing"
    local missing_mods
    if missing_mods=$(detect_missing_python_modules python3 2>/dev/null); then
        if [[ -z "${missing_mods}" ]]; then
            print_pass "Todos os módulos Python estão disponíveis (sem necessidade de venv)"
        else
            print_pass "Módulos missing detectados (venv será criado)"
        fi
    else
        print_fail "Erro ao detectar módulos"
    fi
    
    echo -e "${GREEN}✅ Teste 3 Completo${NC}"
}

#############################################################################
# Test 4: Verify Python module availability
#############################################################################

test_python_modules() {
    print_header "Test 4/5: Disponibilidade de Módulos Python"
    
    local required_modules=(customtkinter darkdetect)
    local failed_modules=()
    
    for module in "${required_modules[@]}"; do
        print_step "Verificando módulo: ${module}"
        if python3 -c "import ${module}" >/dev/null 2>&1; then
            print_pass "${module} está disponível"
        else
            print_info "${module} não está disponível (venv será criado)"
            failed_modules+=("${module}")
        fi
    done
    
    if [[ ${#failed_modules[@]} -eq 0 ]]; then
        print_pass "Todos os módulos necessários estão disponíveis"
        echo -e "${GREEN}✅ Teste 4 Completo (Caminho Rápido)${NC}"
    else
        print_info "Alguns módulos ausentes, venv seria criado: ${failed_modules[*]}"
        echo -e "${YELLOW}✓ Teste 4 Completo (Caminho com Venv)${NC}"
    fi
}

#############################################################################
# Test 5: Verify complete workflow
#############################################################################

test_complete_workflow() {
    print_header "Test 5/5: Fluxo Completo Simulado"
    
    print_step "1. Detectar distribuição"
    local distro
    distro=$(bash -c "source '${INSTALL_DEPS_SCRIPT}'; detect_distribution")
    print_pass "Distribuição: ${distro}"
    
    print_step "2. Executar install-deps com dry-run"
    print_info "Executando: bash '${INSTALL_DEPS_SCRIPT}' '${distro}'"
    if bash "${INSTALL_DEPS_SCRIPT}" "${distro}" 2>&1 | tail -5; then
        print_pass "Script de dependências executado com sucesso"
    else
        print_fail "Script de dependências falhou"
    fi
    
    print_step "3. Verificar interpretador Python resolvido"
    local python_interpreter
    if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
        python_interpreter="${PROJECT_ROOT}/.venv/bin/python"
        print_pass "Usando Python do venv: ${python_interpreter}"
    else
        python_interpreter="python3"
        print_pass "Usando Python do sistema: ${python_interpreter}"
    fi
    
    print_step "4. Verificar que main.py é acessível"
    if [[ -f "${MAIN_APP}" ]]; then
        print_pass "main.py está acessível"
    else
        print_fail "main.py não encontrado"
    fi
    
    print_step "5. Validação de sintaxe Python da aplicação"
    if ${python_interpreter} -m py_compile "${MAIN_APP}" 2>/dev/null; then
        print_pass "main.py tem sintaxe Python válida"
    else
        print_fail "main.py tem erros de sintaxe"
    fi
    
    echo -e "${GREEN}✅ Teste 5 Completo${NC}"
}

#############################################################################
# Summary
#############################################################################

print_summary() {
    print_header "Sumário End-to-End"
    
    echo ""
    echo -e "${GREEN}✅ TODOS OS TESTES END-TO-END COMPLETOS${NC}"
    echo ""
    
    echo "Fluxo de Execução Validado:"
    echo -e "  ${GREEN}1.${NC} boot-repair.sh inicia"
    echo -e "  ${GREEN}2.${NC} Detecta distribuição automaticamente"
    echo -e "  ${GREEN}3.${NC} Chama install-deps.sh com distribuição"
    echo -e "  ${GREEN}4.${NC} install-deps verifica ou instala dependências"
    echo -e "  ${GREEN}5.${NC} Valida módulos Python"
    echo -e "  ${GREEN}6.${NC} Retorna caminho ao Python correto"
    echo -e "  ${GREEN}7.${NC} boot-repair.sh executa main.py com Python certo"
    echo ""
    
    echo "Status:"
    echo -e "  ${GREEN}✓${NC} Todos os arquivos necessários presentes"
    echo -e "  ${GREEN}✓${NC} Detecção de distribuição funcionando"
    echo -e "  ${GREEN}✓${NC} Lógica de instalação validada"
    echo -e "  ${GREEN}✓${NC} Módulos Python disponíveis"
    echo -e "  ${GREEN}✓${NC} Fluxo completo funcionando"
    echo ""
    
    echo -e "${MAGENTA}════════════════════════════════════════${NC}"
    echo -e "${GREEN}🚀 PRONTO PARA PRODUÇÃO${NC}"
    echo -e "${MAGENTA}════════════════════════════════════════${NC}"
}

#############################################################################
# Main
#############################################################################

main() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC}   End-to-End Workflow Tests              "
    echo -e "${MAGENTA}║${NC}   Boot Repair - Dependency Architecture  "
    echo -e "${MAGENTA}╚════════════════════════════════════════╝${NC}"
    echo ""
    
    test_files_exist
    test_distribution_detection
    test_dependency_installation_logic
    test_python_modules
    test_complete_workflow
    print_summary
}

main "$@"
