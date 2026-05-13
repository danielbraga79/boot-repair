from __future__ import annotations

from typing import Callable, Sequence

import customtkinter as ctk
import tkinter as tk

from core.models import Disk, Partition, format_size_bytes
from i18n import TranslationManager

from .base_screen import BaseScreen, Callback, SelectionCallback


class SelectionScreen(BaseScreen):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        translator: TranslationManager,
        on_back: Callback | None = None,
        on_continue: Callback | None = None,
        on_root_selected: SelectionCallback | None = None,
        on_efi_selected: SelectionCallback | None = None,
        on_dual_boot_selected: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            translator=translator,
            title_key='selection.title',
            subtitle_key='selection.subtitle',
            on_back=on_back,
            on_continue=on_continue,
        )
        self._on_root_selected = on_root_selected
        self._on_efi_selected = on_efi_selected
        self._on_dual_boot_selected = on_dual_boot_selected

        summary_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        summary_frame.grid(row=0, column=0, sticky='ew', pady=(10, 20))
        summary_frame.columnconfigure(0, weight=1)

        self.summary_textbox = ctk.CTkTextbox(summary_frame, height=80, wrap='word', state='disabled')
        self.summary_textbox.grid(row=0, column=0, sticky='ew')

        selector_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        selector_frame.grid(row=1, column=0, sticky='ew', pady=(10, 20))
        selector_frame.columnconfigure(1, weight=1)

        self.root_label = ctk.CTkLabel(
            selector_frame,
            text=self.translator.translate('selection.root_label'),
            font=ctk.CTkFont(weight='bold'),
        )
        self.root_label.grid(row=0, column=0, sticky='w', padx=(0, 8), pady=4)

        self.root_var = ctk.StringVar()
        self.root_combo = ctk.CTkComboBox(
            selector_frame,
            variable=self.root_var,
            state='readonly',
            command=self._dispatch_root_selected,
        )
        self.root_combo.grid(row=0, column=1, sticky='ew', pady=4, padx=(0, 20))

        self.efi_label = ctk.CTkLabel(
            selector_frame,
            text=self.translator.translate('selection.efi_label'),
            font=ctk.CTkFont(weight='bold'),
        )
        self.efi_label.grid(row=1, column=0, sticky='w', padx=(0, 8), pady=4)

        self.efi_var = ctk.StringVar()
        self.efi_combo = ctk.CTkComboBox(
            selector_frame,
            variable=self.efi_var,
            state='readonly',
            command=self._dispatch_efi_selected,
        )
        self.efi_combo.grid(row=1, column=1, sticky='ew', pady=4, padx=(0, 20))

        self.dual_boot_var = ctk.BooleanVar(value=False)
        self.dual_boot_checkbox = ctk.CTkCheckBox(
            selector_frame,
            text=self.translator.translate('selection.dual_boot_label'),
            variable=self.dual_boot_var,
            command=self._dispatch_dual_boot_selected,
        )
        self.dual_boot_checkbox.grid(row=2, column=0, columnspan=2, sticky='w', padx=(0, 8), pady=4)

        self.mode_label = ctk.CTkLabel(
            selector_frame,
            text=self.translator.translate('selection.mode_label'),
            font=ctk.CTkFont(weight='bold'),
        )
        self.mode_label.grid(row=3, column=0, sticky='w', padx=(0, 8), pady=4)

        self.mode_var = ctk.StringVar(value='safe')
        self.mode_selector = ctk.CTkSegmentedButton(
            selector_frame,
            values=['safe', 'advanced'],
            variable=self.mode_var,
            command=self._dispatch_mode_selected,
        )
        self.mode_selector.grid(row=3, column=1, sticky='ew', pady=4, padx=(0, 20))

        lists_frame = ctk.CTkFrame(self.content, fg_color='transparent')
        lists_frame.grid(row=2, column=0, sticky='ew', pady=(10, 20))
        lists_frame.columnconfigure(0, weight=1)
        lists_frame.columnconfigure(1, weight=1)
        lists_frame.rowconfigure(1, weight=1)

        disks_frame = ctk.CTkFrame(lists_frame)
        disks_frame.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, 10))
        disks_frame.columnconfigure(0, weight=1)
        disks_frame.rowconfigure(1, weight=1)

        self.disks_heading_label = ctk.CTkLabel(
            disks_frame,
            text=self.translator.translate('selection.disks_heading'),
            font=ctk.CTkFont(weight='bold'),
        )
        self.disks_heading_label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 5))

        self.disk_listbox = tk.Listbox(
            disks_frame,
            height=8,
            exportselection=False,
            bg=ctk.ThemeManager.theme['CTkFrame']['fg_color'][1],
            fg=ctk.ThemeManager.theme['CTkLabel']['text_color'][1],
            selectbackground=ctk.ThemeManager.theme['CTkButton']['fg_color'][1],
        )
        self.disk_listbox.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))

        partitions_frame = ctk.CTkFrame(lists_frame)
        partitions_frame.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=(10, 0))
        partitions_frame.columnconfigure(0, weight=1)
        partitions_frame.rowconfigure(1, weight=1)

        self.partitions_heading_label = ctk.CTkLabel(
            partitions_frame,
            text=self.translator.translate('selection.partitions_heading'),
            font=ctk.CTkFont(weight='bold'),
        )
        self.partitions_heading_label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 5))

        self.partition_listbox = tk.Listbox(
            partitions_frame,
            height=8,
            exportselection=False,
            bg=ctk.ThemeManager.theme['CTkFrame']['fg_color'][1],
            fg=ctk.ThemeManager.theme['CTkLabel']['text_color'][1],
            selectbackground=ctk.ThemeManager.theme['CTkButton']['fg_color'][1],
        )
        self.partition_listbox.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))

        self.set_status(self.translator.translate('selection.status_ready'))

    def _dispatch_root_selected(self, value: str) -> None:
        if self._on_root_selected is not None:
            self._on_root_selected(value)

    def _dispatch_efi_selected(self, value: str) -> None:
        if self._on_efi_selected is not None:
            self._on_efi_selected(value)

    def _dispatch_mode_selected(self, value: str) -> None:
        self.mode_var.set(value)

    def _dispatch_dual_boot_selected(self) -> None:
        if self._on_dual_boot_selected is not None:
            self._on_dual_boot_selected(self.dual_boot_var.get())

    def selected_mode(self) -> str:
        return self.mode_var.get()

    def selected_dual_boot(self) -> bool:
        return bool(self.dual_boot_var.get())

    def set_catalog(self, *, disks: Sequence[Disk], partitions: Sequence[Partition]) -> None:
        partition_disk_map = {partition.name: partition.disk_name for partition in partitions}
        self._partition_disk_map = dict(partition_disk_map)

        disk_strings: list[str] = []
        for disk in disks:
            model = disk.model or self.translator.translate('selection.no_model')
            size = format_size_bytes(disk.size_bytes)
            transport = disk.transport.upper() if disk.transport else ''
            removable = f' ({self.translator.translate("selection.removable")})' if getattr(disk, 'removable', False) else ''
            disk_strings.append(f'{disk.name} — {model} — {size} — {transport}{removable}')

        partition_strings: list[str] = []
        for partition in partitions:
            size = format_size_bytes(partition.size_bytes)
            mount_point = partition.mount_point if partition.mount_point else self.translator.translate('selection.unmounted')
            label = f' — {partition.label}' if partition.label else ''
            partition_strings.append(f'{partition.name} — {size} — {partition.fs_type or ""} — {mount_point}{label}')

        self._fill_listbox(self.disk_listbox, disk_strings, self.translator)
        self._fill_listbox(self.partition_listbox, partition_strings, self.translator)

        partition_names = [p.name for p in partitions]
        self.root_combo.configure(values=partition_names)
        self.efi_combo.configure(values=partition_names)

        if self.root_var.get() not in partition_names:
            self.root_var.set('')
        if self.efi_var.get() not in partition_names:
            self.efi_var.set('')

        self.set_status(self.translator.translate('selection.status_loaded'))

    def set_selection(self, root_partition: str, efi_partition: str, dual_boot_windows: bool = False) -> None:
        self.root_var.set(root_partition)
        self.efi_var.set(efi_partition)
        self.dual_boot_var.set(dual_boot_windows)

    def selected_disk_for_root(self) -> str:
        return self._partition_disk_map.get(self.root_var.get(), '')

    def update_translations(self) -> None:
        super().update_translations()
        self.root_label.configure(text=self.translator.translate('selection.root_label'))
        self.efi_label.configure(text=self.translator.translate('selection.efi_label'))
        self.dual_boot_checkbox.configure(text=self.translator.translate('selection.dual_boot_label'))
        self.mode_label.configure(text=self.translator.translate('selection.mode_label'))
        self.disks_heading_label.configure(text=self.translator.translate('selection.disks_heading'))
        self.partitions_heading_label.configure(text=self.translator.translate('selection.partitions_heading'))
        self.set_status(self.translator.translate('selection.status_ready'))

    @staticmethod
    def _fill_listbox(box: tk.Listbox, values: Sequence[str], translator: TranslationManager) -> None:
        box.delete(0, tk.END)
        if values:
            for value in values:
                box.insert(tk.END, value)
        else:
            box.insert(tk.END, translator.translate('selection.no_items'))
