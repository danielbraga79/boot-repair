from __future__ import annotations

from typing import Sequence

import customtkinter as ctk
import tkinter as tk

from i18n import TranslationManager

from .base_screen import BaseScreen, Callback
from .view_models import PlanViewModel


class PlanScreen(BaseScreen):
    def __init__(self, master: ctk.CTk, *, translator: TranslationManager, on_back: Callback | None = None, on_continue: Callback | None = None) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='plan.title',
            subtitle_key='plan.subtitle',
            on_back=on_back,
            on_continue=on_continue,
            continue_key='plan.continue_button',
        )

        overview_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        overview_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(10, 20))
        overview_frame.columnconfigure(0, weight=1)

        self.title_value = ctk.CTkLabel(
            overview_frame,
            text='',
            wraplength=800,
            justify='left',
            font=ctk.CTkFont(size=14, weight='bold'),
        )
        self.title_value.grid(row=0, column=0, sticky='we', padx=12, pady=(10, 2))

        self.confidence_value = ctk.CTkLabel(
            overview_frame,
            text='',
            wraplength=800,
            justify='left',
            font=ctk.CTkFont(size=12),
        )
        self.confidence_value.grid(row=1, column=0, sticky='we', padx=12, pady=(0, 10))

        self.actions_textbox = self._create_textbox('plan.section.actions', 1, 0)
        self.justifications_textbox = self._create_textbox('plan.section.justifications', 1, 1)
        self.risks_textbox = self._create_textbox('plan.section.risks', 2, 0)
        self.prereq_textbox = self._create_textbox('plan.section.preconditions', 2, 1)
        self.rollback_textbox = self._create_textbox('plan.section.rollback', 3, 0, columnspan=2)

    def _create_textbox(self, title_key: str, row: int, column: int, columnspan: int = 1) -> ctk.CTkTextbox:
        frame = ctk.CTkFrame(self.content)
        frame.grid(row=row, column=column, columnspan=columnspan, sticky='nsew', padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        label = ctk.CTkLabel(
            frame,
            text=self.translator.translate(title_key),
            font=ctk.CTkFont(weight='bold'),
        )
        label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 5))

        textbox = ctk.CTkTextbox(frame, height=80, wrap='word')
        textbox.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))
        return textbox

    def set_plan(self, plan: PlanViewModel) -> None:
        self.title_value.configure(text=plan.title)
        self._plan_confidence = plan.confidence
        self.confidence_value.configure(text=self.translator.translate('plan.confidence', confidence=plan.confidence))
        self._fill_textbox(self.actions_textbox, plan.actions, self.translator)
        self._fill_textbox(self.justifications_textbox, plan.justifications, self.translator)
        self._fill_textbox(self.risks_textbox, plan.risks, self.translator)
        self._fill_textbox(self.prereq_textbox, plan.preconditions, self.translator)
        self._fill_textbox(self.rollback_textbox, plan.rollback, self.translator)

    def update_translations(self) -> None:
        super().update_translations()
        self._refresh_textbox_titles()
        if getattr(self, '_plan_confidence', None) is not None:
            self.confidence_value.configure(
                text=self.translator.translate('plan.confidence', confidence=self._plan_confidence)
            )

    def _refresh_textbox_titles(self) -> None:
        for frame, key in [
            (self.actions_textbox.master, 'plan.section.actions'),
            (self.justifications_textbox.master, 'plan.section.justifications'),
            (self.risks_textbox.master, 'plan.section.risks'),
            (self.prereq_textbox.master, 'plan.section.preconditions'),
            (self.rollback_textbox.master, 'plan.section.rollback'),
        ]:
            for child in frame.winfo_children():
                if isinstance(child, ctk.CTkLabel):
                    child.configure(text=self.translator.translate(key))

    def _fill_textbox(self, textbox: ctk.CTkTextbox, values: Sequence[str], translator: TranslationManager) -> None:
        textbox.delete('1.0', tk.END)
        if values:
            for value in values:
                textbox.insert(tk.END, f'• {value}\n')
        else:
            textbox.insert(tk.END, translator.translate('selection.no_items') + '\n')
        textbox.configure(state='disabled')
