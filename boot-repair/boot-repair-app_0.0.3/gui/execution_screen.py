from __future__ import annotations

from typing import Sequence

import customtkinter as ctk
import tkinter as tk

from i18n import TranslationManager

from .base_screen import BaseScreen, Callback


class ExecutionScreen(BaseScreen):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        translator: TranslationManager,
        on_back: Callback | None = None,
        on_execute: Callback | None = None,
        on_abort: Callback | None = None,
    ) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='execution.title',
            subtitle_key='execution.subtitle',
            on_back=on_back,
            on_continue=on_execute,
            continue_key='execution.continue_button',
        )
        self._on_abort = on_abort
        self._running = False

        self.abort_button = ctk.CTkButton(
            self.footer,
            text=self.translator.translate('general.abort_button'),
            fg_color='transparent',
            border_width=2,
            text_color=('gray10', 'gray90'),
            command=self._dispatch_abort,
        )
        self.abort_button.grid(row=0, column=3, sticky='e', padx=(8, 0))

        self.progress = ctk.CTkProgressBar(self.content, mode='indeterminate')
        self.progress.grid(row=0, column=0, sticky='we', pady=(10, 20), padx=20)

        self.output_textbox = ctk.CTkTextbox(self.content, wrap='word')
        self.output_textbox.grid(row=1, column=0, sticky='nsew', padx=20, pady=(0, 20))

        self.set_running(False)

    def set_running(self, running: bool) -> None:
        self._running = running
        if running:
            self.progress.start()
            self.set_status(self.translator.translate('execution.running_status'))
        else:
            self.progress.stop()
            self.set_status(self.translator.translate('execution.stopped_status'))

    def append_output(self, text: str) -> None:
        self.output_textbox.insert(tk.END, text.rstrip() + '\n')
        self.output_textbox.see(tk.END)

    def replace_output(self, lines: Sequence[str]) -> None:
        self.output_textbox.delete('1.0', tk.END)
        for line in lines:
            self.output_textbox.insert(tk.END, line.rstrip() + '\n')

    def _dispatch_abort(self) -> None:
        if self._on_abort is not None:
            self._on_abort()

    def update_translations(self) -> None:
        super().update_translations()
        self.abort_button.configure(text=self.translator.translate('general.abort_button'))
        self.set_running(self._running)
