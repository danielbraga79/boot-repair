from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LOCALE = 'pt-BR'
AVAILABLE_LOCALES = ('pt-BR', 'en-US', 'es-ES', 'fr-FR', 'de-DE')
LOCALE_FILE_SUFFIX = {
    'pt-BR': 'pt_BR',
    'en-US': 'en_US',
    'es-ES': 'es_ES',
    'fr-FR': 'fr_FR',
    'de-DE': 'de_DE',
}
LANGUAGE_DISPLAY_NAMES = {
    'pt-BR': 'Português (Brasil)',
    'en-US': 'English (US)',
    'es-ES': 'Español (ES)',
    'fr-FR': 'Français (FR)',
    'de-DE': 'Deutsch (DE)',
}


class TranslationManager:
    def __init__(self, locale: str = DEFAULT_LOCALE) -> None:
        self.current_locale = self._normalize_locale(locale)
        self._cache: dict[str, dict[str, str]] = {}
        self._ensure_locale_loaded(self.current_locale)

    def available_locales(self) -> tuple[str, ...]:
        return AVAILABLE_LOCALES

    def display_name(self, locale: str) -> str:
        return LANGUAGE_DISPLAY_NAMES.get(self._normalize_locale(locale), locale)

    def locale_from_display_name(self, display_name: str) -> str | None:
        for code, label in LANGUAGE_DISPLAY_NAMES.items():
            if label == display_name:
                return code
        return None

    def set_locale(self, locale: str) -> None:
        locale_code = self._normalize_locale(locale)
        if locale_code not in AVAILABLE_LOCALES:
            locale_code = DEFAULT_LOCALE
        self.current_locale = locale_code
        self._ensure_locale_loaded(locale_code)

    def translate(self, key: str, **kwargs: Any) -> str:
        value = self._lookup(key, self.current_locale)
        if value is None and self.current_locale != DEFAULT_LOCALE:
            value = self._lookup(key, DEFAULT_LOCALE)
        if value is None:
            return f'[{key}]'
        if kwargs:
            try:
                return value.format(**kwargs)
            except Exception:
                return value
        return value

    def _normalize_locale(self, locale: str) -> str:
        return locale.replace('_', '-').strip()

    def _lookup(self, key: str, locale: str) -> str | None:
        translations = self._cache.get(locale)
        if translations is None:
            translations = self._ensure_locale_loaded(locale)
        return translations.get(key)

    def _ensure_locale_loaded(self, locale: str) -> dict[str, str]:
        locale = self._normalize_locale(locale)
        if locale in self._cache:
            return self._cache[locale]
        file_suffix = LOCALE_FILE_SUFFIX.get(locale, LOCALE_FILE_SUFFIX[DEFAULT_LOCALE])
        locale_file = Path(__file__).parent / 'locales' / f'{file_suffix}.json'
        try:
            with locale_file.open('r', encoding='utf-8') as handle:
                translations = json.load(handle)
        except FileNotFoundError:
            if locale != DEFAULT_LOCALE:
                return self._ensure_locale_loaded(DEFAULT_LOCALE)
            raise
        if not isinstance(translations, dict):
            raise ValueError(f'Invalid locale file format: {locale_file}')
        self._cache[locale] = {str(key): str(value) for key, value in translations.items()}
        return self._cache[locale]
