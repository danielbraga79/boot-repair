from __future__ import annotations

import customtkinter as ctk

from i18n import TranslationManager

from .base_screen import BaseScreen, Callback


class WelcomeScreen(BaseScreen):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        translator: TranslationManager,
        on_continue: Callback | None = None,
        on_help: Callback | None = None,
    ) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='welcome.title',
            subtitle_key='welcome.subtitle',
            on_back=None,
            on_continue=on_continue,
            continue_key='welcome.start_button',
        )
        self.back_button.grid_remove()

        message_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        message_frame.grid(row=0, column=0, sticky='ew', pady=(20, 10))

        self.message_label = ctk.CTkLabel(
            message_frame,
            text=self.translator.translate('welcome.message'),
            wraplength=760,
            justify='left',
            font=ctk.CTkFont(size=12),
        )
        self.message_label.grid(row=0, column=0, sticky='w')

        progress_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        progress_frame.grid(row=1, column=0, sticky='ew', pady=(10, 20))

        self.progress_label = ctk.CTkLabel(
            progress_frame,
            text=self.translator.translate('welcome.progress'),
            font=ctk.CTkFont(size=11),
            text_color='gray60',
        )
        self.progress_label.grid(row=0, column=0, sticky='w')

        self.help_button = ctk.CTkButton(
            self.footer,
            text=self.translator.translate('help.open_button'),
            command=on_help,
            fg_color='transparent',
            border_width=2,
            text_color=('gray10', 'gray90'),
            state='normal' if on_help is not None else 'disabled',
        )
        self.help_button.grid(row=0, column=0, sticky='w')

        self.set_status(self.translator.translate('welcome.status_ready'))

    def update_translations(self) -> None:
        super().update_translations()
        self.message_label.configure(text=self.translator.translate('welcome.message'))
        self.progress_label.configure(text=self.translator.translate('welcome.progress'))
        self.help_button.configure(text=self.translator.translate('help.open_button'))
        self.set_status(self.translator.translate('welcome.status_ready'))
