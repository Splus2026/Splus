"""Сведения для окна «О программе»: размеры книг и индексов, дата сборки. Чистая логика — тестируется без окон."""
import os
import sys
from datetime import datetime


def format_size(n):
    """Размер в байтах -> '12,3 МБ' (до трёх значащих цифр, десятичная запятая)."""
    n = float(max(0, n))
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if n < 1024 or unit == 'ТБ':
            text = f"{n:.0f}" if unit == 'Б' else (f"{n:.1f}" if n < 100 else f"{n:.0f}")
            return f"{text.replace('.', ',')} {unit}"
        n /= 1024


def dir_size(path, recursive=True):
    """Сумма размеров файлов папки (0, если её нет). Недоступные файлы пропускаются."""
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
        if not recursive:
            break
    return total


def books_size(book_paths):
    """Сумма размеров файлов книг (пути — как у FileManager: ('' или 'DB', имя))."""
    total, count = 0, 0
    for subdir, name in book_paths:
        try:
            total += os.path.getsize(os.path.join(subdir, name) if subdir else name)
            count += 1
        except OSError:
            pass
    return total, count


def index_sizes(engine=None):
    """[(подпись, размер)] индексов: каталоги FTS5 и Manticore, если они есть и не пусты."""
    found = []
    candidates = [("FTS5", "indicies_fts5")]
    data_dir = getattr(engine, 'data_dir', None)
    candidates.append(("Manticore", data_dir if data_dir else "indicies_mc"))
    for label, path in candidates:
        size = dir_size(path)
        if size:
            found.append((label, size))
    return found


def build_date(executable=None, script=None):
    """Дата сборки: у собранной программы — время изменения Sineva.exe, из исходников — файла sp.py."""
    path = sys.executable if getattr(sys, 'frozen', False) else (script or (sys.argv[0] if sys.argv else ''))
    if executable:
        path = executable
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime('%d.%m.%Y')
    except OSError:
        return ''


def about_text(version, books, indexes, built):
    """Текст окна «О программе»."""
    book_bytes, book_count = books
    lines = [f"Синева+  {version or '—'}", f"Дата сборки: {built or 'неизвестна'}", "",
             f"Книги: {format_size(book_bytes)} ({book_count} файл.)"]
    if indexes:
        lines += [f"Индексы {label}: {format_size(size)}" for label, size in indexes]
        if len(indexes) > 1:
            lines.append(f"Индексы всего: {format_size(sum(s for _l, s in indexes))}")
    else:
        lines.append("Индексы: пока нет")
    return "\n".join(lines)
