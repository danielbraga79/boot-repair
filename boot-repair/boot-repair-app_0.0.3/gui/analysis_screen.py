from __future__ import annotations

from typing import Sequence

import customtkinter as ctk
import tkinter as tk

from i18n import TranslationManager

from .base_screen import BaseScreen, Callback


class AnalysisScreen(BaseScreen):
    def __init__(self, master: ctk.CTk, *, translator: TranslationManager, on_back: Callback | None = None, on_continue: Callback | None = None) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='analysis.title',
            subtitle_key='analysis.subtitle',
            on_back=on_back,
            on_continue=on_continue,
            continue_key='analysis.continue_button',
        )
        self.output_textbox = ctk.CTkTextbox(self.content, wrap='word')
        self.output_textbox.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)

    def set_evidence(self, lines: Sequence[str]) -> None:
        self.output_textbox.delete('1.0', tk.END)
        for line in lines:
            self.output_textbox.insert(tk.END, line.rstrip() + '\n')
        self.output_textbox.configure(state='disabled')
