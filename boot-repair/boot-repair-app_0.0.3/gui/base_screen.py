from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from i18n import TranslationManager

Callback = Callable[[], None]
SelectionCallback = Callable[[str], None]


class BaseScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        translator: TranslationManager,
        title_key: str,
        subtitle_key: str = '',
        on_back: Callback | None = None,
        on_continue: Callback | None = None,
        continue_key: str | None = None,
        back_key: str | None = None,
    ) -> None:
        super().__init__(master, fg_color='transparent')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.translator = translator
        self.title_key = title_key
        self.subtitle_key = subtitle_key
        self.back_key = back_key or 'general.back_button'
        self.continue_key = continue_key or 'general.continue_button'

        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, sticky='we', padx=20, pady=(20, 10))
        header.columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            header,
            text=self.translator.translate(self.title_key),
            font=ctk.CTkFont(size=18, weight='bold'),
        )
        self.title_label.grid(row=0, column=0, sticky='w')

        self.subtitle_label = ctk.CTkLabel(
            header,
            text=self.translator.translate(self.subtitle_key),
            wraplength=800,
            justify='left',
            font=ctk.CTkFont(size=12),
            text_color='gray70',
        )
        self.subtitle_label.grid(row=1, column=0, sticky='w', pady=(4, 0))

        self.content = ctk.CTkScrollableFrame(self, fg_color='transparent')
        self.content.grid(row=2, column=0, sticky='nsew', padx=20, pady=(10, 10))
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            self,
            text='',
            text_color='#888888',
            font=ctk.CTkFont(size=11),
            wraplength=800,
            justify='left',
        )
        self.status_label.grid(row=3, column=0, sticky='we', padx=20, pady=(0, 10))

        self.footer = ctk.CTkFrame(self, fg_color='transparent')
        self.footer.grid(row=4, column=0, sticky='e', padx=20, pady=(10, 20))
        self.footer.columnconfigure(0, weight=1)

        self.back_button = ctk.CTkButton(
            self.footer,
            text=self.translator.translate(self.back_key),
            command=on_back,
            fg_color='transparent',
            border_width=2,
            text_color=('gray10', 'gray90'),
        )
        self.back_button.grid(row=0, column=1, padx=(0, 8))

        self.continue_button = ctk.CTkButton(
            self.footer,
            text=self.translator.translate(self.continue_key),
            command=on_continue,
        )
        self.continue_button.grid(row=0, column=2)

        self.set_navigation(back_enabled=on_back is not None, continue_enabled=on_continue is not None)

    def set_title(self, text: str) -> None:
        self.title_label.configure(text=text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.configure(text=text)

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def set_navigation(self, *, back_enabled: bool, continue_enabled: bool) -> None:
        self.back_button.configure(state='normal' if back_enabled else 'disabled')
        self.continue_button.configure(state='normal' if continue_enabled else 'disabled')

    def update_translations(self) -> None:
        self.title_label.configure(text=self.translator.translate(self.title_key))
        self.subtitle_label.configure(text=self.translator.translate(self.subtitle_key))
        self.back_button.configure(text=self.translator.translate(self.back_key))
        self.continue_button.configure(text=self.translator.translate(self.continue_key))
