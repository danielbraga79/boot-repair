from __future__ import annotations

import shlex

from core.models import DistributionFamily, DiagnosticCategory, RepairAction, RepairContext, RepairPlan, Risk, RiskLevel, ValidationResult


def _efi_mount_target(context: RepairContext) -> str:
    if context.efi_system_partition:
        for partition in context.partitions:
            if partition.name == context.efi_system_partition and partition.mount_point:
                return f'/mnt{partition.mount_point}'
    return '/mnt/boot/efi'


def _mount_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = [
        RepairAction(
            'mount-root',
            ('mount', context.root_partition, '/mnt'),
            True,
            'action.mount_root.description',
        ),
    ]
    if context.firmware_mode.lower() == 'uefi':
        if not context.efi_system_partition:
            raise ValueError('UEFI repair requires an EFI System Partition')
        efi_target = _efi_mount_target(context)
        actions.append(
            RepairAction(
                'mount-efi',
                ('mkdir', '-p', efi_target),
                True,
                'action.ensure_efi_path.description',
            )
        )
        actions.append(
            RepairAction(
                'mount-efi-partition',
                ('mount', context.efi_system_partition, efi_target),
                True,
                'action.mount_efi_partition.description',
            )
        )
    actions.extend(
        (
            RepairAction('bind-dev', ('mount', '--bind', '/dev', '/mnt/dev'), True, 'action.bind_dev.description'),
            RepairAction('bind-proc', ('mount', '--bind', '/proc', '/mnt/proc'), True, 'action.bind_proc.description'),
            RepairAction('bind-sys', ('mount', '--bind', '/sys', '/mnt/sys'), True, 'action.bind_sys.description'),
        )
    )
    return tuple(actions)


def _bios_target(context: RepairContext) -> str:
    if context.root_disk_name:
        return context.root_disk_name
    if context.root_partition.startswith('/dev/'):
        name = context.root_partition[len('/dev/'):]
        if name.startswith('nvme'):
            return f'/dev/{name.rstrip("0123456789").rstrip("p")}'
        return context.root_partition.rstrip('0123456789')
    return ''


def _efi_relative_target(context: RepairContext) -> str:
    efi_target = _efi_mount_target(context)
    if efi_target.startswith('/mnt'):
        return efi_target[4:] or '/boot/efi'
    return '/boot/efi'


def _bootloader_install_command(context: RepairContext) -> tuple[str, ...]:
    if context.firmware_mode.lower() == 'uefi':
        efi_target = _efi_relative_target(context)
        return (
            'chroot',
            '/mnt',
            '/bin/sh',
            '-c',
            'if command -v grub-install >/dev/null; then grub-install --target=x86_64-efi '
            f'--efi-directory={shlex.quote(efi_target)} --bootloader-id=GRUB --recheck; '
            'elif command -v bootctl >/dev/null; then bootctl --path=' + shlex.quote(efi_target) + ' install; '
            'else echo "no supported UEFI bootloader installer found" >&2; exit 1; fi',
        )
    target_disk = _bios_target(context)
    if not target_disk:
        raise ValueError('BIOS repair requires a root disk target')
    return (
        'chroot',
        '/mnt',
        '/bin/sh',
        '-c',
        'if command -v grub-install >/dev/null; then grub-install --recheck ' + target_disk + '; '
        'else echo "grub-install is unavailable" >&2; exit 1; fi',
    )


def _boot_config_command(context: RepairContext) -> tuple[str, ...]:
    efi_target = _efi_relative_target(context)
    if context.distribution_family == DistributionFamily.ARCH:
        return (
            'chroot',
            '/mnt',
            '/bin/sh',
            '-c',
            'if command -v grub-mkconfig >/dev/null; then grub-mkconfig -o /boot/grub/grub.cfg; '
            'elif command -v update-grub >/dev/null; then update-grub; '
            'elif command -v bootctl >/dev/null; then bootctl --path=' + shlex.quote(efi_target) + ' update; '
            'else echo "no supported boot configuration tool found" >&2; exit 1; fi',
        )
    return (
        'chroot',
        '/mnt',
        '/bin/sh',
        '-c',
        'if command -v update-grub >/dev/null; then update-grub; '
        'elif command -v grub-mkconfig >/dev/null; then grub-mkconfig -o /boot/grub/grub.cfg; '
        'elif command -v bootctl >/dev/null; then bootctl --path=' + shlex.quote(efi_target) + ' update; '
        'else echo "no supported boot configuration tool found" >&2; exit 1; fi',
    )


def _initramfs_command(context: RepairContext) -> tuple[str, ...]:
    if context.distribution_family == DistributionFamily.ARCH:
        return (
            'chroot',
            '/mnt',
            '/bin/sh',
            '-c',
            'if command -v mkinitcpio >/dev/null; then mkinitcpio -P; '
            'elif command -v dracut >/dev/null; then dracut --regenerate-all --force; '
            'elif command -v update-initramfs >/dev/null; then update-initramfs -u; '
            'else echo "no initramfs tool found"; fi',
        )
    return (
        'chroot',
        '/mnt',
        '/bin/sh',
        '-c',
        'if command -v update-initramfs >/dev/null; then update-initramfs -u; '
        'elif command -v dracut >/dev/null; then dracut --regenerate-all --force; '
        'elif command -v mkinitcpio >/dev/null; then mkinitcpio -P; '
        'else echo "no initramfs tool found"; fi',
    )


def _diagnostic_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = []
    root_partition = context.root_partition
    root_entry = next((partition for partition in context.partitions if partition.name == root_partition), None)
    for finding in context.diagnostic_findings:
        if finding.category == DiagnosticCategory.FS_CORRUPTION:
            if root_entry is not None:
                fs_type = root_entry.fs_type.lower()
                if fs_type in {'ext4', 'ext3', 'ext2'}:
                    actions.append(
                        RepairAction(
                            'inspect-ext4',
                            ('fsck.ext4', '-n', root_partition),
                            True,
                            'action.inspect_ext4.description',
                        )
                    )
                    continue
                if fs_type == 'xfs':
                    actions.append(
                        RepairAction(
                            'inspect-xfs',
                            ('xfs_repair', '-n', root_partition),
                            True,
                            'action.inspect_xfs.description',
                        )
                    )
                    continue
                if fs_type == 'btrfs':
                    actions.append(
                        RepairAction(
                            'inspect-btrfs',
                            ('btrfs', 'check', '--readonly', root_partition),
                            True,
                            'action.inspect_btrfs.description',
                        )
                    )
                    continue
            actions.append(
                RepairAction(
                    'inspect-filesystem',
                    ('echo', 'Review filesystem health and run the correct read-only inspection command before repair'),
                    False,
                    'action.inspect_filesystem.description',
                )
            )
        if finding.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE:
            actions.append(
                RepairAction(
                    'inspect-partition-table',
                    ('parted', '-m', context.root_disk_name or root_partition, 'print'),
                    True,
                    'action.inspect_partition_table.description',
                )
            )
        if finding.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR:
            actions.append(
                RepairAction(
                    'verify-btrfs-subvolume',
                    ('echo', 'Inspect Btrfs subvolume layout in /etc/fstab and target mount options before repair'),
                    False,
                    'action.verify_btrfs_subvolume.description',
                )
            )
        if finding.category == DiagnosticCategory.BOOT_PARTITION_FORMATTED:
            actions.append(
                RepairAction(
                    'recreate-boot-structure',
                    ('echo', 'Recreate EFI directory structure and reinstall bootloader files'),
                    False,
                    'action.recreate_boot_structure.description',
                )
            )
            actions.append(
                RepairAction(
                    'reinstall-bootloader',
                    ('echo', 'Reinstall GRUB, systemd-boot, or other bootloader as appropriate'),
                    False,
                    'action.reinstall_bootloader.description',
                )
            )
            actions.append(
                RepairAction(
                    'regenerate-initramfs-boot',
                    ('echo', 'Regenerate initramfs using detected tool (mkinitcpio, dracut, update-initramfs)'),
                    False,
                    'action.regenerate_initramfs_boot.description',
                )
            )
            actions.append(
                RepairAction(
                    'recreate-uefi-entries',
                    ('echo', 'Recreate UEFI boot entries if necessary'),
                    False,
                    'action.recreate_uefi_entries.description',
                )
            )
        if finding.category == DiagnosticCategory.FSTAB_MISSING:
            actions.append(
                RepairAction(
                    'reconstruct-fstab',
                    ('echo', 'Reconstruct /etc/fstab based on detected partitions, UUIDs, and mount points'),
                    False,
                    'action.reconstruct_fstab.description',
                )
            )
            actions.append(
                RepairAction(
                    'validate-uuids',
                    ('echo', 'Validate that detected UUIDs match current partition UUIDs'),
                    False,
                    'action.validate_uuids.description',
                )
            )
            actions.append(
                RepairAction(
                    'review-mountpoints',
                    ('echo', 'Review and confirm mount points for root, boot, efi, swap, and subvolumes'),
                    False,
                    'action.review_mountpoints.description',
                )
            )
            actions.append(
                RepairAction(
                    'write-fstab',
                    ('echo', 'Write the reconstructed fstab file (requires manual confirmation)'),
                    False,
                    'action.write_fstab.description',
                )
            )
            actions.append(
                RepairAction(
                    'validate-fstab-syntax',
                    ('echo', 'Validate fstab syntax and mount compatibility'),
                    False,
                    'action.validate_fstab_syntax.description',
                )
            )
    return tuple(actions)


def _repair_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = [
        RepairAction(
            'install-bootloader',
            _bootloader_install_command(context),
            True,
            'action.install_bootloader.description',
        ),
        RepairAction(
            'regenerate-boot-config',
            _boot_config_command(context),
            True,
            'action.regenerate_boot_config.description',
        ),
        RepairAction(
            'regenerate-initramfs',
            _initramfs_command(context),
            True,
            'action.regenerate_initramfs.description',
        ),
    ]
    diagnostic_plan = _diagnostic_actions(context)
    if diagnostic_plan:
        actions = list(diagnostic_plan) + actions
    return tuple(actions)


def _rollback_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions = [
        RepairAction('unmount-sys', ('umount', '/mnt/sys'), True, 'action.unmount_sys.description'),
        RepairAction('unmount-proc', ('umount', '/mnt/proc'), True, 'action.unmount_proc.description'),
        RepairAction('unmount-dev', ('umount', '/mnt/dev'), True, 'action.unmount_dev.description'),
    ]
    if context.firmware_mode.lower() == 'uefi':
        actions.append(RepairAction('unmount-efi', ('umount', _efi_mount_target(context)), True, 'action.unmount_efi.description'))
    actions.append(RepairAction('unmount-root', ('umount', '/mnt'), True, 'action.unmount_root.description'))
    return tuple(actions)


def _risks(context: RepairContext) -> tuple[Risk, ...]:
    risks = [
        Risk('risk.wrong_target.description', RiskLevel.CRITICAL, 'risk.wrong_target.mitigation'),
        Risk('risk.mount_failure.description', RiskLevel.HIGH, 'risk.mount_failure.mitigation'),
    ]
    if context.firmware_mode.lower() == 'uefi':
        risks.append(Risk('risk.uefi_requires_esp.description', RiskLevel.HIGH, 'risk.uefi_requires_esp.mitigation'))
    if context.efi_system_partition and context.root_disk_name and context.efi_system_partition.startswith('/dev/'):
        efi_partition = next((partition for partition in context.partitions if partition.name == context.efi_system_partition), None)
        if efi_partition is not None and efi_partition.disk_name != context.root_disk_name:
            risks.append(Risk('risk.cross_disk_uefi.description', RiskLevel.MEDIUM, 'risk.cross_disk_uefi.mitigation'))
    if not context.live_environment:
        risks.append(Risk('risk.not_live_environment.description', RiskLevel.MEDIUM, 'risk.not_live_environment.mitigation'))
    if context.distribution != 'unknown':
        risks.append(Risk('risk.detected_distribution.description', RiskLevel.LOW, 'risk.detected_distribution.mitigation', {'distribution': context.distribution}))
    if context.initramfs_tool != 'unknown':
        risks.append(Risk('risk.detected_initramfs_tool.description', RiskLevel.LOW, 'risk.detected_initramfs_tool.mitigation', {'initramfs_tool': context.initramfs_tool}))
    if context.distribution_family == DistributionFamily.ARCH:
        risks.append(Risk('risk.arch_family.description', RiskLevel.LOW, 'risk.arch_family.mitigation'))
    elif context.distribution_family == DistributionFamily.DEBIAN:
        risks.append(Risk('risk.debian_family.description', RiskLevel.LOW, 'risk.debian_family.mitigation'))
    return tuple(risks)


def build_repair_plan(context: RepairContext) -> RepairPlan:
    if not context.confirmed:
        raise ValueError('repair context has not been confirmed')
    if not context.root_partition:
        raise ValueError('repair context requires a root partition')

    confidence = 0.90 if context.live_environment else 0.65
    if context.firmware_mode.lower() == 'unknown':
        confidence -= 0.12
    if not context.evidence:
        confidence -= 0.08
    confidence = max(0.10, min(0.99, confidence))

    preconditions = [
        'precondition.user_confirmed',
        'precondition.root_in_analysis',
        'precondition.consistent_firmware',
    ]
    if context.live_environment:
        preconditions.append('precondition.live_environment')
    else:
        preconditions.append('precondition.live_recommended')
    if context.firmware_mode.lower() == 'uefi':
        preconditions.append('precondition.efi_available')
    if any(finding.category == DiagnosticCategory.FS_CORRUPTION for finding in context.diagnostic_findings):
        preconditions.append('precondition.fs_diagnostics_reviewed')
    if any(finding.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE for finding in context.diagnostic_findings):
        preconditions.append('precondition.partition_table_confirmed')
    if any(finding.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR for finding in context.diagnostic_findings):
        preconditions.append('precondition.btrfs_layout_verified')

    return RepairPlan(
        title='plan.title',
        actions=_mount_actions(context) + _repair_actions(context),
        justifications=(
            'justification.mount_confirmation',
            'justification.chroot_bootloader',
            'justification.initramfs_regeneration',
        ),
        risks=_risks(context),
        preconditions=tuple(preconditions),
        rollback=_rollback_actions(context),
        confidence=confidence,
        trace=('detect', 'analyze', 'validate', 'plan'),
    )


def validate_plan(plan: RepairPlan) -> ValidationResult:
    return plan.validate()
