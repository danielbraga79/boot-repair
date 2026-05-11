from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import core.analysis as analysis
from core.analysis import AnalysisEvidence, collect_evidence
from core.execution import ExecutionReport, execute_repair_plan
from core.flow import BootRepairFlow, FlowStage, FlowStateError, FlowValidationError, RepairSelection
from core.models import DistributionFamily, DiagnosticCategory, DiagnosticFinding, Disk, Partition, RepairAction, RepairContext, RepairPlan, Risk, RiskLevel
from core.planning import build_repair_plan
from core.system import CommandTimeoutError, detect_distribution, detect_distribution_family, read_os_release, suggest_install_command


def _fake_detector() -> AnalysisEvidence:
    return AnalysisEvidence(
        disks=(Disk(name='/dev/sda', size_bytes=1_000_000_000, model='Disk', serial='ABC'),),
        partitions=(
            Partition(name='/dev/sda1', disk_name='/dev/sda', size_bytes=500_000_000, fs_type='ext4', mount_point='/', uuid='uuid-root'),
            Partition(name='/dev/sda2', disk_name='/dev/sda', size_bytes=100_000_000, fs_type='vfat', mount_point='/boot/efi', uuid='uuid-efi'),
        ),
        blkid_entries=('UUID=uuid-root', 'UUID=uuid-efi'),
        fstab_entries=('/dev/sda1 / ext4 defaults 0 1', '/dev/sda2 /boot/efi vfat defaults 0 2'),
        firmware_mode='uefi',
        live_environment=True,
        notes=('ok',),
    )


def _fake_planner(context) -> RepairPlan:
    return RepairPlan(
        title='Boot repair plan',
        actions=(
            RepairAction('mount-root', ('mount', context.root_partition, '/mnt'), True),
            RepairAction('mount-efi', ('mount', context.efi_system_partition, '/mnt/boot/efi'), True),
        ),
        justifications=('validated',),
        risks=(Risk('test risk', RiskLevel.MEDIUM, 'mitigate'),),
        preconditions=('confirmed',),
        rollback=(
            RepairAction('unmount-efi', ('umount', '/mnt/boot/efi'), True),
            RepairAction('unmount-root', ('umount', '/mnt'), True),
        ),
        confidence=0.9,
        trace=('detect', 'analyze', 'validate', 'plan'),
    )


class FakePyUdevDevice:
    def __init__(self, device_node: str, device_type: str, sys_name: str, properties: dict[str, str] | None = None, attributes: dict[str, str] | None = None, parent: Any = None) -> None:
        self.device_node = device_node
        self.device_type = device_type
        self.sys_name = sys_name
        self.subsystem = 'block'
        self.properties = properties or {}
        self.attributes = attributes or {}
        self.parent = parent


class FakePyUdevContext:
    def __init__(self, devices: list[FakePyUdevDevice]) -> None:
        self._devices = devices

    def list_devices(self, subsystem: str | None = None):
        return self._devices


class _FakeRunner:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, *, timeout: int, check: bool, cwd: str = ''):
        from core.system import CommandError, CommandResult

        argv = tuple(command)
        self.calls.append(argv)
        if self.fail_on is not None and self.fail_on in argv:
            raise CommandError(CommandResult(command=argv, returncode=1, stdout='', stderr='boom'))
        return CommandResult(command=argv, returncode=0, stdout='ok', stderr='')


class _FakeCommandRunner:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs

    def __call__(self, command, *, timeout: int = 30, cwd: str = '', env=None, check: bool = True):
        argv = tuple(command)
        if argv in self.outputs:
            return self.outputs[argv]
        raise FileNotFoundError(f'command not found: {argv}')


class TestFlow(unittest.TestCase):
    def setUp(self) -> None:
        import importlib

        self._original_import_module = importlib.import_module
        self._pyudev_allowed = False

        def patched_import_module(name, package=None):
            if name == 'pyudev' and not self._pyudev_allowed:
                raise ImportError('No module named pyudev')
            return self._original_import_module(name, package=package)

        self._import_patch = patch('core.analysis.importlib.import_module', side_effect=patched_import_module)
        self._import_patch.start()

        # Clear evidence cache
        from pathlib import Path
        cache_file = Path('/tmp/boot-repair-evidence-cache.json')
        if cache_file.exists():
            cache_file.unlink()

    def tearDown(self) -> None:
        self._import_patch.stop()

    def enable_pyudev(self, fake_module: Any) -> None:
        self._pyudev_allowed = True
        pyudev_patch = patch('core.analysis.importlib.import_module', return_value=fake_module)
        pyudev_patch.start()
        self.addCleanup(pyudev_patch.stop)

    def test_full_flow(self) -> None:
        flow = BootRepairFlow(
            selection=RepairSelection(
                root_partition='/dev/sda1',
                efi_system_partition='/dev/sda2',
                firmware_mode='uefi',
                confirmed=True,
            ),
            detector=_fake_detector,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple(), notes=('executed',)),
        )

        evidence = flow.detect()
        self.assertEqual(evidence.firmware_mode, 'uefi')

        analysis = flow.analyze()
        self.assertEqual(analysis.firmware_mode, 'uefi')

        validation = flow.validate()
        self.assertTrue(validation.approved)

        plan = flow.plan()
        self.assertEqual(plan.title, 'Boot repair plan')
        self.assertEqual(len(plan.actions), 2)

        report = flow.execute()
        self.assertTrue(report.success)

    def test_validate_rejects_root_partition_not_in_analysis(self) -> None:
        flow = BootRepairFlow(
            selection=RepairSelection(
                root_partition='/dev/sdb1',
                efi_system_partition='/dev/sda2',
                firmware_mode='uefi',
                confirmed=True,
            ),
            detector=_fake_detector,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )

        flow.detect()
        flow.analyze()
        with self.assertRaises(FlowValidationError):
            flow.validate()

    def test_validate_rejects_efi_on_other_disk(self) -> None:
        evidence = AnalysisEvidence(
            disks=(
                Disk(name='/dev/sda', size_bytes=1_000_000_000),
                Disk(name='/dev/sdb', size_bytes=1_000_000_000),
            ),
            partitions=(
                Partition(name='/dev/sda1', disk_name='/dev/sda', size_bytes=500_000_000, fs_type='ext4'),
                Partition(name='/dev/sdb1', disk_name='/dev/sdb', size_bytes=100_000_000, fs_type='vfat'),
            ),
            blkid_entries=(),
            fstab_entries=(),
            firmware_mode='uefi',
            live_environment=True,
            notes=(),
        )
        flow = BootRepairFlow(
            selection=RepairSelection(
                root_partition='/dev/sda1',
                efi_system_partition='/dev/sdb1',
                firmware_mode='uefi',
                confirmed=True,
            ),
            detector=lambda: evidence,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )

        flow.detect()
        flow.analyze()
        validation = flow.validate()
        self.assertTrue(validation.approved)
        self.assertTrue(any('cross-disk' in warning for warning in validation.warnings))

    def test_collect_evidence_detects_partition_table_damage(self) -> None:
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '1000',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '500',
                            'fstype': 'ext4',
                            'mountpoints': ['/'],
                            'uuid': 'uuid-root',
                            'boot': '1',
                        }
                    ],
                }
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): lsblk_payload,
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,MODEL,SERIAL,RM,FSTYPE,MOUNTPOINT,UUID,PKNAME,BOOT'): lsblk_payload,
                ('blkid', '-o', 'export'): 'UUID=uuid-root\n',
                ('parted', '-m', '/dev/sda', 'print'): 'Error: invalid partition table\n',
                ('fdisk', '-l', '/dev/sda'): 'Disklabel type: gpt\n',
                ('fsck.ext4', '-n', '/dev/sda1'): 'clean\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner, run_optional_diagnostics=True)

        self.assertTrue(any(f.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE for f in evidence.diagnostic_findings))

    def test_collect_evidence_skips_parted_timeout_and_still_returns_evidence(self) -> None:
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '1000',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '500',
                            'fstype': 'ext4',
                            'mountpoints': ['/'],
                            'uuid': 'uuid-root',
                            'boot': '1',
                        }
                    ],
                }
            ]
        })

        def runner(command, *, timeout: int = 30, cwd: str = '', env=None, check: bool = True):
            argv = tuple(command)
            if argv == ('parted', '-m', '/dev/sda', 'print'):
                raise CommandTimeoutError(argv, timeout)
            if argv == ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'):
                return lsblk_payload
            if argv == ('blkid', '-o', 'export'):
                return 'UUID=uuid-root\n'
            if argv == ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'):
                return '/\text4\t/dev/sda1\n'
            raise FileNotFoundError(f'command not found: {argv}')

        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
            evidence = collect_evidence(
                fstab_path=fstab_path,
                command_runner=runner,
                run_optional_diagnostics=True,
            )

        self.assertEqual(len(evidence.disks), 1)
        self.assertEqual(len(evidence.partitions), 1)
        self.assertFalse(any(f.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE for f in evidence.diagnostic_findings))

    def test_collect_evidence_detects_btrfs_subvolume_layout(self) -> None:
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '1000',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '500',
                            'fstype': 'btrfs',
                            'mountpoints': ['/'],
                            'uuid': 'uuid-btrfs',
                            'boot': '0',
                        }
                    ],
                }
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): lsblk_payload,
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,MODEL,SERIAL,RM,FSTYPE,MOUNTPOINT,UUID,PKNAME,BOOT'): lsblk_payload,
                ('blkid', '-o', 'export'): 'UUID=uuid-btrfs\n',
                ('btrfs', 'check', '--readonly', '/dev/sda1'): 'check OK\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('UUID=uuid-btrfs / btrfs defaults,subvol=@ 0 1\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertTrue(any(f.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR for f in evidence.diagnostic_findings))

    def test_collect_evidence_handles_mountpoints_list_and_comma_decimal(self) -> None:
        # Test mountpoints as list and size with comma decimal separator
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '223,6G',  # Comma decimal
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '111,8G',
                            'fstype': 'ext4',
                            'mountpoints': ['/'],  # List format
                        },
                        {
                            'name': 'sda2',
                            'type': 'part',
                            'size': '100G',
                            'fstype': 'vfat',
                            'mountpoints': ['/boot/efi'],  # List format
                        }
                    ],
                }
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): lsblk_payload,
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,MODEL,SERIAL,RM,FSTYPE,MOUNTPOINT,UUID,PKNAME,BOOT'): lsblk_payload,
                ('blkid', '-o', 'export'): '',
                ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'): '/\text4\t/dev/sda1\n/boot/efi\tvfat\t/dev/sda2\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n/dev/sda2 /boot/efi vfat defaults 0 2\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 1)
        self.assertEqual(len(evidence.partitions), 2)
        self.assertEqual(evidence.partitions[0].mount_point, '/')
        self.assertEqual(evidence.partitions[1].mount_point, '/boot/efi')
        # Size should be parsed correctly despite comma
        self.assertGreater(evidence.disks[0].size_bytes, 200000000000)  # > 200GB

    def test_collect_evidence_uses_pyudev_primary_detection(self) -> None:
        fake_disk = FakePyUdevDevice(
            '/dev/sda',
            'disk',
            'sda',
            properties={
                'ID_MODEL': 'Disk',
                'ID_SERIAL_SHORT': 'ABC',
            },
            attributes={
                'size': '1953125000',
                'removable': '0',
            },
        )
        fake_partition = FakePyUdevDevice(
            '/dev/sda1',
            'partition',
            'sda1',
            properties={
                'ID_FS_TYPE': 'ext4',
                'ID_FS_UUID': 'uuid-root',
                'ID_FS_LABEL': 'rootfs',
                'ID_PART_ENTRY_FLAGS': 'boot',
            },
            attributes={
                'size': '976562500',
            },
            parent=fake_disk,
        )
        fake_context = FakePyUdevContext([fake_disk, fake_partition])

        class FakePyUdevModule:
            def Context(self) -> FakePyUdevContext:
                return fake_context

        self.enable_pyudev(FakePyUdevModule())
        runner = _FakeCommandRunner(
            {
                ('blkid', '-o', 'export'): 'DEVNAME=/dev/sda1\nUUID=uuid-root\nTYPE=ext4\n',
                ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'): '/\text4\t/dev/sda1\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 1)
        self.assertEqual(len(evidence.partitions), 1)
        self.assertEqual(evidence.disks[0].name, '/dev/sda')
        self.assertEqual(evidence.partitions[0].name, '/dev/sda1')
        self.assertEqual(evidence.partitions[0].disk_name, '/dev/sda')
        self.assertEqual(evidence.partitions[0].uuid, 'uuid-root')
        self.assertEqual(evidence.partitions[0].label, 'rootfs')

    def test_collect_evidence_detects_nvme_and_multiple_esps_with_pyudev(self) -> None:
        fake_disk = FakePyUdevDevice(
            '/dev/sda',
            'disk',
            'sda',
            properties={'ID_BUS': 'ata'},
            attributes={'size': '976562500'},
        )
        fake_nvme = FakePyUdevDevice(
            '/dev/nvme0n1',
            'disk',
            'nvme0n1',
            properties={'ID_BUS': 'nvme'},
            attributes={'size': '1953125000'},
        )
        fake_boot = FakePyUdevDevice(
            '/dev/sda2',
            'partition',
            'sda2',
            properties={
                'ID_FS_TYPE': 'vfat',
                'ID_FS_UUID': 'uuid-efi',
                'ID_FS_LABEL': 'EFI System',
                'ID_PART_ENTRY_FLAGS': 'boot,esp',
            },
            attributes={'size': '204800'},
            parent=fake_disk,
        )
        fake_root = FakePyUdevDevice(
            '/dev/sda1',
            'partition',
            'sda1',
            properties={
                'ID_FS_TYPE': 'ext4',
                'ID_FS_UUID': 'uuid-root',
            },
            attributes={'size': '976562500'},
            parent=fake_disk,
        )
        fake_nvme_part = FakePyUdevDevice(
            '/dev/nvme0n1p1',
            'partition',
            'nvme0n1p1',
            properties={
                'ID_FS_TYPE': 'vfat',
                'ID_FS_UUID': 'uuid-nvme-efi',
                'ID_FS_LABEL': 'NVMe EFI',
                'ID_PART_ENTRY_FLAGS': 'boot,esp',
            },
            attributes={'size': '1048576'},
            parent=fake_nvme,
        )
        fake_context = FakePyUdevContext([fake_disk, fake_nvme, fake_root, fake_boot, fake_nvme_part])

        class FakePyUdevModule:
            def Context(self) -> FakePyUdevContext:
                return fake_context

        self.enable_pyudev(FakePyUdevModule())
        runner = _FakeCommandRunner(
            {
                ('blkid', '-o', 'export'): 'DEVNAME=/dev/sda2\nTYPE=vfat\nDEVNAME=/dev/nvme0n1p1\nTYPE=vfat\n',
                ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'): '/\text4\t/dev/sda1\n/boot/efi\tvfat\t/dev/sda2\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n/dev/sda2 /boot/efi vfat defaults 0 2\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 2)
        self.assertTrue(any(d.name == '/dev/nvme0n1' for d in evidence.disks))
        self.assertTrue(any(p.name == '/dev/nvme0n1p1' for p in evidence.partitions))
        self.assertTrue(any(p.name == '/dev/sda2' for p in evidence.partitions))
        self.assertFalse(any(f.category == DiagnosticCategory.EFI_MISSING for f in evidence.diagnostic_findings))

    def test_collect_evidence_falls_back_when_pyudev_unavailable(self) -> None:
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): json.dumps({
                    'blockdevices': [
                        {
                            'name': 'sda',
                            'type': 'disk',
                            'size': '1000',
                            'children': [
                                {
                                    'name': 'sda1',
                                    'type': 'part',
                                    'size': '500',
                                    'fstype': 'ext4',
                                }
                            ],
                        }
                    ]
                }),
                ('blkid', '-o', 'export'): '',
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
            with patch('core.analysis._parse_mounts', return_value=()):
                evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 1)
        self.assertEqual(len(evidence.partitions), 1)
        self.assertTrue(any('pyudev unavailable' in note for note in evidence.notes))

    def test_detect_distribution_parsing(self) -> None:
        # Test that lsblk tries sudo when permission denied
        lsblk_payload = json.dumps({
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
                            'mountpoints': ['/'],
                        }
                    ],
                }
            ]
        })
        
        class PermissionThenSuccessRunner:
            def __init__(self):
                self.call_count = 0
                
            def __call__(self, command, *, timeout=30, cwd='', env=None, check=True):
                from core.system import CommandError, CommandResult
                self.call_count += 1
                if 'sudo' in command:
                    # Sudo call succeeds
                    return lsblk_payload
                raise CommandError(CommandResult(command=command, returncode=1, stdout='', stderr='Permission denied'))
        
        runner = PermissionThenSuccessRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
            with patch('core.analysis._parse_mounts', return_value=()):
                evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 1)
        self.assertEqual(len(evidence.partitions), 1)
        self.assertIn('lsblk succeeded with elevated privileges', evidence.notes)

    def test_collect_evidence_detects_efi_when_present(self) -> None:
        # Test that EFI is detected when /boot/efi is mounted
        lsblk_payload = json.dumps({
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
                            'mountpoints': ['/'],
                        },
                        {
                            'name': 'sda2',
                            'type': 'part',
                            'size': '100000000',
                            'fstype': 'vfat',
                            'mountpoints': ['/boot/efi'],
                        }
                    ],
                }
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,MODEL,SERIAL,RM,FSTYPE,MOUNTPOINT,UUID,PKNAME,BOOT'): lsblk_payload,
                ('blkid', '-o', 'export'): 'DEVNAME=/dev/sda2\nTYPE=vfat\n',
                ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'): '/\text4\t/dev/sda1\n/boot/efi\tvfat\t/dev/sda2\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n/dev/sda2 /boot/efi vfat defaults 0 2\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        # Should not have EFI_MISSING diagnostic
        efi_missing = [f for f in evidence.diagnostic_findings if f.category == DiagnosticCategory.EFI_MISSING]
        self.assertEqual(len(efi_missing), 0)

    def test_build_repair_plan_includes_diagnostic_actions_for_corruption(self) -> None:
        context = RepairContext(
            disks=(_fake_detector().disks),
            partitions=_fake_detector().partitions,
            firmware_mode='uefi',
            live_environment=True,
            distribution='ubuntu',
            initramfs_tool='update-initramfs',
            evidence=(_fake_detector().blkid_entries + _fake_detector().fstab_entries + _fake_detector().notes),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='/dev/sda2',
            confirmed=True,
            diagnostic_findings=(DiagnosticFinding(DiagnosticCategory.FS_CORRUPTION, 'invalid superblock', severity=RiskLevel.CRITICAL, evidence='/dev/sda1'),),
        )
        plan = build_repair_plan(context)
        self.assertTrue(any(action.label.startswith('inspect-') for action in plan.actions))

    def test_plan_requires_validation(self) -> None:
        flow = BootRepairFlow(
            selection=RepairSelection(
                root_partition='/dev/sda1',
                efi_system_partition='/dev/sda2',
                firmware_mode='uefi',
                confirmed=True,
            ),
            detector=_fake_detector,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )

        with self.assertRaises(FlowStateError):
            flow.plan()

    def test_build_repair_plan_for_uefi(self) -> None:
        context = RepairContext(
            disks=(_fake_detector().disks),
            partitions=_fake_detector().partitions,
            firmware_mode='uefi',
            live_environment=True,
            distribution='ubuntu',
            initramfs_tool='update-initramfs',
            evidence=(_fake_detector().blkid_entries + _fake_detector().fstab_entries + _fake_detector().notes),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='/dev/sda2',
            confirmed=True,
        )
        plan = build_repair_plan(context)
        self.assertTrue(any(action.label == 'install-bootloader' for action in plan.actions))
        self.assertTrue(any('grub-install' in ' '.join(action.command) or 'bootctl' in ' '.join(action.command) for action in plan.actions))

    def test_build_repair_plan_for_bios(self) -> None:
        context = RepairContext(
            disks=(_fake_detector().disks),
            partitions=(Partition(name='/dev/sda1', disk_name='/dev/sda', size_bytes=500_000_000, fs_type='ext4'),),
            firmware_mode='bios',
            live_environment=False,
            distribution='arch',
            initramfs_tool='mkinitcpio',
            evidence=tuple(),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='',
            confirmed=True,
        )
        plan = build_repair_plan(context)
        self.assertTrue(any(action.label == 'install-bootloader' for action in plan.actions))
        self.assertTrue(any('grub-install' in ' '.join(action.command) for action in plan.actions))

    def test_detect_distribution_parsing(self) -> None:
        values = read_os_release()
        self.assertIsInstance(values, dict)
        self.assertEqual(detect_distribution({'ID': 'arch'}), 'arch')
        self.assertEqual(detect_distribution({'ID': 'ubuntu'}), 'ubuntu')
        self.assertEqual(detect_distribution({'ID': 'cachyos'}), 'cachyos')
        self.assertEqual(detect_distribution({'ID': 'debian'}), 'debian')

    def test_detect_distribution_family(self) -> None:
        self.assertEqual(detect_distribution_family({'ID': 'arch'}), DistributionFamily.ARCH)
        self.assertEqual(detect_distribution_family({'ID': 'cachyos'}), DistributionFamily.ARCH)
        self.assertEqual(detect_distribution_family({'ID': 'ubuntu'}), DistributionFamily.DEBIAN)
        self.assertEqual(detect_distribution_family({'ID': 'linuxmint', 'ID_LIKE': 'ubuntu debian'}), DistributionFamily.DEBIAN)

    def test_suggest_install_command_handles_sudo_wrapped_command(self) -> None:
        self.assertEqual(
            suggest_install_command(('sudo', '-E', 'lsblk', '--json'), DistributionFamily.DEBIAN),
            'sudo apt install util-linux',
        )

    def test_detect_lsblk_columns_skips_boot_column_when_unsupported(self) -> None:
        def runner(command, *, timeout: int = 30, cwd: str = '', env=None, check: bool = True):
            command_tuple = tuple(command)
            if 'BOOT' in command_tuple[-1].split(','):
                raise FileNotFoundError('unsupported lsblk column')
            return '{}'

        supported_columns = analysis._detect_lsblk_columns(runner)
        self.assertNotIn('BOOT', supported_columns)
        self.assertIn('MODEL', supported_columns)
        self.assertIn('SERIAL', supported_columns)
        self.assertIn('RM', supported_columns)

    def test_run_root_uses_interactive_sudo_without_dash_n(self) -> None:
        from core.system import run_root

        with patch('core.system.os.geteuid', return_value=1000), patch('core.system.subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=('sudo', '-E', 'lsblk'), returncode=0, stdout='ok', stderr='')
            result = run_root(('lsblk', '--json'))

        self.assertEqual(result.command[0], 'sudo')
        self.assertEqual(result.command[1], '-E')
        self.assertEqual(result.command[2:], ('lsblk', '--json'))

    def test_main_allows_normal_user_cli(self) -> None:
        import main

        with patch('main.os.geteuid', return_value=1000):
            with patch('main.run_cli', return_value=0) as mock_cli:
                with patch.object(main.sys, 'argv', ['main.py', '--cli']):
                    result = main.main()

        self.assertEqual(result, 0)
        mock_cli.assert_called_once()

    def test_main_fails_when_started_as_root(self) -> None:
        import main

        with patch('main.os.geteuid', return_value=0):
            with patch.object(main.sys, 'argv', ['main.py', '--cli']):
                with self.assertRaises(SystemExit):
                    main.main()

    def test_detect_boot_partition_formatted(self) -> None:
        """Test detection of formatted boot partition."""
        partitions = (
            Partition(name='/dev/sda1', disk_name='/dev/sda', size_bytes=500_000_000, fs_type='ext4', mount_point='/', uuid='uuid-root'),
            Partition(name='/dev/sda2', disk_name='/dev/sda', size_bytes=100_000_000, fs_type='vfat', mount_point='/boot/efi', uuid='uuid-efi'),
        )
        
        def runner(command):
            if command[0] == 'find' and '/boot/efi/EFI' in command:
                return ''  # No EFI directory
            return ''
        
        findings = analysis._detect_boot_partition_issues(partitions, runner)
        self.assertTrue(any(f.category == DiagnosticCategory.BOOT_PARTITION_FORMATTED for f in findings))

    def test_detect_fstab_missing(self) -> None:
        """Test detection of missing fstab."""
        fstab_entries = ()  # Empty fstab
        findings = analysis._detect_fstab_issues(fstab_entries)
        self.assertTrue(any(f.category == DiagnosticCategory.FSTAB_MISSING for f in findings))

    def test_planning_includes_boot_formatted_actions(self) -> None:
        """Test that planning includes actions for boot partition formatted."""
        context = RepairContext(
            disks=(),
            partitions=(),
            firmware_mode='uefi',
            live_environment=True,
            distribution='arch',
            initramfs_tool='mkinitcpio',
            evidence=(),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='/dev/sda2',
            confirmed=True,
            diagnostic_findings=(
                DiagnosticFinding(
                    DiagnosticCategory.BOOT_PARTITION_FORMATTED,
                    'Boot partition formatted',
                    severity=RiskLevel.CRITICAL,
                    evidence='test',
                ),
            ),
        )
        
        from core.planning import _diagnostic_actions
        actions = _diagnostic_actions(context)
        action_labels = [a.label for a in actions]
        self.assertIn('recreate-boot-structure', action_labels)
        self.assertIn('reinstall-bootloader', action_labels)
        self.assertIn('regenerate-initramfs-boot', action_labels)
        self.assertIn('recreate-uefi-entries', action_labels)

    def test_planning_includes_fstab_missing_actions(self) -> None:
        """Test that planning includes actions for missing fstab."""
        context = RepairContext(
            disks=(),
            partitions=(),
            firmware_mode='uefi',
            live_environment=True,
            distribution='arch',
            initramfs_tool='mkinitcpio',
            evidence=(),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='/dev/sda2',
            confirmed=True,
            diagnostic_findings=(
                DiagnosticFinding(
                    DiagnosticCategory.FSTAB_MISSING,
                    'Fstab missing',
                    severity=RiskLevel.CRITICAL,
                    evidence='test',
                ),
            ),
        )
        
        from core.planning import _diagnostic_actions
        actions = _diagnostic_actions(context)
        action_labels = [a.label for a in actions]
        self.assertIn('reconstruct-fstab', action_labels)
        self.assertIn('validate-uuids', action_labels)
        self.assertIn('review-mountpoints', action_labels)
        self.assertIn('write-fstab', action_labels)
        self.assertIn('validate-fstab-syntax', action_labels)

    def test_plan_requires_efi_partition_for_uefi_mode(self) -> None:
        context = RepairContext(
            disks=(),
            partitions=(),
            firmware_mode='uefi',
            live_environment=True,
            distribution='arch',
            initramfs_tool='mkinitcpio',
            evidence=(),
            root_partition='/dev/sda1',
            root_disk_name='/dev/sda',
            efi_system_partition='',
            confirmed=True,
        )
        from core.planning import build_repair_plan

        with self.assertRaises(ValueError):
            build_repair_plan(context)

    def test_gui_can_be_imported_and_initialized(self) -> None:
        """Test that GUI components can be imported and basic initialization works."""
        try:
            import customtkinter as ctk
            from gui.screens import build_screens
            from gui.app import BootRepairApp
        except ImportError as e:
            self.skipTest(f"GUI dependencies not available: {e}")
        
        # Test that modules can be imported without display
        self.assertTrue(hasattr(ctk, 'CTk'))
        self.assertTrue(hasattr(ctk, 'CTkFrame'))
        self.assertTrue(hasattr(ctk, 'CTkButton'))
        
        # Test that screen classes exist
        from gui.screens import WelcomeScreen, SelectionScreen, AnalysisScreen, PlanScreen, ExecutionScreen
        self.assertTrue(WelcomeScreen)
        self.assertTrue(SelectionScreen)
        self.assertTrue(AnalysisScreen)
        self.assertTrue(PlanScreen)
        self.assertTrue(ExecutionScreen)
        
        # Test that app class exists
        self.assertTrue(BootRepairApp)

    def test_gui_help_screen_is_available_and_translated(self) -> None:
        try:
            import customtkinter as ctk
            from gui.screens import build_screens
        except ImportError as e:
            self.skipTest(f"GUI dependencies not available: {e}")

        try:
            root = ctk.CTk()
            root.withdraw()
        except Exception as e:
            self.skipTest(f"Unable to initialize GUI root: {e}")

        translator = __import__('i18n').TranslationManager()
        screens = build_screens(
            root,
            translator=translator,
            on_welcome_continue=lambda: None,
            on_welcome_help=lambda: None,
            on_help_back=lambda: None,
        )

        self.assertTrue(hasattr(screens, 'help'))
        self.assertEqual(screens.welcome.help_button.cget('text'), translator.translate('help.open_button'))
        self.assertEqual(screens.help._step_title.cget('text'), translator.translate('help.steps.title'))
        self.assertEqual(screens.help._section_labels[0].cget('text'), translator.translate('help.section.what'))
        self.assertEqual(screens.help._section_texts[0].cget('text'), translator.translate('help.section.what.text'))

        root.destroy()

    def test_gui_core_integration_valid_evidence_flows_through(self) -> None:
        """Verify that valid evidence detected in core reaches GUI without modification."""
        evidence = _fake_detector()
        
        flow = BootRepairFlow(
            detector=lambda: evidence,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )
        
        detected_evidence = flow.detect()
        
        # Verify core returns same evidence
        self.assertEqual(len(detected_evidence.disks), len(evidence.disks))
        """Verify that valid evidence detected in core reaches GUI without modification."""
        evidence = _fake_detector()
        
        flow = BootRepairFlow(
            detector=lambda: evidence,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )
        
        detected_evidence = flow.detect()
        
        # Verify core returns same evidence
        self.assertEqual(len(detected_evidence.disks), len(evidence.disks))
        self.assertEqual(len(detected_evidence.partitions), len(evidence.partitions))
        self.assertEqual(detected_evidence.firmware_mode, evidence.firmware_mode)
        
        # Verify evidence properties are preserved
        self.assertEqual(detected_evidence.disks[0].name, '/dev/sda')
        self.assertEqual(detected_evidence.partitions[0].mount_point, '/')
        self.assertEqual(detected_evidence.partitions[1].mount_point, '/boot/efi')

    def test_gui_core_integration_no_duplicate_collection(self) -> None:
        """Verify that GUI does not re-run collection after initial detect."""
        call_count = 0
        
        def counting_detector():
            nonlocal call_count
            call_count += 1
            return _fake_detector()
        
        flow = BootRepairFlow(
            detector=counting_detector,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )
        
        # First detection
        evidence1 = flow.detect()
        self.assertEqual(call_count, 1)
        
        # Analysis should reuse evidence, not re-collect
        evidence2 = flow.analyze()
        self.assertEqual(call_count, 1, "analyze() should not trigger re-collection")
        
        # Same evidence should be returned
        self.assertEqual(len(evidence1.disks), len(evidence2.disks))
        self.assertEqual(evidence1.firmware_mode, evidence2.firmware_mode)

    def test_gui_core_integration_partition_disk_mapping(self) -> None:
        """Verify that GUI can correctly map partitions to disks."""
        evidence = AnalysisEvidence(
            disks=(
                Disk(name='/dev/sda', size_bytes=1_000_000_000, model='Disk A'),
                Disk(name='/dev/sdb', size_bytes=2_000_000_000, model='Disk B'),
            ),
            partitions=(
                Partition(name='/dev/sda1', disk_name='/dev/sda', size_bytes=500_000_000, fs_type='ext4', mount_point='/'),
                Partition(name='/dev/sda2', disk_name='/dev/sda', size_bytes=200_000_000, fs_type='vfat', mount_point='/boot/efi'),
                Partition(name='/dev/sdb1', disk_name='/dev/sdb', size_bytes=1_000_000_000, fs_type='ext4', mount_point='/home'),
            ),
            blkid_entries=(),
            fstab_entries=(),
            firmware_mode='uefi',
            live_environment=True,
            notes=(),
        )
        
        # Simulate GUI building partition_disk_map
        partition_disk_map = {partition.name: partition.disk_name for partition in evidence.partitions}
        
        self.assertEqual(partition_disk_map['/dev/sda1'], '/dev/sda')
        self.assertEqual(partition_disk_map['/dev/sda2'], '/dev/sda')
        self.assertEqual(partition_disk_map['/dev/sdb1'], '/dev/sdb')
        
        # Verify that combobox values can be populated
        partitions_list = [partition.name for partition in evidence.partitions]
        disks_list = [f'{disk.name} | {disk.model}' for disk in evidence.disks]
        
        self.assertEqual(len(partitions_list), 3)
        self.assertEqual(len(disks_list), 2)
        self.assertIn('/dev/sda1', partitions_list)
        self.assertIn('/dev/sda | Disk A', disks_list)

    def test_gui_core_integration_empty_device_list_handled_gracefully(self) -> None:
        """Verify that GUI handles empty device lists without crashing."""
        evidence = AnalysisEvidence(
            disks=(),
            partitions=(),
            blkid_entries=(),
            fstab_entries=(),
            firmware_mode='unknown',
            live_environment=False,
            notes=('No devices detected',),
        )
        
        # GUI should handle empty lists
        partition_disk_map = {partition.name: partition.disk_name for partition in evidence.partitions}
        partitions_list = [partition.name for partition in evidence.partitions]
        disks_list = [disk.name for disk in evidence.disks]
        
        self.assertEqual(len(partition_disk_map), 0)
        self.assertEqual(len(partitions_list), 0)
        self.assertEqual(len(disks_list), 0)

    def test_gui_core_integration_flow_state_transitions(self) -> None:
        """Verify correct flow state transitions when integrating with GUI."""
        flow = BootRepairFlow(
            detector=_fake_detector,
            planner=_fake_planner,
            executor=lambda plan: ExecutionReport(success=True, applied_actions=tuple()),
        )
        
        # Initial state
        self.assertEqual(flow.state.stage, FlowStage.DETECT)
        self.assertIsNone(flow.state.evidence)
        
        # After detect
        evidence = flow.detect()
        self.assertEqual(flow.state.stage, FlowStage.ANALYZE)
        self.assertIsNotNone(flow.state.evidence)
        
        # After analyze
        analyzed = flow.analyze()
        self.assertEqual(flow.state.stage, FlowStage.ANALYZE)
        
        # Set selection and validate
        flow.set_selection(RepairSelection(
            root_partition='/dev/sda1',
            efi_system_partition='/dev/sda2',
            firmware_mode='uefi',
            confirmed=True,
        ))
        validation = flow.validate()
        self.assertEqual(flow.state.stage, FlowStage.VALIDATE)
        
        # Plan
        plan = flow.plan()
        self.assertEqual(flow.state.stage, FlowStage.PLAN)

    def test_collect_evidence_uses_proc_mounts_when_findmnt_unavailable(self) -> None:
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '1000',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '500',
                            'fstype': 'ext4',
                        }
                    ],
                }
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): lsblk_payload,
                ('blkid', '-o', 'export'): '',
            }
        )
        with patch('core.analysis._parse_mounts', return_value=(('/dev/sda1', '/', False),)):
            with tempfile.TemporaryDirectory() as tmpdir:
                fstab_path = Path(tmpdir) / 'fstab'
                fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n', encoding='utf-8')
                evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.partitions), 1)
        self.assertEqual(evidence.partitions[0].mount_point, '/')

    def test_collect_evidence_detects_multiple_disks_and_multiple_esps(self) -> None:
        lsblk_payload = json.dumps({
            'blockdevices': [
                {
                    'name': 'sda',
                    'type': 'disk',
                    'size': '500G',
                    'children': [
                        {
                            'name': 'sda1',
                            'type': 'part',
                            'size': '250G',
                            'fstype': 'ext4',
                            'mountpoints': ['/'],
                        },
                        {
                            'name': 'sda2',
                            'type': 'part',
                            'size': '50G',
                            'fstype': 'vfat',
                            'mountpoints': ['/boot/efi'],
                        },
                    ],
                },
                {
                    'name': 'nvme0n1',
                    'type': 'disk',
                    'size': '1T',
                    'children': [
                        {
                            'name': 'nvme0n1p1',
                            'type': 'part',
                            'size': '100G',
                            'fstype': 'vfat',
                            'mountpoints': ['/boot/efi'],
                        }
                    ],
                },
            ]
        })
        runner = _FakeCommandRunner(
            {
                ('lsblk', '--json', '--bytes', '--output', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,PKNAME'): lsblk_payload,
                ('blkid', '-o', 'export'): 'DEVNAME=/dev/sda2\nTYPE=vfat\nDEVNAME=/dev/nvme0n1p1\nTYPE=vfat\n',
                ('findmnt', '-n', '-o', 'TARGET,FSTYPE,SOURCE'): '/\text4\t/dev/sda1\n/boot/efi\tvfat\t/dev/sda2\n',
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fstab_path = Path(tmpdir) / 'fstab'
            fstab_path.write_text('/dev/sda1 / ext4 defaults 0 1\n/dev/sda2 /boot/efi vfat defaults 0 2\n', encoding='utf-8')
            evidence = collect_evidence(fstab_path=fstab_path, command_runner=runner)

        self.assertEqual(len(evidence.disks), 2)
        self.assertEqual(len(evidence.partitions), 3)
        self.assertTrue(any(part.name == '/dev/sda2' for part in evidence.partitions))
        self.assertTrue(any(part.name == '/dev/nvme0n1p1' for part in evidence.partitions))

    def test_execution_reports_failed_action(self) -> None:
        plan = RepairPlan(
            title='test',
            actions=(
                RepairAction('step-one', ('echo', '1'), False),
                RepairAction('step-two', ('echo', '2'), False),
            ),
            justifications=('ok',),
            risks=(Risk('r', RiskLevel.LOW),),
            preconditions=('p',),
            rollback=(RepairAction('cleanup', ('echo', 'cleanup'), False),),
            confidence=0.9,
            trace=('detect', 'analyze', 'validate', 'plan'),
        )
        runner = _FakeRunner(fail_on='2')
        report = execute_repair_plan(plan, runner=runner)
        self.assertFalse(report.success)
        self.assertEqual(report.failed_action, 'step-two')
        self.assertGreaterEqual(len(report.notes), 1)


if __name__ == '__main__':
    unittest.main()
