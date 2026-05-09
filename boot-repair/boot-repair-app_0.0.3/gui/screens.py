from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

from .analysis_screen import AnalysisScreen
from .base_screen import BaseScreen, Callback, SelectionCallback
from .execution_screen import ExecutionScreen
from .help_screen import HelpScreen
from .plan_screen import PlanScreen
from .selection_screen import SelectionScreen
from .view_models import EvidenceViewModel, PlanViewModel
from .welcome_screen import WelcomeScreen


__all__ = [
    'BaseScreen',
    'Callback',
    'SelectionCallback',
    'EvidenceViewModel',
    'PlanViewModel',
    'WelcomeScreen',
    'HelpScreen',
    'SelectionScreen',
    'AnalysisScreen',
    'PlanScreen',
    'ExecutionScreen',
    'ScreenBundle',
    'build_screens',
]


@dataclass(slots=True)
class ScreenBundle:
    welcome: WelcomeScreen
    help: HelpScreen
    selection: SelectionScreen
    analysis: AnalysisScreen
    plan: PlanScreen
    execution: ExecutionScreen


def build_screens(
    master: ctk.CTk,
    *,
    translator,
    on_welcome_continue=None,
    on_welcome_help=None,
    on_help_back=None,
    on_selection_back=None,
    on_selection_continue=None,
    on_analysis_back=None,
    on_analysis_continue=None,
    on_plan_back=None,
    on_plan_continue=None,
    on_execution_back=None,
    on_execution_execute=None,
    on_execution_abort=None,
    on_root_selected=None,
    on_efi_selected=None,
) -> ScreenBundle:
    welcome = WelcomeScreen(
        master,
        translator=translator,
        on_continue=on_welcome_continue,
        on_help=on_welcome_help,
    )
    help_screen = HelpScreen(master, translator=translator, on_back=on_help_back)
    selection = SelectionScreen(
        master,
        translator=translator,
        on_back=on_selection_back,
        on_continue=on_selection_continue,
        on_root_selected=on_root_selected,
        on_efi_selected=on_efi_selected,
    )
    analysis = AnalysisScreen(master, translator=translator, on_back=on_analysis_back, on_continue=on_analysis_continue)
    plan = PlanScreen(master, translator=translator, on_back=on_plan_back, on_continue=on_plan_continue)
    execution = ExecutionScreen(
        master,
        translator=translator,
        on_back=on_execution_back,
        on_execute=on_execution_execute,
        on_abort=on_execution_abort,
    )
    return ScreenBundle(
        welcome=welcome,
        help=help_screen,
        selection=selection,
        analysis=analysis,
        plan=plan,
        execution=execution,
    )
