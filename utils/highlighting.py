import re

"""Чистые (без обращения к Tkinter) функции для подсветки совпадений и
определения позиций в тексте. Вынесены из services/search_controller.py при
выделении отрисовки результатов в ui/results_renderer.py — эти функции
одинаково нужны и контроллеру (для передачи данных в отрисовщик), и самому
отрисовщику, поэтому им место в общем модуле utils/, а не в UI-модуле."""


def get_intervals(text, exact_words, partial_fragments):
    """Находит и объединяет интервалы точных и частичных совпадений слов
       запроса в тексте. Возвращает список [start, end, prio] (prio=2 —
       точное совпадение, prio=1 — частичное), отсортированный по позиции."""
    intervals = []
    for w in exact_words:
        pattern = re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE)
        for match in pattern.finditer(text):
            intervals.append((match.start(), match.end(), 2))
    for frag in partial_fragments:
        pattern = re.compile(re.escape(frag), re.IGNORECASE)
        for match in pattern.finditer(text):
            intervals.append((match.start(), match.end(), 1))
    if not intervals:
        return []
    intervals.sort(key=lambda x: (x[0], x[1]))
    merged = []
    for start, end, prio in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end, prio])
        else:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
                merged[-1][2] = max(merged[-1][2], prio)
    return merged


def build_brief_view_mapped(content, exact_words, partial_fragments):
    """Строит краткую версию текста топика: оставляет только предложения,
       в которых есть подсветка слов запроса, а пропущенный между ними текст
       заменяет многоточием. Текст до первого и после последнего такого
       предложения не показывается вовсе. Возвращает (текст, интервалы) —
       интервалы подсветки пересчитаны под координаты нового (короткого)
       текста, чтобы их можно было применить так же, как обычно.

       Третий элемент результата — карта кусков segments:
       [(начало_на_экране, начало_в_исходном_тексте, длина)]. Короткий текст
       состоит из непрерывных кусков исходного, склеенных " … ", и по этой
       карте выделение на экране переводится в смещения исходного текста (и
       обратно) — так подчёркивание ("Ч", services/marks.py) работает и в
       кратком режиме. Если текст показан целиком, карта — один кусок."""
    intervals = get_intervals(content, exact_words, partial_fragments)
    identity = [(0, 0, len(content))]
    if not intervals:
        return content, intervals, identity

    # Разбиваем текст топика на предложения по конечной пунктуации
    sentence_bounds = []
    pos = 0
    for m in re.finditer(r'[^.!?]*[.!?]+', content):
        sentence_bounds.append((pos, m.end()))
        pos = m.end()
    if pos < len(content):
        sentence_bounds.append((pos, len(content)))
    if not sentence_bounds:
        return content, intervals, identity

    kept_flags = [
        any(istart < e and iend > s for istart, iend, _ in intervals)
        for s, e in sentence_bounds
    ]
    if not any(kept_flags):
        return content, intervals, identity

    # Группируем подряд идущие "оставляемые" предложения в непрерывные
    # диапазоны исходного текста
    runs = []
    i = 0
    n = len(sentence_bounds)
    while i < n:
        if kept_flags[i]:
            run_start = sentence_bounds[i][0]
            j = i
            while j < n and kept_flags[j]:
                j += 1
            run_end = sentence_bounds[j - 1][1]
            runs.append((run_start, run_end))
            i = j
        else:
            i += 1

    brief_parts = []
    brief_intervals = []
    segments = []
    cursor = 0
    for run_idx, (r_start, r_end) in enumerate(runs):
        if run_idx > 0:
            sep = " … "
            brief_parts.append(sep)
            cursor += len(sep)
        run_text = content[r_start:r_end]
        segments.append((cursor, r_start, len(run_text)))
        brief_parts.append(run_text)
        for istart, iend, prio in intervals:
            if istart >= r_start and iend <= r_end:
                brief_intervals.append((cursor + (istart - r_start), cursor + (iend - r_start), prio))
        cursor += len(run_text)

    return "".join(brief_parts), brief_intervals, segments


def build_brief_view(content, exact_words, partial_fragments):
    """Краткая версия текста топика — (текст, интервалы подсветки). Карту кусков
       для перевода выделения на экране в исходный текст даёт
       build_brief_view_mapped (это та же функция, здесь карта отбрасывается)."""
    text, intervals, _segments = build_brief_view_mapped(content, exact_words, partial_fragments)
    return text, intervals


# Максимум "слов" (кусков без пробелов), которые допускается включать в
# резервный поиск topic_text по регулярному выражению — см. _find_topic_text.
# Ограничивает размер построенного паттерна для очень крупных топиков.
_FUZZY_MATCH_MAX_TOKENS = 300


def _find_topic_text(content: str, search_text: str):
    """Ищет search_text в content. Сначала — точным совпадением. Если не
       найдено, пробует более "терпимый" к пробельным символам поиск: та же
       последовательность слов, но между ними допускается любое количество
       пробелов/переводов строк вместо точных.

       Это нужно из-за того, что для .docx индексация (file_manager.py) и
       просмотр по гиперссылке (search_controller.py) исторически по-разному
       обрабатывают пустые абзацы — один пропускает их, другой сохраняет как
       пустые строки. Из-за этого расхождения текст топика, сохранённый при
       индексации, иногда не находится побайтово в тексте, который строится
       при просмотре (лишняя/недостающая пустая строка ровно на границе
       топика) — тогда без этого резервного поиска гиперссылка открывала
       начало файла без всякой связи с реальным результатом поиска.

       Возвращает (pos, length) или (-1, 0), если не найдено ни так, ни так."""
    pos = content.find(search_text)
    if pos != -1:
        return pos, len(search_text)

    tokens = search_text.split()
    if not tokens:
        return -1, 0
    pattern_tokens = tokens[:_FUZZY_MATCH_MAX_TOKENS]
    pattern = r'\s+'.join(re.escape(t) for t in pattern_tokens)
    try:
        match = re.search(pattern, content)
    except re.error:
        return -1, 0
    if not match:
        return -1, 0
    start = match.start()
    if len(tokens) > _FUZZY_MATCH_MAX_TOKENS:
        # Топик крупнее лимита токенов — конец приблизительный (не критично,
        # используется только как область для подсветки и не влияет на то,
        # что мы уже правильно нашли НАЧАЛО топика вместо начала файла).
        end = start + len(search_text)
    else:
        end = match.end()
    return start, end - start


def determine_position(content: str, ext: str, topic_text: str, position: str) -> tuple:
    """Определяет позицию топика в тексте файла-источника (для просмотра по
       гиперссылке). Возвращает (line_num, char_pos, target_char_pos,
       topic_start, topic_end)."""
    topic_start = 0
    topic_end = 0
    if topic_text and topic_text.strip():
        search_text = topic_text.strip()
        pos, match_len = _find_topic_text(content, search_text)
        if pos != -1:
            topic_start = pos
            topic_end = pos + match_len
            line_num = content[:pos].count('\n') + 1
            line_start = content[:pos].rfind('\n') + 1
            char_pos = pos - line_start
            return line_num, char_pos, pos, topic_start, topic_end
    if ext == '.txt' and position and position != '0':
        try:
            pos_int = int(position)
            if pos_int >= 0:
                line_num = pos_int + 1
                total_lines = content.count('\n') + 1
                if line_num > total_lines:
                    line_num = total_lines
                char_pos = 0
                # Строки считаем по \n — так их считает окно просмотра (Tk) и так выше посчитан total_lines.
                # splitlines() считает разрывами ещё form feed, \x1c-\x1e, \x85, U+2028/2029 — в текстах, где они
                # есть (например, из PDF), позиция «уезжала» на строку раньше.
                lines = content.split('\n')
                target_char_pos = 0
                for i in range(min(pos_int, len(lines))):
                    target_char_pos += len(lines[i]) + 1
                target_char_pos = min(target_char_pos, len(content))
                if topic_text:
                    topic_start = target_char_pos
                    topic_end = target_char_pos + len(topic_text)
                    if topic_end > len(content):
                        topic_end = len(content)
                else:
                    topic_start = max(0, target_char_pos - 2000)
                    topic_end = min(len(content), target_char_pos + 2000)
                return line_num, char_pos, target_char_pos, topic_start, topic_end
        except (ValueError, TypeError):
            pass
    return 1, 0, 0, 0, min(len(content), 2000)


def compute_file_highlight_intervals(full_content: str, topic_start: int, topic_end: int,
                                     highlight_words: list, highlight_fragments: list,
                                     context_size: int = 500, max_tags: int = 200):
    """Вычисляет объединённые интервалы подсветки для текста файла-источника
       (в координатах full_content, без учёта смещения шапки "Назад к
       результатам" — это добавляет вызывающий код/отрисовщик).

       Возвращает (merged, total_intervals): merged — список [start, end, tag],
       уже объединённый и обрезанный до max_tags; total_intervals — сколько
       интервалов было найдено до объединения (используется для статистики)."""
    if not highlight_words and not highlight_fragments:
        return [], 0
    if not full_content:
        return [], 0
    if context_size == 0:
        start_pos = 0
        end_pos = len(full_content)
        use_partial = False
        max_tags = 500
    else:
        if topic_start < topic_end:
            start_pos = max(0, topic_start - context_size)
            end_pos = min(len(full_content), topic_end + context_size)
        else:
            target = (topic_start + topic_end) // 2 if topic_start < topic_end else len(full_content) // 2
            start_pos = max(0, target - context_size)
            end_pos = min(len(full_content), target + context_size)
        use_partial = True
    search_content = full_content[start_pos:end_pos]
    offset = start_pos
    exact_intervals = []
    partial_intervals = []
    search_lower = search_content.lower()
    for word in highlight_words:
        if not word or len(word) < 2:
            continue
        word_lower = word.lower()
        pos = search_lower.find(word_lower)
        while pos != -1:
            exact_intervals.append((pos + offset, pos + offset + len(word)))
            pos = search_lower.find(word_lower, pos + 1)
    if use_partial and highlight_fragments and len(exact_intervals) < 50:
        for frag in highlight_fragments:
            if not frag or len(frag) < 2:
                continue
            frag_lower = frag.lower()
            pos = search_lower.find(frag_lower)
            while pos != -1:
                start = pos + offset
                end = start + len(frag)
                is_exact = any(s <= start and e >= end for s, e in exact_intervals)
                if not is_exact:
                    partial_intervals.append((start, end))
                pos = search_lower.find(frag_lower, pos + 1)
    intervals = [(*s, "highlight") for s in exact_intervals] + [(*s, "partial") for s in partial_intervals]
    total_intervals = len(intervals)
    if not intervals:
        return [], total_intervals
    intervals.sort(key=lambda x: (x[0], x[1]))
    merged = []
    for start, end, tag in intervals:
        if not merged:
            merged.append([start, end, tag])
        else:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
                if tag == "highlight":
                    merged[-1][2] = "highlight"
            else:
                merged.append([start, end, tag])
    if len(merged) > max_tags:
        merged = merged[:max_tags]
    return merged, total_intervals


def compute_display_window(content: str, target_char_pos: int, topic_start_pos: int, topic_end_pos: int,
                           max_display_chars: int) -> tuple:
    """Какую часть файла показать в окне просмотра. Возвращает (display_content, display_topic_start,
       display_topic_end) — показываемый текст и границы топика в его координатах.

       Файл не больше max_display_chars (или предел 0 — "без ограничения") показывается целиком. Иначе
       показывается окно в max_display_chars символов, центрированное на начале топика (у начала и конца
       файла окно прижимается к краю).

       Позиция 0 — это тоже позиция: топик в самом начале файла (и "позиция неизвестна" — тогда
       determine_position возвращает область первых символов) показывается с НАЧАЛА файла. Середина файла
       берётся, только когда топика нет вовсе (пустая область): раньше условие было просто
       "target_char_pos > 0", и клик по первому блоку большого файла открывал его середину."""
    if max_display_chars > 0 and len(content) > max_display_chars:
        if target_char_pos > 0 or topic_end_pos > topic_start_pos:
            center = target_char_pos
        else:
            center = len(content) // 2
        half = max_display_chars // 2
        start_display = max(0, center - half)
        end_display = min(len(content), start_display + max_display_chars)
        if end_display - start_display < max_display_chars:
            start_display = max(0, end_display - max_display_chars)
        display_content = content[start_display:end_display]
        display_topic_start = max(0, topic_start_pos - start_display)
        display_topic_end = min(len(display_content), topic_end_pos - start_display)
        return display_content, display_topic_start, display_topic_end
    return content, topic_start_pos, topic_end_pos


def locate_in_text(text: str, pos: int) -> tuple:
    """Номер строки (с 1) и столбец (с 0) для позиции pos в тексте. Позиция за концом текста — начало (1, 0)."""
    if pos < len(text):
        line_num = text[:pos].count('\n') + 1
        line_start = text[:pos].rfind('\n') + 1
        return line_num, max(0, pos - line_start)
    return 1, 0

