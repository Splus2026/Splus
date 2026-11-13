import tkinter as tk
from tkinter import simpledialog
from tkinter import ttk, scrolledtext
import os
import sys
import subprocess
import re
from abc import ABC
from .word_panel import WordPanel
from config import CONFIG_FILE, CONSPECT_FILE, MARKS_DB_FILE, KEY_CONCEPTS_FILE, DIARY_FILE, SYNC_FOLDER_FILE, SYNC_BASE_DIR, save_config
import stats_logger
from services import dialogs
from services.index_manager import IndexManager
from ui.index_check_list import IndexCheckList
from services.file_manager import FileManager
from services.search_controller import SearchController
from services.vector_model_manager import VectorModelManager
from ui.vector_params_dialog import ask_vector_params
from ui.file_merger_dialog import open_file_merger_dialog
from services.numerator import NumeratorController
from ui.numerator_dialog import show_numerator_dialog
from ui.tooltip import ToolTip
from ui.layer_bar import LayerBar
from services.marks import MarksStore, export_marks_docx
from utils.password import check_password, make_password_record
from utils import key_concepts
from ui.results_renderer import ResultsRenderer
from ui.visualization_controller import VisualizationController
from ui.custom_dialogs import messagebox


def nav_toggle_layout(char_w, kp_w=0):
    """Отступы и ширина кнопок "Ч", "КП" и "Кратко/Всё" в строке навигации.
       char_w — ширина одной "позиции" (знака шрифта кнопок) в пикселях, kp_w —
       реальная ширина кнопки "КП" в пикселях (0 — кнопки нет).

       Отступ перед переключателем раньше был 180 пикселей (около 20 позиций).
       Теперь он на 5 позиций короче, а сама кнопка на 3 позиции шире (6 знаков
       "Кратко" + 3). Зачем: при обычном размере окна строка из кнопок
       навигации не вмещает всех, и менеджер раскладки сжимает ПОСЛЕДНЮЮ кнопку —
       из "Кратко" оставалось видно только "ратк". Сдвиг влево возвращает ей
       место, а запас по бокам от более широкой кнопки (надпись стоит по центру)
       поглотит остаток сжатия, не задев букв. Постоянная ширина заодно не даёт
       кнопке менять размер при переключении "Кратко" <-> "Всё".

       "КП" встаёт справа от "Ч" В ТОМ ЖЕ отступе: её ширина (и просвет в 4
       пикселя между "Ч" и "КП") вычитается из отступов, так что "Кратко/Всё"
       остаётся на прежнем месте, а строка в целом не становится шире — иначе
       вернулось бы сжатие. "Ч" с "КП" остаются посередине: убранное делится
       поровну. Единица — позиция шрифта, а не пиксель: при другом масштабе
       Windows "5 позиций" остаются пятью."""
    pads_total = 150 - 5 * char_w          # от прежних 75 + 75 после сдвига на 5 позиций
    inner = 0
    if kp_w > 0:
        inner = 4
        pads_total -= kp_w + inner
    pads_total = max(0, pads_total)
    return {
        'underline_padx': (pads_total - pads_total // 2, 0),
        'kp_padx': (inner, 0),
        'brief_padx': (pads_total // 2, 3),
        'brief_width': 6 + 3,
    }


class NavButton(tk.Button):
    """Кнопка постраничной навигации по результатам.

    В обычном tk.Button при переходе в state='disabled' меняется только цвет
    текста (на малоконтрастный системный серый), а фон кнопки остаётся прежним.
    Эта кнопка при каждом .config(state=...) дополнительно сама подставляет
    подходящий фон: тёмный (active_bg) для 'normal' и светлый (disabled_bg) для
    'disabled', а для текста в неактивном состоянии всегда используется чёрный
    цвет (disabledforeground) — так неактивная кнопка выглядит контрастно, а не
    просто "бледной"."""

    def __init__(self, master=None, active_bg='#4a7a8a', disabled_bg='#B7CAD0', **kwargs):
        self._nav_active_bg = active_bg
        self._nav_disabled_bg = disabled_bg
        kwargs.setdefault('disabledforeground', 'black')
        if 'bg' not in kwargs and 'background' not in kwargs:
            initial_state = kwargs.get('state', 'normal')
            kwargs['bg'] = disabled_bg if initial_state in ('disabled', tk.DISABLED) else active_bg
        super().__init__(master, **kwargs)

    def _apply_state_bg(self, kwargs):
        state = kwargs.get('state')
        if state is not None and 'bg' not in kwargs and 'background' not in kwargs:
            if state in ('disabled', tk.DISABLED):
                kwargs['bg'] = self._nav_disabled_bg
            elif state in ('normal', tk.NORMAL):
                kwargs['bg'] = self._nav_active_bg
        return kwargs

    def config(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        kwargs = self._apply_state_bg(kwargs)
        return super().config(**kwargs)

    configure = config


class AppWindow(ABC):
    """Базовый класс окна приложения (тонкий контроллер)."""

    def __init__(self, root, engine, config):
        # Сервисы показывают сообщения через services.dialogs, не зная об окнах: настоящую реализацию
        # (Tk-диалоги) регистрирует окно — ДО создания сервисов.
        dialogs.set_backend(messagebox)
        self.root = root
        self.engine = engine
        self.config = config
        self.font_size = 12
        self.highlight_scheme = 'blue'

        self.default_separator = config.get('default_separator', 'N1000')
        self.debug_log_enabled = config.get('debug_log_enabled', False)
        self.config_dict = config.get('bases', {})
        self.current_index = None

        # Виджеты
        self.word_panel = None
        self.result_text = None
        self.query_entry = None
        self.status_entry = None
        self.scroll_left_btn = None
        self.scroll_right_btn = None

        # Второе окно результатов и вторая панель "Совпадения" — для режима
        # разделения (два выбранных Excel-индекса, см. _update_split_view_layout)
        self.word_panel_2 = None
        self.word_panel_top_frame = None
        self.word_panel_bottom_frame = None
        self.result_text_2 = None
        self.results_paned = None
        self.results_top_frame = None
        self.results_bottom_frame = None
        self.results_top_label = None
        self.results_bottom_label = None
        self.results_renderer_2 = None
        self.split_view_active = False

        # Навигационные кнопки
        self.btn_first = None
        self.btn_back = None
        self.btn_forward = None
        self.btn_last = None
        self.btn_brief_toggle = None
        self.btn_variations_toggle = None
        # Состояние кнопки "−В/+В" (исключение словоформ, см. toggle_word_variations).
        self._variations_excluded = False
        # Нумератор разбивки (services/numerator.py) — создаётся при первом
        # включении, см. _activate_numerator.
        self.numerator = None
        # Подчёркнутые фрагменты ("Ч"): хранилище создаётся в _init_services.
        self.marks_store = None
        # Визуализации в среднем окне (2D/3D, облако тегов, TextRank, граф...) и навигация "Назад"
        # по их уровням — отдельный объект (ui/visualization_controller.py); окно остаётся
        # владельцем виджетов, контроллер берёт их через ссылку на окно.
        self.viz = VisualizationController(self)

        self.index_check_list = None
        self.text_listbox = None
        self.progress_bar = None

        self.selected_count_label = None    # <-- количество выбранных индексов (наверху, рядом с "Индексы:")

        self.status_row_frame = None
        self.bottom_row_frame = None

        self.index_manager = None
        self.file_manager = None
        self.search_controller = None
        self.vector_model_manager = None
        self.results_renderer = None

        self.excluded_words = set()

        self._create_widgets()
        self._init_services()
        self.update_index_list()
        self.update_text_list()
        self._bind_shortcuts()

        stats_logger.set_status_callback(self._update_log_field)
        self._show_help_text()
        self._conspect_lock = False
        # Состояние для правого клика "сохранить в конспект" — см.
        # append_selection_to_conspect(): текст последней сохранённой на
        # диск цитаты, её источник и флаг "источник для неё уже дописан".
        self._last_conspect_text = None
        self._last_conspect_source = None
        self._conspect_source_written = True

    def _init_services(self):
        self.results_renderer = ResultsRenderer(self.result_text, label_widget=self.results_top_label)
        self.results_renderer.font_size = self.font_size
        # Подчёркнутые фрагменты ("Ч", services/marks.py): файл базы открывается
        # при первом обращении, так что недоступная папка не мешает запуску.
        self.marks_store = MarksStore(MARKS_DB_FILE)
        self._ensure_diary()
        self.results_renderer.marks_store = self.marks_store
        self.results_renderer.note_click = lambda nid: self.layer_bar.on_note_clicked(nid)
        self.results_renderer_2 = ResultsRenderer(self.result_text_2, label_widget=self.results_bottom_label)
        self.results_renderer_2.font_size = self.font_size

        self.index_manager = IndexManager(
            engine=self.engine,
            config_dict=self.config_dict,
            check_list=self.index_check_list,
            selected_count_label=self.selected_count_label,
            update_status_callback=self._update_log_field,
            clear_result_callback=self._clear_results,
            parent=self.root
        )
        self.index_check_list.update_font_size(self.font_size)
        # Смена отмеченных индексов в режиме просмотра одного файла ("**").
        self.index_manager.selection_changed_callback = self._on_index_selection_changed

        self.vector_model_manager = VectorModelManager(
            engine=self.engine,
            config_dict=self.config,
            update_status_callback=self._update_log_field
        )
        self.index_manager.vector_model_manager = self.vector_model_manager
        self.index_manager.preload_started_callback = self._start_vector_preload

        self.file_manager = FileManager(
            engine=self.engine,
            config_dict=self.config_dict,
            default_separator=self.default_separator,
            text_listbox=self.text_listbox,
            update_status_callback=self._update_log_field,
            index_display_map=self.index_manager.index_display_map,
            update_index_list_callback=self.update_index_list
        )
        self.file_manager.save_config_callback = lambda: self.config.save()
        self.search_controller = SearchController(
            engine=self.engine,
            config=self.config,
            result_text=self.result_text,
            word_panel=self.word_panel,
            query_entry=self.query_entry,
            index_manager=self.index_manager,
            file_manager=self.file_manager,
            status_update_callback=self._update_log_field,
            get_current_index_name_callback=self._get_current_index_name,
            config_dict=self.config_dict,
            results_renderer=self.results_renderer,
            results_renderer_2=self.results_renderer_2,
            word_panel_2=self.word_panel_2,
            split_view_enabled_callback=lambda: self.config.get('excel_split_view_enabled', False),
            set_split_view_active_callback=self._set_split_view_active,
            vector_model_manager=self.vector_model_manager,
            hide_vector_viz_callback=self.viz.hide_vector_visualization,
            variations_excluded_callback=lambda: self._variations_excluded
        )
        self.search_controller.set_nav_buttons(self.btn_first, self.btn_back, self.btn_forward, self.btn_last)
        self.excluded_words = self.search_controller.excluded_words

    def _create_widgets(self):
        """Строит главное окно по зонам: строка поиска, строка статуса (внизу), основная панель из трёх частей —
           слева «Совпадения», в центре навигация и результаты, справа индексы и файлы. Порядок построения важен:
           строка статуса упаковывается ДО основной панели (см. _build_status_row)."""
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)
        self._build_search_row(top_frame)

        self._build_status_row()

        # --- Основная панель ---
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._build_left_panel(main_paned)
        self._build_center_panel(main_paned)
        self._build_right_panel(main_paned)

        self._update_log_field("Готов к работе")

    def _build_search_row(self, top_frame):
        """Строка поиска: надпись, поле запроса, меню «Настройки», кнопка «Выход»."""
        # --- Строка поиска (теперь единственная строка в верхней части окна —
        #     строка статусных сообщений перенесена в самый низ окна, см. ниже) ---
        self.bottom_row_frame = tk.Frame(top_frame, bg='#d4e8f7')
        self.bottom_row_frame.pack(fill=tk.X, pady=3)

        tk.Label(self.bottom_row_frame, text="Поисковый запрос:", font=('Arial', 12, 'bold'),
                 bg='#d4e8f7', fg='#1a4a7a').pack(side='left', padx=(0, 5))

        self.query_entry = ttk.Entry(self.bottom_row_frame, width=30, font=('Consolas', self.font_size))
        self.query_entry.pack(side='left', fill=tk.X, expand=True, padx=5)
        self.query_entry.bind("<Return>", lambda e: self.do_search())
        self.query_entry.focus_set()

        self.btn_settings = tk.Menubutton(self.bottom_row_frame, text="Настройки",
                                          font=('Arial', 12, 'bold'), bg='#6a4a8a', fg='white',
                                          padx=3, pady=1, relief='raised', borderwidth=2)
        self.settings_menu = tk.Menu(self.btn_settings, tearoff=0, font=('Arial', 12))
        self.settings_menu.add_command(label="Конфигурация", command=self.open_config)
        self.settings_menu.add_command(label="Экспорт подчеркнутых", command=self.export_underlined)
        self.settings_menu.add_command(label="Папка синхронизации…", command=self.choose_sync_folder)
        self.settings_menu.add_command(label="Синхронизировать с телефоном", command=self.sync_with_phone)
        self.settings_menu.add_command(label="Сменить пароль", command=self.change_password_dialog)
        # "Выбор движка" — сам список движков (пункты меню) заполняет
        # MainWindow, здесь только заготовка подменю (аналогично тому, как
        # раньше engine_placeholder заполнялся выпадающим списком).
        self.engine_submenu = tk.Menu(self.settings_menu, tearoff=0, font=('Arial', 12))
        self.settings_menu.add_cascade(label="Выбор движка", menu=self.engine_submenu)
        self.btn_settings.config(menu=self.settings_menu)
        self.btn_settings.pack(side='left', padx=3)

        tk.Button(self.bottom_row_frame, text="Выход", command=self.on_close,
                  font=('Arial', 12, 'bold'), bg='#b84a4a', fg='white',
                  padx=3, pady=1).pack(side='right', padx=3)

    def _build_status_row(self):
        """Строка статусных сообщений внизу окна (с кнопками прокрутки) и скрытая полоса прогресса."""
        # --- Строка статусных сообщений (перенесена в самый низ окна, под всеми
        #     тремя панелями). Пакуется ДО main_paned, хотя визуально она внизу:
        #     у неё side='bottom', а main_paned ниже упаковывается с
        #     expand=True/fill=BOTH и должен занять всё оставшееся место, поэтому
        #     все "некэкспандящиеся" строки (верхняя строка поиска и эта строка
        #     статуса) должны быть упакованы раньше него. ---
        self.status_row_frame = tk.Frame(self.root, bg='#d4e8f7')
        self.status_row_frame.pack(fill=tk.X, padx=10, pady=(0, 8), side='bottom')
        self.status_row_frame.columnconfigure(0, weight=1)
        self.status_row_frame.columnconfigure(1, weight=0)

        status_frame = tk.Frame(self.status_row_frame, bg='#d4e8f7')
        status_frame.grid(row=0, column=0, sticky='we', padx=5)
        status_frame.columnconfigure(0, weight=0)
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(2, weight=0)

        self.scroll_left_btn = tk.Button(status_frame, text="◄", command=self._scroll_left,
                                         font=('Arial', 10), bg='#d4e8f7', fg='#1a4a7a',
                                         relief='flat', borderwidth=1, padx=2, pady=0)
        self.scroll_left_btn.grid(row=0, column=0, sticky='ns')

        self.status_entry = tk.Entry(status_frame, state='readonly', relief='flat', borderwidth=0,
                                     font=('Arial', 12), fg='#1a4a7a', bg='#d4e8f7')
        self.status_entry.grid(row=0, column=1, sticky='we', padx=2)

        self.scroll_right_btn = tk.Button(status_frame, text="►", command=self._scroll_right,
                                          font=('Arial', 10), bg='#d4e8f7', fg='#1a4a7a',
                                          relief='flat', borderwidth=1, padx=2, pady=0)
        self.scroll_right_btn.grid(row=0, column=2, sticky='ns')

        self.progress_bar = ttk.Progressbar(self.status_row_frame, orient='horizontal', length=200, mode='determinate')
        self.progress_bar.grid(row=0, column=1, sticky='we', padx=5)
        self.progress_bar.grid_remove()

    def _build_left_panel(self, main_paned):
        """Левая часть: верхняя и нижняя панели «Совпадения» (нижняя — только в режиме разделения)."""
        # Ширина левой панели — на 15% шире прежних 196px (14% от ширины окна
        # при запуске, см. root.geometry("1400x750") в sp.py).
        left_frame = ttk.Frame(main_paned, width=225)
        main_paned.add(left_frame, weight=0)
        left_frame.config(width=225)

        # Верхняя и нижняя панель "Совпадения" — вторая используется только в
        # режиме разделения окна результатов (см. _update_split_view_layout),
        # когда выбраны индексы двух Excel-файлов и разделение включено в
        # настройках.
        self.word_panel_top_frame = tk.Frame(left_frame)
        self.word_panel_top_frame.pack(fill='both', expand=True)
        self.word_panel = WordPanel(self.word_panel_top_frame, self)

        self.word_panel_bottom_frame = tk.Frame(left_frame)
        self.word_panel_2 = WordPanel(self.word_panel_bottom_frame, self)
        # Нижняя панель не показывается сразу — только когда включится режим
        # разделения (см. _update_split_view_layout).

    def _build_center_panel(self, main_paned):
        """Центральная часть: полоса навигации по страницам и окна результатов."""
        center_frame = ttk.Frame(main_paned)
        main_paned.add(center_frame, weight=4)
        self._build_nav_bar(center_frame)
        self.layer_bar = LayerBar(self)
        self.layer_bar.build(center_frame)
        self._build_results_area(center_frame)

    def _build_nav_bar(self, center_frame):
        """Навигация по страницам результатов и кнопки «Ч», «КП», «Кратко», «−В»."""
        # --- Навигация по страницам результатов (перенесена наверх, на уровень
        #     надписей "Совпадения:" и "Индексы:" левой/правой панелей) ---
        nav_frame = tk.Frame(center_frame, bg='#d4e8f7')
        nav_frame.pack(side='top', fill=tk.X, padx=5, pady=(5, 5))

        self.btn_first = NavButton(nav_frame, text="<< В начало", command=self.go_to_first_page,
                                   font=('Arial', 12, 'bold'), fg='white',
                                   padx=3, pady=1, state='disabled')
        self.btn_first.pack(side='left', padx=3)

        self.btn_back = NavButton(nav_frame, text="◀ Назад", command=self.page_back,
                                  font=('Arial', 12, 'bold'), fg='white',
                                  padx=3, pady=1, state='disabled')
        self.btn_back.pack(side='left', padx=(80, 3))

        self.btn_forward = NavButton(nav_frame, text="Вперед ▶", command=self.page_forward,
                                     font=('Arial', 12, 'bold'), fg='white',
                                     padx=3, pady=1, state='disabled')
        self.btn_forward.pack(side='left', padx=(3, 80))

        self.btn_last = NavButton(nav_frame, text="В конец >>", command=self.go_to_last_page,
                                  font=('Arial', 12, 'bold'), fg='white',
                                  padx=3, pady=1, state='disabled')
        self.btn_last.pack(side='left', padx=3)

        # Ширина одной "позиции" (знака) шрифта кнопок — в ней заданы сдвиг и
        # ширина ниже (см. nav_toggle_layout).
        import tkinter.font as tkfont
        char_w = tkfont.Font(root=self.root, font=('Arial', 12, 'bold')).measure('0')

        # "Ч" — подчеркнуть выделенное в окне результатов (как в Word; повторно —
        # снять). Стоит посередине между "В конец" и переключателем "Кратко"/"Всё".
        self.btn_underline = tk.Button(nav_frame, text="Ч", command=self._toggle_underline,
                                       font=('Arial', 12, 'bold underline'), bg='#6a4a8a', fg='white',
                                       padx=6, pady=1)
        # "КП" (синяя) — справа от "Ч": добавить выделенное слово в словарь ключевых
        # понятий (см. _add_key_concept). Берём её РЕАЛЬНУЮ ширину, чтобы вычесть из
        # отступов (см. nav_toggle_layout); если Tk её ещё не посчитал — прикидка.
        self.btn_key_concepts = tk.Button(nav_frame, text="КП", command=self._add_key_concept,
                                          font=('Arial', 12, 'bold'), bg='#2a6fbf', fg='white',
                                          padx=6, pady=1)
        kp_w = self.btn_key_concepts.winfo_reqwidth()
        if kp_w <= 1:
            kp_w = round(4.5 * char_w)
        toggle_layout = nav_toggle_layout(char_w, kp_w)
        self.btn_underline.pack(side='left', padx=toggle_layout['underline_padx'])
        ToolTip(self.btn_underline, "Подчеркнуть")
        self.btn_key_concepts.pack(side='left', padx=toggle_layout['kp_padx'])
        ToolTip(self.btn_key_concepts, "Ключевые понятия")

        # Переключатель "Кратко"/"Всё" (надпись — то, во что он переключит).
        # Шире и левее прежнего — см. nav_toggle_layout.
        self.btn_brief_toggle = tk.Button(nav_frame, text="Кратко", command=self.toggle_brief_mode,
                                          font=('Arial', 12, 'bold'), bg='#4a7a8a', fg='white',
                                          padx=3, pady=1, width=toggle_layout['brief_width'])
        self.btn_brief_toggle.pack(side='left', padx=toggle_layout['brief_padx'])
        # Подсказка читает надпись кнопки в момент показа (см. _brief_tooltip_text).
        ToolTip(self.btn_brief_toggle, self._brief_tooltip_text)

        # "−В/+В" — исключить/вернуть явные словоформы одного и того же
        # слова в окне "Совпадения" (см. toggle_word_variations). Справа,
        # над средним окном; появляется/прячется вместе с кнопкой "3D/2D"
        # у самого окна "Совпадения" — см. ui/word_panel.py,
        # show_3d_button/hide_3d_button.
        self.btn_variations_toggle = tk.Button(
            nav_frame, text="−В", command=self.toggle_word_variations,
            font=('Arial', 12, 'bold'), bg='#6a4a8a', fg='white', padx=3, pady=1
        )
        # Подсказка следует за кнопкой: текст берётся в момент показа (см.
        # _variations_tooltip_text), а не при создании.
        ToolTip(self.btn_variations_toggle, self._variations_tooltip_text)
        # Не пакуется здесь — show_variations_button()/hide_variations_button() управляют видимостью.

    def _build_results_area(self, center_frame):
        """Верхнее и нижнее окна результатов, подписи файлов, холст 2D-визуализации и привязки мыши."""
        # Верхнее и нижнее окно результатов — второе используется только в
        # режиме разделения (см. _set_split_view_active). ttk.PanedWindow
        # даёт пользователю возможность перетаскивать границу между ними;
        # изначально при включении режима разделения выставляется поровну.
        self.results_paned = ttk.PanedWindow(center_frame, orient=tk.VERTICAL)
        self.results_paned.pack(side='top', fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.results_top_frame = tk.Frame(self.results_paned, bg='#d4e8f7')
        self.results_paned.add(self.results_top_frame, weight=1)

        self.results_bottom_frame = tk.Frame(self.results_paned, bg='#d4e8f7')
        # Не добавляется в results_paned сразу — только в режиме разделения.

        # Подпись "имя-алиас" файла-источника над верхней панелью — видна
        # только в режиме разделения (в обычном режиме об этом уже сказано
        # в шапке каждого топика, повторять тут не нужно).
        self.results_top_label = tk.Label(self.results_top_frame, text="",
                                          font=('Arial', 10, 'bold'),
                                          bg='#d4e8f7', fg='#1a4a7a', anchor='w')
        # Не пакуется сразу — показывается только в режиме разделения.

        self.result_text = scrolledtext.ScrolledText(
            self.results_top_frame, wrap=tk.WORD, font=("Consolas", self.font_size)
        )
        self.result_text.pack(side='top', fill=tk.BOTH, expand=True)

        # Canvas для 2D-визуализации векторной близости слов (кнопка
        # "3D/2D" у окна "Совпадения") — та же область среднего окна, что
        # у result_text: показываем один из двух, никогда оба одновременно
        # (см. show_vector_visualization_2d/hide_vector_visualization).
        self.vector_viz_canvas = tk.Canvas(self.results_top_frame, bg='white', highlightthickness=0)

        self.result_text.tag_configure("highlight", background="#FFFF00", selectforeground="black")
        self.result_text.tag_configure("partial", background="#FFFF99", selectforeground="black")
        self.result_text.tag_configure("hyperlink", foreground="blue", underline=True)
        self.result_text.tag_bind("hyperlink", "<Enter>", lambda e: self.result_text.config(cursor="hand2"))
        self.result_text.tag_bind("hyperlink", "<Leave>", lambda e: self.result_text.config(cursor=""))
        self.result_text.tag_bind("hyperlink", "<Button-1>", self.on_hyperlink_click)
        self.result_text.bind('<Button-3>', self.append_selection_to_conspect)

        # Подпись "имя-алиас" для нижней панели — аналогично, видна только в
        # режиме разделения.
        self.results_bottom_label = tk.Label(self.results_bottom_frame, text="",
                                             font=('Arial', 10, 'bold'),
                                             bg='#d4e8f7', fg='#1a4a7a', anchor='w')
        # Не пакуется сразу — показывается только в режиме разделения.

        # Нижнее окно результатов — используется только в режиме разделения
        # (два выбранных Excel-индекса + включённая настройка). В этом режиме
        # шапок и гиперссылок нет (см. ResultsRenderer/SearchController), так
        # что тег "hyperlink" здесь не нужен.
        self.result_text_2 = scrolledtext.ScrolledText(
            self.results_bottom_frame, wrap=tk.WORD, font=("Consolas", self.font_size)
        )
        self.result_text_2.pack(side='top', fill=tk.BOTH, expand=True)
        self.result_text_2.tag_configure("highlight", background="#FFFF00", selectforeground="black")
        self.result_text_2.tag_configure("partial", background="#FFFF99", selectforeground="black")
        self.result_text_2.bind('<Button-3>', self.append_selection_to_conspect)

    def _build_right_panel(self, main_paned):
        """Правая часть: список индексов, список файлов и кнопки «Редактировать»/«Собрать базу»."""
        # --- Правая панель ---
        # Ширина увеличена до значения, которое умещает самую широкую строку
        # кнопок целиком (нижнюю — "Собрать базу" + список движков), плюс
        # ещё +5% от ширины окна за счёт центральной панели (по просьбе).
        right_frame = ttk.Frame(main_paned, width=355)
        main_paned.add(right_frame, weight=0)
        right_frame.config(width=355)
        # Без этого содержимое (кнопки, список индексов, список файлов) может
        # "раздуть" ширину панели сверх 320px, если сумма естественных ширин
        # элементов внутри больше этого значения (та же причина, по которой
        # раньше раздувалась левая панель "Совпадения" — см. ui/word_panel.py).
        right_frame.pack_propagate(False)
        self._build_index_section(right_frame)
        self._build_files_section(right_frame)
        self._build_prepare_buttons(right_frame)

    def _build_index_section(self, right_frame):
        """Заголовок с кнопками и список индексов с чекбоксами."""
        top_right_frame = ttk.Frame(right_frame)
        top_right_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Заголовок и кнопки в одной строке ---
        header_frame = tk.Frame(top_right_frame, bg='#d4e8f7')
        header_frame.pack(fill=tk.X, pady=2)

        tk.Label(header_frame, text="Индексы:", font=('Arial', 12, 'bold'),
                 bg='#d4e8f7', fg='#1a4a7a').pack(side='left')

        self.selected_count_label = tk.Label(header_frame, text="(0)",
                                             font=('Arial', 12, 'bold'),
                                             bg='#d4e8f7', fg='#1a4a7a')
        self.selected_count_label.pack(side='left', padx=(4, 8))

        btn_select_all = tk.Button(header_frame, text="Все", command=self._toggle_select_all,
                                   bg='#4a7a8a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_select_all.pack(side='left', padx=5)

        btn_delete_selected = tk.Button(header_frame, text="Удалить",
                                        command=lambda: self._delete_selected_indices(from_button=True),
                                        bg='#b84a4a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_delete_selected.pack(side='left', padx=2)

        # "Облако тегов" — не требует никакой обученной векторной модели,
        # только сам текст отмеченных книг (одной или нескольких сразу),
        # поэтому кнопка рядом со списком индексов, а не привязана к
        # "3D/2D" (та появляется только при активной модели).
        btn_word_cloud = tk.Button(header_frame, text="Т",
                                   command=self.viz.show_word_cloud_for_selected,
                                   bg='#6a4a8a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_word_cloud.pack(side='left', padx=2)
        ToolTip(btn_word_cloud, "Облако тегов — самые частые слова отмеченных книг")

        # TextRank — тоже не требует векторной модели, только текст; в
        # отличие от облака тегов (частота) здесь "центральность" — слово
        # важно не потому, что частое само по себе, а потому что стоит
        # рядом с другими важными словами (тот же принцип, что у PageRank).
        btn_textrank = tk.Button(header_frame, text="Ц",
                                 command=self.viz.show_textrank_for_selected,
                                 bg='#6a4a8a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_textrank.pack(side='left', padx=2)
        ToolTip(btn_textrank, "Центральные понятия — главные слова текста отмеченных книг (TextRank)")

        # --- Список индексов с чекбоксами ---
        self.index_check_list = IndexCheckList(
            top_right_frame,
            selection_callback=None,
            single_select=(getattr(self.engine, 'engine_type', 'fts5') == 'fts5')
        )
        self.index_check_list.pack(fill=tk.BOTH, expand=True)

    def _build_files_section(self, right_frame):
        """Заголовок с кнопками «В индекс»/«Векторы» и список файлов."""
        bottom_right_frame = ttk.Frame(right_frame)
        bottom_right_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        header_frame2 = tk.Frame(bottom_right_frame, bg='#d4e8f7')
        header_frame2.pack(fill=tk.X, pady=2)
        tk.Label(header_frame2, text="Файлы:", font=('Arial', 12, 'bold'),
                 bg='#d4e8f7', fg='#1a4a7a').pack(side='left')
        btn_add_index = tk.Button(header_frame2, text="▲ В индекс", command=self._add_to_index,
                                  bg='#6a4a8a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_add_index.pack(side='left', padx=3)
        btn_vectors = tk.Button(header_frame2, text="▲ Векторы", command=self.prepare_vectors,
                                bg='#6a4a8a', fg='white', font=('Arial', 12, 'bold'), padx=3, pady=1)
        btn_vectors.pack(side='left', padx=3)

        self.text_listbox = tk.Listbox(
            bottom_right_frame,
            font=('Consolas', self.font_size),
            bg='white',
            fg='#1a2a3a',
            selectmode=tk.EXTENDED
        )
        self.text_listbox.pack(fill=tk.BOTH, expand=True)
        self.text_listbox.bind('<<ListboxSelect>>', self._on_text_select)
        self.text_listbox.bind('<Button-3>', self._on_text_right_click)

    def _build_prepare_buttons(self, right_frame):
        """Кнопки «Редактировать» и «Собрать базу» внизу правой панели."""
        prepare_frame = tk.Frame(right_frame, bg='#d4e8f7')
        prepare_frame.pack(fill=tk.X, padx=5, pady=5)
        # Пиктограмма обновления крупнее, а сама кнопка остаётся прежнего размера: кнопка лежит в рамке
        # фиксированного размера (ширина — в 1,5 раза больше, чем у кнопки с глифом шрифта 12, высота — как у соседней кнопки).
        refresh_box = tk.Frame(prepare_frame, bg='#d4e8f7')
        btn_refresh = tk.Button(refresh_box, text="\u21bb", command=self._refresh_lists,
                                font=('Arial', 16, 'bold'), bg='#6a4a8a', fg='white',
                                padx=0, pady=0)
        btn_refresh.pack(fill='both', expand=True)
        ToolTip(btn_refresh, "Обновить список файлов")
        btn_edit = tk.Button(prepare_frame, text="Редактировать", command=self._open_selected_file,
                             font=('Arial', 12, 'bold'), bg='#6a4a8a', fg='white',
                             padx=3, pady=1)
        try:
            from tkinter import font as tkfont
            btn_edit.update_idletasks()
            height = btn_edit.winfo_reqheight()
            width = (tkfont.Font(family='Arial', size=12, weight='bold').measure("\u21bb") + 6
                     + 2 * (int(btn_refresh.cget('borderwidth')) + int(btn_refresh.cget('highlightthickness'))))
            width = int(width * 1.5)   # шире прежней в полтора раза
            if height > 1 and width > 1:
                refresh_box.configure(width=width, height=height)
                refresh_box.pack_propagate(False)
        except Exception:
            pass   # не вышло измерить — кнопка просто примет естественный размер
        refresh_box.pack(side='left', padx=(0, 5))
        btn_edit.pack(side='left')
        tk.Button(prepare_frame, text="Собрать базу", command=self.open_file_merger,
                  font=('Arial', 12, 'bold'), bg='#6a4a8a', fg='white',
                  padx=3, pady=1).pack(side='left', padx=(5, 0))

    def _refresh_lists(self):
        """Кнопка обновления: перечитывает mconfig.ini (псевдонимы баз) и заново
           строит список файлов (DB и рабочая папка) и список индексов — чтобы не
           перезапускать программу после правки настроек или добавления файлов."""
        try:
            self.config.reload()   # на месте: self.config_dict и менеджеры видят свежие данные
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось перечитать настройки:\n{e}", parent=self.root)
            return
        bases = self.config.get('bases', {})
        if bases is not self.config_dict:
            self.config_dict = bases
            for mgr in (self.file_manager, self.index_manager):
                mgr.config_dict = bases
        # Сохраняем выделение в списке файлов — по самому файлу, а не по тексту строки:
        # после смены псевдонима строка выглядит иначе.
        entries = getattr(self.file_manager, '_listed_entries', {}) or {}
        selected = {entries.get(self.text_listbox.get(i)) for i in self.text_listbox.curselection()}
        selected.discard(None)
        self.update_text_list()
        if selected:
            entries = getattr(self.file_manager, '_listed_entries', {}) or {}
            for i in range(self.text_listbox.size()):
                if entries.get(self.text_listbox.get(i)) in selected:
                    self.text_listbox.selection_set(i)
        self.file_manager.on_text_select(None)
        self.index_manager.index_display_map.clear()
        self.update_index_list()
        self._update_log_field("Списки файлов и индексов обновлены")

    # ---------- Методы-обёртки для сервисов ----------
    def update_index_list(self):
        self.index_manager.update_index_list()

    def update_text_list(self):
        self.file_manager.update_text_list()

    def _add_to_index(self):
        self.file_manager.add_to_index(
            show_progress_callback=self._show_progress,
            update_progress_callback=self._update_progress,
            hide_progress_callback=self._hide_progress
        )

    def _open_selected_file(self):
        opened = self.file_manager.open_selected_file()
        # Нумератор разбивки включается только если файл действительно открыт
        # и в mconfig.ini [Settings] стоит enable_numerator_on_update = 1.
        if opened and self.config.get('enable_numerator_on_update', False):
            self._activate_numerator()

    def _activate_numerator(self):
        """Включает F7 (вызов диалога нумератора поверх любой программы) и на
           полсекунды показывает подсказку. Повторное нажатие "Редактировать"
           безопасно: уже включённый нумератор остаётся как был, подсказка
           показывается снова."""
        if self.numerator is None:
            self.numerator = NumeratorController(
                self.root,
                status_callback=self._update_log_field,
                notify_callback=lambda text, ms: self._show_temporary_notification(text, duration_ms=ms),
                open_dialog_callback=lambda controller: show_numerator_dialog(self.root, controller),
            )
        if self.numerator.activate():
            self._show_temporary_notification("F7 — вызов нумератора", duration_ms=500)
        elif self.numerator.last_error:
            # В строке состояния причина тоже есть, но самое вероятное — не
            # установлены библиотеки — требует действия пользователя, и строку
            # состояния он мог не заметить.
            messagebox.showwarning("Нумератор разбивки", self.numerator.last_error)

    def _on_text_select(self, event):
        self.file_manager.on_text_select(event)

    def _on_text_right_click(self, event):
        self.file_manager.on_text_right_click(event)

    def _set_split_view_active(self, active: bool):
        """Показывает/скрывает нижнее окно результатов и нижнюю панель
           "Совпадения" — вызывается search_controller-ом при каждом поиске,
           когда он определяет, включён ли режим разделения (настройка +
           выбраны ровно два индекса)."""
        if active == self.split_view_active:
            return
        self.split_view_active = active
        if active:
            self.results_paned.add(self.results_bottom_frame, weight=1)
            self.word_panel_bottom_frame.pack(fill='both', expand=True)
            # before=... — иначе подпись, упакованная после уже занявшего
            # всё место (expand=True) result_text, была бы сжата до нуля
            # (та же ловушка порядка pack, что была со скроллбаром списка
            # индексов).
            self.results_top_label.pack(side='top', fill=tk.X, padx=3, pady=(2, 0),
                                        before=self.result_text)
            self.results_bottom_label.pack(side='top', fill=tk.X, padx=3, pady=(2, 0),
                                           before=self.result_text_2)
            # Разделитель между окнами выставляется точно посередине только
            # после того, как paned window получит свой реальный размер —
            # непосредственно после .add() высота ещё не определена.
            self.root.after(50, self._center_results_sash)
        else:
            self.results_paned.forget(self.results_bottom_frame)
            self.word_panel_bottom_frame.pack_forget()
            self.results_top_label.pack_forget()
            self.results_bottom_label.pack_forget()

    def _center_results_sash(self):
        try:
            height = self.results_paned.winfo_height()
            if height > 1:
                self.results_paned.sashpos(0, height // 2)
        except tk.TclError:
            pass

    def _on_index_selection_changed(self, selected):
        """В режиме просмотра одного файла ("**" в поле поиска) смена отмеченных
           индексов сразу показывает новый файл — или пояснение, если отмечен не
           один подходящий индекс. Иначе окно продолжало бы показывать прежний
           файл при уже другом отмеченном, а Manticore результаты при смене
           индекса сам не очищает."""
        entry = getattr(self, 'query_entry', None)
        if entry is not None and entry.get().strip() == self.search_controller.BROWSE_QUERY:
            self.do_search()

    def _clear_results(self):
        self.search_controller.exit_browse_mode()
        self.word_panel.clear()
        self.result_text.delete(1.0, tk.END)
        self.search_controller.all_filtered_topics = []
        self.search_controller.all_filtered_topics_b = []
        self.search_controller.results_page = 0
        self.search_controller.is_viewing_file = False
        self.search_controller.saved_state = {}
        self.btn_back.config(state='disabled')
        self.btn_forward.config(state='disabled')
        self.btn_first.config(state='disabled')
        self.btn_last.config(state='disabled')
        self.excluded_words.clear()
        self.word_panel_2.clear()
        self.result_text_2.delete(1.0, tk.END)
        self._set_split_view_active(False)
        self._show_help_text()

    def _toggle_select_all(self):
        self.index_manager.toggle_select_all()

    def _delete_selected_indices(self, event=None, from_button=False):
        if not from_button:
            focused = self.root.focus_get()
            if focused in (self.query_entry, self.result_text, self.text_listbox):
                return
        self.index_manager.delete_selected_indices()

    # ---------- Управление прогресс-баром ----------
    def _show_progress(self, max_value=100, initial=0, mode='determinate'):
        self.status_row_frame.columnconfigure(1, weight=1)
        self.progress_bar.grid()
        self.progress_bar['mode'] = mode
        if mode == 'determinate':
            self.progress_bar['maximum'] = max_value
            self.progress_bar['value'] = initial
        self.root.update()

    def _update_progress(self, value):
        self.progress_bar['value'] = value
        self.root.update()

    def _hide_progress(self):
        self.progress_bar.grid_remove()
        self.status_row_frame.columnconfigure(1, weight=0)
        self.root.update()

    def _show_training_banner(self, text):
        """Небольшое информационное окно без кнопок — появляется на время
           обучения/дообучения модели и закрывается сама собой, как только
           оно завершится (вызывающий код делает это в finally). Сам вызов
           train()/continue_train() синхронный (блокирует интерфейс), так
           что окно показывается и прячется ровно на время этой блокирующей
           операции — никакой отдельной логики закрытия по таймеру не
           нужно.

           Возвращает (banner, cancel_check) — cancel_check передаётся в
           train()/continue_train(): при каждом вызове "прокачивает" цикл
           событий Tkinter (иначе нажатие Esc просто осталось бы в очереди
           необработанных событий до следующего update() — а обучение
           вызывает его не на каждой эпохе, реже) и возвращает, было ли
           запрошено прерывание."""
        banner = tk.Toplevel(self.root)
        banner.title("Векторы")
        banner.resizable(False, False)
        banner.transient(self.root)
        tk.Label(banner, text=text, font=('Arial', 13, 'bold'), padx=30).pack(pady=(20, 5))
        tk.Label(banner, text="(Esc — прервать)", font=('Arial', 10), fg='#777777').pack(pady=(0, 15))
        banner.update_idletasks()
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - banner.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - banner.winfo_height()) // 2
            banner.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

        cancel_state = {'requested': False}

        def on_escape(event=None):
            print("⌨️ Esc нажат — прерывание запрошено")
            cancel_state['requested'] = True

        banner.bind('<Escape>', on_escape)
        self.root.bind('<Escape>', on_escape)
        banner.focus_set()
        banner.update()

        check_count = [0]

        def cancel_check():
            check_count[0] += 1
            try:
                self.root.update()
            except tk.TclError:
                pass
            if cancel_state['requested']:
                print(f"⏹ Прерывание обнаружено (проверка №{check_count[0]})")
            return cancel_state['requested']

        return banner, cancel_check

    def _hide_training_banner(self, banner):
        try:
            self.root.unbind('<Escape>')
        except tk.TclError:
            pass
        try:
            banner.destroy()
        except tk.TclError:
            pass

    def _selected_results_text(self):
        """Выделенный мышью текст в окне результатов (в режиме разделения — в любой
           из двух панелей) либо None."""
        for widget in (self.result_text, getattr(self, 'result_text_2', None)):
            if widget is None or not widget.winfo_ismapped():
                continue
            ranges = widget.tag_ranges("sel")
            if ranges:
                return widget.get(ranges[0], ranges[1])
        return None

    def _add_key_concept(self):
        """Кнопка "КП": выделенное в среднем окне слово — в словарь ключевых
           понятий (файл key_concepts.txt рядом с mconfig.ini, по слову на строке,
           строчными; можно править вручную). Слов должно быть ровно одно — выделенное
           предложение случайно не засорит словарь. Словарь нужен параметру
           key_concepts_only (см. _key_concept_words)."""
        if self.vector_viz_canvas.winfo_ismapped():
            self._show_temporary_notification("Откройте окно результатов", duration_ms=900)
            return
        selected = self._selected_results_text()
        if selected is None:
            self._show_temporary_notification("Выделите слово", duration_ms=900)
            return
        words = key_concepts.extract_words(selected)
        if not words:
            self._show_temporary_notification("Выделено не слово", duration_ms=900)
            return
        if len(words) > 1:
            self._show_temporary_notification("Выделите одно слово", duration_ms=900)
            return
        word = words[0]
        try:
            added = key_concepts.add_key_concept(KEY_CONCEPTS_FILE, word)
        except OSError as e:
            messagebox.showerror("Ключевые понятия",
                                 f"Не удалось записать словарь:\n{KEY_CONCEPTS_FILE}\n\n{e}")
            return
        shown = word if len(word) <= 20 else word[:19] + "…"
        if added:
            self._show_temporary_notification(f"Добавлено: {shown}", duration_ms=900)
            self._update_log_field(f"Ключевое понятие добавлено: {word}")
        else:
            self._show_temporary_notification(f"Уже в словаре: {shown}", duration_ms=900)

    def _key_concept_words(self):
        """None — фильтр выключен (параметр key_concepts_only = 0 в mconfig.ini).
           Иначе — слова словаря ключевых понятий (список может быть пустым: словарь
           ещё не заведён или не читается — вызывающий код скажет об этом)."""
        if not self.config.get('key_concepts_only', False):
            return None
        try:
            return key_concepts.load_key_concepts(KEY_CONCEPTS_FILE)
        except OSError as e:
            print(f"⚠️ Не удалось прочитать словарь ключевых понятий: {e}")
            return []

    def _warn_key_concepts_empty(self, title):
        messagebox.showinfo(
            title,
            "Включён параметр key_concepts_only, но словарь ключевых понятий пуст.\n\n"
            "Добавьте слова кнопкой «КП» (выделите слово в окне результатов) или "
            "выключите параметр в mconfig.ini.\n\n"
            f"Файл словаря: {KEY_CONCEPTS_FILE}", height=360)

    def _toggle_underline(self):
        """Кнопка "Ч" над окном результатов: подчёркивает выделенное мышью (как
           подчёркивание в Word); если всё выделенное уже подчёркнуто — снимает.
           Отметки хранятся в marks.db рядом с mconfig.ini (services/marks.py) и
           показываются при любой последующей работе с этим текстом — в
           результатах поиска (в том числе в кратком режиме) и при просмотре
           файла."""
        if getattr(self.search_controller, 'split_mode_active', False):
            self._show_temporary_notification("Нет в режиме разделения", duration_ms=900)
            return
        if self.vector_viz_canvas.winfo_ismapped():
            self._show_temporary_notification("Откройте окно результатов", duration_ms=900)
            return
        try:
            status, _count = self.results_renderer.toggle_underline()
        except Exception as e:
            messagebox.showerror("Подчёркивание", f"Не удалось сохранить отметку:\n{e}")
            return
        hints = {
            'no_selection': "Сначала выделите текст",
            'outside': "Выделите текст внутри блока",
            'empty': "Выделены только пробелы",
            'unsupported': "Здесь подчёркивание недоступно",
            'unavailable': "Хранилище отметок недоступно",
        }
        if status in hints:
            self._show_temporary_notification(hints[status], duration_ms=900)
        elif status == 'added':
            self._update_log_field("✏️ Подчёркнуто")
        elif status == 'removed':
            self._update_log_field("Подчёркивание снято")

    def _sync_folder(self):
        try:
            with open(SYNC_FOLDER_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''

    def choose_sync_folder(self):
        """Настройки → "Папка синхронизации…": папка Google Диска (та же, что выбрана на телефоне)."""
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Папка синхронизации (Google Диск)", initialdir=self._sync_folder() or None)
        if not path:
            return
        with open(SYNC_FOLDER_FILE, 'w', encoding='utf-8') as f:
            f.write(path)
        messagebox.showinfo("Синхронизация", f"Папка выбрана:\n{path}\n\nТеперь: Настройки → Синхронизировать с телефоном.")

    def _ensure_diary(self):
        """Дневник DB/dnev.txt: при первом запуске создаётся пустым (если папки или файла нет)."""
        try:
            os.makedirs(os.path.dirname(DIARY_FILE), exist_ok=True)
            if not os.path.exists(DIARY_FILE):
                open(DIARY_FILE, 'ab').close()
        except OSError as e:
            print(f"⚠️ Не удалось создать дневник: {e}")

    def sync_with_phone(self):
        """Настройки → "Синхронизировать с телефоном": только вручную. Подчёркивания (включая снятие), конспект и дневник
           сливаются с файлами папки Google Диска; тот же обмен делает кнопка в Синева Mobile. Идёт в фоне, пока
           открыто окно «Синхронизация» (оно не даёт работать дальше); по окончании — итог в том же окне."""
        import threading
        from services import sync_folder
        if getattr(self, '_sync_win', None) is not None:
            return
        folder = self._sync_folder()
        if not folder:
            messagebox.showinfo("Синхронизация", "Сначала выберите папку: Настройки → Папка синхронизации…")
            return
        self._ensure_diary()
        win = tk.Toplevel(self.root)
        win.title("Синхронизация")
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)            # пока идёт обмен, закрыть нельзя
        label = tk.Label(win, text="Идёт синхронизация…\nПодождите, не закрывайте программу.", padx=30, pady=18,
                         font=("Segoe UI", 11))
        label.pack()
        bar = ttk.Progressbar(win, mode='indeterminate', length=260)
        bar.pack(padx=20, pady=(0, 12))
        bar.start(12)
        button = tk.Button(win, text="Готово", state='disabled', width=12, command=lambda: self._sync_close())
        button.pack(pady=(0, 14))
        self._sync_win = win
        try:
            win.grab_set()
        except Exception:
            pass
        box = {}

        def work():
            try:
                box['rep'] = sync_folder.sync_with_folder(folder, self.marks_store, CONSPECT_FILE, SYNC_BASE_DIR, DIARY_FILE)
            except Exception as e:
                box['err'] = e

        thread = threading.Thread(target=work, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.root.after(150, poll)
                return
            bar.stop()
            if 'err' in box:
                label.config(text=f"Синхронизация не удалась:\n{box['err']}")
            else:
                rep = box['rep']
                try:
                    self.results_renderer.apply_marks()
                except Exception:
                    pass
                if rep['texts_changed']:
                    self.update_text_list()
                label.config(text=("Синхронизация завершена.\n"
                                   f"Подчёркиваний: +{rep['marks_added']}, −{rep['marks_removed']}\n"
                                   f"Размер, цвет, мысли: +{rep['extra_added']}, −{rep['extra_removed']}\n"
                                   f"Файлов обновлено здесь: {len(rep['texts_changed'])}, в папке: {len(rep['texts_pushed'])}"))
            button.config(state='normal')

        self.root.after(150, poll)

    def _sync_close(self):
        win, self._sync_win = getattr(self, '_sync_win', None), None
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

    def export_underlined(self):
        """Настройки → "Экспорт подчеркнутых": все подчёркнутые фрагменты — одним
           документом Word в папку DB (по разделу на файл-источник, подчёркнутое
           подчёркнуто, окружение серым)."""
        try:
            marks = self.marks_store.all_marks()
        except Exception as e:
            messagebox.showerror("Экспорт подчеркнутых", f"Не удалось прочитать отметки:\n{e}")
            return
        if not marks:
            messagebox.showinfo("Экспорт подчеркнутых",
                                "Подчёркнутых фрагментов пока нет.\n\n"
                                "Выделите текст в окне результатов и нажмите «Ч».")
            return
        from datetime import datetime
        os.makedirs('DB', exist_ok=True)
        path = os.path.join('DB', datetime.now().strftime("Подчёркнутое %Y-%m-%d %H-%M-%S.docx"))
        try:
            export_marks_docx(marks, path)
        except Exception as e:
            messagebox.showerror("Экспорт подчеркнутых", f"Не удалось сохранить файл:\n{e}")
            return
        self.update_text_list()  # новый файл появился в DB
        if messagebox.askyesno("Экспорт подчеркнутых",
                               f"Сохранено: {path}\nФрагментов: {len(marks)}\n\nОткрыть файл?"):
            try:
                if sys.platform == 'win32':
                    os.startfile(path)
                else:
                    subprocess.Popen(['xdg-open', path])
            except Exception as e:
                messagebox.showerror("Экспорт подчеркнутых", f"Не удалось открыть файл:\n{e}")

    def _variations_tooltip_text(self):
        """Подсказка кнопки "−В/+В": по надписи на ней видно, что кнопка сделает
           при нажатии СЕЙЧАС. "−В" — варианты слов сейчас показаны, нажатие
           их уберёт; "+В" — они убраны, нажатие вернёт."""
        if self.btn_variations_toggle.cget('text').startswith('+'):
            return "Плюс варианты слова"
        return "Минус варианты слова"

    def show_variations_button(self):
        self.btn_variations_toggle.pack(side='right', padx=(3, 10))

    def hide_variations_button(self):
        self.btn_variations_toggle.pack_forget()

    def toggle_word_variations(self):
        """Кнопка "−В/+В": "−В" — исключить из окна "Совпадения" (и из
           открытой визуализации, если она есть) явные словоформы одного и
           того же слова (например, "равновесие"/"равновесием"/
           "равновесию") — из каждой такой группы остаётся только самый
           рейтинговый представитель, а освободившееся место занимают
           следующие по рейтингу, НЕ являющиеся словоформами уже
           показанных, — пока не наберётся vector_model_topn слов (см.
           VectorModelManager.get_neighbors_deduplicated). "+В" — вернуть
           обычный, полный список (с словоформами).

           Состояние (self._variations_excluded) хранится тут и читается
           через колбэк в SearchController — так оно не "забывается" на
           следующем запросе другим словом, а не только для текущего
           поиска."""
        query_word = getattr(self.word_panel, '_last_query_word', None)
        vector_key = getattr(self.word_panel, '_last_vector_key', None)
        if not query_word or not vector_key:
            return

        self._variations_excluded = not self._variations_excluded
        self.btn_variations_toggle.config(text="+В" if self._variations_excluded else "−В")

        # do_search() сам скрывает визуализацию в начале (обычное
        # поведение для любого поиска) — запоминаем, была ли она открыта,
        # ДО этого вызова, иначе к моменту проверки она уже будет скрыта.
        was_showing_viz = self.vector_viz_canvas.winfo_ismapped()
        # Перезапускаем тот же запрос — do_search() сам заново спросит variations_excluded_callback и
        # получит нужный (полный или без словоформ) список; так состояние остаётся единым и для окна
        # "Совпадения", и для последующих запросов, а не только для одного текущего вызова. Обновление
        # открытой визуализации — забота контроллера визуализаций.
        self.viz.repeat_search_replacing_level(was_showing_viz, query_word, vector_key)

    def _start_vector_preload(self, display_key):
        """Показывает индикатор загрузки модели и запускает отслеживание её
           готовности опросом из главного потока (вызывается сразу после
           IndexManager.preload_model_async(), а не изнутри него — сам
           фоновый поток загрузки ничего в интерфейсе не трогает: сигналы
           из чужого потока в Tkinter через root.after(...) на практике
           оказались ненадёжными — застревали в очереди, пока что-то ещё,
           например ввод в поле запроса, не "будило" цикл событий).
           Опрос — единственный способ, который ведёт себя предсказуемо."""
        self._show_progress(mode='indeterminate')
        self.progress_bar.start(10)
        self._update_log_field(f"⏳ Загрузка векторной модели «{display_key}»...")
        self._poll_vector_preload(display_key)

    def _poll_vector_preload(self, display_key):
        vmm = self.vector_model_manager
        if vmm.is_loaded(display_key):
            self.progress_bar.stop()
            self._hide_progress()
            self._update_log_field(f"✅ Модель «{display_key}» загружена, можно искать")
            return
        if not vmm.is_preloading(display_key):
            # Поток завершился, но модель так и не попала в кеш — значит,
            # загрузка не удалась (подробности — в консоли, из _get_model).
            self.progress_bar.stop()
            self._hide_progress()
            self._update_log_field(f"❌ Не удалось загрузить модель «{display_key}»")
            return
        self.root.after(200, lambda: self._poll_vector_preload(display_key))

    # ---------- Поле служебных сообщений ----------
    def _update_log_field(self, message):
        # root.after(...) — чтобы это было безопасно вызывать и из фонового
        # потока тоже: напрямую трогать виджеты Tkinter из другого потока
        # нельзя, а сама постановка в очередь через after() — можно из
        # любого потока (в отличие от НАДЁЖНОСТИ такого вызова — см.
        # _poll_vector_preload, где по этой причине выбран другой подход).
        def _do_update():
            if hasattr(self, 'status_entry'):
                self.status_entry.config(state='normal')
                self.status_entry.delete(0, tk.END)
                self.status_entry.insert(0, message)
                self.status_entry.config(state='readonly')
                self.status_entry.xview_moveto(0)
        self.root.after(0, _do_update)

    def _scroll_left(self):
        if hasattr(self, 'status_entry'):
            current = self.status_entry.xview()[0]
            if current > 0:
                self.status_entry.xview_moveto(current - 0.01)

    def _scroll_right(self):
        if hasattr(self, 'status_entry'):
            current = self.status_entry.xview()[0]
            if current < 1.0:
                self.status_entry.xview_moveto(current + 0.01)

    # ---------- Текст справки ----------
    def _show_help_text(self):
        self.results_renderer.render_help_text()
        self.btn_first.config(state='disabled')
        self.btn_back.config(state='disabled')
        self.btn_forward.config(state='disabled')
        self.btn_last.config(state='disabled')

    # ---------- Обновление шрифта ----------
    def _update_fonts(self):
        self.result_text.configure(font=('Consolas', self.font_size))
        if hasattr(self, 'word_panel'):
            self.word_panel.update_font_size(self.font_size)
        if self.result_text_2:
            self.result_text_2.configure(font=('Consolas', self.font_size))
        if self.word_panel_2:
            self.word_panel_2.update_font_size(self.font_size)
        self.query_entry.configure(font=('Consolas', self.font_size))
        if self.text_listbox:
            self.text_listbox.configure(font=('Consolas', self.font_size))
        if self.index_check_list:
            self.index_check_list.update_font_size(self.font_size)
        # Обновляем шрифт у счётчика выбранных индексов
        if self.selected_count_label:
            self.selected_count_label.configure(font=('Arial', self.font_size, 'bold'))
        if self.results_renderer:
            self.results_renderer.font_size = self.font_size
        if self.results_renderer_2:
            self.results_renderer_2.font_size = self.font_size
        try:
            self.result_text.tag_config("help_text", font=('Arial', self.font_size))
        except tk.TclError:
            pass

    # ---------- Навигационные методы ----------
    def go_to_first_page(self):
        self.search_controller.go_to_first_page()

    def go_to_last_page(self):
        self.search_controller.go_to_last_page()

    def page_back(self):
        self.search_controller.page_back(self._back_to_results_from_file)

    def page_forward(self):
        self.search_controller.page_forward()

    def change_password_dialog(self):
        """Настройки → "Сменить пароль" (перенесено из прежней версии). Новый
           (сменный) пароль хранится в mconfig.ini только как соленый хеш и
           действует НАРАВНЕ с прежним (день и месяц, ДДММ): подходит любой из
           двух, поэтому забытый сменный пароль не запирает программу. Старым
           паролем в этом диалоге тоже может быть любой из двух."""
        bg = '#d4e8f7'
        dialog = tk.Toplevel(self.root)
        dialog.title("Смена пароля")
        dialog.configure(bg=bg)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        width, height = 420, 450
        x = (dialog.winfo_screenwidth() - width) // 2
        y = max(0, (dialog.winfo_screenheight() - height) // 3)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

        old_var, new_var, confirm_var = tk.StringVar(), tk.StringVar(), tk.StringVar()

        def add_field(caption, var, first=False):
            tk.Label(dialog, text=caption, font=('Arial', 12, 'bold'), bg=bg,
                     fg='#1a4a7a').pack(pady=(20 if first else 10, 5))
            entry = tk.Entry(dialog, textvariable=var, font=('Arial', 12), width=20, show='*')
            entry.pack(pady=5)
            return entry

        old_entry = add_field("Старый пароль:", old_var, first=True)
        add_field("Новый пароль:", new_var)
        add_field("Повторите новый пароль:", confirm_var)
        tk.Label(dialog, text="Прежний пароль (день и месяц, ДДММ)\nпродолжит работать наравне с новым.",
                 font=('Arial', 10), bg=bg, fg='#4a7a9a', justify='center').pack(pady=(10, 0))
        error_label = tk.Label(dialog, text="", font=('Arial', 11), bg=bg, fg='#cc0000')
        error_label.pack(pady=5)

        def on_change():
            old, new, confirm = old_var.get(), new_var.get(), confirm_var.get()
            if not old or not new or not confirm:
                error_label.config(text="Заполните все поля!")
                return
            if new != confirm:
                error_label.config(text="Новые пароли не совпадают!")
                return
            if not check_password(old, self.config.get('password_hash', ''),
                                  self.config.get('password_salt', '')):
                error_label.config(text="Неверный старый пароль!")
                return
            try:
                self._store_password(new)
            except Exception as e:
                error_label.config(text=f"Не удалось сохранить: {e}")
                return
            messagebox.showinfo("Успех", "Пароль успешно изменён!\n\n"
                                         "Прежний пароль (день и месяц) тоже работает.", parent=dialog)
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=bg)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="✅ Сменить пароль", command=on_change, bg='#3a8a4a', fg='white',
                  font=('Arial', 12, 'bold'), padx=15, pady=5).pack(side='left', padx=10)
        tk.Button(btn_frame, text="✖ Отмена", command=dialog.destroy, bg='#b84a4a', fg='white',
                  font=('Arial', 12, 'bold'), padx=15, pady=5).pack(side='left', padx=10)
        dialog.bind('<Return>', lambda e: on_change())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        old_entry.focus_set()

    def _store_password(self, new_password):
        """Сохраняет сменный пароль (хеш и соль) в mconfig.ini.

           Обновляются ВСЕ живые словари конфигурации (как в
           _remember_merge_dirs): после переключения движка self.config
           заменяется заново загруженным, а VectorModelManager держит прежний —
           его следующее сохранение настроек вернуло бы старый пароль. Если
           записать файл не удалось, значения откатываются: иначе
           несохранённый пароль "прилип" бы к конфигурации и записался при
           ближайшем другом сохранении настроек."""
        new_hash, new_salt = make_password_record(new_password)
        holders = [self.config]
        vmm_config = getattr(self.vector_model_manager, 'config_dict', None)
        if isinstance(vmm_config, dict) and vmm_config is not self.config:
            holders.append(vmm_config)
        previous = [(h, h.get('password_hash', ''), h.get('password_salt', '')) for h in holders]
        for holder in holders:
            holder['password_hash'] = new_hash
            holder['password_salt'] = new_salt
        try:
            save_config(self.config)
        except Exception:
            for holder, old_hash, old_salt in previous:
                holder['password_hash'] = old_hash
                holder['password_salt'] = old_salt
            raise

    def _brief_tooltip_text(self):
        """Подсказка переключателя "Кратко"/"Всё": надпись на кнопке — то, во что
           она переключит. У "Всё" подсказка "Полный текст"; у "Кратко" подсказки
           нет (пустой текст — ToolTip ничего не показывает)."""
        return "Полный текст" if self.btn_brief_toggle.cget('text') == "Всё" else ""

    def toggle_brief_mode(self):
        """Переключает кнопку и режим отображения топиков между
           "Кратко" (только предложения с подсветками) и "Всё"
           (полный текст) — в пределах текущей страницы результатов.
           Надпись на кнопке — то, во что она переключит."""
        brief_enabled = self.search_controller.toggle_brief_mode()
        self.btn_brief_toggle.config(text="Всё" if brief_enabled else "Кратко")

    def _back_to_results_from_file(self):
        if hasattr(self.search_controller, '_back_to_results_from_file'):
            self.search_controller._back_to_results_from_file()

    # ---------- Горячие клавиши ----------
    def _bind_shortcuts(self):
        self.root.bind('<Control-plus>', self.increase_font)
        self.root.bind('<Control-equal>', self.increase_font)
        self.root.bind('<Control-minus>', self.decrease_font)
        self.root.bind('<F10>', self.show_stats_log)
        if self.index_check_list:
            self.index_check_list.bind('<Delete>', self._delete_selected_indices)
            self.index_check_list.bind('<BackSpace>', self._delete_selected_indices)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def show_stats_log(self, event=None):
        if not hasattr(stats_logger, 'LOG_FILE') or stats_logger.LOG_FILE is None:
            messagebox.showinfo("Статистика", "Сбор статистики отключён или лог-файл не создан.")
            return
        content = stats_logger.get_stats_log_content()
        if not content:
            content = "Лог-файл пуст."
        win = tk.Toplevel(self.root)
        win.title("Лог статистики")
        win.geometry("800x600")
        text = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Consolas", 10))
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, content)
        text.config(state='disabled')

    # ---------- Остальные методы ----------
    def _get_current_index_name(self):
        if hasattr(self.engine, '_current_index') and self.engine._current_index:
            if os.path.sep in str(self.engine._current_index):
                return os.path.basename(self.engine._current_index)
            return str(self.engine._current_index)
        return "не выбран"

    def increase_font(self, event=None):
        if self.font_size < 24:
            self.font_size += 1
            self._update_fonts()

    def decrease_font(self, event=None):
        if self.font_size > 6:
            self.font_size -= 1
            self._update_fonts()

    def open_config(self):
        try:
            if sys.platform == 'win32':
                os.startfile(CONFIG_FILE)
            else:
                subprocess.Popen(['xdg-open', CONFIG_FILE])
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл конфигурации:\n{e}")

    def append_selection_to_conspect(self, event):
        """Сохранение выделенного текста в конспект правой кнопкой мыши.

           Логика определяется не чётностью клика, а тем, совпадает ли
           ТЕКУЩЕЕ выделение с последним, что реально было сохранено на
           диск (self._last_conspect_text):
           - выделение НОВОЕ (отличается от последнего сохранённого,
             включая самый первый клик) → сохраняем его как цитату;
           - выделение ТО ЖЕ САМОЕ, и источник для него ещё не дописан →
             дописываем источник;
           - выделение ТО ЖЕ САМОЕ, источник уже дописан → ничего не делаем.
           Это позволяет сохранять цитату за цитатой без обязательного
           запроса источника после каждой, и не путает первую цитату с
           запросом источника, как было раньше."""
        if getattr(self, '_conspect_lock', False):
            return
        self._conspect_lock = True
        try:
            try:
                widget = event.widget
                selected = widget.selection_get()
            except tk.TclError:
                return
            selected = selected.strip() if selected else ''
            if not selected:
                return

            last_text = getattr(self, '_last_conspect_text', None)
            if selected == last_text:
                # То же самое выделение, что и в прошлый раз.
                if getattr(self, '_conspect_source_written', True):
                    # Источник для него уже дописан — больше ничего не делаем.
                    return
                source_label = getattr(self, '_last_conspect_source', '') or ''
                if not source_label:
                    return
                try:
                    with open(CONSPECT_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"({source_label})\n")
                    self._conspect_source_written = True
                    self._show_temporary_notification("✅ Источник добавлен в конспект")
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось записать в конспект:\n{e}")
                return

            # Новое выделение — сохраняем его как цитату.
            source_label = self._get_conspect_source_label(widget)
            entry = "......." + selected + "\n"
            try:
                with open(CONSPECT_FILE, 'a', encoding='utf-8') as f:
                    f.write(entry)
                self._show_temporary_notification("✅ Сохранено в конспект")
                self._last_conspect_text = selected
                self._last_conspect_source = source_label
                self._conspect_source_written = False
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось записать в конспект:\n{e}")
        finally:
            self.root.after(500, lambda: setattr(self, '_conspect_lock', False))

    def _get_conspect_source_label(self, widget=None):
        """Определяет "имя_файла (алиас)" источника для текста, только что
           выделенного в result_text (или result_text_2 в режиме разделения —
           widget указывает, в каком именно виджете была выделена цитата):
           если сейчас открыт файл-источник по гиперссылке — берём его метку;
           если это окно результатов — поднимаемся вверх по тексту до
           ближайшей шапки-гиперссылки топика, которой и принадлежит
           выделенный фрагмент. В режиме разделения шапок нет вовсе, поэтому
           для result_text_2 источник всегда будет пустым — это ожидаемо."""
        widget = widget or self.result_text
        if getattr(self.search_controller, 'is_viewing_file', False) and widget is self.result_text:
            return getattr(self.search_controller, '_current_view_file_label', '') or ''
        # Режим просмотра одного файла ("**"): у блоков нет шапок-гиперссылок, по
        # которым источник искался бы ниже, а источник и так один — этот файл.
        # Без этого источник к цитате не дописался бы никогда.
        if widget is self.result_text and getattr(self.search_controller, 'browse_file_label', None):
            return self.search_controller.browse_file_label
        try:
            sel_start = widget.index("sel.first")
        except tk.TclError:
            return ''
        prev_range = widget.tag_prevrange("hyperlink", sel_start)
        if not prev_range:
            return ''
        header_text = widget.get(prev_range[0], prev_range[1])
        m = re.match(r'^Файл:\s*(.+?)\s*\|', header_text)
        if m:
            return m.group(1).strip()
        m = re.match(r'^Файл:\s*(.+)$', header_text)
        if m:
            return m.group(1).strip()
        return ''

    def _show_temporary_notification(self, message, duration_ms=700):
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg='#d4e8f7')
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 100
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 30
        popup.geometry(f"350x80+{x}+{y}")
        label = tk.Label(
            popup,
            text=message,
            font=('Arial', 14, 'bold'),
            bg='#3a8a4a',
            fg='white',
            padx=10,
            pady=10
        )
        label.pack(fill=tk.BOTH, expand=True)
        popup.after(duration_ms, popup.destroy)
        popup.attributes('-topmost', True)

    def on_hyperlink_click(self, event):
        self.search_controller.on_hyperlink_click(event)

    def on_close(self):
        if self.numerator is not None:
            self.numerator.shutdown()  # вернуть F7/F8/F9 другим программам
        marks_store = getattr(self, 'marks_store', None)  # выход должен быть терпим к любому состоянию
        if marks_store is not None:
            marks_store.close()
        if hasattr(stats_logger, 'STATS_ENABLED') and stats_logger.STATS_ENABLED:
            stats_logger.log_shutdown()
        if self.engine:
            self.engine.close()
        self.root.destroy()

    def do_search(self):
        self.search_controller.do_search()

    def refresh_display(self):
        self.search_controller.refresh_display()

    def open_file_merger(self):
        """Кнопка "Собрать базу" — окно склейки нескольких файлов в один (см.
           ui/file_merger_dialog.py). Папки, запомненные с прошлого раза,
           берутся из настроек (mconfig.ini через load_config)."""
        output_dir = (self.config.get('merge_output_dir') or 'DB')
        if not os.path.isdir(output_dir):
            # Запомненной папки уже нет (удалена, отключён диск) — возвращаемся
            # к подкаталогу DB, а не предлагаем сохранять в никуда.
            output_dir = 'DB'
        try:
            open_file_merger_dialog(
                self.root,
                initial_source_dir=self.config.get('merge_source_dir') or '',
                initial_output_dir=output_dir,
                on_dirs_changed=self._remember_merge_dirs,
                on_merged=self._on_base_merged,
                on_files_moved=self.file_manager.on_books_copied,
            )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть окно сборки базы:\n{e}")

    def _remember_merge_dirs(self, source_dir=None, output_dir=None):
        """Запоминает папки окна "Собрать базу" в настройках и сохраняет
           mconfig.ini. None — этот параметр не менялся.

           Обновляем ВСЕ живые словари конфигурации, а не только self.config:
           после переключения движка (ui/main_window.py) self.config
           заменяется заново загруженным словарём, а VectorModelManager
           продолжает держать прежний — и его следующее сохранение настроек
           (save_config при обучении модели) затёрло бы только что
           запомненную папку устаревшим значением."""
        holders = [self.config]
        vmm_config = getattr(self.vector_model_manager, 'config_dict', None)
        if isinstance(vmm_config, dict) and vmm_config is not self.config:
            holders.append(vmm_config)
        changed = False
        for key, value in (('merge_source_dir', source_dir), ('merge_output_dir', output_dir)):
            if value is None:
                continue
            for holder in holders:
                holder[key] = value
            changed = True
        if changed:
            try:
                save_config(self.config)
            except Exception as e:
                print(f"⚠️ Не удалось сохранить запомненные папки сборки базы: {e}")

    def _on_base_merged(self, output_path):
        """Склейка завершена. Если результат лёг туда, где приложение ищет
           файлы для индексации (папка DB или рабочая папка) — обновляем
           список файлов справа внизу, чтобы он сразу там появился. Иначе
           список не трогаем: обновление сбрасывает выделение, а нового файла
           в нём всё равно не будет."""
        out_dir = os.path.normcase(os.path.abspath(os.path.dirname(output_path)))
        scanned = {os.path.normcase(os.path.abspath('DB')), os.path.normcase(os.path.abspath('.'))}
        if out_dir in scanned:
            self.update_text_list()
        self._update_log_field(f"База собрана: {os.path.basename(output_path)}")

    def prepare_vectors(self):
        """Обучает векторную модель на тексте выбранных в правом нижнем окне
           книг (тот же список файлов, что и для обычной индексации) — см.
           services/vector_model_manager.py.

           Два разных сценария по тому, что отмечено в списке индексов:
           - если там отмечена галочкой уже существующая модель ("FT ..."/
             "PM ... [модель]") — это ДООБУЧЕНИЕ этой модели на выбранных
             файлах (с подтверждением), без всякого диалога параметров: они
             уже заданы при её создании и не меняются;
           - если модель не отмечена — открывается диалог выбора ТИПА новой
             модели (всегда ровно столько пунктов, сколько типов
             зарегистрировано — сейчас FastText и MiniLM, — уже обученные
             модели в этот список не подмешиваются) и настройки её
             параметров."""
        selected_files = list(self.file_manager.selected_text_files)
        if not selected_files:
            messagebox.showwarning("Внимание", "Не выбрано ни одного файла (в списке справа снизу).")
            return

        display_names_by_file = self._display_names_for_files(selected_files)

        ticked = self.index_manager.get_selected_indices_ordered()
        ticked_models = [k for k in ticked if self.vector_model_manager.is_vector_key(k)]
        retrain_key = ticked_models[0] if ticked_models else None

        model_type = model_params = semantic_window = name_suffix = None
        if retrain_key:
            if not self._confirm_retrain(retrain_key, display_names_by_file):
                return
        else:
            settings = self._ask_new_model_settings(selected_files, display_names_by_file)
            if settings is None:
                return
            model_type, model_params, semantic_window, name_suffix = settings

        success, message = self._run_training(
            retrain_key, selected_files, display_names_by_file,
            model_type, model_params, semantic_window, name_suffix
        )
        if success:
            messagebox.showinfo("Векторы", message)
            self.update_index_list()
        else:
            messagebox.showerror("Ошибка обучения", message)

    def _display_names_for_files(self, selected_files):
        """{файл: название} — название из настроек баз, а для файла вне настроек — имя без расширения."""
        display_names_by_file = {}
        for f in selected_files:
            base_name = os.path.basename(f)
            if base_name in self.config_dict:
                display_name, _, _ = self.config_dict[base_name]
            else:
                display_name = os.path.splitext(base_name)[0]
            display_names_by_file[f] = display_name
        return display_names_by_file

    def _confirm_retrain(self, retrain_key, display_names_by_file):
        names = ", ".join(display_names_by_file.values())
        return messagebox.askyesno(
            "Дообучение модели",
            f"Дообучить модель «{retrain_key}» на выбранных файлах?\n{names}\n"
            f"(если вместо этого нужна новая модель — снимите галочку с «{retrain_key}» в списке индексов)"
        )

    def _ask_new_model_settings(self, selected_files, display_names_by_file):
        """Диалог параметров новой модели и решение, что делать, если модель с таким именем уже есть.
           Возвращает (тип, параметры, окно смысла, уточнение имени) или None, если пользователь отказался."""
        total_bytes = sum(os.path.getsize(f) for f in selected_files if os.path.exists(f))

        def suggest_fn(mtype, planned_total_mb):
            return self.vector_model_manager.suggest_params(mtype, total_bytes, planned_total_mb)

        sentence_window_config = (
            self.config.get('vector_sentences_before', 7),   # настройки, а не словарь баз (config_dict — это базы)
            self.config.get('vector_sentences_after', 10)
        )
        choice = ask_vector_params(self.root, suggest_fn, total_bytes / (1024 * 1024),
                                   sentence_window_config=sentence_window_config)
        if choice is None:
            return None
        model_type = choice['model_type']

        proceed, name_suffix = self._resolve_model_name_conflict(model_type, selected_files, display_names_by_file)
        if not proceed:
            return None
        return model_type, choice['params'], choice.get('semantic_window'), name_suffix

    def _resolve_model_name_conflict(self, model_type, selected_files, display_names_by_file):
        """Если модель с таким именем уже есть — даёт выбрать: перезаписать, другое имя или отмена.
           Возвращает (продолжать ли, уточнение к имени или None)."""
        prospective_key = self.vector_model_manager.compute_display_key(
            model_type, selected_files, display_names_by_file
        )
        if not self.vector_model_manager.is_vector_key(prospective_key):
            return True, None
        # На одном и том же файле может быть смысл держать сразу
        # несколько моделей с разными параметрами (например, разные
        # "окна смысла" у MiniLM) — поэтому кроме перезаписи и
        # отмены даём выбрать другое имя, а не только да/нет.
        decision = messagebox.ask_choice(
            "Модель уже существует",
            f"Модель «{prospective_key}» для этого набора файлов уже существует.\n\n"
            "Она могла с тех пор дообучаться на дополнительных материалах — "
            "перезапись СОТРЁТ её, и все накопленные результаты дообучения будут "
            "потеряны.\n\n"
            "Перезаписать существующую модель, дать этой новой модели другое имя, "
            "или отменить создание?",
            buttons=('Перезаписать', 'Другое имя', 'Отмена'),
            height=420
        )
        if decision is None or decision == 'Отмена':
            return False, None
        if decision != 'Другое имя':
            return True, None
        suffix = simpledialog.askstring(
            "Другое имя модели",
            "Уточнение к имени модели (например: «вариант 2»):",
            parent=self.root
        )
        if not suffix or not suffix.strip():
            return False, None
        name_suffix = suffix.strip()
        new_key = self.vector_model_manager.compute_display_key(
            model_type, selected_files, display_names_by_file, name_suffix=name_suffix
        )
        if self.vector_model_manager.is_vector_key(new_key):
            messagebox.showerror(
                "Имя всё равно занято",
                f"Модель «{new_key}» тоже уже существует — выберите другое уточнение."
            )
            return False, None
        return True, name_suffix

    def _run_training(self, retrain_key, selected_files, display_names_by_file,
                      model_type, model_params, semantic_window, name_suffix):
        """Обучение или дообучение под баннером и полосой прогресса. Возвращает (успех, сообщение). Неожиданное
           исключение не пропадает в консоли: оно становится сообщением об ошибке (полоса и баннер убираются всегда)."""
        banner, cancel_check = self._show_training_banner(
            "Дообучение модели, подождите... (Esc — прервать)" if retrain_key
            else "Обучение модели, подождите... (Esc — прервать)"
        )
        self._show_progress(max_value=100, initial=0, mode='determinate')

        def progress_cb(fraction):
            self._update_progress(int(fraction * 100))

        try:
            if retrain_key:
                return self.vector_model_manager.continue_train(
                    retrain_key, selected_files, display_names_by_file,
                    cancel_check=cancel_check, progress_callback=progress_cb
                )
            return self.vector_model_manager.train(
                selected_files, display_names_by_file, model_type=model_type,
                model_params=model_params, semantic_window=semantic_window,
                name_suffix=name_suffix, cancel_check=cancel_check,
                progress_callback=progress_cb
            )
        except Exception as e:
            print(f"❌ Ошибка обучения: {e}")
            return False, f"Ошибка обучения: {e}"
        finally:
            self._hide_progress()
            self._hide_training_banner(banner)