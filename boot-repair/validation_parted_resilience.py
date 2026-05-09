#!/usr/bin/env python3
"""
Teste de resilência: simula timeout do parted e valida que a GUI ainda abre.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

sys.path.insert(0, str(Path(__file__).parent / 'boot-repair-app_0.0.3'))

from core.analysis import collect_evidence, collect_optional_diagnostics
from core.system import CommandTimeoutError
from core.models import Disk, Partition, AnalysisEvidence


def fake_runner_with_timeout(command, *, timeout=30, cwd='', env=None, check=True):
    """Simula parted timeout mas retorna lsblk com sucesso."""
    argv = tuple(command)
    
    # Simular timeout em parted
    if argv[0] == 'parted':
        raise CommandTimeoutError(argv, timeout)
    
    # Simular fdisk falha
    if argv[0] == 'fdisk':
        raise CommandTimeoutError(argv, timeout)
    
    # lsblk retorna dados válidos
    if argv[0] == 'lsblk' and '--json' in argv:
        return json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '1000000000',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '500000000',
                            'fstype': 'ext4',
                            'mountpoint': '/',
                            'uuid': 'test-uuid-1',
                        }
                    ]
                }
            ]
        })
    
    # blkid retorna dados
    if argv[0] == 'blkid':
        return 'DEVNAME=/dev/sda1 UUID=test-uuid-1 TYPE=ext4'
    
    # findmnt retorna dados
    if argv[0] == 'findmnt':
        return '/ ext4 /dev/sda1'
    
    return ''


def test_resilience_to_parted_timeout():
    """Testa que collect_evidence retorna dados válidos mesmo com parted timeout."""
    print("\n" + "="*70)
    print("TESTE: Resilência contra timeout do parted")
    print("="*70)
    
    try:
        with patch('core.analysis.capture', side_effect=fake_runner_with_timeout):
            evidence = collect_evidence(run_optional_diagnostics=False)
            
            print(f"\n✓ collect_evidence completou com sucesso")
            print(f"  - Disks: {len(evidence.disks)}")
            print(f"  - Partitions: {len(evidence.partitions)}")
            
            # Validar dados críticos
            assert evidence.disks, "❌ Nenhum disco detectado"
            assert evidence.partitions, "❌ Nenhuma partição detectada"
            print(f"\n✓ Dados críticos detectados")
            print(f"  - Disco: {evidence.disks[0].name if evidence.disks else 'N/A'}")
            print(f"  - Partição: {evidence.partitions[0].name if evidence.partitions else 'N/A'}")
            
            # Validar que a GUI poderia abrir
            if evidence.disks and evidence.partitions:
                print(f"\n✓ GUI PODE ABRIR COM SUCESSO")
            else:
                print(f"\n❌ GUI NÃO PODERIA ABRIR")
                return False
            
            return True
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_optional_diagnostics_with_timeout():
    """Testa que diagnósticos opcionais falham gracefully."""
    print("\n" + "="*70)
    print("TESTE: Diagnósticos opcionais com timeout")
    print("="*70)
    
    try:
        # Criar evidência de teste
        disks = (Disk(name='/dev/sda', size_bytes=1000000000, path='/dev/sda'),)
        partitions = (Partition(
            name='/dev/sda1',
            disk_name='/dev/sda',
            size_bytes=500000000,
            fs_type='ext4',
            mount_point='/',
            uuid='test-uuid-1',
        ),)
        
        with patch('core.analysis.capture', side_effect=fake_runner_with_timeout):
            findings = collect_optional_diagnostics(
                disks=disks,
                partitions=partitions,
                fstab_entries=(),
                firmware_mode='BIOS',
                blkid_entries=(),
            )
            
            print(f"\n✓ collect_optional_diagnostics completou")
            print(f"  - Findings: {len(findings)}")
            
            # Diagnósticos opcionais podem retornar vazio se não encontrarem problemas
            if findings:
                print(f"\n✓ {len(findings)} issue(s) detectado(s)")
            else:
                print(f"\n✓ Nenhum problema encontrado (esperado com timeout)")
            
            return True
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*70)
    print("VALIDAÇÃO DE RESILÊNCIA: Timeout do Parted")
    print("="*70)
    
    test1_ok = test_resilience_to_parted_timeout()
    test2_ok = test_optional_diagnostics_with_timeout()
    
    print("\n" + "="*70)
    print("RESULTADO FINAL")
    print("="*70)
    
    if test1_ok and test2_ok:
        print("\n✅ TODOS OS TESTES PASSARAM")
        print("\nCritério de sucesso atendido:")
        print("  ✓ GUI abre mesmo com parted timeout")
        print("  ✓ Discos detectados")
        print("  ✓ Partições detectadas")
        print("  ✓ Diagnósticos opcionais falham gracefully")
        return 0
    else:
        print("\n❌ ALGUNS TESTES FALHARAM")
        return 1


if __name__ == '__main__':
    sys.exit(main())
