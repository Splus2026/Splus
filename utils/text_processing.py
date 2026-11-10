import os
import re
import zipfile
from collections import OrderedDict
from datetime import datetime
from xml.etree import ElementTree as ET

# Кодировки, которые пробуются по очереди при чтении .txt файлов —
# используется всеми модулями, читающими файлы-источники (общий, единый список).
TEXT_ENCODINGS = ['utf-8', 'cp1251', 'latin-1', 'koi8-r']

_DOCX_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Кеш уже извлечённых абзацев .docx — файл + время изменения + размер → список
# абзацев (без применения keep_empty_docx_paragraphs, он применяется после).
# Разбор .docx — самая медленная часть открытия файла по гиперссылке, а один
# и тот же файл-источник часто открывают повторно (разные топики из одного
# файла), поэтому повторные открытия того же файла не читают и не парсят его
# заново, пока он не изменился на диске. Размер кеша ограничен, чтобы не
# накапливать в памяти неограниченное количество больших документов.
_docx_paragraphs_cache = OrderedDict()
_DOCX_CACHE_MAX_FILES = 5


def _read_docx_paragraphs_fast(file_path):
    """Извлекает текст абзацев .docx прямым разбором word/document.xml, минуя
       тяжёлую объектную модель python-docx. На больших документах (десятки
       тысяч абзацев) это в 4-5 раз быстрее при полностью идентичном
       результате — проверено на документах с разрывами строк (<w:br/>),
       табуляцией (<w:tab/>), несколькими <w:r> в одном абзаце и пустыми
       абзацами. Как и doc.paragraphs в python-docx, берёт только абзацы,
       являющиеся непосредственными детьми <w:body> — абзацы внутри таблиц
       (<w:tbl>) не включаются."""
    with zipfile.ZipFile(file_path) as z:
        xml_bytes = z.read('word/document.xml')
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_DOCX_W_NS}body")
    if body is None:
        raise ValueError("word/document.xml: не найден <w:body>")
    paragraphs = []
    for p in body.findall(f"{_DOCX_W_NS}p"):
        parts = []
        for node in p.iter():
            tag = node.tag
            if tag == f"{_DOCX_W_NS}t":
                parts.append(node.text or "")
            elif tag == f"{_DOCX_W_NS}tab":
                parts.append("\t")
            elif tag in (f"{_DOCX_W_NS}br", f"{_DOCX_W_NS}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return paragraphs


def _read_docx_paragraphs_with_docx_lib(file_path):
    """Надёжный, но медленный резервный способ через python-docx — на случай,
       если быстрый разбор XML не справился с каким-то нестандартным .docx."""
    try:
        from docx import Document
    except ImportError:
        raise Exception("Для чтения .docx установите python-docx")
    try:
        doc = Document(file_path)
        return [p.text for p in doc.paragraphs]
    except Exception as e:
        raise Exception(f"Ошибка чтения .docx: {e}")


def _get_docx_paragraphs_cached(file_path):
    try:
        stat = os.stat(file_path)
        cache_key = os.path.abspath(file_path)
    except OSError:
        stat = None
        cache_key = None

    if stat is not None and cache_key in _docx_paragraphs_cache:
        cached_mtime, cached_size, cached_paragraphs = _docx_paragraphs_cache[cache_key]
        if cached_mtime == stat.st_mtime and cached_size == stat.st_size:
            _docx_paragraphs_cache.move_to_end(cache_key)
            return cached_paragraphs

    try:
        paragraphs = _read_docx_paragraphs_fast(file_path)
    except Exception:
        # Быстрый разбор не справился (нестандартная структура документа) —
        # используем надёжный python-docx как раньше.
        paragraphs = _read_docx_paragraphs_with_docx_lib(file_path)

    if stat is not None:
        _docx_paragraphs_cache[cache_key] = (stat.st_mtime, stat.st_size, paragraphs)
        _docx_paragraphs_cache.move_to_end(cache_key)
        while len(_docx_paragraphs_cache) > _DOCX_CACHE_MAX_FILES:
            _docx_paragraphs_cache.popitem(last=False)

    return paragraphs


def read_text_file(file_path: str, keep_empty_docx_paragraphs: bool = True) -> str:
    """Читает содержимое файла-источника (.txt в одной из TEXT_ENCODINGS,
       либо .docx) и возвращает текст.

       Раньше эта логика была продублирована почти буквально в
       services/file_manager.py и services/search_controller.py — вынесена
       сюда как единая точка чтения файлов-источников.

       keep_empty_docx_paragraphs: у двух прежних копий этой логики было разное
       поведение для .docx — одна сохраняла пустые абзацы (пустые строки),
       другая их пропускала. Чтобы не изменить поведение ни в одном из мест
       (индексация файла и просмотр файла по гиперссылке), поведение
       выбирается этим параметром, а не унифицируется молча."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.docx':
        paragraphs = _get_docx_paragraphs_cached(file_path)
        if not keep_empty_docx_paragraphs:
            paragraphs = [p for p in paragraphs if p.strip()]
        return "\n".join(paragraphs)

    for enc in TEXT_ENCODINGS:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise Exception("Не удалось прочитать файл ни в одной из кодировок.")


# Транслитерация кириллицы для make_safe_index_name — без неё имя файла,
# состоящее целиком из кириллических букв (обычное дело для русских названий
# файлов), после санитизации превращалось в пустую строку и заменялось общей
# заглушкой 'index' — из-за чего РАЗНЫЕ файлы получали ОДНО и то же имя
# индекса в Manticore и затирали данные друг друга при создании.
_CYRILLIC_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'і': 'i', 'ї': 'yi', 'є': 'ye', 'ґ': 'g',
}


def _transliterate(text: str) -> str:
    result = []
    for ch in text:
        lower = ch.lower()
        if lower in _CYRILLIC_TRANSLIT:
            result.append(_CYRILLIC_TRANSLIT[lower])
        else:
            result.append(ch)
    return ''.join(result)


def make_safe_index_name(filename: str, engine_type: str) -> tuple:
    """Строит безопасное имя индекса для движка (manticore/elasticsearch) из
       имени файла-источника. Возвращает (safe_name, expected_full_name).

       Раньше эта санитизация была продублирована в services/file_manager.py
       (с учётом ведущей цифры) и services/index_manager.py (без учёта!) —
       из-за расхождения двух копий алиас файла, чьё имя начинается с цифры,
       не находился при подсчёте выбранных индексов. Вынесено сюда как одна
       функция, чтобы оба места гарантированно совпадали.

       Всегда возвращает имя в нижнем регистре: Manticore сам хранит имена
       таблиц в нижнем регистре (SHOW TABLES возвращает их именно так), и
       если это имя не привести к нижнему регистру заранее, последующие
       проверки "такой индекс уже существует?" (по точному совпадению строк)
       не срабатывают — что при повторной индексации того же файла приводило
       не к обычному запросу "Перезаписать?", а прямо к ошибке СУБД
       "table already exists"."""
    base = os.path.splitext(os.path.basename(filename))[0]
    base = _transliterate(base)
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    safe_name = re.sub(r'_+', '_', safe_name).strip('_').lower()
    if not safe_name:
        safe_name = 'index'
    if engine_type == 'manticore':
        if safe_name[0].isdigit():
            safe_name = 'idx_' + safe_name
        expected_full_name = safe_name
    else:
        expected_full_name = f"ms_{safe_name}"
    return safe_name, expected_full_name


def split_into_sections_by_separator(lines, separator):
    if separator == "Numeric":
        return _split_numeric(lines)
    elif separator == "ExcelRow1":
        return _split_excel_rows(lines)
    elif separator.startswith('N') and separator != "Numeric":
        if separator.startswith('NS'):
            return _split_semantic(lines, separator)
        else:
            return _split_fixed_size(lines, separator)
    else:
        return _split_by_string(lines, separator)

def _split_excel_rows(lines):
    """Разделитель 'ExcelRow1' для Excel-файлов: каждая строка — один топик.
       К моменту вызова строки уже подготовлены utils/excel_processing.py
       (одна строка листа = одна строка текста, без внутренних переводов
       строк), так что здесь достаточно просто взять их по одной."""
    sections = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        sections.append({
            'lines': [line],
            'title': line.strip()[:100],
            'start_line': i
        })
    return sections

def _split_numeric(lines):
    sections = []
    current_section = []
    current_title = ""
    current_start = 0
    for i, line in enumerate(lines):
        if line.strip() and re.match(r'^\d+', line.strip()):
            if current_section:
                sections.append({
                    'lines': current_section,
                    'title': current_title,
                    'start_line': current_start
                })
            current_title = line.strip()[:100]
            current_section = [line]
            current_start = i
        else:
            current_section.append(line)
    if current_section:
        sections.append({
            'lines': current_section,
            'title': current_title,
            'start_line': current_start
        })
    return sections

def _split_fixed_size(lines, separator):
    try:
        block_size = int(separator[1:])
    except:
        block_size = 100
    if block_size <= 0:
        block_size = 100
    full_text = '\n'.join(lines)
    text_len = len(full_text)
    sections = []
    pos = 0
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line) + 1)
    def get_line_number(pos):
        lo, hi = 0, len(line_offsets) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if line_offsets[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return lo
    while pos < text_len:
        end = min(pos + block_size, text_len)
        if end < text_len:
            space_pos = full_text.rfind(' ', pos, end)
            if space_pos > pos:
                end = space_pos + 1
            else:
                next_space = full_text.find(' ', end)
                # Пробела дальше нет — это ПОСЛЕДНЕЕ слово текста: берём его целиком (раньше его
                # резало ровно на размере блока, если оно длиннее блока).
                end = next_space + 1 if next_space != -1 else text_len
        block_text = full_text[pos:end].strip()
        if block_text:
            line_num = get_line_number(pos)
            sections.append({
                'lines': [block_text],
                'title': f"Блок {len(sections)+1} (символы {pos+1}-{end})",
                'start_line': line_num - 1
            })
        pos = end
    return sections

def _split_semantic(lines, separator):
    target_size = 200
    try:
        target_size = int(separator[2:])
    except:
        pass
    full_text = '\n'.join(lines)
    blocks, positions = split_into_blocks_by_semantic_with_positions(full_text, target_size)
    sections = []
    for i, (block, start_pos, end_pos) in enumerate(zip(blocks, positions['starts'], positions['ends']), 1):
        line_num = 0
        char_count = 0
        for j, line in enumerate(lines):
            if char_count + len(line) + 1 > start_pos:
                line_num = j
                break
            char_count += len(line) + 1
        sections.append({
            'lines': [block],
            'title': f"Блок {i} (смысловой)",
            'start_line': line_num
        })
    return sections

def _split_by_string(lines, separator):
    sections = []
    current_section = []
    current_title = ""
    current_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith(separator):
            if current_section:
                sections.append({
                    'lines': current_section,
                    'title': current_title,
                    'start_line': current_start
                })
            current_title = line.strip()[:100]
            current_section = [line]
            current_start = i
        else:
            current_section.append(line)
    if current_section:
        sections.append({
            'lines': current_section,
            'title': current_title,
            'start_line': current_start
        })
    return sections

def split_into_blocks_by_semantic_with_positions(text, target_size=200):
    paragraphs = text.split('\n\n')
    blocks = []
    starts = []
    ends = []
    current_block = []
    current_size = 0
    current_pos = 0
    for para in paragraphs:
        if not para.strip():
            continue
        para_start = text.find(para, current_pos)
        if para_start == -1:
            continue
        current_pos = para_start
        sentences = re.split(r'[.!?]\s+', para)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            sent_len = len(sent)
            sent_start = text.find(sent, current_pos)
            if sent_start == -1:
                continue
            if sent_len > target_size * 1.5:
                # Позиции: на каждый блок РОВНО по одному началу и одному концу (начало блока
                # записывается при его открытии, поэтому при закрытии его повторять нельзя — раньше
                # здесь дописывалось лишнее начало, и у всех блоков, кроме первого, позиция
                # оказывалась чужой).
                if current_block:
                    blocks.append(' '.join(current_block))
                    ends.append(current_pos)
                    current_block = []
                    current_size = 0
                words = sent.split()
                temp_block = []
                temp_size = 0
                consumed = 0
                block_start = sent_start
                for word in words:
                    if temp_size + len(word) + 1 > target_size and temp_block:
                        blocks.append(' '.join(temp_block))
                        starts.append(block_start)
                        ends.append(block_start + temp_size - 1)
                        consumed += temp_size
                        block_start = sent_start + consumed
                        temp_block = []
                        temp_size = 0
                    temp_block.append(word)
                    temp_size += len(word) + 1
                if temp_block:
                    blocks.append(' '.join(temp_block))
                    starts.append(block_start)
                    ends.append(sent_start + sent_len)
                current_pos = sent_start + sent_len
                continue
            if current_size + sent_len + 1 > target_size and current_block:
                blocks.append(' '.join(current_block))
                ends.append(current_pos)
                current_block = []
                current_size = 0
            if not current_block:
                starts.append(sent_start)
            current_block.append(sent)
            current_size += sent_len + 1
            current_pos = sent_start + sent_len
    if current_block:
        blocks.append(' '.join(current_block))
        ends.append(current_pos)
    if not blocks and text.strip():
        blocks = [text.strip()]
        starts = [0]
        ends = [len(text)]
    return blocks, {'starts': starts, 'ends': ends}

def split_into_blocks_by_size_with_positions(text, block_size):
    if block_size <= 0:
        return [text], {'starts': [0], 'ends': [len(text)]}
    blocks = []
    starts = []
    ends = []
    text_length = len(text)
    pos = 0
    while pos < text_length:
        end = min(pos + block_size, text_length)
        if end < text_length:
            space_pos = text.rfind(' ', pos, end)
            if space_pos > pos:
                end = space_pos + 1
            else:
                next_space = text.find(' ', end)
                # Пробела дальше нет — это ПОСЛЕДНЕЕ слово текста: берём его целиком.
                end = next_space + 1 if next_space != -1 else text_length
        block_text = text[pos:end].strip()
        blocks.append(block_text)
        starts.append(pos)
        ends.append(end)
        pos = end
    return blocks, {'starts': starts, 'ends': ends}

def log_sections(separator, sections, log_file="index_debug.log"):
    try:
        if separator == "Numeric":
            sep_desc = "Разделитель по номерам строк"
        elif separator.startswith('NS'):
            try:
                size = int(separator[2:])
                sep_desc = f"Смысловой блок, ~{size} символов"
            except:
                sep_desc = f"Смысловой блок (неверный параметр: {separator})"
        elif separator.startswith('N'):
            try:
                size = int(separator[1:])
                sep_desc = f"Фиксированный размер: {size} символов"
            except:
                sep_desc = f"Фиксированный размер (неверный параметр: {separator})"
        else:
            sep_desc = f"Строковый разделитель: '{separator}'"
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Диагностика разбиения на топики ===\n")
            f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Тип разделителя: {separator}\n")
            f.write(f"Расшифровка: {sep_desc}\n")
            f.write(f"Всего топиков: {len(sections)}\n\n")
            f.write("Первые 7 топиков (с позициями):\n")
            for i, section in enumerate(sections[:7], 1):
                f.write(f"\n--- Топик {i} ---\n")
                f.write(f"Позиция (строка): {section.get('start_line', 0)}\n")
                text = '\n'.join(section['lines'])
                f.write(f"Текст: {text[:500]}...\n" if len(text) > 500 else f"Текст: {text}\n")
            f.write("\n=== Конец диагностики ===\n")
    except Exception as e:
        print(f"Ошибка записи диагностики: {e}")

_SENTENCE_FALLBACK_RE = re.compile(r'(?<=[.!?])\s+')


def split_sentences(text: str) -> list:
    """Разбивает текст абзаца на предложения. Пробует nltk (punkt) — если
       пакет/данные недоступны (нет интернета для скачивания и т.п.), тихо
       переходит на простое регулярное разбиение по концам предложений —
       хуже с сокращениями, но работает всегда и без внешних зависимостей.
       Используется и для "кругов связи" FastText (VectorModelManager), и
       для "окон смысла" MiniLM (utils/semantic_chunking.py)."""
    try:
        import nltk
        try:
            nltk.data.find('tokenizers/punkt_tab')
        except LookupError:
            nltk.data.find('tokenizers/punkt')
        from nltk.tokenize import sent_tokenize
        return sent_tokenize(text, language='russian')
    except Exception:
        return [s.strip() for s in _SENTENCE_FALLBACK_RE.split(text) if s.strip()]
