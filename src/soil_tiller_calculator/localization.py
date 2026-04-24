from __future__ import annotations

import json
from importlib import resources
from typing import Any


class Localizer:
    """Простой загрузчик переводов интерфейса.

    Берёт строки из JSON-файлов в папке locales. Если перевод отсутствует,
    сначала пробует английский fallback, затем возвращает сам ключ.
    """

    def __init__(self, language: str = "ru") -> None:
        """Создаёт локализатор для выбранного языка."""
        self._fallback = self._load_language("en")
        self.language = language
        self._messages = self._load_language(language)

    def set_language(self, language: str) -> None:
        """Переключает активный язык и заново загружает словарь переводов."""
        self.language = language
        self._messages = self._load_language(language)

    def gettext(self, key: str, **kwargs: Any) -> str:
        """Возвращает переведённую строку по ключу.

        key: ключ локализации.
        kwargs: значения для подстановки в шаблон через str.format.
        """
        text = self._messages.get(key, self._fallback.get(key, key))
        if kwargs:
            return text.format(**kwargs)
        return text

    __call__ = gettext

    @staticmethod
    def _load_language(language: str) -> dict[str, str]:
        """Загружает JSON-файл локали и возвращает словарь переводов."""
        try:
            package = resources.files("soil_tiller_calculator").joinpath("locales", f"{language}.json")
            return json.loads(package.read_text(encoding="utf-8"))
        except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError):
            return {}
