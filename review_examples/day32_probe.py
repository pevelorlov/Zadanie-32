"""Учебный модуль для проверки AI-ревью; приложение его не импортирует.

Контракты функций описаны в README.md рядом с этим файлом.
"""


def average(total, count):
    return total / count if count else 0


def merge_facts(existing, generated):
    locked = [fact for fact in existing if fact.get("locked")]
    return locked + list(generated)
