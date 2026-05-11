from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace

import customtkinter as ctk

from core.analysis import AnalysisEvidence, collect_optional_diagnostics
from core.execution import ExecutionReport
from core.flow import BootRepairFlow, RepairSelection
from core.models import RepairAction, RepairPlan, format_size_bytes
from gui.screens import PlanViewModel, build_screens
from i18n import TranslationManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppState:
    root_partition: str = ''
    efi_partition: str = ''
    operation_mode: OperationMode = OperationMode.SAFE


class BootRepairApp:
    def __init__(self, root: ctk.CTk) -> None:
        ctk.set_appearance_mode('system')
        ctk.set_default_color_theme('blue')

        self.translator = TranslationManager()
        self.root = root
        self.root.title(self.translator.translate('app.window_title'))
        self.root.geometry('1100x750')
        self.root.minsize(1000, 700)

        self._build_language_selector()

        self.container = ctk.CTkFrame(self.root, fg_color='transparent')
        self.container.pack(fill='both', expand=True)
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)

        self.flow = BootRepairFlow()
        self.state = AppState()
        self.evidence: AnalysisEvidence | None = None
        self._initialization_failed = False
        self._advanced_diagnostics_started = False

        self.screens = build_screens(
            self.container,
            translator=self.translator,
            on_welcome_continue=self._initialize_and_show_selection,
            on_welcome_help=self._show_help,
            on_help_back=self._show_welcome,
            on_selection_back=self._show_welcome,
            on_selection_continue=self._run_analysis,
            on_analysis_back=self._show_selection,
            on_analysis_continue=self._run_validation,
            on_plan_back=self._show_analysis,
            on_plan_continue=self._show_execution,
            on_execution_back=self._show_plan,
            on_execution_execute=self._execute_plan,
            on_execution_abort=self._abort_execution,
            on_root_selected=self._select_root_partition,
            on_efi_selected=self._select_efi_partition,
        )

        for screen in self._all_screens():
            screen.grid(row=0, column=0, sticky='nsew')

        self._show(self.screens.welcome)

    def _build_language_selector(self) -> None:
        toolbar = ctk.CTkFrame(self.root, fg_color='transparent')
        toolbar.pack(fill='x', padx=20, pady=(20, 0))
        toolbar.columnconfigure(1, weight=1)

        self.language_label = ctk.CTkLabel(
            toolbar,
            text=self.translator.translate('language.selector.label'),
            font=ctk.CTkFont(size=11),
        )
        self.language_label.grid(row=0, column=0, sticky='w')

        values = [self.translator.display_name(code) for code in self.translator.available_locales()]
        self.language_var = ctk.StringVar(value=self.translator.display_name(self.translator.current_locale))
        self.language_combo = ctk.CTkComboBox(
            toolbar,
            values=values,
            variable=self.language_var,
            state='readonly',
            command=self._on_language_selected,
        )
        self.language_combo.grid(row=0, column=1, sticky='e')

    def _on_language_selected(self, value: str) -> None:
        locale = self.translator.locale_from_display_name(value)
        if locale is None:
            return
        self.translator.set_locale(locale)
        self.language_var.set(self.translator.display_name(locale))
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.root.title(self.translator.translate('app.window_title'))
        self.language_label.configure(text=self.translator.translate('language.selector.label'))
        for screen in self._all_screens():
            screen.update_translations()

    def _all_screens(self):
        return (
            self.screens.welcome,
            self.screens.help,
            self.screens.selection,
            self.screens.analysis,
            self.screens.plan,
            self.screens.execution,
        )

    def _show_help(self) -> None:
        self._show(self.screens.help)

    def _initialize_and_show_selection(self) -> None:
        try:
            logger.info('Initializing application: collecting evidence')
            evidence = self.flow.detect()
            self.evidence = evidence
            logger.info(
                f'Initial evidence loaded: {len(evidence.disks)} disks, {len(evidence.partitions)} partitions'
            )

            if not evidence.disks and not evidence.partitions:
                logger.warning('No disks or partitions detected during initialization')
                self.screens.welcome.set_status(self.translator.translate('errors.no_disks_or_partitions'))
                return

            self.screens.selection.set_catalog(disks=evidence.disks, partitions=evidence.partitions)
            logger.info(
                f'SelectionScreen populated with {len(evidence.disks)} disks and {len(evidence.partitions)} partitions'
            )
            self.screens.selection.set_status(self.translator.translate('selection.status_loaded'))
        except Exception as exc:
            self._initialization_failed = True
            error_msg = self.translator.translate('errors.analysis_failed', error=str(exc))
            logger.error(error_msg, exc_info=exc)
            self.screens.welcome.set_status(error_msg)
            return

        self._show_selection()

    def _log_geometry_manager_error(self, widget, exc: Exception) -> None:
        try:
            manager = widget.winfo_manager()
            parent_manager = widget.master.winfo_manager() if hasattr(widget, 'master') else '<unknown>'
        except Exception:
            manager = '<unknown>'
            parent_manager = '<unknown>'
        logger.exception(
            'Geometry manager error: widget=%s parent=%s manager=%s parent_manager=%s',
            widget,
            getattr(widget, 'master', '<none>'),
            manager,
            parent_manager,
            exc_info=exc,
        )

    def _show(self, screen) -> None:
        try:
            for item in self._all_screens():
                item.grid_remove()
            screen.grid(row=0, column=0, sticky='nsew')
        except Exception as exc:
            self._log_geometry_manager_error(screen, exc)
            raise

    def _show_welcome(self) -> None:
        self._show(self.screens.welcome)

    def _show_selection(self) -> None:
        self._show(self.screens.selection)

    def _run_advanced_diagnostics(self, evidence: AnalysisEvidence) -> AnalysisEvidence:
        if self._advanced_diagnostics_started:
            return evidence
        self._advanced_diagnostics_started = True
        logger.info('Starting advanced diagnostics')
        try:
            findings = collect_optional_diagnostics(
                disks=evidence.disks,
                partitions=evidence.partitions,
                fstab_entries=evidence.fstab_entries,
                firmware_mode=evidence.firmware_mode,
                blkid_entries=evidence.blkid_entries,
            )
            if not findings:
                logger.info('Advanced diagnostics completed with no additional findings')
                return evidence

            logger.info(f'Advanced diagnostics completed with {len(findings)} findings')
            new_evidence = replace(
                evidence,
                diagnostic_findings=tuple(evidence.diagnostic_findings) + tuple(findings),
                notes=tuple(evidence.notes) + ('advanced diagnostics completed',),
            )
            self.flow.state.evidence = new_evidence
            self.evidence = new_evidence
            return new_evidence
        except Exception as exc:
            logger.warning('Advanced diagnostics failed: %s', exc, exc_info=exc)
            return evidence

    def _schedule_selection_status_update(self, message: str) -> None:
        def update() -> None:
            if self.screens.selection.winfo_ismapped():
                self.screens.selection.set_status(message)

        try:
            self.root.after(0, update)
        except Exception:
            logger.warning('Failed to schedule selection status update for optional diagnostics')

    def _show_analysis(self) -> None:
        self._show(self.screens.analysis)

    def _show_plan(self) -> None:
        self._show(self.screens.plan)

    def _show_execution(self) -> None:
        self.screens.execution.replace_output(
            [self.translator.translate('execution.ready_message')]
        )
        self._show(self.screens.execution)

    def _select_root_partition(self, value: str) -> None:
        self.state.root_partition = value.strip()
        self.screens.selection.set_selection(self.state.root_partition, self.state.efi_partition)
        disk = self.screens.selection.selected_disk_for_root()
        if disk:
            self.screens.selection.set_status(
                self.translator.translate('selection.root_selected', disk=disk)
            )

    def _select_efi_partition(self, value: str) -> None:
        self.state.efi_partition = value.strip()
        self.screens.selection.set_selection(self.state.root_partition, self.state.efi_partition)

    def _run_analysis(self) -> None:
        if not self.state.root_partition:
            error_msg = self.translator.translate('errors.select_root')
            logger.warning(error_msg)
            self.screens.selection.set_status(error_msg)
            return

        if not self.evidence:
            error_msg = self.translator.translate('errors.evidence_not_loaded')
            logger.error(error_msg)
            self.screens.selection.set_status(error_msg)
            return

        if self.screens.selection.selected_mode() == 'advanced':
            self.screens.selection.set_status('Running advanced diagnostics before analysis...')
            self.evidence = self._run_advanced_diagnostics(self.evidence)

        try:
            logger.info('Starting analysis phase from GUI')
            analyzed_evidence = self.flow.analyze()
            logger.info(
                f'Analysis complete: {len(analyzed_evidence.disks)} disks, {len(analyzed_evidence.partitions)} partitions'
            )
            self.evidence = analyzed_evidence
        except Exception as exc:
            error_msg = self.translator.translate('errors.analysis_failed', error=str(exc))
            logger.error(error_msg, exc_info=exc)
            self.screens.selection.set_status(error_msg)
            return

        self._render_analysis(self.evidence)
        self._show_analysis()

    def _run_validation(self) -> None:
        if self.evidence is None:
            error_msg = self.translator.translate('errors.evidence_not_loaded')
            logger.error(error_msg)
            self.screens.analysis.set_status(error_msg)
            self._show_analysis()
            return

        selection = RepairSelection(
            root_partition=self.state.root_partition,
            efi_system_partition=self.state.efi_partition,
            firmware_mode=self.evidence.firmware_mode,
            operation_mode=OperationMode(self.screens.selection.selected_mode()),
            confirmed=True,
            notes=('selected from GUI',),
        )
        self.flow.set_selection(selection)
        try:
            logger.info('Starting validation phase from GUI')
            self.flow.validate()
            logger.info('Validation complete, starting planning phase')
            plan = self.flow.plan()
            logger.info(f'Plan created: {plan.title} (confidence: {plan.confidence:.0%})')
        except Exception as exc:
            error_msg = self.translator.translate('errors.validation_failed', error=str(exc))
            logger.error(error_msg, exc_info=exc)
            self.screens.analysis.set_status(error_msg)
            self._show_analysis()
            return

        self._render_plan(plan)
        self._show_plan()

    def _execute_plan(self) -> None:
        self.screens.execution.set_running(True)
        try:
            logger.info('Starting execution phase from GUI')
            report = self.flow.execute()
            logger.info(f'Execution complete: success={report.success}')
        except Exception as exc:
            error_msg = self.translator.translate('errors.execution_failed', error=str(exc))
            logger.error(error_msg, exc_info=exc)
            self.screens.execution.set_running(False)
            self.screens.execution.append_output(error_msg)
            return
        finally:
            self.screens.execution.set_running(False)

        self._render_execution(report)

    def _abort_execution(self) -> None:
        self.screens.execution.append_output(
            self.translator.translate('errors.execution_aborted')
        )
        self._show_plan()

    def _render_analysis(self, evidence: AnalysisEvidence) -> None:
        yes = self.translator.translate('general.yes')
        no = self.translator.translate('general.no')
        lines = [
            self.translator.translate('analysis.details.firmware', firmware=evidence.firmware_mode),
            self.translator.translate(
                'analysis.details.live_environment',
                value=yes if evidence.live_environment else no,
            ),
            self.translator.translate('analysis.details.distribution', distribution=evidence.distribution),
            self.translator.translate(
                'analysis.details.distribution_family',
                family=evidence.distribution_family.value,
            ),
            self.translator.translate('analysis.details.initramfs_tool', tool=evidence.initramfs_tool),
            self.translator.translate('analysis.details.disks_detected', count=len(evidence.disks)),
            self.translator.translate('analysis.details.partitions_detected', count=len(evidence.partitions)),
        ]

        if evidence.disks:
            lines.append(self.translator.translate('analysis.details.disks'))
            for disk in evidence.disks:
                lines.append(
                    self.translator.translate(
                        'analysis.details.disk_entry',
                        name=disk.name,
                        model=disk.model or self.translator.translate('selection.no_model'),
                        size=format_size_bytes(disk.size_bytes),
                    )
                )

        if evidence.partitions:
            lines.append(self.translator.translate('analysis.details.partitions'))
            for partition in evidence.partitions:
                mount_point = partition.mount_point or self.translator.translate('selection.unmounted')
                label = f' — {partition.label}' if partition.label else ''
                lines.append(
                    self.translator.translate(
                        'analysis.details.partition_entry',
                        name=partition.name,
                        disk_name=partition.disk_name or self.translator.translate('selection.no_model'),
                        fs_type=partition.fs_type or '',
                        mount_point=mount_point,
                        label=label,
                    )
                )

        if evidence.blkid_entries:
            lines.append(self.translator.translate('analysis.details.blkid_label'))
            lines.extend(f'  {entry}' for entry in evidence.blkid_entries)

        if evidence.fstab_entries:
            lines.append(self.translator.translate('analysis.details.fstab_label'))
            lines.extend(f'  {entry}' for entry in evidence.fstab_entries)

        if evidence.diagnostic_findings:
            lines.append(self.translator.translate('analysis.details.diagnostics_label'))
            lines.extend(
                f'  [{finding.category}] {finding.description} ({finding.severity.value})'
                for finding in evidence.diagnostic_findings
            )

        if evidence.notes:
            lines.append(self.translator.translate('analysis.details.notes_label'))
            lines.extend(f'  {note}' for note in evidence.notes)

        self.screens.analysis.set_evidence(lines)
        self.screens.selection.set_catalog(disks=evidence.disks, partitions=evidence.partitions)
        self.screens.selection.set_selection(self.state.root_partition, self.state.efi_partition)
        self.screens.analysis.set_status(self.translator.translate('analysis.completed'))

    def _render_plan(self, plan: RepairPlan) -> None:
        view_model = PlanViewModel(
            title=self.translator.translate('plan.title'),
            confidence=f'{plan.confidence:.0%}',
            actions=tuple(f"{action.label}: {self.translator.translate(action.description)}" for action in plan.actions),
            justifications=tuple(self.translator.translate(j) for j in plan.justifications),
            risks=tuple(
                f"{risk.level.value.upper()}: {self.translator.translate(risk.description, **(risk.params or {}))}"
                + (f" | {self.translator.translate('plan.risk_mitigation')}: {self.translator.translate(risk.mitigation, **(risk.params or {}))}" if risk.mitigation else '')
                for risk in plan.risks
            ),
            preconditions=tuple(self.translator.translate(p) for p in plan.preconditions),
            rollback=tuple(f"{action.label}: {self.translator.translate(action.description)}" for action in plan.rollback),
        )
        self.screens.plan.set_plan(view_model)

    def _render_execution(self, report: ExecutionReport) -> None:
        success_text = self.translator.translate('general.yes') if report.success else self.translator.translate('general.no')
        lines = [
            self.translator.translate('execution.success_line', success=success_text),
            self.translator.translate('execution.steps_label') + ' ' + str(len(report.applied_actions)),
        ]
        if report.failed_action:
            lines.append(self.translator.translate('errors.execution_failed', error=report.failed_action))
        if report.applied_actions:
            lines.append(self.translator.translate('execution.steps_label'))
            lines.extend(f"  {step.action}: {' '.join(step.command)}" for step in report.applied_actions)
        if report.rollback_steps:
            lines.append(self.translator.translate('execution.rollback_label'))
            lines.extend(f"  {step.action}: {' '.join(step.command)}" for step in report.rollback_steps)
        if report.notes:
            lines.append(self.translator.translate('analysis.details.notes_label'))
            lines.extend(f'  {note}' for note in report.notes)
        self.screens.execution.replace_output(lines)

    def run(self) -> int:
        self.root.mainloop()
        return 0


def _show_startup_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Boot Repair', f'Failed to start the interface:\n{message}')
        root.destroy()
    except Exception:
        pass


def main() -> int:
    try:
        root = ctk.CTk()
        app = BootRepairApp(root)
        return app.run()
    except Exception as exc:
        logger.exception('GUI failed to start')
        _show_startup_error(str(exc))
        return 1
