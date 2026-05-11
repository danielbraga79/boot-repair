from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CORE_APP_PATH = ROOT_DIR / 'boot-repair-app_0.0.3'
if str(CORE_APP_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_APP_PATH))

from i18n import DEFAULT_LOCALE, TranslationManager


class TestI18n(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = TranslationManager()

    def test_default_locale_is_pt_br(self) -> None:
        self.assertEqual(self.translator.current_locale, DEFAULT_LOCALE)
        self.assertEqual(self.translator.translate('app.window_title'), 'Boot Repair Assistant')

    def test_language_switch_to_en_us(self) -> None:
        self.translator.set_locale('en-US')
        self.assertEqual(self.translator.current_locale, 'en-US')
        self.assertEqual(self.translator.translate('selection.root_label'), 'Root partition')
        self.assertEqual(self.translator.translate('welcome.start_button'), 'Start')

    def test_language_switch_to_es_es(self) -> None:
        self.translator.set_locale('es-ES')
        self.assertEqual(self.translator.translate('selection.disks_heading'), 'Discos detectados')

    def test_help_translations_are_available(self) -> None:
        self.assertEqual(self.translator.translate('help.title'), 'Ajuda rápida')
        self.assertEqual(self.translator.translate('help.open_button'), 'Ajuda')
        self.assertEqual(self.translator.translate('help.steps.step1'), 'Detectar: clique em Iniciar para coletar discos e partições.')

    def test_missing_key_falls_back_safely(self) -> None:
        self.assertEqual(self.translator.translate('nonexistent.key'), '[nonexistent.key]')

    def test_all_required_locales_are_available(self) -> None:
        for locale in ('pt-BR', 'en-US', 'es-ES', 'fr-FR', 'de-DE'):
            self.assertIn(locale, self.translator.available_locales())

    def test_locale_display_name_roundtrip(self) -> None:
        for locale in self.translator.available_locales():
            display_name = self.translator.display_name(locale)
            self.assertEqual(self.translator.locale_from_display_name(display_name), locale)

    def test_locale_key_set_consistency(self) -> None:
        default_translations = self.translator._ensure_locale_loaded(DEFAULT_LOCALE)
        default_keys = set(default_translations.keys())
        for locale in self.translator.available_locales():
            translations = self.translator._ensure_locale_loaded(locale)
            self.assertEqual(
                set(translations.keys()),
                default_keys,
                msg=f'Locale {locale} has inconsistent translation keys',
            )

    def test_loads_all_locale_files(self) -> None:
        for locale in self.translator.available_locales():
            self.translator.set_locale(locale)
            self.assertTrue(self.translator.translate('app.window_title'))


if __name__ == '__main__':
    raise SystemExit(unittest.main())
