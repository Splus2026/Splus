import re
import tkinter as tk
from bisect import bisect_right
from config import resource_path
from utils.highlighting import get_intervals, build_brief_view, build_brief_view_mapped
from services import marks as marks_lib


# Пунктирная линия между блоками в режиме просмотра одного файла ("**").
BLOCK_SEPARATOR = "-" * 70


class ResultsRenderer:
    """Отвечает за прямую отрисовку в result_text: страницу результатов
       поиска, текст справки, содержимое открытого файла-источника, подсветку
       и прокрутку к топику.

       Выделен из services/search_controller.py, чтобы отделить "что искать,
       фильтровать и на какой странице показывать" (SearchController) от
       "как именно это отрисовать в Tkinter-виджете" (этот класс). Сам класс
       не хранит поисковое состояние — всё нужное ему передаётся параметрами
       при каждом вызове; единственное, что он хранит сам — это ссылку на
       виджет и текущий размер шрифта (нужен для текста справки)."""

    def __init__(self, result_text, label_widget=None):
        self.result_text = result_text
        self.font_size = 12
        # Метка "имя-алиас" файла-источника над окном — используется только
        # в режиме разделения на два Excel-файла (см. set_pane_label).
        self.label_widget = label_widget
        # Подчёркивание ("Ч", см. services/marks.py). marks_store задаёт главное
        # окно и только для основной панели; regions — блоки текста, которые
        # сейчас на экране и в которых можно подчёркивать (пусто — справка,
        # ошибка, режим разделения на два Excel-файла).
        self.marks_store = None
        self.regions = []
        self.result_text.tag_config("user_mark", underline=True)
        self.result_text.tag_config("block_separator", foreground="#8a8a8a")
        # Слои поверх подчёркнутого (как в Синеве Mobile): крупный шрифт, цвет и свои мысли.
        self.font_step = 2          # на сколько пунктов «крупный» шрифт больше обычного
        self.marks_only = False     # режим «только отмеченное» (подчёркнутое, выделенное, мысли): правка слоёв выключена
        self.note_click = None      # callback(note_id): клик по тексту мысли
        self._replay = None         # как заново нарисовать то, что на экране (после добавления/правки мысли)
        self._note_spans = []       # [(регион, начало, конец, id_мысли)] — где на экране мысли

    STYLE_COLOR = '#8a00a6'
    NOTE_COLOR = '#1a6a3a'

    def _config_layer_tags(self):
        """Теги слоёв. Шрифт задаётся полностью (Tk не умеет «на 2 пункта больше»), поэтому вызывается заново
           при каждой расстановке слоёв — размер шрифта окна мог измениться кнопками «+»/«−»."""
        try:
            size = int(self.font_size)
            self.result_text.tag_config("user_big", font=('Consolas', size + int(self.font_step)))
            self.result_text.tag_config("user_color", foreground=self.STYLE_COLOR)
            self.result_text.tag_config("user_note", font=('Consolas', size, 'italic'), foreground=self.NOTE_COLOR)
            self.result_text.tag_bind("user_note", "<Enter>", lambda e: self.result_text.config(cursor="hand2"))
            self.result_text.tag_bind("user_note", "<Leave>", lambda e: self.result_text.config(cursor=""))
            self.result_text.tag_bind("user_note", "<Button-1>", self._on_note_click)
        except Exception:
            pass   # оформление слоёв не должно ломать показ результатов

    def _on_note_click(self, event):
        if self.note_click is None:
            return
        try:
            index = self.result_text.index(f"@{event.x},{event.y}")
        except Exception:
            return
        nid = self.note_at(index)
        if nid is not None:
            self.note_click(nid)

    def note_at(self, index):
        """Номер мысли, текст которой лежит в позиции index окна, либо None."""
        for region, start, end, nid in self._note_spans:
            try:
                a = self._offset_to_index(region, start)
                b = self._offset_to_index(region, end)
            except Exception:
                continue
            if self._parse_index(a) <= self._parse_index(index) < self._parse_index(b):
                return nid
        return None

    def replay(self):
        """Перерисовывает то, что сейчас на экране (после добавления, правки или удаления мысли),
           сохраняя положение прокрутки. False — перерисовывать нечего (справка, просмотр файла, разделение)."""
        if self._replay is None:
            return False
        try:
            pos = self.result_text.yview()[0]
        except Exception:
            pos = None
        self._replay()
        if pos is not None:
            try:
                self.result_text.yview_moveto(pos)
            except Exception:
                pass
        return True

    def _marks_text(self, content, file_name):
        """Режим «только отмеченное»: подчёркнутые места, места с крупным шрифтом/цветом и слова с мыслями,
           склеенные « … ». -> (текст, карта кусков)."""
        store = self.marks_store
        key = marks_lib.file_key(file_name)
        spans = []
        try:
            for records in (store.marks_for_file(key), store.styles_for_file(key), store.notes_for_file(key)):
                spans += [(a, b) for _m, a, b in marks_lib.find_mark_spans(content, records)]
        except Exception as e:
            print(f"⚠️ Не удалось собрать отмеченные места: {e}")
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        if not merged:
            return '(отметок нет)', []
        text, segments = '', []
        for i, (a, b) in enumerate(merged):
            if i:
                text += ' … '
            segments.append((len(text), a, b - a))
            text += content[a:b]
        return text, segments

    def _build_view(self, content, exact_words, partial_fragments, brief_mode, file_name, with_notes=True):
        """(текст на экране, интервалы подсветки, карта кусков, места мыслей [(начало, конец, id)]) одного блока:
           полный, краткий или «только отмеченное»; мысли встроены в текст курсивом в скобках."""
        if self.marks_only and self.marks_store is not None and file_name:
            display, segments = self._marks_text(content, file_name)
            intervals = get_intervals(display, exact_words, partial_fragments)
        elif brief_mode:
            display, intervals, segments = build_brief_view_mapped(content, exact_words, partial_fragments)
        else:
            display = content
            intervals = get_intervals(content, exact_words, partial_fragments)
            segments = [(0, 0, len(content))]
        notes = []
        if with_notes and self.marks_store is not None and file_name and segments:
            try:
                found = marks_lib.find_mark_spans(content, self.marks_store.notes_for_file(marks_lib.file_key(file_name)))
                for nt, cs, ce in found:
                    shown = marks_lib.content_span_to_display(segments, cs, ce)
                    if shown:
                        notes.append((shown[-1][1], nt.text or '', nt.id))
            except Exception as e:
                print(f"⚠️ Не удалось показать мысли: {e}")
        spans = []
        if notes:
            notes.sort(key=lambda n: n[0])
            display, intervals, segments, ranges = marks_lib.embed_notes(
                display, intervals, segments, [(p, t) for p, t, _i in notes])
            spans = [(a, b, n[2]) for (a, b), n in zip(ranges, notes)]
        return display, intervals, segments, spans

    def set_pane_label(self, text: str):
        if self.label_widget:
            self.label_widget.config(text=text)

    # ---------- Текст справки ----------
    def render_help_text(self):
        """Показывает содержимое readme.txt как текст справки — когда нет
           результатов поиска, запрос слишком короткий, или это первый показ
           окна. Раньше эта логика была продублирована в app_window.py и
           search_controller.py — теперь единая реализация."""
        self.result_text.config(state='normal')
        self.result_text.update_idletasks()
        self.result_text.delete(1.0, tk.END)
        self.regions = []
        self._replay = None
        help_file = resource_path("readme.txt")
        try:
            with open(help_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            content = "Файл справки (readme.txt) не найден."
        except Exception as e:
            content = f"Ошибка чтения файла справки: {e}"
        self.result_text.insert(tk.END, content, ("help_text",))
        self.result_text.tag_config("help_text", justify='left', font=('Arial', self.font_size), foreground='#1a4a7a')
        self.result_text.config(state='normal')

    # ---------- Страница результатов поиска ----------
    def render_results_page(self, topics, page_num, total_count,
                            exact_words, partial_fragments, brief_mode):
        """topics — список словарей {'global_idx', 'rowid', 'header', 'content'},
           уже полностью подготовленных вызывающим кодом (имя файла/алиас,
           уровень совпадения и т.п. — это его забота, не отрисовщика).
           Рисует шапку страницы, затем для каждого топика — его
           заголовок-гиперссылку (тег block_{global_idx}_{rowid}) и текст с
           подсветкой (полный или "краткий", если brief_mode=True)."""
        self._replay = lambda: self.render_results_page(topics, page_num, total_count, exact_words,
                                                        partial_fragments, brief_mode)
        self.result_text.config(state='normal')
        self.result_text.update_idletasks()
        self.result_text.delete(1.0, tk.END)
        self.regions = []

        header_text = f"=== Результаты поиска (страница {page_num + 1}, всего {total_count}) ===\n\n"
        self.result_text.insert(tk.END, header_text)

        for item in topics:
            if not item.get('skip_header'):
                tag_name = f"block_{item['global_idx']}_{item['rowid']}"
                self.result_text.insert(tk.END, item['header'], ("hyperlink", tag_name))
                self.result_text.insert(tk.END, "\n")

            content = item['content']
            display_content, intervals, segments, note_spans = self._build_view(
                content, exact_words, partial_fragments, brief_mode, item.get('file_name'))

            region_start = self.result_text.index('end-1c')
            self._insert_highlighted_text(display_content, intervals)
            region_end = self.result_text.index('end-1c')
            if item.get('file_name') and display_content:
                self.regions.append({
                    'start': region_start, 'end': region_end, 'display': display_content,
                    'content': content, 'segments': segments, 'file_name': item['file_name'],
                    'note_spans': note_spans,
                })
            self.result_text.insert(tk.END, "\n\n")

        self.result_text.config(state='normal')
        self.apply_marks()

    def render_blocks_page(self, topics, separator=BLOCK_SEPARATOR):
        """Режим просмотра одного файла ("**", см. SearchController.
           _do_single_file_browse): просто блоки (topics — словари с 'content' и
           'file_name') подряд, между соседними — пунктирная линия, без шапок и
           без заголовка страницы. Блоки регистрируются как места для
           подчёркивания ("Ч") точно так же, как в обычных результатах поиска.
           Линия — не часть блока: подчёркнуть её нельзя."""
        self._replay = lambda: self.render_blocks_page(topics, separator)
        self.result_text.config(state='normal')
        self.result_text.update_idletasks()
        self.result_text.delete(1.0, tk.END)
        self.regions = []
        for number, item in enumerate(topics):
            if number:
                self.result_text.insert(tk.END, "\n")
                self.result_text.insert(tk.END, separator, "block_separator")
                self.result_text.insert(tk.END, "\n")
            content = item['content']
            display_content, intervals, segments, note_spans = self._build_view(
                content, [], [], False, item.get('file_name'))
            region_start = self.result_text.index('end-1c')
            self.result_text.insert(tk.END, display_content)
            region_end = self.result_text.index('end-1c')
            if item.get('file_name') and content:
                self.regions.append({
                    'start': region_start, 'end': region_end, 'display': display_content,
                    'content': content, 'segments': segments,
                    'file_name': item['file_name'], 'note_spans': note_spans,
                })
        self.result_text.config(state='normal')
        self.apply_marks()

    def render_results_page_compact(self, topics, exact_words, partial_fragments, brief_mode):
        """Компактная отрисовка — для режима разделения окна результатов на
           два файла: без шапок топиков, без итоговой строки "Результаты
           поиска" и без пустых строк между найденными строками — каждая
           сразу за предыдущей, как строки исходной таблицы."""
        self.result_text.config(state='normal')
        self.result_text.update_idletasks()
        self.result_text.delete(1.0, tk.END)
        self.regions = []  # режим разделения: подчёркивание здесь не поддерживается
        self._replay = None

        for item in topics:
            content = item['content']
            if brief_mode:
                display_content, intervals = build_brief_view(content, exact_words, partial_fragments)
            else:
                display_content = content
                intervals = get_intervals(content, exact_words, partial_fragments)

            self._insert_highlighted_text(display_content, intervals)
            self.result_text.insert(tk.END, "\n")

        self.result_text.config(state='normal')

    def _insert_highlighted_text(self, text, intervals):
        if intervals:
            last = 0
            for start_pos, end_pos, prio in intervals:
                if start_pos > last:
                    self.result_text.insert(tk.END, text[last:start_pos])
                tag = "highlight" if prio == 2 else "partial"
                self.result_text.insert(tk.END, text[start_pos:end_pos], tag)
                last = end_pos
            if last < len(text):
                self.result_text.insert(tk.END, text[last:])
        else:
            self.result_text.insert(tk.END, text)

    # ---------- Прокрутка к топику при возврате из файла-источника ----------
    def scroll_to_topic(self, rowid, global_idx=None):
        """Прокручивает список результатов к топику, из которого был выполнен
           переход на файл-источник, и на мгновение подсвечивает его заголовок.
           При поиске сразу по нескольким индексам rowid не гарантированно уникален
           (у каждого индекса своя нумерация), поэтому в первую очередь ищем точный
           тег block_{global_idx}_{rowid} — он однозначно указывает на нужный топик."""
        target_tag = None
        if global_idx is not None:
            candidate_tag = f"block_{global_idx}_{rowid}"
            if self.result_text.tag_ranges(candidate_tag):
                target_tag = candidate_tag
        if not target_tag:
            # Резервный вариант (например, если тег с точной позицией не найден) —
            # ищем первый топик с совпадающим rowid.
            for tag in self.result_text.tag_names():
                if tag.startswith('block_'):
                    parts = tag.split('_')
                    if len(parts) == 3 and parts[2] == str(rowid):
                        target_tag = tag
                        break
        if not target_tag:
            return
        ranges = self.result_text.tag_ranges(target_tag)
        if not ranges:
            return
        start_index = ranges[0]
        self.result_text.config(state='normal')
        self.result_text.yview(start_index)
        self.result_text.mark_set("insert", start_index)

        # Кратковременная подсветка заголовка топика, чтобы было видно, куда вернулись
        self.result_text.tag_configure("return_marker", background="#CFE8FF")
        self.result_text.tag_add("return_marker", ranges[0], ranges[1])

        def _clear_marker():
            try:
                self.result_text.tag_remove("return_marker", "1.0", tk.END)
            except tk.TclError:
                pass
        self.result_text.after(1200, _clear_marker)

    # ---------- Просмотр файла-источника по гиперссылке ----------
    def render_file_content(self, display_content, back_callback, file_name=None):
        """Отображает содержимое файла-источника со ссылкой "◀ Назад к
           результатам" наверху (клик по ней вызывает back_callback).
           Возвращает global_offset — длину этой шапки в символах, нужную
           вызывающему коду, чтобы пересчитать позиции подсветки."""
        self.result_text.config(state='normal')
        self.result_text.delete(1.0, tk.END)
        self.result_text.update_idletasks()
        self.regions = []
        self._replay = None
        header = "◀ Назад к результатам\n\n"
        self.result_text.insert(tk.END, header)
        self.result_text.tag_config("hyperlink_back", foreground="blue", underline=True)
        self.result_text.tag_bind("hyperlink_back", "<Enter>", lambda e: self.result_text.config(cursor="hand2"))
        self.result_text.tag_bind("hyperlink_back", "<Leave>", lambda e: self.result_text.config(cursor=""))
        self.result_text.tag_bind("hyperlink_back", "<Button-1>", back_callback)
        self.result_text.tag_add("hyperlink_back", "1.0", "1.end")
        region_start = self.result_text.index('end-1c')
        self.result_text.insert(tk.END, display_content)
        if file_name and display_content:
            # Весь показанный файл (или его окно) — один блок для подчёркивания.
            self.regions.append({
                'start': region_start, 'end': self.result_text.index('end-1c'),
                'display': display_content, 'content': display_content,
                'segments': [(0, 0, len(display_content))], 'file_name': file_name,
            })
        self.result_text.update_idletasks()
        self.apply_marks()
        return len(header)

    def scroll_to_file_position(self, display_line_num, display_char_pos):
        scroll_line_num = display_line_num + 2
        scroll_index = f"{scroll_line_num}.{display_char_pos}"
        self.result_text.yview(scroll_index)
        self.result_text.mark_set("insert", scroll_index)
        self.result_text.focus_set()

    def apply_highlights(self, merged_intervals, global_offset):
        """Применяет уже вычисленные (см. utils.highlighting.
           compute_file_highlight_intervals) интервалы подсветки к тексту
           файла-источника, смещённые на global_offset (длину шапки "Назад к
           результатам"). Возвращает число успешно применённых тегов."""
        self.result_text.config(state='normal')
        self.result_text.update_idletasks()
        applied = 0
        for start, end, tag in merged_intervals:
            start_idx = f"1.0+{global_offset + start}c"
            end_idx = f"1.0+{global_offset + end}c"
            try:
                self.result_text.tag_add(tag, start_idx, end_idx)
                applied += 1
            except Exception:
                pass
        self.result_text.config(state='normal')
        return applied

    def render_error(self, message):
        self.regions = []
        self._replay = None
        self.result_text.config(state='normal')
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, message)

    # ---------- Подчёркивание (см. services/marks.py) ----------
    @staticmethod
    def _parse_index(index):
        line, col = str(index).split('.')
        return int(line), int(col)

    def _line_starts(self, region):
        """Смещения начал строк текста блока (для перевода смещение <-> индекс Tk)."""
        starts = region.get('line_starts')
        if starts is None:
            starts = [0] + [m.end() for m in re.finditer('\n', region['display'])]
            region['line_starts'] = starts
        return starts

    def _index_to_offset(self, region, index):
        line, col = self._parse_index(index)
        line0, col0 = self._parse_index(region['start'])
        starts = self._line_starts(region)
        rel = line - line0
        if rel < 0:
            return 0
        if rel >= len(starts):
            return len(region['display'])
        offset = starts[rel] + (col - col0 if rel == 0 else col)
        return max(0, min(offset, len(region['display'])))

    def _offset_to_index(self, region, offset):
        starts = self._line_starts(region)
        rel = bisect_right(starts, offset) - 1
        line0, col0 = self._parse_index(region['start'])
        col = offset - starts[rel]
        return f"{line0 + rel}.{col + (col0 if rel == 0 else 0)}"

    LAYER_TAGS = ("user_mark", "user_big", "user_color", "user_note")

    def apply_marks(self):
        """Заново расставляет подчёркивание, крупный шрифт, цвет и мысли на всём, что сейчас на экране.
           Вызывается после каждой отрисовки и после каждого действия с отметками. Сбой хранилища (нет
           доступа к marks.db) не должен ломать показ результатов — слоёв просто не будет."""
        for tag in self.LAYER_TAGS:
            self.result_text.tag_remove(tag, "1.0", "end")
        self._note_spans = []
        store = self.marks_store
        if store is None or not self.regions:
            return
        self._config_layer_tags()   # не в __init__: теги нужны, только когда есть что отмечать
        try:
            for region in self.regions:
                key = marks_lib.file_key(region['file_name'])
                layers = (("user_mark", store.marks_for_file(key)),
                          ("user_big", store.styles_for_file(key, 'big')),
                          ("user_color", store.styles_for_file(key, 'color')))
                for tag, records in layers:
                    if not records:
                        continue
                    for _rec, c_start, c_end in marks_lib.find_mark_spans(region['content'], records):
                        for d_start, d_end in marks_lib.content_span_to_display(region['segments'], c_start, c_end):
                            self.result_text.tag_add(tag, self._offset_to_index(region, d_start),
                                                     self._offset_to_index(region, d_end))
                for start, end, nid in region.get('note_spans', ()):
                    self.result_text.tag_add("user_note", self._offset_to_index(region, start),
                                             self._offset_to_index(region, end))
                    self._note_spans.append((region, start, end, nid))
        except Exception as e:
            print(f"⚠️ Не удалось показать подчёркивания: {e}")

    def _selection_pieces(self):
        """Выделение, разложенное по блокам: (статус, [(блок, начало, конец в тексте блока)]).
           Статус 'ok' либо 'unavailable' | 'no_selection' | 'unsupported' | 'outside'."""
        if self.marks_store is None:
            return 'unavailable', []
        ranges = self.result_text.tag_ranges("sel")
        if not ranges:
            return 'no_selection', []
        if not self.regions:
            return 'unsupported', []
        sel_start, sel_end = self._parse_index(ranges[0]), self._parse_index(ranges[1])
        pieces, touched = [], False
        for region in self.regions:
            a = max(sel_start, self._parse_index(region['start']))
            b = min(sel_end, self._parse_index(region['end']))
            if not a < b:
                continue
            touched = True
            d_start = self._index_to_offset(region, f"{a[0]}.{a[1]}")
            d_end = self._index_to_offset(region, f"{b[0]}.{b[1]}")
            for c_start, c_end in marks_lib.display_span_to_content(region['segments'], d_start, d_end):
                pieces.append((region, c_start, c_end))
        return ('ok' if touched else 'outside'), pieces

    def toggle_underline(self):
        """Кнопка "Ч", как подчёркивание в Word: если всё выделенное уже
           подчёркнуто — подчёркивание снимается, иначе выделенное подчёркивается.
           Возвращает (статус, число_отрезков): 'added' | 'removed' |
           'no_selection' | 'outside' (выделены одни шапки/пустота между
           блоками) | 'empty' (одни пробелы) | 'unsupported' | 'unavailable' |
           'marks_only' (в режиме «только отмеченное» отметки не правятся).
           Ошибки хранилища (marks.db недоступен) пробрасываются вызывающему."""
        status, pieces = self._selection_pieces()
        if status != 'ok':
            return status, 0
        if self.marks_only:
            return 'marks_only', 0
        store = self.marks_store
        analyses = []  # (блок, (start, end, пересекающиеся_отметки, целиком_подчёркнут))
        located_cache = {}
        for region, c_start, c_end in pieces:
            if id(region) not in located_cache:
                marks = store.marks_for_file(marks_lib.file_key(region['file_name']))
                located_cache[id(region)] = marks_lib.find_mark_spans(region['content'], marks) if marks else []
            analysis = marks_lib.analyze_span(region['content'], located_cache[id(region)], c_start, c_end)
            if analysis:
                analyses.append((region, analysis))
        if not analyses:
            return 'empty', 0

        # Как в Word: подчёркивание снимается, только если подчёркнуто ВСЁ выделенное.
        remove_mode = all(fully for _region, (_s, _e, _ov, fully) in analyses)
        delete_ids, additions = set(), []
        for region, (cs, ce, overlapping, _fully) in analyses:
            if remove_mode:
                ids, spans = marks_lib.plan_remove(region['content'], cs, ce, overlapping)
            else:
                ids, spans = marks_lib.plan_add(cs, ce, overlapping)
            delete_ids.update(ids)
            for span in spans:
                if (id(region), span) not in [(id(r), s) for r, s in additions]:
                    additions.append((region, span))
        store.delete_marks(sorted(delete_ids))
        for region, (start, end) in additions:
            fields = marks_lib.span_fields(region['content'], start, end)
            if fields:
                store.add_mark(region['file_name'], *fields)
        if remove_mode:   # крупный шрифт и цвет живут только внутри подчёркнутого
            for region, (cs, ce, _ov, _fully) in analyses:
                self._subtract_styles(region, cs, ce)
        self.apply_marks()
        return ('removed' if remove_mode else 'added'), len(analyses)

    def _subtract_styles(self, region, cs, ce):
        store, content, file_name = self.marks_store, region['content'], region['file_name']
        key = marks_lib.file_key(file_name)
        for kind in marks_lib.STYLE_KINDS:
            located = marks_lib.find_mark_spans(content, store.styles_for_file(key, kind))
            info = marks_lib.analyze_span(content, located, cs, ce)
            if info is None or not info[2]:
                continue
            delete_ids, keep = marks_lib.plan_remove(content, info[0], info[1], info[2])
            store.delete_styles(delete_ids)
            for a, b in keep:
                fields = marks_lib.span_fields(content, a, b)
                if fields:
                    store.add_style(file_name, kind, *fields)

    def style_selection(self, kind):
        """Кнопки «A+» (kind='big', крупный шрифт) и «Цвет» (kind='color'): оформляется выделенное, которое целиком
           подчёркнуто; повторное нажатие снимает оформление. Статусы: 'on' | 'off' | 'need_mark' (выделено не
           внутри подчёркнутого) | 'empty' | а также 'no_selection' | 'outside' | 'unsupported' | 'unavailable' |
           'marks_only'."""
        status, pieces = self._selection_pieces()
        if status != 'ok':
            return status
        if self.marks_only:
            return 'marks_only'
        store = self.marks_store
        todo = []        # (блок, начало, конец) — то, что оформляем
        for region, c_start, c_end in pieces:
            key = marks_lib.file_key(region['file_name'])
            located = marks_lib.find_mark_spans(region['content'], store.marks_for_file(key))
            info = marks_lib.analyze_span(region['content'], located, c_start, c_end)
            if info is None:
                continue
            if not info[3]:
                return 'need_mark'
            todo.append((region, info[0], info[1]))
        if not todo:
            return 'empty'

        def analyze(region, cs, ce):
            key = marks_lib.file_key(region['file_name'])
            located = marks_lib.find_mark_spans(region['content'], store.styles_for_file(key, kind))
            return marks_lib.analyze_span(region['content'], located, cs, ce)

        remove_mode = all((analyze(r, a, b) or (0, 0, 0, False))[3] for r, a, b in todo)
        for region, cs, ce in todo:
            content, file_name = region['content'], region['file_name']
            info = analyze(region, cs, ce)
            if info is None:
                continue
            if remove_mode:
                delete_ids, new = marks_lib.plan_remove(content, info[0], info[1], info[2])
            elif info[3]:
                continue
            else:
                delete_ids, new = marks_lib.plan_add(info[0], info[1], info[2])
            store.delete_styles(delete_ids)
            for a, b in new:
                fields = marks_lib.span_fields(content, a, b)
                if fields:
                    store.add_style(file_name, kind, *fields)
        self.apply_marks()
        return 'off' if remove_mode else 'on'

    # ---------- свои мысли ----------
    def selection_note(self):
        """Мысль под выделением (или под курсором-кликом по её тексту): (статус, id_мысли_или_None).
           Статус 'ok' | 'no_selection' | 'outside' | 'unsupported' | 'unavailable' | 'marks_only'."""
        if self.marks_store is None:
            return 'unavailable', None
        if self.marks_only:
            return 'marks_only', None
        status, pieces = self._selection_pieces()
        if status != 'ok':
            return status, None
        pieces = [p for p in pieces if marks_lib.trim_span(p[0]['content'], p[1], p[2])[0]
                  < marks_lib.trim_span(p[0]['content'], p[1], p[2])[1]]
        if not pieces:
            return 'outside', None
        region, cs, ce = pieces[-1]
        fields = marks_lib.span_fields(region['content'], cs, ce)
        key = marks_lib.file_key(region['file_name'])
        for nt in self.marks_store.notes_for_file(key):
            if fields and (nt.fragment, nt.before, nt.after) == fields:
                return 'ok', nt.id
        return 'ok', None

    def add_note(self, text, note_id=None):
        """Мысль к выделенному фрагменту (показывается курсивом в скобках сразу за ним). Если такая мысль уже есть —
           её текст заменяется. Возвращает статус ('added' | 'updated' | 'empty' | как у selection_note)."""
        text = (text or '').strip()
        status, existing = self.selection_note()
        if status != 'ok':
            return status
        if not text:
            return 'empty'
        _st, pieces = self._selection_pieces()
        region, cs, ce = [p for p in pieces if marks_lib.trim_span(p[0]['content'], p[1], p[2])[0]
                          < marks_lib.trim_span(p[0]['content'], p[1], p[2])[1]][-1]
        if existing is not None:
            self.marks_store.update_note(existing, text=text)
            result = 'updated'
        else:
            fields = marks_lib.span_fields(region['content'], cs, ce)
            self.marks_store.add_note(region['file_name'], fields[0], fields[1], fields[2], text)
            result = 'added'
        if not self.replay():
            self.apply_marks()
        return result

    def edit_note(self, nid, text):
        """Правка текста мысли (пустой текст — удаление)."""
        text = (text or '').strip()
        if text:
            self.marks_store.update_note(nid, text=text)
        else:
            self.marks_store.delete_note(nid)
        if not self.replay():
            self.apply_marks()

    def delete_note(self, nid):
        self.marks_store.delete_note(nid)
        if not self.replay():
            self.apply_marks()
