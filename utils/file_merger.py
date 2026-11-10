"""Логика окна "Собрать базу" (ui/file_merger_dialog.py): чтение исходных
   файлов, склейка в один текст и запись результата.

   Вынесено из самого окна, чтобы не зависеть от tkinter — эту часть можно
   проверять на настоящих файлах без графики.

   Главное правило склейки — в итоговый файл НЕ добавляется ничего, кроме
   строки-разделителя, заданной пользователем: ни шапки "ОБЪЕДИНЁННЫЙ ФАЙЛ",
   ни имён/путей файлов, ни пометок "Страница N из M", ни "КОНЕЦ ФАЙЛА" (всё
   это делал старый вариант этого окна из прежнего проекта). Если что-то не
   удалось прочитать — это сообщается в журнале окна, а не вписывается в
   сам результат."""

import codecs
import importlib.util
import os
import re

from utils.text_processing import read_text_file

# Что можно склеивать. Старый вариант окна принимал ещё .doc, но его
# "извлечение" было эвристикой по сырым байтам (чтение как utf-8 с отбрасыванием
# непонятного и поиск похожих на текст кусков) — на обычных русских .doc-файлах
# (однобайтовая cp1251 или utf-16) она не находит почти ничего, так что
# "поддержка" была мнимой. Честнее не принимать такие файлы вовсе.
SUPPORTED_EXTENSIONS = ('.txt', '.docx', '.pdf')

# Форматы РЕЗУЛЬТАТА — те, что приложение умеет потом читать и индексировать
# (см. FileManager._scan_text_files: .txt/.docx/.xlsx). PDF в этот список не
# входит: из списка файлов приложения его всё равно нельзя было бы добавить в
# индекс.
OUTPUT_FORMATS = ('txt', 'docx')

# Пунктирная линия по умолчанию — длиной 70, как "-" * 70 в старом проекте.
DEFAULT_SEPARATOR = '-' * 70
DEFAULT_OUTPUT_NAME = 'out'  # без расширения


# ---------- подбор файлов ----------

def natural_sort_key(name: str):
    """Ключ "естественной" сортировки: "глава2" раньше "глава10" (обычная
       строковая поставила бы "глава10" раньше). Для склейки порядок файлов
       существенен — это порядок глав/книг в итоговой базе."""
    # re.split с одной группой даёт строго чередование "не цифры, цифры,
    # не цифры, ..." — на чётных местах всегда строки, на нечётных всегда
    # числа, так что сравнение ключей двух разных имён никогда не упирается в
    # сравнение числа со строкой.
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', name)]


def is_supported_file(path: str) -> bool:
    name = os.path.basename(path)
    # "~$имя.docx" — временный файл-замок, который Word создаёт рядом с
    # открытым документом; сам по себе он не является настоящим .docx и при
    # чтении даёт ошибку.
    if name.startswith('~$'):
        return False
    return os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS


def list_supported_files(folder: str) -> list:
    """Полные пути поддерживаемых файлов из папки (без подпапок), в
       естественном порядке имён."""
    result = []
    with os.scandir(folder) as it:
        for entry in it:
            if entry.is_file() and is_supported_file(entry.name):
                result.append(entry.path)
    result.sort(key=lambda p: natural_sort_key(os.path.basename(p)))
    return result


def normalize_path_key(path: str) -> str:
    """Ключ для сравнения путей ("тот же файл?") — без учёта регистра на
       Windows и без различий в написании пути."""
    return os.path.normcase(os.path.abspath(path))


# ---------- доступность библиотек ----------

def pdf_reader_available() -> bool:
    return (importlib.util.find_spec('pypdf') is not None
            or importlib.util.find_spec('PyPDF2') is not None)


def docx_available() -> bool:
    return importlib.util.find_spec('docx') is not None


# ---------- чтение ----------

def _read_txt(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read()
    # Файлы с меткой порядка байтов (BOM) обрабатываем сами: стандартное чтение
    # приложения (read_text_file) оставило бы символ BOM в начале текста, а при
    # склейке он оказался бы посреди итогового файла, а UTF-16 вообще превратил
    # бы в мусор (cp1251 "успешно" декодирует почти любые байты).
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode('utf-8', errors='replace')
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return raw.decode('utf-32', errors='replace')
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode('utf-16', errors='replace')
    # Остальное — тем же способом, каким приложение читает тексты при
    # индексации (набор кодировок TEXT_ENCODINGS).
    return read_text_file(path)


def _read_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # прежнее название той же библиотеки
        except ImportError:
            raise ImportError("Для чтения PDF установите пакет pypdf: pip install pypdf")

    reader = PdfReader(path)
    if getattr(reader, 'is_encrypted', False):
        # Многие PDF "зашифрованы" пустым паролем (только запрет копирования/
        # печати) — такие читаются без пароля.
        try:
            decrypted = reader.decrypt('')
        except Exception as e:
            raise ValueError(f"PDF защищён паролем или шифрованием, которое не удалось снять ({e})")
        if not decrypted:
            raise ValueError("PDF защищён паролем")

    pages = []
    for page in reader.pages:
        page_text = page.extract_text() or ''
        if page_text.strip():
            pages.append(page_text)
    # Никаких пометок "--- Страница N из M ---" между страницами (их вставлял
    # прежний вариант) — только сам текст.
    return '\n'.join(pages)


def read_source_text(path: str) -> str:
    """Читает текст исходного файла (.txt/.docx/.pdf). При проблеме бросает
       исключение с понятным сообщением — вызывающий код записывает его в
       журнал, а в итоговый файл ничего не вписывается."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.txt':
        return _read_txt(path)
    if ext == '.docx':
        # Пустые абзацы пропускаются — так же, как при индексации .docx в
        # приложении (FileManager._read_file_content): собранная база будет
        # читаться так же, как читалась бы каждая из книг по отдельности.
        return read_text_file(path, keep_empty_docx_paragraphs=False)
    if ext == '.pdf':
        return _read_pdf(path)
    raise ValueError(f"Формат {ext or '(без расширения)'} не поддерживается")


# ---------- склейка ----------

def merge_texts(texts, separator: str = '') -> str:
    """Склеивает тексты в один. Между соседними текстами — РОВНО одна строка:
       separator (если он пустой — просто пустая строка). Ничего другого не
       добавляется.

       Края каждого текста слегка нормализуются: убираются пустые строки в
       самом начале и любые пробельные символы/переводы строк в самом конце.
       Иначе расположение разделителя зависело бы от того, заканчивается ли
       конкретный файл переводом строки (у одних файлов — да, у других — нет):
       перед одним разделителем появлялась бы лишняя пустая строка, перед
       другим — нет. Внутри текста ничего не меняется.

       Пустые (после нормализации) тексты пропускаются, чтобы не получить
       подряд два разделителя с пустотой между ними. Итог заканчивается
       одним переводом строки, как обычный текстовый файл."""
    separator = (separator or '').replace('\r\n', '\n').replace('\r', '\n')
    cleaned = []
    for text in texts:
        text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
        text = text.lstrip('\n').rstrip()
        if text:
            cleaned.append(text)
    if not cleaned:
        return ''
    return ('\n' + separator + '\n').join(cleaned) + '\n'


# ---------- запись ----------

def ensure_extension(path: str, ext: str) -> str:
    """Приводит расширение имени файла к выбранному формату. Если у файла
       уже другое "наше" расширение (.txt/.docx) — заменяет его, а не
       приклеивает второе (иначе "база.txt" при выборе DOCX превратилась бы в
       "база.txt.docx")."""
    base, current = os.path.splitext(path)
    wanted = '.' + ext.lower()
    if current.lower() == wanted:
        return path
    if current.lower() in ('.' + f for f in OUTPUT_FORMATS):
        return base + wanted
    return path + wanted


# Символы, недопустимые в XML (на нём построен .docx): python-docx на них
# падает с ValueError. В тексте, пришедшем из PDF, они изредка встречаются.
_XML_INVALID_RE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


def _write_docx(text: str, path: str):
    try:
        from docx import Document
    except ImportError:
        raise ImportError("Для сохранения в DOCX установите python-docx: pip install python-docx")
    doc = Document()
    for line in text.split('\n'):
        doc.add_paragraph(_XML_INVALID_RE.sub('', line))
    doc.save(path)


def write_merged(text: str, output_path: str, fmt: str):
    """Записывает результат. Сначала во временный файл рядом, затем подменой
       — чтобы при сбое посреди записи не остался наполовину записанный
       "итоговый" файл (а если на этом месте уже был прежний результат — он
       не пропал бы)."""
    fmt = fmt.lower()
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f"Неизвестный формат результата: {fmt}")
    tmp_path = output_path + '.part'
    try:
        if fmt == 'txt':
            # errors='replace': из PDF иногда приходят одиночные суррогатные
            # символы, которые utf-8 закодировать не может — лучше "?" на
            # месте такого символа, чем потерять всё объединение на самом
            # последнем шаге.
            with open(tmp_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write(text)
        else:
            _write_docx(text, tmp_path)
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
