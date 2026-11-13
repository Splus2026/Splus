import os
import time
import tkinter as tk
from services.dialogs import messagebox
from typing import List, Dict, Any, NamedTuple, Optional

from utils.query_parser import parse_query_words, get_fragments_with_levels
from utils.text_processing import read_text_file
from utils.highlighting import (
    get_intervals,
    build_brief_view,
    determine_position,
    compute_file_highlight_intervals,
    compute_display_window,
    locate_in_text,
)
from config import CONSPECT_FILE
from vector_engines import CHUNK_BASED_MODEL_TYPES
import stats_logger


class SearchPlan(NamedTuple):
    """Что и как искать — решение, принятое по отмеченным индексам (см. SearchController._plan_search).

       selected_ordered — отмеченные индексы в порядке отметки (для FTS5 пусто);
       indices_to_search — по каким индексам искать обычным поиском (None — движок сам знает);
       vector_key — отмеченная векторная модель (первая) или None;
       real_indices — обычные индексы, отмеченные вместе с моделью."""
    selected_ordered: list
    indices_to_search: Optional[list]
    vector_key: Optional[str]
    real_indices: list


class SearchController:
    """Управление поиском, фильтрацией и пагинацией результатов.

    Сама отрисовка в Tkinter-виджет result_text (страница результатов, текст
    справки, просмотр файла-источника, подсветка, прокрутка) вынесена в
    ui.results_renderer.ResultsRenderer — этот класс готовит данные для
    отображения (что искать, что отфильтровано, что показывать на текущей
    странице) и передаёт их отрисовщику, но сам напрямую с виджетом почти не
    работает."""

    def __init__(self, engine, config, result_text, word_panel, query_entry,
                 index_manager, file_manager, status_update_callback,
                 get_current_index_name_callback, config_dict, results_renderer,
                 results_renderer_2=None, word_panel_2=None,
                 split_view_enabled_callback=None, set_split_view_active_callback=None,
                 vector_model_manager=None, hide_vector_viz_callback=None,
                 variations_excluded_callback=None):
        self.engine = engine
        self.config = config
        self.result_text = result_text
        self.renderer = results_renderer
        self.word_panel = word_panel
        self.query_entry = query_entry
        self.index_manager = index_manager
        self.file_manager = file_manager
        self.update_status = status_update_callback
        self.get_current_index_name = get_current_index_name_callback
        self.config_dict = config_dict

        # Поиск по обученной векторной модели (кнопка "Векторы") — может
        # быть не задан (None), тогда векторный режим просто никогда не
        # активируется, остальной код работает как раньше.
        self.vector_model_manager = vector_model_manager
        # 2D-визуализация векторной близости (кнопка "3D/2D") временно
        # занимает среднее окно — перед показом ЛЮБЫХ обычных результатов
        # надо убедиться, что она не осталась висеть с прошлого раза.
        self.hide_vector_viz_callback = hide_vector_viz_callback
        # "−В/+В" (см. ui/app_window.py, toggle_word_variations) — состояние
        # хранится в AppWindow, а не тут, чтобы сохраняться при переходе на
        # новое слово запроса (не только для одного, текущего поиска).
        self.variations_excluded_callback = variations_excluded_callback

        # Режим разделения окна результатов на два файла (для Excel) — второй
        # рендерер/панель совпадений и функции определения/применения режима.
        # Всё это может быть не задано (None) — тогда режим разделения просто
        # никогда не активируется, остальной код работает как раньше.
        self.renderer_2 = results_renderer_2
        self.word_panel_2 = word_panel_2
        self.split_view_enabled_callback = split_view_enabled_callback
        self.set_split_view_active_callback = set_split_view_active_callback
        self.split_mode_active = False

        # Состояние поиска
        self.results_page = 0
        self.page_size = 20
        self.all_filtered_topics = []
        self.all_topic_words = {}
        self.word_counts = {}
        self.current_query_words_lower = []
        self.current_partial_fragments = []
        self.excluded_words = set()
        self._last_all_fragments_levels = []
        self._full_topic_data = []

        # Параллельное состояние для второго файла в режиме разделения —
        # используется только когда self.split_mode_active=True.
        self.all_filtered_topics_b = []
        self.word_counts_b = {}
        self._full_topic_data_b = []

        # Для просмотра файла в главном окне
        self.is_viewing_file = False
        self.saved_state = {}

        # Режим отображения топиков на текущей странице результатов:
        # False — полный текст, True — только предложения с подсветками
        # (переключатель "Кратко"/"Развёрнуто").
        self.brief_mode = False
        # Метка (имя + алиас) файла, который сейчас открыт по гиперссылке —
        # актуальна, когда is_viewing_file=True.
        self._current_view_file_label = ""

        # Режим просмотра одного файла ("**" в поле поиска, см.
        # _do_single_file_browse): имя отмеченного индекса, метка файла
        # (имя + алиас — нужна, чтобы дописывать источник к цитате в конспекте:
        # шапок-гиперссылок у блоков в этом режиме нет).
        self.browse_mode = False
        self.browse_index = None
        self.browse_file_label = None

        # Навигационные кнопки
        self.btn_first = None
        self.btn_back = None
        self.btn_forward = None
        self.btn_last = None

        # Отслеживание предыдущего запроса — чтобы отличить "продолжение
        # набора текущего слова" (тогда исключения слов из левой панели нужно
        # сохранить) от "начал вводить совсем другой запрос" (тогда старые
        # исключения нужно сбросить, иначе они незаметно "прилипают" к новым
        # не связанным запросам).
        self._last_query = ""

        # Статистика нажатий (передаётся из MainWindow)
        self._typing_stats_str = ""
        self._typing_total_ms = 0

    # ---------- Вспомогательные методы ----------
    def _get_file_display_name(self, file_name: str) -> str:
        if not file_name:
            return ""
        base_name = os.path.basename(file_name)
        if base_name in self.config_dict:
            display_name, _, _ = self.config_dict[base_name]
            return display_name
        return base_name

    def _format_file_label(self, file_name: str) -> str:
        """Возвращает "имя_файла (алиас)" (или просто "имя_файла", если алиас
           совпадает с именем файла или отсутствует) — то же представление,
           что показывается в шапках результатов, и которое используется при
           дозаписи источника цитаты в конспект."""
        if not file_name:
            return ""
        base_file = os.path.basename(file_name)
        display_name = self._get_file_display_name(file_name)
        if display_name and display_name != base_file:
            return f"{base_file} ({display_name})"
        return base_file

    def _format_index_file_label(self, index_name: str) -> str:
        """Возвращает "имя_файла (алиас)" для индекса Manticore по его имени
           (а не по имени файла топика) — нужно для подписи над каждой
           панелью в режиме разделения окна результатов, когда файл нужно
           показать даже если топиков пока нет (например, при 0 результатов)."""
        file_name = ''
        if index_name in self.index_manager.index_display_map:
            alias = self.index_manager.index_display_map[index_name]
            for config_file, (display_name, _, _) in self.config_dict.items():
                if display_name == alias:
                    file_name = config_file
                    break
        if not file_name:
            file_name = index_name
        return self._format_file_label(file_name)

    def toggle_brief_mode(self):
        """Переключает режим отображения топиков на текущей странице результатов
           между полным текстом и кратким (только предложения с подсветками)."""
        self.brief_mode = not self.brief_mode
        if not self.is_viewing_file:
            self._display_page()
        return self.brief_mode

    def toggle_marks_only(self):
        """Режим «только отмеченное»: вместо текста топиков — одни подчёркнутые места, места с крупным шрифтом
           и цветом и слова с мыслями (склеены « … »). Работает вместе с «Кратко»/«Всё» (отмеченное главнее)."""
        self.renderer.marks_only = not self.renderer.marks_only
        if not self.is_viewing_file:
            self._display_page()
        return self.renderer.marks_only

    # ---------- Режим просмотра одного файла ("**") ----------
    BROWSE_QUERY = '**'
    BROWSE_EXTENSIONS = ('.txt', '.docx')

    def exit_browse_mode(self):
        """Сбрасывает режим просмотра одного файла. Вызывается при любом другом
           запросе и при очистке окна результатов — иначе метка файла для
           конспекта "прилипла" бы к чужим результатам."""
        if self.browse_mode:
            # Блоки файла лежат в all_filtered_topics: оставить их — значит, дать
            # кнопкам листания показать их потом как ложные "результаты поиска"
            # (с шапками и уровнем 0). Обычные результаты поиска не трогаем.
            self.all_filtered_topics = []
            self.results_page = 0
        self.browse_mode = False
        self.browse_index = None
        self.browse_file_label = None

    def _browse_hint(self, message):
        """Условия режима не выполнены (или файл не прочитался): вместо блоков
           показываем пояснение, режим сброшен."""
        self.exit_browse_mode()
        self.all_filtered_topics = []
        self.all_filtered_topics_b = []
        self.results_page = 0
        self._full_topic_data = []
        self.word_panel.clear()
        self.renderer.render_error(message)
        self._update_nav_buttons()

    def _do_single_file_browse(self):
        """"**" в поле поиска: в окне результатов — просто блоки (топики) ОДНОГО
           отмеченного файла по порядку, друг от друга отделены пунктирной линией,
           без шапок и без поиска. Всё остальное в среднем окне работает как
           обычно: листание страниц, "Ч", "КП", сохранение выделенного в конспект
           правой кнопкой (источник — этот файл, см. browse_file_label).

           Условия: в окне индексов отмечен ровно один индекс, и это обычный
           индекс файла .txt или .docx (не векторная модель, не Excel); движок —
           Manticore (только у него есть get_all_sections). Иначе — пояснение.

           Функция идемпотентна: поле с "**" отрабатывает на каждое отпускание
           клавиши (Enter, Shift, стрелки — см. MainWindow._on_key_release), и
           повторный вызов для уже показанного файла ничего не делает — не
           перечитывает индекс и не возвращает на первую страницу."""
        hint_prefix = "Режим просмотра файла («**»): "
        selected = self.index_manager.get_selected_indices_ordered()
        if len(selected) != 1:
            self._browse_hint(hint_prefix + "отметьте в окне «Индексы» ровно один индекс файла .txt или .docx.")
            return
        index_name = selected[0]
        if self.vector_model_manager and self.vector_model_manager.is_vector_key(index_name):
            self._browse_hint(hint_prefix + "отмечена векторная модель, а нужен индекс файла .txt или .docx.")
            return
        if not hasattr(self.engine, 'get_all_sections'):
            self._browse_hint(hint_prefix + "поддерживается только движком Manticore.")
            return
        if self._is_excel_index(index_name):
            self._browse_hint(hint_prefix + "работает с файлами .txt и .docx, а отмечена таблица Excel.")
            return

        if self.browse_mode and self.browse_index == index_name and self.all_filtered_topics:
            return

        try:
            sections = self.engine.get_all_sections(index_name)
        except Exception as e:
            self._browse_hint(f"Не удалось прочитать индекс «{index_name}»: {e}")
            return
        topics = []
        file_name = ''
        for rowid, text, section_file in sections:
            if section_file and not file_name:
                file_name = section_file
            if text and text.strip():
                topics.append({'rowid': rowid, 'content': text, 'file_name': section_file or ''})
        topics.sort(key=lambda t: t['rowid'])  # get_all_sections и так по возрастанию — подстраховка
        if not topics:
            self._browse_hint("В выбранном индексе нет блоков.")
            return
        extension = os.path.splitext(file_name)[1].lower()
        if extension not in self.BROWSE_EXTENSIONS:
            self._browse_hint(hint_prefix + "работает с файлами .txt и .docx, а у выбранного индекса "
                              f"файл {extension or 'без расширения'}.")
            return
        for topic in topics:
            topic['file_name'] = topic['file_name'] or file_name

        # Окно "Совпадения", исключённые слова, подсветка и режим разделения
        # относятся к обычному поиску — здесь их нет.
        self.split_mode_active = False
        if self.set_split_view_active_callback:
            self.set_split_view_active_callback(False)
        self.word_panel.clear()
        self.excluded_words.clear()
        self.current_query_words_lower = []
        self.current_partial_fragments = []
        self._last_all_fragments_levels = []
        self._full_topic_data = []  # иначе refresh_display() подменил бы блоки старым поиском
        self.all_filtered_topics_b = []
        self.all_filtered_topics = topics
        self.results_page = 0
        self.is_viewing_file = False
        self.saved_state = {}
        self.browse_mode = True
        self.browse_index = index_name
        self.browse_file_label = self._format_file_label(file_name)
        self._display_page()

    def _split_panel_words(self, word_counts):
        """Делит слова панели "Совпадения" на точные слова запроса и остальные (для них — самая длинная
           подходящая часть запроса, по ней слово подсвечивается). Общий шаг для обеих панелей."""
        exact_words = set()
        prefix_dict = {}
        for word in word_counts:
            if any(word == w_lower for w_lower in self.current_query_words_lower):
                exact_words.add(word)
            else:
                best_pref = ''
                for frag, level, _ in self._last_all_fragments_levels:
                    if (frag.lower() in word.lower() or word.lower().startswith(frag.lower())) and len(frag) > len(best_pref):
                        best_pref = frag
                prefix_dict[word] = best_pref
        return exact_words, prefix_dict

    def _update_word_panel(self):
        if not getattr(self, 'word_counts', None):
            self.word_panel.clear()
            return
        exact_words, prefix_dict = self._split_panel_words(self.word_counts)
        # Сортировка по длине подсвеченной части и разбивка на полнотекстовые/
        # инфиксные совпадения теперь выполняется внутри WordPanel.update_words —
        # туда же передаём счётчики вхождений слов для отображения в скобках.
        self.word_panel.update_words(exact_words, prefix_dict, self.word_counts, 'blue')

    def _count_matched_words(self, results):
        """Сколько топиков содержит каждое совпавшее слово и какой лучший уровень совпадения у слова."""
        word_counts = {}
        all_topic_words = {}
        for item in results:
            meta = item.get('meta', {})
            matched_words = meta.get('matched_words', [])
            for w in matched_words:
                word_counts[w] = word_counts.get(w, 0) + 1
                level = meta.get('max_level', 0)
                if w not in all_topic_words or level > all_topic_words[w]:
                    all_topic_words[w] = level
        return word_counts, all_topic_words

    def _update_word_panel_from_results(self, results):
        self.word_counts, self.all_topic_words = self._count_matched_words(results)
        query = self.query_entry.get().strip()
        self._last_all_fragments_levels = []
        min_word_length = 2 if self.split_mode_active else 3
        for word, min_len, must_start in parse_query_words(query, min_word_length=min_word_length):
            for frag, level in get_fragments_with_levels(word, min_len):
                self._last_all_fragments_levels.append((frag, level, must_start))

    # ---------- Второй файл в режиме разделения окна результатов ----------
    def _update_word_panel_from_results_b(self, results):
        """Аналог _update_word_panel_from_results(), но для второго файла в
           режиме разделения. current_query_words_lower/_last_all_fragments_levels
           общие для обоих файлов (это один и тот же запрос), поэтому здесь
           пересчитывается только словарь счётчиков слов второго файла."""
        self.word_counts_b, _ = self._count_matched_words(results)

    def _update_word_panel_b(self):
        if not self.word_panel_2:
            return
        if not self.word_counts_b:
            self.word_panel_2.clear()
            return
        exact_words, prefix_dict = self._split_panel_words(self.word_counts_b)
        self.word_panel_2.update_words(exact_words, prefix_dict, self.word_counts_b, 'blue')

    def _log_display_time(self, phase_times: dict, total_ms: float, operation: str = "display_page"):
        """Логирует время выполнения этапов отображения."""
        # Вывод в консоль
        parts = []
        for name, val in phase_times.items():
            parts.append(f"{name}: {val:.1f} мс")
        details = ", ".join(parts)
        console_msg = f"⏱ {operation} занял {total_ms:.1f} мс ({details})"
        print(console_msg)
        self.update_status(console_msg)

        # Логирование в stats_logger
        if stats_logger.STATS_ENABLED:
            stats_logger.log_display_page(
                total_ms=total_ms,
                phase_times=phase_times,
                topic_count=len(self.all_filtered_topics)
            )

    def _apply_filter_and_display(self, results, search_time_ms=None) -> float:
        """Фильтрация по исключённым словам, сортировка и отображение страницы.
           Возвращает время отображения страницы в миллисекундах."""
        start_total = time.time()
        self.is_viewing_file = False
        self.saved_state = {}

        display_time = 0.0

        # Фильтрация
        t_filter = time.time()
        filtered_topics = self._filter_excluded(results)
        self.all_filtered_topics = filtered_topics
        self.results_page = 0
        t_filter = (time.time() - t_filter) * 1000

        # Обновление панели слов
        t_wordpanel = time.time()
        self._update_word_panel()
        t_wordpanel = (time.time() - t_wordpanel) * 1000

        if not filtered_topics:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            total_ms = (time.time() - start_total) * 1000
            self._log_display_time({
                'фильтрация': t_filter,
                'слов_панель': t_wordpanel,
                'отрисовка_справки': total_ms - t_filter - t_wordpanel
            }, total_ms, "apply_filter_and_display (пусто)")
            return 0.0

        # Сортировка
        t_sort = time.time()
        filtered_topics.sort(key=self._relevance_key, reverse=True)
        self.all_filtered_topics = filtered_topics
        t_sort = (time.time() - t_sort) * 1000

        # Отображение страницы (с замером внутри)
        display_time = self._display_page(search_time_ms, measure=True)

        total_ms = (time.time() - start_total) * 1000
        self._log_display_time({
            'фильтрация': t_filter,
            'слов_панель': t_wordpanel,
            'сортировка': t_sort,
            'отрисовка_страницы': display_time
        }, total_ms, "apply_filter_and_display")

        return display_time

    def _filter_excluded(self, results):
        """Топики, у которых осталось хотя бы одно НЕ исключённое слово: топик скрывается, только если
           исключены ВСЕ его совпавшие слова (у топика без совпавших слов такого слова нет — он тоже скрыт)."""
        excluded = self.excluded_words
        return [item for item in results
                if not all(w in excluded for w in item.get('meta', {}).get('matched_words', []))]

    @staticmethod
    def _relevance_key(item):
        """Ключ сортировки результатов от лучшего: уровень совпадения, затем число совпадений на этом уровне."""
        meta = item.get('meta', {})
        return meta.get('max_level', 0), meta.get('count_at_max', 0)

    def _apply_filter_and_display_b(self, results):
        """Аналог _apply_filter_and_display(), но для второго файла в режиме
           разделения: пишет в all_filtered_topics_b и рисует в renderer_2 —
           без замеров/логирования (это вспомогательная панель, отдельная
           статистика по ней не нужна)."""
        filtered_topics = self._filter_excluded(results)
        self.all_filtered_topics_b = filtered_topics

        self._update_word_panel_b()

        if not filtered_topics:
            if self.renderer_2:
                self.renderer_2.render_error("Нет результатов.")
            return

        filtered_topics.sort(key=self._relevance_key, reverse=True)
        self.all_filtered_topics_b = filtered_topics
        self._display_page_b()

    def _update_nav_buttons(self):
        if self.btn_first is None:
            return
        if self.is_viewing_file:
            self.btn_first.config(state='disabled')
            self.btn_back.config(state='normal')
            self.btn_forward.config(state='disabled')
            self.btn_last.config(state='disabled')
            return
        max_page = self._max_page_combined()
        self.btn_back.config(state='normal' if self.results_page > 0 else 'disabled')
        self.btn_forward.config(state='normal' if self.results_page < max_page else 'disabled')
        self.btn_first.config(state='normal' if self.results_page > 0 else 'disabled')
        self.btn_last.config(state='normal' if self.results_page < max_page else 'disabled')

    def _max_page_combined(self):
        """Максимальный номер страницы. В обычном режиме — только по первому
           (единственному) списку результатов; в режиме разделения — по тому
           из двух файлов, где страниц больше, чтобы кнопки навигации
           учитывали оба окна одновременно."""
        page_size = self._current_page_size()
        max_page_a = max(0, (len(self.all_filtered_topics) - 1) // page_size)
        if not self.split_mode_active:
            return max_page_a
        max_page_b = max(0, (len(self.all_filtered_topics_b) - 1) // page_size)
        return max(max_page_a, max_page_b)

    def _current_page_size(self):
        """Сколько результатов показывать за раз на текущей странице. В
           режиме разделения (два Excel-файла) используется отдельный
           настраиваемый параметр конфигурации excel_split_page_size —
           вместо обычных 20 (self.page_size)."""
        if self.split_mode_active:
            return self.config.get('excel_split_page_size', 20) or 20
        return self.page_size

    # ---------- Публичные методы ----------
    def set_nav_buttons(self, btn_first, btn_back, btn_forward, btn_last):
        self.btn_first = btn_first
        self.btn_back = btn_back
        self.btn_forward = btn_forward
        self.btn_last = btn_last

    def set_typing_stats(self, stats_str: str, total_ms: float):
        """Устанавливает статистику нажатий, переданную из MainWindow."""
        self._typing_stats_str = stats_str
        self._typing_total_ms = total_ms

    def _prepare_panes_for_model_search(self):
        """Общее начало поиска по векторным моделям (и FastText, и MiniLM): режим разделения выключается,
           окна и панель "Совпадения" очищаются, результаты прошлого поиска забываются (их на экране уже нет —
           иначе кнопки листания продолжили бы листать их под справкой)."""
        self.split_mode_active = False
        if self.set_split_view_active_callback:
            self.set_split_view_active_callback(False)

        self.word_panel.clear()
        self.result_text.delete(1.0, tk.END)
        self._reset_results_state()
        self.is_viewing_file = False
        self.saved_state = {}

    def _do_vector_search(self, query, vector_key, real_indices):
        """Поиск по обученной векторной модели (кнопка "Векторы") — теперь
           работает СОВМЕСТНО с обычными индексами: модель только
           подсказывает, какие слова близки к запросу, а сам поиск/подсветка
           топиков идут по real_indices — индексам, отмеченным галочками
           ВМЕСТЕ с моделью (их может быть несколько, и это не обязательно
           тот файл, на котором модель обучалась). Левое окно показывает
           слова, близкие к запросу в векторном пространстве, с числовой
           близостью (без подсветки и без клика-исключения — это не
           совпадения по тексту, а соседи по смыслу).

           Это ветка ТОЛЬКО для word-embedding моделей (FastText) — для
           моделей уровня целых предложений (MiniLM) см. _do_semantic_search,
           куда управление передаётся ниже по типу модели."""
        model_type = self.vector_model_manager.get_model_type(vector_key)
        if model_type in CHUNK_BASED_MODEL_TYPES:
            self._do_semantic_search(query, vector_key, real_indices)
            return

        self._prepare_panes_for_model_search()

        query_word = query.strip().split()[0] if query.strip() else ''
        if not query_word:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            return

        start_time = time.time()
        t_neighbors_start = time.time()
        if self.variations_excluded_callback and self.variations_excluded_callback():
            neighbors = self.vector_model_manager.get_neighbors_deduplicated(vector_key, query_word)
        else:
            neighbors = self.vector_model_manager.get_neighbors(vector_key, query_word)
        t_neighbors_ms = (time.time() - t_neighbors_start) * 1000

        # Левое окно — слова, близкие по вектору, с числом близости.
        self.word_panel.update_vector_words(neighbors, query_word=query_word, vector_key=vector_key)
        self.word_counts = {}

        # Слова обёрнуты в точки (.слово.) — это переводит их сопоставление
        # с обычного, нечёткого (со всеми сокращёнными фрагментами слова) на
        # точное совпадение целиком. Смысл: слова, которые вернула векторная
        # модель, уже конкретны и осмысленны сами по себе — нечёткое
        # раскрытие каждого до более коротких фрагментов только добавляет
        # шум и заметно замедляет разбор (примерно в 2-3 раза на большом
        # тексте — фрагментов на слово получается в разы больше).
        neighbor_words = [w for w, _score in neighbors]
        effective_query = " ".join(f".{w}." for w in dict.fromkeys([query_word] + neighbor_words))

        t_search_start = time.time()
        try:
            topic_results = self.engine.search(effective_query, indices=real_indices,
                                               min_word_length=2, unique_word_rating=True)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка поиска: {e}")
            return
        t_search_ms = (time.time() - t_search_start) * 1000
        search_time = (time.time() - start_time) * 1000
        print(f"⏱ Векторный поиск: {search_time:.1f} мс "
             f"(соседи по модели: {t_neighbors_ms:.1f} мс, поиск по индексу: {t_search_ms:.1f} мс)")

        if stats_logger.STATS_ENABLED:
            stats_logger.log_search(
                engine_type='vector',
                query=query,
                index_name=f"{vector_key} -> {', '.join(real_indices)}",
                search_time_ms=search_time
            )

        if not topic_results:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            return

        # Подсвечиваем в топиках само слово запроса и все найденные соседние
        # слова — как обычные точные совпадения (никакого сокращения до
        # префиксов/долей слова тут не нужно).
        self.current_query_words_lower = list(dict.fromkeys(
            [query_word.lower()] + [w.lower() for w in neighbor_words]
        ))
        self.current_partial_fragments = []
        self._last_all_fragments_levels = []

        self._full_topic_data = topic_results
        topic_results_sorted = sorted(topic_results, key=self._relevance_key, reverse=True)
        self.all_filtered_topics = topic_results_sorted
        self.results_page = 0
        self._display_page()
        # На случай если _display_page() при total==0 успел бы показать
        # обычную справку — здесь всегда есть результаты (проверили выше),
        # так что дополнительно ничего восстанавливать не нужно.

    def _do_semantic_search(self, query, vector_key, real_indices):
        """Поиск через модель уровня целых предложений (MiniLM) — в отличие
           от _do_vector_search (FastText: список близких слов + обычный
           текстовый поиск ими), здесь запрос кодируется в вектор и
           напрямую сравнивается с векторами уже закодированных при
           обучении топиков (см. VectorModelManager.search_semantic) — сама
           модель сразу возвращает похожие по смыслу топики, а не слова.
           В отличие от FastText, индекс(ы) для поиска здесь НЕ нужно
           отмечать галочкой — они определились при обучении ("окно
           смысла") и берутся из конфигурации (get_associated_indices);
           real_indices (что отмечено галочкой сейчас) не используется, но
           параметр оставлен для единообразия сигнатуры с
           _do_vector_search."""
        self._prepare_panes_for_model_search()

        if not query.strip():
            self.renderer.render_help_text()
            self._update_nav_buttons()
            return

        # У этой модели нет "похожих слов" (она сравнивает целые предложения,
        # а не слова) — вместо пустой панели показываем понятное пояснение,
        # чтобы это не выглядело как ошибка.
        self.word_panel.show_message(
            "Семантический поиск: список близких слов не "
            "предусмотрен — модель сравнивает целые фрагменты текста "
            "по смыслу, а не отдельные слова."
        )

        start_time = time.time()
        topn = self.config.get('vector_model_topn', 15)  # настройка, а не словарь баз (config_dict — это базы)
        matches = self.vector_model_manager.search_semantic(vector_key, query, topn=topn)
        search_time = (time.time() - start_time) * 1000
        print(f"⏱ Семантический поиск: {search_time:.1f} мс ({len(matches)} топиков от модели)")

        if stats_logger.STATS_ENABLED:
            stats_logger.log_search(
                engine_type='semantic',
                query=query,
                index_name=f"{vector_key} -> {', '.join(real_indices)}",
                search_time_ms=search_time
            )

        associated_indices = set(self.vector_model_manager.get_associated_indices(vector_key))
        matches = [m for m in matches if m[0] in associated_indices]

        if not matches:
            self.renderer.render_help_text()
            self.update_status("⚠️ Семантический поиск не нашёл ничего среди отмеченных индексов.")
            self._update_nav_buttons()
            return

        # Подсвечиваем буквальные слова запроса и их укороченные фрагменты
        # (та же логика, что и в обычном поиске, — см. do_search) — это
        # не основа отбора топиков (общих слов с запросом может не быть
        # вовсе), а просто бонус, если совпадение или его часть всё же
        # есть. Ровно тот же приём, что и в вашем веб-проекте: там для
        # длинных слов подсветка идёт по "укороченному" совпадению
        # (обрезают последние 2 буквы), чтобы ловить и "звезда", и
        # "звёзды" — у нас для этого уже есть более гибкая многоуровневая
        # система (get_fragments_with_levels), которой обычный поиск и так
        # пользуется, здесь просто переиспользуем её.
        self._remember_query_words(parse_query_words(query, min_word_length=2))

        topic_results = []
        for index_name, rowid, score in matches:
            info = self.engine.get_section_info_from(index_name, rowid)
            if not info:
                continue
            topic_results.append({
                'rowid': rowid,
                'content': info.get('text', ''),
                'file_name': info.get('file_name', ''),
                'position': info.get('position', '0'),
                'semantic_score': score,
            })

        if not topic_results:
            self.renderer.render_help_text()
            self.update_status("⚠️ Не удалось получить содержимое найденных топиков.")
            self._update_nav_buttons()
            return

        self._full_topic_data = topic_results
        # Уже отсортированы по убыванию близости моделью (search_passages) —
        # порядок sorted() здесь только формально приводит к общей форме.
        self.all_filtered_topics = sorted(topic_results, key=lambda x: x['semantic_score'], reverse=True)
        self.results_page = 0
        self._display_page()

    def gather_text_for_indices(self, index_names):
        """Собирает весь текст по списку реальных индексов (одна книга или
           несколько сразу) — для облака тегов (кнопка "Облако тегов" у
           списка индексов, не требует никакой обученной модели, только
           сам текст). Записи, соответствующие векторным моделям (их тоже
           можно было случайно отметить галочкой вместе с обычными
           индексами), пропускаются — у них нет собственного текста."""
        texts = []
        for index_name in index_names:
            if self.vector_model_manager and self.vector_model_manager.is_vector_key(index_name):
                continue
            try:
                rows = self.engine.get_all_sections(index_name)
            except Exception as e:
                print(f"⚠ Не удалось прочитать индекс «{index_name}» для облака тегов: {e}")
                continue
            for _rowid, text, _file_name in rows:
                if text:
                    texts.append(text)
        return texts

    def _is_excel_index(self, index_name):
        """Определяет, соответствует ли индекс Excel-файлу (.xlsx) — тем же
           способом, что уже используется при отрисовке топиков: ищем
           исходный путь файла через сопоставление display_name в
           конфигурации, раз сам index_name это не путь, а
           транслитерированное имя индекса.
           ВАЖНО: self.config_dict здесь — это УЖЕ только файловые записи
           {имя_файла: (display, separator, exclude)} — в app_window.py он
           собирается как config.get('bases', {}) ДО передачи сюда (полный
           конфиг с настройками вроде excel_split_view_enabled и
           vector_models живёт отдельно, в self.config, а не в
           self.config_dict — две разные переменные с разным
           содержимым). Перепутать уровни — реальная, уже случавшаяся
           ошибка в обе стороны: один раз из-за этого поиск файла никогда
           не находил совпадение (split_mode_active не включался вообще
           ни для каких индексов), другой раз — по той же причине, но в
           обратную сторону."""
        file_name = None
        if index_name in self.index_manager.index_display_map:
            display_name = self.index_manager.index_display_map[index_name]
            for config_file, (dn, _sep, _excl) in self.config_dict.items():
                if dn == display_name:
                    file_name = config_file
                    break
        if not file_name:
            file_name = index_name
        return os.path.splitext(file_name)[1].lower() == '.xlsx'

    # ---------- Поиск ----------
    def do_search(self):
        """Выполняет поиск по запросу из поля ввода и показывает результат.

           Шаги: проверки и подготовка -> особые запросы (короткий, "**") -> выбор режима по отмеченным
           индексам (SearchPlan: векторный / два Excel-файла / обычный) -> поиск -> итог в статусной
           строке. Каждый режим — отдельный метод; порядок шагов и условия те же, что были в одной
           большой функции (поведение закреплено проверками tests/battery_search_flow.py)."""
        if not self.engine or not self.engine._current_index:
            messagebox.showwarning("Внимание", "Индекс не выбран.")
            return

        # 2D-визуализация (кнопка "3D/2D") временно занимает среднее окно —
        # любой новый обычный поиск должен вернуть его к обычному виду.
        if self.hide_vector_viz_callback:
            self.hide_vector_viz_callback()

        query = self.query_entry.get().strip()

        # Любой запрос, кроме "**", выводит из режима просмотра одного файла.
        if query != self.BROWSE_QUERY:
            self.exit_browse_mode()

        self._forget_exclusions_for_new_query(query)

        if len(query) < 2:
            self._show_empty_query_state(query)
            return

        # "**" — режим просмотра одного файла (блоки файла подряд, без поиска).
        if query == self.BROWSE_QUERY:
            self._do_single_file_browse()
            return

        self.is_viewing_file = False
        self.saved_state = {}

        if stats_logger.STATS_ENABLED:
            stats_logger.log_exclusions(query, self.excluded_words)

        plan = self._plan_search()
        if plan.vector_key:
            self._route_vector_search(query, plan)
            return

        self._choose_split_mode(plan.selected_ordered)
        self._clear_result_panes()

        # В режиме разделения (два Excel-файла) ищутся и совпадения из двух
        # символов (например, "12" в запросе "Болт М 12"), а не только от
        # трёх символов, как обычно — старт самого поиска (при вводе < 2
        # символов) не меняется, речь только о том, какие слова запроса
        # считаются полноценными для сопоставления.
        min_word_length = 2 if self.split_mode_active else 3

        query_words_info = parse_query_words(query, min_word_length=min_word_length)
        if not query_words_info:
            self.renderer.render_help_text()
            return
        self._remember_query_words(query_words_info)

        if self.split_mode_active:
            timings = self._search_two_files(query, plan.selected_ordered, min_word_length)
        else:
            timings = self._search_selected_indices(query, plan.indices_to_search, min_word_length)
        if timings is None:
            return
        self._report_search_timings(query, *timings)

    def _forget_exclusions_for_new_query(self, query):
        """Если новый запрос не является продолжением/сокращением предыдущего (т.е. пользователь не
           просто дописывает или стирает то же слово, а начал вводить фактически другой запрос) —
           сбрасывает исключения слов. Иначе список исключений, набранный для одного запроса,
           незаметно "прилипает" ко всем последующим не связанным с ним запросам (это и была
           причина устойчивого списка исключений в логе статистики)."""
        previous_query_lower = self._last_query.lower()
        query_lower = query.lower()
        is_continuation = (
            query_lower == previous_query_lower
            or query_lower.startswith(previous_query_lower)
            or previous_query_lower.startswith(query_lower)
        )
        if not is_continuation:
            self.excluded_words.clear()
        self._last_query = query

    def _reset_results_state(self):
        """Забывает результаты прошлого поиска. Вызывается, когда на экране они уже не показаны (справка,
           пустой результат, очищенные окна): иначе в памяти оставались старые топики и номер
           страницы, и кнопки листания (а также "Кратко") продолжали работать со старыми результатами
           под текстом справки."""
        self.all_filtered_topics = []
        self.all_filtered_topics_b = []
        self._full_topic_data = []
        self._full_topic_data_b = []
        self.word_counts = {}
        self.word_counts_b = {}
        self.all_topic_words = {}
        self.results_page = 0

    def _show_empty_query_state(self, query):
        """Запрос короче двух символов: вместо результатов — справка, всё состояние сброшено."""
        self.excluded_words.clear()
        self.renderer.render_help_text()
        self._reset_results_state()
        self._update_nav_buttons()
        self.word_panel.clear()
        self.is_viewing_file = False
        self.saved_state = {}
        if stats_logger.STATS_ENABLED:
            stats_logger.log_exclusions(query, self.excluded_words)

    def _plan_search(self) -> SearchPlan:
        """Что искать и каким способом — по отмеченным индексам (порядок отметки сохраняется)."""
        engine_type = getattr(self.engine, 'engine_type', 'fts5')
        indices_to_search = None
        selected_ordered = []
        if engine_type in ('elasticsearch', 'manticore'):
            selected_ordered = self.index_manager.get_selected_indices_ordered()
            if selected_ordered:
                indices_to_search = selected_ordered
            else:
                indices_to_search = [self.engine._current_index]

        # Модель ("FT ...") теперь работает ТОЛЬКО совместно с обычными
        # индексами: если среди отмеченных строк есть модель, поиск ведётся
        # по всем ОДНОВРЕМЕННО отмеченным обычным индексам (их может быть
        # несколько, и это не обязательно тот файл, на котором модель
        # обучалась) — модель лишь подсказывает, какие слова искать. Если
        # моделей отмечено несколько — используется первая.
        vector_key = None
        real_indices = []
        if self.vector_model_manager:
            for key in selected_ordered:
                if self.vector_model_manager.is_vector_key(key):
                    if vector_key is None:
                        vector_key = key
                else:
                    real_indices.append(key)
        return SearchPlan(selected_ordered, indices_to_search, vector_key, real_indices)

    def _route_vector_search(self, query, plan):
        """Отмечена векторная модель: запускает векторный поиск (или объясняет, чего не хватает)."""
        model_type = self.vector_model_manager.get_model_type(plan.vector_key)
        if model_type in CHUNK_BASED_MODEL_TYPES:
            # MiniLM знает свой индекс из конфигурации (сохранён при
            # обучении, см. VectorModelManager.get_associated_indices) —
            # отмечать его галочкой отдельно не нужно, в отличие от
            # FastText, которому обязательно нужен хотя бы один
            # отмеченный обычный индекс.
            self._do_vector_search(query, plan.vector_key, plan.real_indices)
            return
        if not plan.real_indices:
            self.renderer.render_help_text()
            self._reset_results_state()
            self.update_status("⚠️ Для векторного поиска отметьте галочкой ещё и хотя бы один обычный индекс.")
            self._update_nav_buttons()
            return
        self._do_vector_search(query, plan.vector_key, plan.real_indices)

    def _choose_split_mode(self, selected_ordered):
        """Режим разделения окна результатов на два файла: включён в настройках, выбрано ровно два
           индекса, И ОБА — Excel-файлы (сам режим задуман для построчного сопоставления двух таблиц,
           для обычных текстовых файлов он не имеет смысла). Порядок выбора определяет, какой файл
           идёт в верхнее окно, какой — в нижнее."""
        self.split_mode_active = bool(
            self.split_view_enabled_callback and self.split_view_enabled_callback()
            and len(selected_ordered) == 2
            and self.renderer_2 is not None
            and all(self._is_excel_index(idx) for idx in selected_ordered)
        )
        if self.set_split_view_active_callback:
            self.set_split_view_active_callback(self.split_mode_active)

    def _clear_result_panes(self):
        """Очищает окна результатов и панели "Совпадения" перед новым поиском — и вместе с ними
           забывает результаты прошлого (их на экране больше нет)."""
        self.word_panel.clear()
        self.result_text.delete(1.0, tk.END)
        if self.split_mode_active:
            self.word_panel_2.clear()
            self.renderer_2.result_text.delete(1.0, tk.END)
        self._reset_results_state()

    def _remember_query_words(self, query_words_info):
        """Запоминает слова запроса и их фрагменты — для подсветки и панели "Совпадения"."""
        self.current_query_words_lower = [info[0].lower() for info in query_words_info]
        self.current_partial_fragments = list(set(
            frag for word, min_len, _ in query_words_info
            for frag, _ in get_fragments_with_levels(word, min_len)
        ))
        self._last_all_fragments_levels = []
        for word, min_len, must_start in query_words_info:
            for frag, level in get_fragments_with_levels(word, min_len):
                self._last_all_fragments_levels.append((frag, level, must_start))

    def _search_two_files(self, query, selected_ordered, min_word_length):
        """Режим разделения: поиск отдельно по каждому из двух Excel-файлов. Возвращает
           (время поиска, время вывода) в мс или None, если показывать нечего."""
        index_a, index_b = selected_ordered[0], selected_ordered[1]
        self.renderer.set_pane_label(self._format_index_file_label(index_a))
        self.renderer_2.set_pane_label(self._format_index_file_label(index_b))
        try:
            start_time = time.time()
            results_a = self.engine.search(query, indices=[index_a], min_word_length=min_word_length,
                                           unique_word_rating=True)
            results_b = self.engine.search(query, indices=[index_b], min_word_length=min_word_length,
                                           unique_word_rating=True)
            search_time = (time.time() - start_time) * 1000
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка поиска: {e}")
            return None

        if not results_a and not results_b:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            self.word_panel.clear()
            return None

        if stats_logger.STATS_ENABLED:
            stats_logger.log_search(
                engine_type=self.engine.engine_type,
                query=query,
                index_name=f"{index_a} + {index_b} (разделение)",
                search_time_ms=search_time
            )

        self._full_topic_data = results_a
        self._full_topic_data_b = results_b
        self._update_word_panel_from_results(results_a)
        self._update_word_panel_from_results_b(results_b)

        display_time = self._apply_filter_and_display(results_a, search_time)
        self._apply_filter_and_display_b(results_b)
        return search_time, display_time

    def _search_selected_indices(self, query, indices_to_search, min_word_length):
        """Обычный поиск по отмеченным индексам. Возвращает (время поиска, время вывода) в мс
           или None, если показывать нечего."""
        try:
            start_time = time.time()
            results = self.engine.search(query, indices=indices_to_search, min_word_length=min_word_length)
            search_time = (time.time() - start_time) * 1000
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка поиска: {e}")
            return None

        if not results:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            self.word_panel.clear()
            return None

        if stats_logger.STATS_ENABLED:
            if indices_to_search:
                index_names = ', '.join(indices_to_search)
            else:
                index_names = self.get_current_index_name()
            stats_logger.log_search(
                engine_type=self.engine.engine_type,
                query=query,
                index_name=index_names,
                search_time_ms=search_time
            )

        self._full_topic_data = results
        self._update_word_panel_from_results(results)

        # Отображаем результаты и получаем время отображения
        display_time = self._apply_filter_and_display(results, search_time)
        return search_time, display_time

    def _report_search_timings(self, query, search_time, display_time):
        """Итоговое сообщение в статусной строке и запись в журнал статистики."""
        if self._typing_stats_str:
            msg = (f"ЗАПРОС-{self._typing_total_ms:.0f} мс: '{query}'='{self._typing_stats_str}'  "
                   f"ПОИСК -{search_time:.0f} мс  ВЫВОД РЕЗУЛЬТАТОВ -{display_time:.0f} мс")
        else:
            msg = f"ПОИСК -{search_time:.0f} мс  ВЫВОД РЕЗУЛЬТАТОВ -{display_time:.0f} мс"
        self.update_status(msg)

        if stats_logger.STATS_ENABLED:
            stats_logger.log_typing_stats(query, self._typing_stats_str, self._typing_total_ms,
                                          search_time, display_time)


    def refresh_display(self):
        """Обновляет отображение после изменения исключённых слов."""
        if not hasattr(self, '_full_topic_data') or not self._full_topic_data:
            return

        start_total = time.time()

        t_filter = time.time()
        filtered_topics = self._filter_excluded(self._full_topic_data)
        self.all_filtered_topics = filtered_topics
        self.results_page = 0 if self.results_page < 0 else self.results_page
        max_page = max(0, (len(filtered_topics) - 1) // self._current_page_size())
        if self.results_page > max_page:
            self.results_page = max_page
        t_filter = (time.time() - t_filter) * 1000

        if not filtered_topics:
            self.renderer.render_help_text()
            self._update_nav_buttons()
            self._update_word_panel()
            total_ms = (time.time() - start_total) * 1000
            self._log_display_time({'фильтрация': t_filter, 'отрисовка_справки': total_ms - t_filter}, total_ms, "refresh_display (пусто)")
            if self.split_mode_active and self._full_topic_data_b:
                self._apply_filter_and_display_b(self._full_topic_data_b)
            return

        t_sort = time.time()
        filtered_topics.sort(key=self._relevance_key, reverse=True)
        self.all_filtered_topics = filtered_topics
        t_sort = (time.time() - t_sort) * 1000

        display_time = self._display_page(measure=True)

        total_ms = (time.time() - start_total) * 1000
        self._log_display_time({
            'фильтрация': t_filter,
            'сортировка': t_sort,
            'отрисовка_страницы': display_time
        }, total_ms, "refresh_display")
        self._update_word_panel()
        self.result_text.update_idletasks()

        # Исключения слов общие для обеих панелей в режиме разделения — при
        # изменении списка исключений (клик по слову в любой из панелей
        # "Совпадения") нужно обновить и второй файл.
        if self.split_mode_active and self._full_topic_data_b:
            self._apply_filter_and_display_b(self._full_topic_data_b)

    def _display_page(self, search_time_ms=None, measure=False):
        """Отображает текущую страницу результатов. Если measure=True, возвращает время отрисовки.

           Режимы отрисовки (каждый — отдельный метод): пусто (справка), просмотр файла "**" (блоки),
           разделение на два файла (компактно) и обычный (с шапками)."""
        start_time = time.time() if measure else 0.0

        # Сбрасываем состояние просмотра файла, если оно застряло
        if self.is_viewing_file:
            self.is_viewing_file = False
            self.saved_state = {}

        total = len(self.all_filtered_topics)
        if total == 0:
            self.renderer.render_help_text()
            self._update_nav_buttons()
        else:
            page_size = self._current_page_size()
            start = self.results_page * page_size
            end = min(start + page_size, total)
            page_topics = self.all_filtered_topics[start:end]
            if self.browse_mode:
                self._render_browse_page(page_topics, total, page_size)
            elif self.split_mode_active:
                self._render_split_page(page_topics)
            else:
                self._render_normal_page(page_topics, start, total)

        if measure:
            return (time.time() - start_time) * 1000

    def _render_browse_page(self, page_topics, total, page_size):
        """Режим просмотра одного файла ("**"): блоки подряд, без шапок."""
        self.renderer.render_blocks_page(page_topics)
        self._update_nav_buttons()
        pages = (total + page_size - 1) // page_size
        self.update_status(f"📄 {self.browse_file_label} — блоков: {total}, "
                           f"страница {self.results_page + 1} из {pages}")

    def _render_split_page(self, page_topics):
        """Компактный режим (без шапок, без пустых строк) — используется для ОБЕИХ панелей, когда
           активно разделение окна результатов."""
        self.renderer.render_results_page_compact(
            page_topics, self.current_query_words_lower, self.current_partial_fragments, self.brief_mode
        )
        self._update_nav_buttons()

    def _render_normal_page(self, page_topics, start, total):
        """Обычная страница: у каждого топика шапка (файл, уровень или близость) и подсветка."""
        topics_to_render = self._build_topic_entries(page_topics, start)
        self.renderer.render_results_page(
            topics_to_render,
            page_num=self.results_page,
            total_count=total,
            exact_words=self.current_query_words_lower,
            partial_fragments=self.current_partial_fragments,
            brief_mode=self.brief_mode
        )
        self._update_nav_buttons()

    def _build_topic_entries(self, page_topics, start):
        """Готовит данные для отрисовки (поиск имени файла/алиаса, форматирование шапки) — сама
           отрисовка в Tkinter-виджет делегирована ResultsRenderer."""
        current_index_name = self.get_current_index_name()
        entries = []
        for local_idx, item in enumerate(page_topics, start=1):
            global_idx = start + local_idx - 1  # уникальная позиция топика в all_filtered_topics —
                                                 # не зависит от rowid, который может совпадать
                                                 # у топиков из разных индексов при мультипоиске
            file_name = self._topic_file_name(item, current_index_name)
            # У Excel-топиков ("одна строка = один топик") нет шапки и
            # перехода по гиперссылке на файл-источник — только сам текст
            # строки с подсветкой.
            is_excel = os.path.splitext(file_name)[1].lower() == '.xlsx'
            entries.append({
                'global_idx': global_idx,
                'rowid': item.get('rowid'),
                'header': "" if is_excel else self._topic_header(item, file_name),
                'content': item.get('content', ''),
                'skip_header': is_excel,
                'file_name': file_name,  # для подчёркивания (ui/results_renderer.py)
            })
        return entries

    def _topic_file_name(self, item, current_index_name):
        """Файл топика; если у топика его нет — файл текущего индекса (по алиасу в настройках баз),
           а если и его нет — имя самого индекса."""
        file_name = item.get('file_name', '')
        if not file_name:
            if current_index_name in self.index_manager.index_display_map:
                for config_file, (display_name, _, _) in self.config_dict.items():
                    if display_name == self.index_manager.index_display_map[current_index_name]:
                        file_name = config_file
                        break
            if not file_name:
                file_name = current_index_name
        return file_name

    def _topic_header(self, item, file_name):
        """Шапка топика: "Файл: имя (алиас) | (уровень N, совп. M)" либо, для семантического поиска
           (MiniLM ранжирует по близости векторов, а не по числу/уровню совпавших слов — это другая
           метрика), "(семантическая близость N%)"."""
        header_parts = []
        if file_name:
            header_parts.append(f"Файл: {self._format_file_label(file_name)}")
        semantic_score = item.get('semantic_score')
        if semantic_score is not None:
            header_parts.append(f"(семантическая близость {semantic_score * 100:.0f}%)")
        else:
            meta = item.get('meta', {})
            header_parts.append(f"(уровень {meta.get('max_level', 0)}, совп. {meta.get('count_at_max', 0)})")
        return " | ".join(header_parts)

    def _display_page_b(self):
        """Отрисовывает текущую страницу второго файла в режиме разделения —
           всегда в компактном режиме (без шапок, без пустых строк). Номер
           страницы (self.results_page) общий с первым файлом."""
        if not self.renderer_2:
            return
        total = len(self.all_filtered_topics_b)
        if total == 0:
            self.renderer_2.render_error("Нет результатов.")
            return
        page_size = self._current_page_size()
        start = self.results_page * page_size
        end = min(start + page_size, total)
        page_topics = self.all_filtered_topics_b[start:end]
        self.renderer_2.render_results_page_compact(
            page_topics, self.current_query_words_lower, self.current_partial_fragments, self.brief_mode
        )

    def page_back(self, back_to_results_callback):
        if self.is_viewing_file:
            back_to_results_callback()
            return
        if self.results_page > 0:
            self.results_page -= 1
            self._display_page()
            if self.split_mode_active:
                self._display_page_b()

    def page_forward(self):
        if self.is_viewing_file:
            return
        max_page = self._max_page_combined()
        if self.results_page < max_page:
            self.results_page += 1
            self._display_page()
            if self.split_mode_active:
                self._display_page_b()

    def go_to_first_page(self):
        if self.results_page > 0:
            self.results_page = 0
            self._display_page()
            if self.split_mode_active:
                self._display_page_b()

    def go_to_last_page(self):
        max_page = self._max_page_combined()
        if self.results_page < max_page:
            self.results_page = max_page
            self._display_page()
            if self.split_mode_active:
                self._display_page_b()

    def reset_exclusions(self):
        self.excluded_words.clear()
        self.refresh_display()

    def on_hyperlink_click(self, event):
        index = self.result_text.index(f"@{event.x},{event.y}")
        tags = self.result_text.tag_names(index)
        for tag in tags:
            if tag.startswith('block_'):
                parts = tag.split('_')
                if len(parts) == 3:
                    _, global_idx_str, rowid_str = parts
                    rowid = int(rowid_str)
                    try:
                        global_idx = int(global_idx_str)
                    except ValueError:
                        global_idx = None
                    self._open_file_for_topic(rowid, global_idx)
                    return

    def _find_clicked_topic(self, rowid, global_idx):
        """Топик, по заголовку которого кликнули. Сначала — по точной позиции в общем списке результатов:
           это надёжно работает даже когда rowid совпадает у топиков из разных индексов (при поиске сразу
           по нескольким индексам rowid уникален только внутри индекса). Не вышло — первый топик с таким
           rowid. Нет и его — None."""
        if global_idx is not None and 0 <= global_idx < len(self.all_filtered_topics):
            candidate = self.all_filtered_topics[global_idx]
            if candidate.get('rowid') == rowid:
                return candidate
        for item in self.all_filtered_topics:
            if item.get('rowid') == rowid:
                return item
        return None

    def _topic_source(self, rowid, topic_data):
        """(имя файла, позиция, текст топика) — из топика в результатах, а если его там нет, из индекса
           движка. None, если данных нет нигде (пользователю уже показано сообщение)."""
        if not topic_data:
            info = self.engine.get_section_info(rowid)
            if not info:
                messagebox.showerror("Ошибка", f"Не удалось получить информацию о топике {rowid}")
                return None
            return info.get('file_name', ''), info.get('position', '0'), info.get('text', '')
        return topic_data.get('file_name', ''), topic_data.get('position', '0'), topic_data.get('content', '')

    def _resolve_source_path(self, file_name):
        """Где на диске лежит файл-источник: имя как есть, в папке DB, только по имени файла (путь мог
           быть записан на другой машине), затем по настройкам баз (алиас или имя файла). None — нигде нет."""
        possible_paths = [
            file_name,
            os.path.join("DB", file_name),
            os.path.join(".", file_name)
        ]
        base_name = os.path.basename(file_name)
        possible_paths.append(base_name)
        possible_paths.append(os.path.join("DB", base_name))

        for path in possible_paths:
            if os.path.exists(path):
                return path

        for config_file, (display_name, _, _) in self.config_dict.items():
            if display_name == file_name or os.path.basename(config_file) == file_name:
                if os.path.exists(config_file):
                    return config_file
                elif os.path.exists(os.path.join("DB", config_file)):
                    return os.path.join("DB", config_file)
        return None

    def _open_file_for_topic(self, rowid: int, global_idx: int = None):
        try:
            topic_data = self._find_clicked_topic(rowid, global_idx)
            source = self._topic_source(rowid, topic_data)
            if source is None:
                return
            file_name, position, text_content = source

            if not file_name:
                messagebox.showinfo("Информация", "Для этого топика не сохранено имя файла.")
                return

            file_path = self._resolve_source_path(file_name)
            if not file_path:
                messagebox.showerror("Ошибка", f"Файл не найден: {file_name}")
                return

            highlight_words = self.current_query_words_lower
            highlight_fragments = self.current_partial_fragments
            highlight_context_size = self.config.get('highlight_context_size', 500)
            max_display_chars = self.config.get('max_display_chars', 50000)

            self._display_file_content(
                file_path,
                position,
                highlight_words,
                highlight_fragments,
                text_content,
                file_name,
                highlight_context_size,
                max_display_chars,
                rowid=rowid,
                global_idx=global_idx
            )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {e}")
            print(f"❌ Ошибка открытия файла: {e}")

    def _display_file_content(self, file_path, position, highlight_words, highlight_fragments,
                              topic_text, file_name, highlight_context_size=500, max_display_chars=50000,
                              rowid=None, global_idx=None):
        self.saved_state = {
            'all_filtered_topics': self.all_filtered_topics.copy(),
            'results_page': self.results_page,
            'current_query_words_lower': self.current_query_words_lower.copy(),
            'current_partial_fragments': self.current_partial_fragments.copy(),
            'clicked_rowid': rowid,
            'clicked_global_idx': global_idx,
        }
        self.is_viewing_file = True
        # Метка файла-источника (имя + алиас) для текущего открытого файла —
        # используется при повторном правом клике, чтобы дописать источник
        # сохранённой в конспект цитаты.
        self._current_view_file_label = self._format_file_label(file_name)

        total_start = time.time()
        try:
            read_start = time.time()
            content, used_enc = self._read_file_with_encoding(file_path)
            read_time = (time.time() - read_start) * 1000
            file_size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else len(content)

            pos_start = time.time()
            ext = os.path.splitext(file_path)[1].lower()
            line_num, char_pos, target_char_pos, topic_start_pos, topic_end_pos = determine_position(
                content, ext, topic_text, position
            )
            pos_time = (time.time() - pos_start) * 1000

            display_content, display_topic_start, display_topic_end = compute_display_window(
                content, target_char_pos, topic_start_pos, topic_end_pos, max_display_chars
            )
            display_size_chars = len(display_content)
            highlight_area_chars = display_topic_end - display_topic_start

            insert_start = time.time()
            global_offset = self.renderer.render_file_content(
                display_content, self._back_to_results_from_file, file_name=file_name)
            insert_time = (time.time() - insert_start) * 1000

            display_line_num, display_char_pos = locate_in_text(display_content, display_topic_start)

            scroll_start = time.time()
            self.renderer.scroll_to_file_position(display_line_num, display_char_pos)
            scroll_time = (time.time() - scroll_start) * 1000

            highlight_start = time.time()
            merged_intervals, intervals_found = compute_file_highlight_intervals(
                display_content,
                display_topic_start,
                display_topic_end,
                highlight_words,
                highlight_fragments,
                highlight_context_size
            )
            tags_applied = self.renderer.apply_highlights(merged_intervals, global_offset)
            highlight_time = (time.time() - highlight_start) * 1000

            total_time = (time.time() - total_start) * 1000
            self._log_file_open(
                file_path=file_path,
                total_time_ms=total_time,
                read_time_ms=read_time,
                pos_time_ms=pos_time,
                insert_time_ms=insert_time,
                scroll_time_ms=scroll_time,
                highlight_time_ms=highlight_time,
                file_size_bytes=file_size_bytes,
                display_size_chars=display_size_chars,
                highlight_area_chars=highlight_area_chars,
                intervals_found=intervals_found,
                tags_applied=tags_applied
            )
            self._update_nav_buttons()

        except Exception as e:
            self.renderer.render_error(f"Ошибка загрузки файла: {e}")
            print(f"❌ Ошибка загрузки файла: {e}")
            self.is_viewing_file = False
            self.saved_state = {}

    def _back_to_results_from_file(self, event=None):
        if not self.is_viewing_file:
            return
        self.is_viewing_file = False
        self.all_filtered_topics = self.saved_state.get('all_filtered_topics', [])
        self.results_page = self.saved_state.get('results_page', 0)
        self.current_query_words_lower = self.saved_state.get('current_query_words_lower', [])
        self.current_partial_fragments = self.saved_state.get('current_partial_fragments', [])
        clicked_rowid = self.saved_state.get('clicked_rowid')
        clicked_global_idx = self.saved_state.get('clicked_global_idx')
        self.saved_state = {}
        self._display_page()
        self._update_nav_buttons()
        if clicked_rowid is not None:
            self.renderer.scroll_to_topic(clicked_rowid, clicked_global_idx)

    # ---------- Вспомогательные методы для открытия файла ----------
    def _read_file_with_encoding(self, file_path):
        # Историческое поведение этого места (просмотр файла по гиперссылке):
        # пустые абзацы .docx сохраняются как пустые строки — в отличие от
        # индексации файла в file_manager.py, где они пропускаются.
        content = read_text_file(file_path, keep_empty_docx_paragraphs=True)
        ext = os.path.splitext(file_path)[1].lower()
        used_enc = 'docx' if ext == '.docx' else 'utf-8'
        return content, used_enc

    def _log_file_open(self, file_path, total_time_ms, read_time_ms, pos_time_ms,
                       insert_time_ms, scroll_time_ms, highlight_time_ms,
                       file_size_bytes, display_size_chars, highlight_area_chars,
                       intervals_found, tags_applied):
        file_size_mb = file_size_bytes / (1024 * 1024)
        status_msg = (f"Время открытия файла: {total_time_ms:.0f} мс | "
                      f"Размер {file_size_mb:.2f} МБ | "
                      f"Область {display_size_chars} симв. | "
                      f"Подсветка {tags_applied} тегов")
        self.update_status(status_msg)
        if stats_logger.STATS_ENABLED:
            stats_logger.log_file_open(
                file_path=file_path,
                total_time_ms=total_time_ms,
                read_time_ms=read_time_ms,
                pos_time_ms=pos_time_ms,
                insert_time_ms=insert_time_ms,
                scroll_time_ms=scroll_time_ms,
                highlight_time_ms=highlight_time_ms,
                file_size_mb=file_size_mb,
                display_size_chars=display_size_chars,
                highlight_area_chars=highlight_area_chars,
                intervals_found=intervals_found,
                tags_applied=tags_applied
            )