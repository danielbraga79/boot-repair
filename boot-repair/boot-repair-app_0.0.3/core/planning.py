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
            'Mount the selected root filesystem',
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
                f'Ensure EFI mount path exists at {efi_target}',
            )
        )
        actions.append(
            RepairAction(
                'mount-efi-partition',
                ('mount', context.efi_system_partition, efi_target),
                True,
                'Mount the EFI System Partition for repair',
            )
        )
    actions.extend(
        (
            RepairAction('bind-dev', ('mount', '--bind', '/dev', '/mnt/dev'), True, 'Expose /dev in the repair environment'),
            RepairAction('bind-proc', ('mount', '--bind', '/proc', '/mnt/proc'), True, 'Expose /proc in the repair environment'),
            RepairAction('bind-sys', ('mount', '--bind', '/sys', '/mnt/sys'), True, 'Expose /sys in the repair environment'),
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
                            'Inspect the ext filesystem for inconsistencies before attempting repair',
                        )
                    )
                    continue
                if fs_type == 'xfs':
                    actions.append(
                        RepairAction(
                            'inspect-xfs',
                            ('xfs_repair', '-n', root_partition),
                            True,
                            'Inspect the XFS filesystem non-destructively before repair',
                        )
                    )
                    continue
                if fs_type == 'btrfs':
                    actions.append(
                        RepairAction(
                            'inspect-btrfs',
                            ('btrfs', 'check', '--readonly', root_partition),
                            True,
                            'Inspect the Btrfs filesystem in read-only mode to collect evidence before repair',
                        )
                    )
                    continue
            actions.append(
                RepairAction(
                    'inspect-filesystem',
                    ('echo', 'Review filesystem health and run the correct read-only inspection command before repair'),
                    False,
                    'Provide a safe diagnostic step for filesystem corruption findings',
                )
            )
        if finding.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE:
            actions.append(
                RepairAction(
                    'inspect-partition-table',
                    ('parted', '-m', context.root_disk_name or root_partition, 'print'),
                    True,
                    'Review partition table metadata and backup GPT headers in a non-destructive way',
                )
            )
        if finding.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR:
            actions.append(
                RepairAction(
                    'verify-btrfs-subvolume',
                    ('echo', 'Inspect Btrfs subvolume layout in /etc/fstab and target mount options before repair'),
                    False,
                    'Guide the user to confirm Btrfs subvolume configuration before repairing boot',
                )
            )
        if finding.category == DiagnosticCategory.BOOT_PARTITION_FORMATTED:
            actions.append(
                RepairAction(
                    'recreate-boot-structure',
                    ('echo', 'Recreate EFI directory structure and reinstall bootloader files'),
                    False,
                    'Plan to recreate missing boot/EFI structure without automatic execution',
                )
            )
            actions.append(
                RepairAction(
                    'reinstall-bootloader',
                    ('echo', 'Reinstall GRUB, systemd-boot, or other bootloader as appropriate'),
                    False,
                    'Plan bootloader reinstallation for formatted boot partition',
                )
            )
            actions.append(
                RepairAction(
                    'regenerate-initramfs-boot',
                    ('echo', 'Regenerate initramfs using detected tool (mkinitcpio, dracut, update-initramfs)'),
                    False,
                    'Plan initramfs regeneration for boot partition recovery',
                )
            )
            actions.append(
                RepairAction(
                    'recreate-uefi-entries',
                    ('echo', 'Recreate UEFI boot entries if necessary'),
                    False,
                    'Plan UEFI boot entry recreation',
                )
            )
        if finding.category == DiagnosticCategory.FSTAB_MISSING:
            actions.append(
                RepairAction(
                    'reconstruct-fstab',
                    ('echo', 'Reconstruct /etc/fstab based on detected partitions, UUIDs, and mount points'),
                    False,
                    'Plan fstab reconstruction with validation steps',
                )
            )
            actions.append(
                RepairAction(
                    'validate-uuids',
                    ('echo', 'Validate that detected UUIDs match current partition UUIDs'),
                    False,
                    'Ensure UUID consistency before writing fstab',
                )
            )
            actions.append(
                RepairAction(
                    'review-mountpoints',
                    ('echo', 'Review and confirm mount points for root, boot, efi, swap, and subvolumes'),
                    False,
                    'Manual review of mount point configuration',
                )
            )
            actions.append(
                RepairAction(
                    'write-fstab',
                    ('echo', 'Write the reconstructed fstab file (requires manual confirmation)'),
                    False,
                    'Final step to write fstab after validation',
                )
            )
            actions.append(
                RepairAction(
                    'validate-fstab-syntax',
                    ('echo', 'Validate fstab syntax and mount compatibility'),
                    False,
                    'Syntax and logical validation of fstab',
                )
            )
    return tuple(actions)


def _repair_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = [
        RepairAction(
            'install-bootloader',
            _bootloader_install_command(context),
            True,
            'Install or repair the bootloader inside the chrooted environment',
        ),
        RepairAction(
            'regenerate-boot-config',
            _boot_config_command(context),
            True,
            'Regenerate the bootloader configuration inside the chrooted environment',
        ),
        RepairAction(
            'regenerate-initramfs',
            _initramfs_command(context),
            True,
            'Regenerate the initramfs if a supported tool is available in the target environment',
        ),
    ]
    diagnostic_plan = _diagnostic_actions(context)
    if diagnostic_plan:
        actions = list(diagnostic_plan) + actions
    return tuple(actions)


def _rollback_actions(context: RepairContext) -> tuple[RepairAction, ...]:
    actions = [
        RepairAction('unmount-sys', ('umount', '/mnt/sys'), True, 'Unmount /mnt/sys'),
        RepairAction('unmount-proc', ('umount', '/mnt/proc'), True, 'Unmount /mnt/proc'),
        RepairAction('unmount-dev', ('umount', '/mnt/dev'), True, 'Unmount /mnt/dev'),
    ]
    if context.firmware_mode.lower() == 'uefi':
        actions.append(RepairAction('unmount-efi', ('umount', _efi_mount_target(context)), True, 'Unmount the EFI System Partition'))
    actions.append(RepairAction('unmount-root', ('umount', '/mnt'), True, 'Unmount the root filesystem'))
    return tuple(actions)


def _risks(context: RepairContext) -> tuple[Risk, ...]:
    risks = [
        Risk('Wrong target device can make the system unbootable', RiskLevel.CRITICAL, 'Confirm the selected root partition before execution'),
        Risk('Filesystem mounts can fail if the target is already mounted', RiskLevel.HIGH, 'Review mount points in the analysis stage before planning'),
    ]
    if context.firmware_mode.lower() == 'uefi':
        risks.append(Risk('UEFI repair requires a valid EFI System Partition', RiskLevel.HIGH, 'Verify that the EFI partition is selected and belongs to a valid ESP target'))
    if context.efi_system_partition and context.root_disk_name and context.efi_system_partition.startswith('/dev/'):
        efi_partition = next((partition for partition in context.partitions if partition.name == context.efi_system_partition), None)
        if efi_partition is not None and efi_partition.disk_name != context.root_disk_name:
            risks.append(Risk('EFI and root partitions are on different disks', RiskLevel.MEDIUM, 'Confirm cross-disk UEFI boot topology before proceeding'))
    if not context.live_environment:
        risks.append(Risk('Repairs outside a live environment are less reliable', RiskLevel.MEDIUM, 'Prefer a live boot environment for the operation'))
    if context.distribution != 'unknown':
        risks.append(Risk(f'Detected distribution: {context.distribution}', RiskLevel.LOW, 'Use distribution-specific tools when available.'))
    if context.initramfs_tool != 'unknown':
        risks.append(Risk(f'Detected initramfs tool: {context.initramfs_tool}', RiskLevel.LOW, 'The repair plan includes regeneration if the tool exists in the target environment.'))
    if context.distribution_family == DistributionFamily.ARCH:
        risks.append(Risk('Detected Arch-family distribution', RiskLevel.LOW, 'Arch and Arch-based systems may use mkinitcpio, bootctl, or grub-mkconfig.'))
    elif context.distribution_family == DistributionFamily.DEBIAN:
        risks.append(Risk('Detected Debian-family distribution', RiskLevel.LOW, 'Debian-family systems may use update-initramfs and update-grub.'))
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
        'User confirmed the target partition.',
        'The selected root partition appears in the analysis results.',
        'The selected repair target is consistent with the detected firmware mode.',
    ]
    if context.live_environment:
        preconditions.append('The system is running in a live recovery environment.')
    else:
        preconditions.append('A live recovery environment is recommended before execution.')
    if context.firmware_mode.lower() == 'uefi':
        preconditions.append('The EFI System Partition is available and mounted or accessible for repair.')
    if any(finding.category == DiagnosticCategory.FS_CORRUPTION for finding in context.diagnostic_findings):
        preconditions.append('Filesystem diagnostics have been collected and reviewed before applying bootloader repair.')
    if any(finding.category == DiagnosticCategory.PARTITION_TABLE_DAMAGE for finding in context.diagnostic_findings):
        preconditions.append('Partition table inconsistencies are present; confirm repair targets and backup metadata before execution.')
    if any(finding.category == DiagnosticCategory.BTRFS_LAYOUT_ERROR for finding in context.diagnostic_findings):
        preconditions.append('Btrfs subvolume layout was detected; verify /etc/fstab and mount options prior to repair.')

    return RepairPlan(
        title='Boot repair plan',
        actions=_mount_actions(context) + _repair_actions(context),
        justifications=(
            'The plan only mounts the selected target after explicit confirmation.',
            'Bootloader repair is executed inside a chroot with explicit commands.',
            'Initramfs regeneration is included when available to maintain boot consistency.',
        ),
        risks=_risks(context),
        preconditions=tuple(preconditions),
        rollback=_rollback_actions(context),
        confidence=confidence,
        trace=('detect', 'analyze', 'validate', 'plan'),
    )


def validate_plan(plan: RepairPlan) -> ValidationResult:
    return plan.validate()
