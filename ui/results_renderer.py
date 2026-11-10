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
            if brief_mode:
                display_content, intervals, segments = build_brief_view_mapped(
                    content, exact_words, partial_fragments)
            else:
                display_content = content
                intervals = get_intervals(content, exact_words, partial_fragments)
                segments = [(0, 0, len(content))]

            region_start = self.result_text.index('end-1c')
            self._insert_highlighted_text(display_content, intervals)
            region_end = self.result_text.index('end-1c')
            if item.get('file_name') and display_content:
                self.regions.append({
                    'start': region_start, 'end': region_end, 'display': display_content,
                    'content': content, 'segments': segments, 'file_name': item['file_name'],
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
            region_start = self.result_text.index('end-1c')
            self.result_text.insert(tk.END, content)
            region_end = self.result_text.index('end-1c')
            if item.get('file_name') and content:
                self.regions.append({
                    'start': region_start, 'end': region_end, 'display': content,
                    'content': content, 'segments': [(0, 0, len(content))],
                    'file_name': item['file_name'],
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

    def apply_marks(self):
        """Заново расставляет подчёркивание на всём, что сейчас на экране.
           Вызывается после каждой отрисовки и после "Ч". Сбой хранилища (нет
           доступа к marks.db) не должен ломать показ результатов — подчёркивания
           просто не будет."""
        self.result_text.tag_remove("user_mark", "1.0", "end")
        store = self.marks_store
        if store is None or not self.regions:
            return
        try:
            for region in self.regions:
                marks = store.marks_for_file(marks_lib.file_key(region['file_name']))
                if not marks:
                    continue
                for _mark, c_start, c_end in marks_lib.find_mark_spans(region['content'], marks):
                    for d_start, d_end in marks_lib.content_span_to_display(region['segments'], c_start, c_end):
                        self.result_text.tag_add("user_mark", self._offset_to_index(region, d_start),
                                                 self._offset_to_index(region, d_end))
        except Exception as e:
            print(f"⚠️ Не удалось показать подчёркивания: {e}")

    def toggle_underline(self):
        """Кнопка "Ч", как подчёркивание в Word: если всё выделенное уже
           подчёркнуто — подчёркивание снимается, иначе выделенное подчёркивается.
           Возвращает (статус, число_отрезков): 'added' | 'removed' |
           'no_selection' | 'outside' (выделены одни шапки/пустота между
           блоками) | 'empty' (одни пробелы) | 'unsupported' | 'unavailable'.
           Ошибки хранилища (marks.db недоступен) пробрасываются вызывающему."""
        store = self.marks_store
        if store is None:
            return 'unavailable', 0
        ranges = self.result_text.tag_ranges("sel")
        if not ranges:
            return 'no_selection', 0
        if not self.regions:
            return 'unsupported', 0
        sel_start, sel_end = self._parse_index(ranges[0]), self._parse_index(ranges[1])

        touched = False
        analyses = []  # (блок, (start, end, пересекающиеся_отметки, целиком_подчёркнут))
        for region in self.regions:
            a = max(sel_start, self._parse_index(region['start']))
            b = min(sel_end, self._parse_index(region['end']))
            if not a < b:
                continue
            touched = True
            d_start = self._index_to_offset(region, f"{a[0]}.{a[1]}")
            d_end = self._index_to_offset(region, f"{b[0]}.{b[1]}")
            marks = store.marks_for_file(marks_lib.file_key(region['file_name']))
            located = marks_lib.find_mark_spans(region['content'], marks) if marks else []
            for c_start, c_end in marks_lib.display_span_to_content(region['segments'], d_start, d_end):
                analysis = marks_lib.analyze_span(region['content'], located, c_start, c_end)
                if analysis:
                    analyses.append((region, analysis))
        if not touched:
            return 'outside', 0
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
        self.apply_marks()
        return ('removed' if remove_mode else 'added'), len(analyses)
