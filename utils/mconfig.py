"""Строка настроек внутри самой книги: первая строка файла (для Word — первая строка текста) вида

    mconfig=" isida_1.docx = Разоблаченная Изида, N2000"

Имя файла в ней должно совпадать с фактическим именем книги; тогда название (алиас) и разделитель
берутся оттуда. Формат тот же, что в Синеве Mobile. Саму строку в тексте книги (поиск, чтение,
обучение моделей) не показываем — её убирает strip() внутри utils.text_processing.read_text_file.

Модуль не импортирует text_processing на верхнем уровне (тот сам использует strip), поэтому
чтение первой строки — через отложенный импорт."""
import os
import re
from typing import Optional, Tuple

_QUOTES = '"“”„«»\''
_LINE = re.compile(r'^\s*mconfig\s*=\s*[' + _QUOTES + r']\s*(.*?)\s*[' + _QUOTES + r']\s*$', re.IGNORECASE)


def parse(line: str) -> Optional[Tuple[str, str, str]]:
    """(имя файла, название, разделитель) из строки mconfig или None, если строка не такого вида."""
    m = _LINE.match(line or '')
    if not m or '=' not in m.group(1):
        return None
    name, rest = m.group(1).split('=', 1)
    if ',' not in rest:
        return None
    display, sep = rest.rsplit(',', 1)
    name, display, sep = name.strip(), display.strip(), sep.strip()
    return (name, display, sep) if name and display and sep else None


def strip(text: str) -> str:
    """Текст без служебной первой строки mconfig."""
    if 'mconfig' not in text[:600].lower():
        return text
    head, _sep, rest = text.lstrip('﻿').partition('\n')
    return rest if _LINE.match(head.strip()) else text


def first_line(path: str) -> str:
    """Первая строка книги (.txt — по началу файла, .docx — первый абзац); пусто, если прочитать не удалось."""
    try:
        from utils.text_processing import _get_docx_paragraphs_cached, TEXT_ENCODINGS
        if os.path.splitext(path)[1].lower() == '.docx':
            paras = _get_docx_paragraphs_cached(path)
            return (paras[0] if paras else '').strip()
        with open(path, 'rb') as f:
            head = f.read(4096)
        for enc in TEXT_ENCODINGS:
            try:
                return head.decode(enc, errors='strict' if len(head) < 4096 else 'ignore').lstrip('﻿').split('\n', 1)[0].strip()
            except UnicodeDecodeError:
                continue
    except Exception:
        pass
    return ''


def read(path: str) -> Tuple[Optional[Tuple[str, str]], str]:
    """((название, разделитель) или None, пояснение). Пояснение пусто, если mconfig в книге нет."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in ('.txt', '.docx'):
        return None, ''
    line = first_line(path)
    if 'mconfig' not in line.lower():
        return None, ''
    parsed = parse(line)
    if not parsed:
        return None, "строка mconfig в книге записана неверно (нужно: mconfig=\"файл.docx = Название, N2000\")"
    name, display, sep = parsed
    actual = os.path.basename(path)
    if name.casefold() != actual.casefold():
        return None, f"имя файла в mconfig ({name}) не совпадает с именем книги ({actual}) — строка пропущена"
    return (display, sep), ''
