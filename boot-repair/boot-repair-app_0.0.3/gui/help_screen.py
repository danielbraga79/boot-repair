from __future__ import annotations

import customtkinter as ctk

from i18n import TranslationManager

from .base_screen import BaseScreen, Callback


class HelpScreen(BaseScreen):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        translator: TranslationManager,
        on_back: Callback | None = None,
    ) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='help.title',
            subtitle_key='help.subtitle',
            on_back=on_back,
            on_continue=None,
        )
        self.continue_button.grid_remove()

        guide_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        guide_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)
        guide_frame.columnconfigure(0, weight=1)

        self._section_labels: list[ctk.CTkLabel] = []
        self._section_texts: list[ctk.CTkLabel] = []
        self._step_labels: list[ctk.CTkLabel] = []

        sections = [
            ('help.section.what', 'help.section.what.text'),
            ('help.section.sudo', 'help.section.sudo.text'),
            ('help.section.start', 'help.section.start.text'),
            ('help.section.choose', 'help.section.choose.text'),
            ('help.section.read', 'help.section.read.text'),
            ('help.section.assisted', 'help.section.assisted.text'),
        ]

        row = 0
        for title_key, text_key in sections:
            section_title = ctk.CTkLabel(
                guide_frame,
                text=self.translator.translate(title_key),
                font=ctk.CTkFont(weight='bold'),
                justify='left',
            )
            section_title.grid(row=row, column=0, sticky='w', pady=(8, 2))
            row += 1
            self._section_labels.append(section_title)

            section_text = ctk.CTkLabel(
                guide_frame,
                text=self.translator.translate(text_key),
                wraplength=820,
                justify='left',
                font=ctk.CTkFont(size=11),
                text_color='gray80',
            )
            section_text.grid(row=row, column=0, sticky='w')
            row += 1
            self._section_texts.append(section_text)

        self._step_title = ctk.CTkLabel(
            guide_frame,
            text=self.translator.translate('help.steps.title'),
            font=ctk.CTkFont(weight='bold'),
            justify='left',
        )
        self._step_title.grid(row=row, column=0, sticky='w', pady=(16, 4))
        row += 1

        for step_number in range(1, 5):
            step_label = ctk.CTkLabel(
                guide_frame,
                text=f'{step_number}. {self.translator.translate(f"help.steps.step{step_number}")}',
                wraplength=820,
                justify='left',
                font=ctk.CTkFont(size=11),
                text_color='gray80',
            )
            step_label.grid(row=row, column=0, sticky='w', pady=(2, 0))
            self._step_labels.append(step_label)
            row += 1

    def update_translations(self) -> None:
        super().update_translations()
        section_keys = [
            'help.section.what',
            'help.section.start',
            'help.section.choose',
            'help.section.sudo',
            'help.section.read',
        ]
        section_text_keys = [
            'help.section.what.text',
            'help.section.sudo.text',
            'help.section.start.text',
            'help.section.choose.text',
            'help.section.read.text',
            'help.section.assisted.text',
        ]
        for label, key in zip(self._section_labels, section_keys):
            label.configure(text=self.translator.translate(key))
        for label, key in zip(self._section_texts, section_text_keys):
            label.configure(text=self.translator.translate(key))
        self._step_title.configure(text=self.translator.translate('help.steps.title'))
        for number, label in enumerate(self._step_labels, start=1):
            label.configure(text=f'{number}. {self.translator.translate(f"help.steps.step{number}")}')
