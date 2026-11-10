"""Визуализации в среднем окне: 2D/3D-проекции слов, граф-сеть, радиальная раскладка, облако
   тегов, центральные понятия (TextRank), "Сгущение понятий", "Всё пространство", столбцы,
   тепловая карта, дендрограмма — и навигация "Назад" по их уровням.

   Раньше всё это (30 методов, около 1100 строк — две пятых класса AppWindow) жило прямо в окне
   приложения. Теперь это отдельный объект со своим состоянием; окно остаётся владельцем
   виджетов и создаёт контроллер в __init__ (self.viz)."""

import os
import tkinter as tk

from ui.custom_dialogs import messagebox
from ui import vector_visualization
from utils import key_concepts


class VisualizationController:
    """Рисует визуализации на холсте среднего окна (он ПОДМЕНЯЕТ текст результатов на время
       показа) и ведёт историю уровней для кнопки "◀ Назад".

       Граница с окном (app) — вот всё, чем контроллер пользуется, и ничем больше:
         виджеты и сервисы: result_text, vector_viz_canvas, query_entry, root, word_panel,
                            search_controller, vector_model_manager, index_manager;
         методы окна:       _key_concept_words(), _warn_key_concepts_empty(title) — словарь
                            ключевых понятий (кнопка "КП"); _update_log_field(text) — строка
                            состояния.
       Контроллер НЕ импортирует окно (циклической зависимости нет): ему достаточно любого объекта
       с этими членами — поэтому его можно проверять без настоящего окна (tests/)."""

    def __init__(self, app):
        self.app = app
        # Последняя открытая визуализация (чем её перерисовать) — чтобы при переключении словоформ
        # ("−В/+В", см. repeat_search_replacing_level) обновить и её, если она открыта; выставляется
        # в show_vector_viz_menu.
        self._last_viz_revisualize = None
        # Навигация "Назад" по уровням визуализации (см. _on_viz_word_click): история снимков
        # предыдущих уровней, описание показанного сейчас уровня, режим текущего перехода (None |
        # 'forward' | 'back' | 'replace') и кнопка "Назад" (создаётся при первой надобности).
        self._viz_history = []
        self._current_viz = None
        self._viz_nav_mode = None
        self._viz_registered = False
        self.btn_viz_back = None

    def repeat_search_replacing_level(self, was_showing, query_word, vector_key):
        """Повторяет поиск (после переключения словоформ "−В/+В") и, если визуализация была
           открыта, перерисовывает её с новыми соседями.

           Пересчёт словоформ заменяет ТЕКУЩИЙ уровень новым списком соседей, а не начинает
           цепочку заново: режим 'replace' не даёт do_search() (его hide_vector_visualization) и
           перерисовке сбросить историю. was_showing запоминается вызывающим ДО этого вызова:
           do_search() сам скрывает визуализацию в начале, и к моменту проверки она уже скрыта."""
        self._viz_nav_mode = 'replace' if was_showing else None
        try:
            self.app.search_controller.do_search()

            new_neighbors = getattr(self.app.word_panel, '_last_neighbors', None)
            if new_neighbors and was_showing and self._last_viz_revisualize is not None:
                self._last_viz_revisualize(query_word, new_neighbors, vector_key)
        finally:
            self._viz_nav_mode = None
            if was_showing and not self.app.vector_viz_canvas.winfo_ismapped():
                self._clear_viz_history()  # визуализацию заново не показали — цепочка оборвана

    def _revisualize_bar(self, query_word, neighbors, vector_key):
        self.show_bar_chart(neighbors, query_word)

    def _revisualize_heatmap(self, query_word, neighbors, vector_key):
        words = [query_word] + [w for w, _s in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            return
        self.show_heatmap(vectors, query_word)

    def _revisualize_dendrogram(self, query_word, neighbors, vector_key):
        words = [query_word] + [w for w, _s in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            return
        self.show_dendrogram_viz(vectors, query_word)

    def show_vector_viz_menu(self, query_word, neighbors, vector_key):
        """Вызывается кнопкой "3D/2D" у окна "Совпадения" — показывает
           всплывающее меню с вариантами визуализации векторной близости
           слов (само слово запроса + его соседи из окна "Совпадения").
           То, что технически можно нарисовать в самом Tkinter (2D-проекции,
           столбцы, тепловая карта, дендрограмма, граф) — рисуется прямо в
           среднем окне (Canvas, подменяет result_text на время показа);
           3D — как интерактивная HTML-страница (вращается мышью),
           открывается в браузере — вращаемую 3D-сцену без сторонних
           библиотек типа matplotlib в самом Tkinter не показать, а тянуть
           такую зависимость только ради этого не стоит."""
        words = [query_word] + [w for w, _score in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            messagebox.showinfo(
                "Визуализация",
                "Недостаточно слов с векторами для визуализации (нужно хотя бы два)."
            )
            return

        def _pick(revisualize_fn, show_fn):
            """Запоминает, ЧЕМ рисовать заново (см. toggle_word_variations
               — при исключении/возврате словоформ обновляет и открытую
               визуализацию, не только окно "Совпадения"), затем рисует."""
            def _action():
                self._last_viz_revisualize = revisualize_fn
                show_fn()
            return _action

        menu = tk.Menu(self.app.root, tearoff=0)

        proj_pca = tk.Menu(menu, tearoff=0)
        proj_pca.add_command(label="2D (в этом окне)", command=_pick(
            self._visualize_2d_for, lambda: self._do_visualize(vectors, query_word, dims=2, vector_key=vector_key)
        ))
        proj_pca.add_command(label="3D (веб-страница)",
                             command=lambda: self._do_visualize(vectors, query_word, dims=3, vector_key=vector_key))
        menu.add_cascade(label="Проекция (PCA)", menu=proj_pca)

        proj_tsne = tk.Menu(menu, tearoff=0)
        proj_tsne.add_command(label="2D (в этом окне)", command=_pick(
            self._visualize_2d_for, lambda: self._do_visualize_tsne(vectors, query_word, dims=2, vector_key=vector_key)
        ))
        proj_tsne.add_command(label="3D (веб-страница)",
                              command=lambda: self._do_visualize_tsne(vectors, query_word, dims=3, vector_key=vector_key))
        menu.add_cascade(label="Проекция (t-SNE, точнее для соседства)", menu=proj_tsne)

        menu.add_separator()
        menu.add_command(label="Столбчатая диаграмма близости", command=_pick(
            self._revisualize_bar, lambda: self.show_bar_chart(neighbors, query_word)
        ))
        menu.add_command(label="Тепловая карта попарных близостей", command=_pick(
            self._revisualize_heatmap, lambda: self.show_heatmap(vectors, query_word)
        ))
        menu.add_command(label="Дендрограмма (иерархия групп)", command=_pick(
            self._revisualize_dendrogram, lambda: self.show_dendrogram_viz(vectors, query_word)
        ))
        menu.add_command(label="Граф-сеть связей", command=_pick(
            self._revisualize_network, lambda: self.show_network_graph(vectors, query_word, vector_key)
        ))
        menu.add_command(label="По секторам (радиально)", command=_pick(
            self._revisualize_radial, lambda: self.show_radial_layout(vectors, query_word, vector_key)
        ))

        # "Сгущения понятий" — последняя строка, только для FastText (у
        # MiniLM/LSA нет отдельных векторов слов, см. get_word_vectors).
        # Анализирует не соседей ОДНОГО слова запроса, а словарь модели
        # целиком — ищет слово-"центр" самой насыщенной (густо скопившейся)
        # области всего пространства (см. vector_visualization.
        # find_densest_cluster) и показывает его ровно как обычное слово
        # запроса — поэтому вся уже существующая отрисовка ниже
        # переиспользуется без единого изменения в ней самой.
        if self.app.vector_model_manager.get_model_type(vector_key) == 'fasttext':
            menu.add_separator()
            density_menu = tk.Menu(menu, tearoff=0)

            def _density_action(kind):
                def _action():
                    data = self._get_density_cluster_data(vector_key)
                    if data is None:
                        return
                    c_word, c_neighbors, c_vectors = data
                    if kind == '2d_pca':
                        self._last_viz_revisualize = self._visualize_2d_for
                        self._do_visualize(c_vectors, c_word, dims=2, vector_key=vector_key)
                    elif kind == '3d_pca':
                        self._do_visualize(c_vectors, c_word, dims=3, vector_key=vector_key)
                    elif kind == '2d_tsne':
                        self._last_viz_revisualize = self._visualize_2d_for
                        self._do_visualize_tsne(c_vectors, c_word, dims=2, vector_key=vector_key)
                    elif kind == '3d_tsne':
                        self._do_visualize_tsne(c_vectors, c_word, dims=3, vector_key=vector_key)
                    elif kind == 'bar':
                        self._last_viz_revisualize = self._revisualize_bar
                        self.show_bar_chart(c_neighbors, c_word)
                    elif kind == 'heatmap':
                        self._last_viz_revisualize = self._revisualize_heatmap
                        self.show_heatmap(c_vectors, c_word)
                    elif kind == 'dendrogram':
                        self._last_viz_revisualize = self._revisualize_dendrogram
                        self.show_dendrogram_viz(c_vectors, c_word)
                    elif kind == 'network':
                        self._last_viz_revisualize = self._revisualize_network
                        self.show_network_graph(c_vectors, c_word, vector_key)
                    elif kind == 'radial':
                        self._last_viz_revisualize = self._revisualize_radial
                        self.show_radial_layout(c_vectors, c_word, vector_key)
                return _action

            density_proj_pca = tk.Menu(density_menu, tearoff=0)
            density_proj_pca.add_command(label="2D (в этом окне)", command=_density_action('2d_pca'))
            density_proj_pca.add_command(label="3D (веб-страница)", command=_density_action('3d_pca'))
            density_menu.add_cascade(label="Проекция (PCA)", menu=density_proj_pca)

            density_proj_tsne = tk.Menu(density_menu, tearoff=0)
            density_proj_tsne.add_command(label="2D (в этом окне)", command=_density_action('2d_tsne'))
            density_proj_tsne.add_command(label="3D (веб-страница)", command=_density_action('3d_tsne'))
            density_menu.add_cascade(label="Проекция (t-SNE)", menu=density_proj_tsne)

            density_menu.add_separator()
            density_menu.add_command(label="Столбчатая диаграмма близости", command=_density_action('bar'))
            density_menu.add_command(label="Тепловая карта попарных близостей", command=_density_action('heatmap'))
            density_menu.add_command(label="Дендрограмма (иерархия групп)", command=_density_action('dendrogram'))
            density_menu.add_command(label="Граф-сеть связей", command=_density_action('network'))
            density_menu.add_command(label="По секторам (радиально)", command=_density_action('radial'))

            menu.add_cascade(label="Сгущения понятий (анализ всего пространства)", menu=density_menu)

            def _show_full_space():
                key_words = self.app._key_concept_words()  # None — фильтр выключен
                if key_words is not None and not key_words:
                    self.app._warn_key_concepts_empty("Всё пространство")
                    return
                vocab_vectors = self.app.vector_model_manager.get_vocabulary_vectors(
                    vector_key, max_words=5000, key_words=key_words
                )
                if len(vocab_vectors) < 2:
                    messagebox.showinfo(
                        "Всё пространство",
                        "В словаре модели недостаточно подходящих слов для отображения."
                        if key_words is None else
                        "Из словаря ключевых понятий (с вариациями) в модели найдено меньше двух слов."
                    )
                    return
                self._last_viz_revisualize = None  # клик по слову тут ведёт к его СОБСТВЕННЫМ
                                                    # соседям (обычная визуализация), не назад в облако
                self.show_full_space_cloud(
                    vocab_vectors, vector_key,
                    title=None if key_words is None else "Ключевые понятия — всё пространство модели")

            menu.add_command(label="Всё пространство (облако точек — приблизьте для слов)",
                             command=_show_full_space)

        try:
            x = self.app.root.winfo_pointerx()
            y = self.app.root.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def show_textrank_for_selected(self):
        """Обработчик кнопки "Центральные понятия" — TextRank/PageRank по
           графу совместной встречаемости слов отмеченных индексов (одна
           книга или сразу несколько). Не требует векторной модели — работает
           прямо по тексту, как и облако тегов. Результат показывается через
           уже готовую столбчатую диаграмму (переиспользуем её формат
           (слово, число), хотя число здесь — не близость к слову запроса,
           а оценка центральности по TextRank)."""
        selected = self.app.index_manager.get_selected_indices_ordered()
        if not selected:
            messagebox.showinfo("Центральные понятия", "Сначала отметьте галочкой хотя бы один индекс.")
            return
        texts = self.app.search_controller.gather_text_for_indices(selected)
        if not texts:
            messagebox.showinfo(
                "Центральные понятия",
                "Не удалось получить текст отмеченных индексов (возможно, отмечены "
                "только векторные модели, без обычных индексов)."
            )
            return
        key_words = self.app._key_concept_words()  # None — фильтр выключен
        if key_words is not None and not key_words:
            self.app._warn_key_concepts_empty("Центральные понятия")
            return
        words, edges = vector_visualization.build_cooccurrence_graph(texts, key_words=key_words)
        if not words:
            messagebox.showinfo(
                "Центральные понятия",
                "После отсева коротких и служебных слов ничего содержательного не осталось."
            )
            return
        ranked = vector_visualization.compute_textrank(words, edges)
        if key_words is not None:
            # Центральность посчитана по всему тексту (граф включает и слова словаря,
            # которых нет среди самых частых), а показываем только слова словаря и их вариации.
            allowed = key_concepts.expand_dictionary(key_words, set(words))
            ranked = [(w, score) for w, score in ranked if w in allowed]
            if not ranked:
                messagebox.showinfo(
                    "Центральные понятия",
                    "Ни одного слова словаря ключевых понятий (с вариациями) нет в отмеченных книгах."
                )
                return
        top_ranked = ranked[:30]
        central_word = top_ranked[0][0] if top_ranked else ""
        label = "Центральные ключевые понятия" if key_words is not None else "Центральные понятия текста"
        self.hide_vector_visualization()  # на случай, если открыта другая визуализация - сбрасываем перед show_bar_chart
        self.show_bar_chart(
            top_ranked, central_word,
            title=f"{label} (TextRank) — главное: «{central_word}»"
        )

    def show_word_cloud_for_selected(self):
        """Обработчик кнопки "Облако тегов" — собирает текст всех сейчас
           отмеченных галочкой реальных индексов (одна книга или сразу
           несколько — тогда облако общее, по всем вместе) и строит по
           ним частотное облако слов. Векторные модели, если отмечены
           вместе с обычными индексами, пропускаются — у них нет
           собственного текста (см. gather_text_for_indices)."""
        selected = self.app.index_manager.get_selected_indices_ordered()
        if not selected:
            messagebox.showinfo("Облако тегов", "Сначала отметьте галочкой хотя бы один индекс.")
            return
        texts = self.app.search_controller.gather_text_for_indices(selected)
        if not texts:
            messagebox.showinfo(
                "Облако тегов",
                "Не удалось получить текст отмеченных индексов (возможно, отмечены "
                "только векторные модели, без обычных индексов)."
            )
            return
        key_words = self.app._key_concept_words()  # None — фильтр выключен
        if key_words is None:
            word_freq_pairs = vector_visualization.compute_word_frequencies(texts)
            cloud_title = "Облако тегов"
            nothing = "После отсева коротких и служебных слов ничего содержательного не осталось."
        else:
            if not key_words:
                self.app._warn_key_concepts_empty("Облако тегов")
                return
            word_freq_pairs = vector_visualization.compute_key_word_frequencies(texts, key_words)
            cloud_title = "Облако ключевых понятий"
            nothing = "Ни одного слова словаря ключевых понятий (с вариациями) нет в отмеченных книгах."
        if not word_freq_pairs:
            messagebox.showinfo("Облако тегов", nothing)
            return
        self.show_word_cloud(word_freq_pairs, title=cloud_title)

    def show_word_cloud(self, word_freq_pairs, title="Облако тегов"):
        """Рисует облако тегов — размер слова пропорционален частоте,
           раскладка по спирали без наложений (см. vector_visualization.
           layout_word_cloud). Колесо мыши — масштаб (с фиксацией точки
           под курсором, тот же механизм, что и у остальных визуализаций),
           перетаскивание — сдвиг. В отличие от векторных визуализаций,
           тут нет понятия "клик — новый запрос" (это не о близости слов
           друг к другу, а просто о частоте в тексте)."""
        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas

        w = canvas.winfo_width() or 900
        h = canvas.winfo_height() or 600

        import tkinter.font as tkfont

        def measure(word, size):
            f = tkfont.Font(family='Arial', size=size, weight='bold')
            return f.measure(word), f.metrics('linespace')

        placed = vector_visualization.layout_word_cloud(word_freq_pairs, measure, w, h - 40)
        if not placed:
            messagebox.showinfo("Облако тегов", "Не удалось разместить ни одного слова.")
            self.hide_vector_visualization()
            return

        max_freq = word_freq_pairs[0][1]
        min_freq = word_freq_pairs[-1][1]
        freq_span = max(max_freq - min_freq, 1)
        freq_by_word = dict(word_freq_pairs)

        viz_state = {'zoom': 1.0, 'pan_x': 0.0, 'pan_y': 0.0, 'drag_start': None}

        def redraw():
            canvas.delete('all')
            zoom = viz_state['zoom']

            def scale(x, y):
                sx = (x - w / 2) * zoom + w / 2 + viz_state['pan_x']
                sy = (y - h / 2) * zoom + h / 2 + 40 + viz_state['pan_y']
                return sx, sy

            for word, x, y, size in placed:
                sx, sy = scale(x, y)
                scaled_size = max(6, int(size * zoom))
                freq = freq_by_word.get(word, min_freq)
                t = (freq - min_freq) / freq_span
                import colorsys
                hue = 0.62 - t * 0.5  # от сине-фиолетового (редкое) к тёплому красному (частое)
                r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.75)
                color = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
                canvas.create_text(sx, sy, text=word, font=('Arial', scaled_size, 'bold'), fill=color)

            canvas.create_text(
                w // 2, 20,
                text=f"{title} — {len(placed)} слов — "
                     f"колесо мыши: масштаб, перетаскивание: сдвиг",
                font=('Arial', 13, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas, lambda: (w / 2, h / 2 + 40), viz_state, redraw
        )
        redraw()

    def show_full_space_cloud(self, vectors_dict, vector_key, label_zoom_threshold=3.0, view=None, title=None):
        """Показывает ВСЁ пространство модели (образец словаря) как облако
           точек — без подписей слов, пока не приблизить: при тысячах слов
           подписи сразу были бы нечитаемым месивом. Колесо мыши
           (масштаб — тот же механизм, что и у остальных визуализаций, с
           фиксацией точки под курсором) при достижении label_zoom_threshold
           включает подписи — но только для точек, реально попадающих в
           видимую область экрана (иначе рисовать текст для тысяч слов на
           каждой перерисовке было бы медленно), клик по подписанному
           слову — обычный переход к его собственным соседям."""
        words, coords = vector_visualization.reduce_to_dims(vectors_dict, 2)
        if len(words) < 2:
            return

        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas

        viz_state = self._new_viz_state(view)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = max(x_max - x_min, 1e-9)
        y_span = max(y_max - y_min, 1e-9)
        margin = 40

        def redraw():
            canvas.delete('all')
            w = canvas.winfo_width() or 700
            h = canvas.winfo_height() or 500
            zoom = viz_state['zoom']

            def scale(x, y):
                sx = margin + (x - x_min) / x_span * (w - 2 * margin) * zoom + viz_state['pan_x']
                sy = h - margin - (y - y_min) / y_span * (h - 2 * margin) * zoom + viz_state['pan_y']
                return sx, sy

            show_labels = zoom >= label_zoom_threshold
            drawn = 0

            for word, (x, y) in zip(words, coords):
                sx, sy = scale(x, y)
                # Точки далеко за пределами видимой области не рисуем —
                # при тысячах слов это главная экономия времени,
                # особенно заметная после приближения, когда большинство
                # точек оказывается за кадром.
                if sx < -20 or sx > w + 20 or sy < -20 or sy > h + 20:
                    continue
                drawn += 1
                tag = f"cloudword_{word}"
                canvas.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill='#2a6fbf', outline='', tags=(tag,))
                if show_labels:
                    canvas.create_text(sx, sy - 11, text=word, font=('Arial', 10), tags=(tag,))

                    def _make_click(w_=word):
                        def _h(event):
                            self._on_viz_word_click(w_, vector_key)
                            return "break"
                        return _h
                    canvas.tag_bind(tag, '<Button-1>', _make_click())
                    canvas.tag_bind(tag, '<Enter>', lambda e: canvas.config(cursor='hand2'))
                    canvas.tag_bind(tag, '<Leave>', lambda e: canvas.config(cursor=''))

            hint = ("приблизьте колесом мыши, чтобы увидеть слова" if not show_labels
                   else "клик по слову: новый запрос им")
            canvas.create_text(
                w // 2, 20,
                text=f"{title or 'Всё пространство модели'} — {len(words)} слов (видно сейчас: {drawn}) — {hint}",
                font=('Arial', 13, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas, lambda: (margin, (canvas.winfo_height() or 500) - margin), viz_state, redraw
        )
        redraw()
        self._register_viz(
            lambda v: self.show_full_space_cloud(vectors_dict, vector_key, label_zoom_threshold,
                                                 view=v, title=title),
            viz_state, "всё пространство")

    def _get_density_cluster_data(self, vector_key):
        """Находит центр самой насыщенной понятиями области словаря модели
           и его соседей (см. "Сгущения понятий" в меню "3D/2D") — и сразу
           получает их векторы, в том же виде (слово, соседи, векторы),
           что и обычный "ручной" запрос словом, чтобы переиспользовать
           всю уже готовую отрисовку без изменений. Возвращает None (и
           показывает пояснение), если данных недостаточно."""
        key_words = self.app._key_concept_words()  # None — фильтр выключен
        if key_words is not None and not key_words:
            self.app._warn_key_concepts_empty("Сгущения понятий")
            return None
        vocab_vectors = self.app.vector_model_manager.get_vocabulary_vectors(vector_key, key_words=key_words)
        min_words = 10 if key_words is None else 5
        if len(vocab_vectors) < min_words:
            if key_words is None:
                messagebox.showinfo(
                    "Сгущения понятий",
                    "В словаре модели слишком мало подходящих слов для анализа "
                    "плотности (нужно хотя бы несколько десятков)."
                )
            else:
                messagebox.showinfo(
                    "Сгущения понятий",
                    f"Из словаря ключевых понятий (с вариациями) в модели найдено слов: "
                    f"{len(vocab_vectors)}.\n\nДля анализа плотности нужно не меньше {min_words}. "
                    "Добавьте слов кнопкой «КП»."
                )
            return None
        # Слов мало (словарь ключевых понятий небольшой) — число ближайших соседей
        # для оценки плотности подстраивается под их количество.
        k = 15 if key_words is None else min(15, len(vocab_vectors) - 1)
        center_word, neighbors = vector_visualization.find_densest_cluster(vocab_vectors, k=k, topn=k)
        if not center_word:
            messagebox.showinfo("Сгущения понятий", "Не удалось найти насыщенную область.")
            return None
        words = [center_word] + [w for w, _s in neighbors]
        vectors = {w: vocab_vectors[w] for w in words if w in vocab_vectors}
        return center_word, neighbors, vectors

    def _do_visualize_tsne(self, vectors, query_word, dims, vector_key=None):
        words, coords = vector_visualization.reduce_to_dims_tsne(vectors, dims)
        if dims == 2:
            self.show_vector_visualization_2d(words, coords, query_word, vector_key,
                                              method_label="t-SNE")
        else:
            output_dir = os.path.join("DB", "visualizations")
            try:
                path = vector_visualization.open_3d_visualization(words, coords, query_word, output_dir)
                self.app._update_log_field(f"🌐 3D-визуализация (t-SNE) открыта в браузере: {path}")
            except Exception as e:
                messagebox.showerror("Визуализация", f"Не удалось построить 3D-визуализацию: {e}")

    def _do_visualize(self, vectors, query_word, dims, vector_key=None):
        words, coords = vector_visualization.reduce_to_dims(vectors, dims)
        if dims == 2:
            self.show_vector_visualization_2d(words, coords, query_word, vector_key)
        else:
            output_dir = os.path.join("DB", "visualizations")
            try:
                path = vector_visualization.open_3d_visualization(words, coords, query_word, output_dir)
                self.app._update_log_field(f"🌐 3D-визуализация открыта в браузере: {path}")
            except Exception as e:
                messagebox.showerror("Визуализация", f"Не удалось построить 3D-визуализацию: {e}")

    def _visualize_2d_for(self, query_word, neighbors, vector_key):
        """Общий путь и для первого показа 2D (из меню), и для клика по
           слову внутри уже открытой визуализации (см. _on_viz_word_click)
           — получает вектора и сразу перерисовывает, без повторного
           показа меню выбора 2D/3D."""
        words = [query_word] + [w for w, _score in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            return
        self._do_visualize(vectors, query_word, dims=2, vector_key=vector_key)

    def _on_viz_word_click(self, word, vector_key, revisualize=None):
        """Клик по слову внутри визуализации — равносильно тому, что
           пользователь сам ввёл это слово запросом и нажал поиск (в том
           же векторном режиме): обновляются и обычные результаты, и
           список в окне "Совпадения", а сама визуализация сразу
           перерисовывается для НОВОГО слова и его vector_model_topn
           соседей — без необходимости заново нажимать кнопку "3D/2D".

           revisualize(query_word, neighbors, vector_key) — КАКОЙ именно
           визуализацией перерисовать результат: по умолчанию (не задан) —
           2D-проекция, но граф-сеть и любые другие передают сюда свою
           собственную функцию, чтобы клик оставался В ПРЕДЕЛАХ той же
           визуализации, а не всегда "убегал" в 2D-проекцию."""
        # Снимок ТЕКУЩЕГО уровня — до того, как строка запроса будет
        # перезаписана кликнутым словом (кнопка "Назад" вернёт всё как было).
        self._push_current_viz()
        self._viz_nav_mode = 'forward'
        self._viz_registered = False
        try:
            self.app.query_entry.delete(0, tk.END)
            self.app.query_entry.insert(0, word)
            self.app.search_controller.do_search()
            # do_search() внутри уже вызвал hide_vector_viz_callback (вернул
            # обычный текст) и обновил word_panel новыми соседями для word —
            # сразу показываем визуализацию заново для них, а не обычный текст.
            neighbors = getattr(self.app.word_panel, '_last_neighbors', None)
            new_vector_key = getattr(self.app.word_panel, '_last_vector_key', None)
            new_query_word = getattr(self.app.word_panel, '_last_query_word', None)
            if not neighbors or not new_vector_key:
                return
            if revisualize is not None:
                revisualize(new_query_word, neighbors, new_vector_key)
            else:
                self._visualize_2d_for(new_query_word, neighbors, new_vector_key)
        finally:
            self._viz_nav_mode = None
            if self._viz_registered:
                self._update_viz_back_button()
            else:
                # Новая визуализация не показана (у слова нет соседей или
                # перерисовка не удалась) — на экране уже обычный текст,
                # цепочка уровней оборвана, возвращаться некуда.
                self._clear_viz_history()

    def _revisualize_network(self, query_word, neighbors, vector_key, threshold=0.4):
        """revisualize-функция для клика внутри графа-сети (см.
           _on_viz_word_click) — держит клик в пределах той же
           визуализации, а не переключает на 2D-проекцию."""
        words = [query_word] + [w for w, _score in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            return
        self.show_network_graph(vectors, query_word, vector_key, threshold=threshold)

    def _setup_viz_zoom_pan(self, canvas, get_origin, viz_state, redraw_fn):
        """Общая логика приближения (колесо мыши, с фиксацией точки под
           курсором — иначе близко расположенные точки при приближении
           "убегают" от курсора) и панорамирования (перетаскивание) —
           используется во всех визуализациях, что рисуют координатную
           сцену на Canvas (2D-проекция, граф-сеть, дендрограмма, радиальная
           раскладка). get_origin() — вызываемый без аргументов, возвращает
           (origin_x, origin_y) — экранную точку, которая соответствует
           точке (0,0) нормированных координат при zoom=1/pan=0; вызывается
           заново при каждом повороте колеса (не константа — например, у
           радиальной раскладки это центр canvas, который меняется при
           изменении размера окна). viz_state — уже созданный вызывающим
           кодом словарь {'zoom', 'pan_x', 'pan_y', 'drag_start'} (нужен
           вызывающему ДО этого вызова — его же читает redraw_fn).
           redraw_fn() — функция самой визуализации, перерисовывающая всё
           заново с ТЕКУЩИМИ zoom/pan."""
        def on_zoom(event):
            zooming_in = getattr(event, 'delta', 0) > 0 or getattr(event, 'num', None) == 4
            factor = 1.15 if zooming_in else (1 / 1.15)
            old_zoom = viz_state['zoom']
            new_zoom = max(0.2, min(15.0, old_zoom * factor))
            if new_zoom == old_zoom:
                return  # уже у предела масштаба
            ratio = new_zoom / old_zoom
            mx, my = event.x, event.y
            origin_x, origin_y = get_origin()
            shifted_x = mx - origin_x
            shifted_y = my - origin_y
            viz_state['pan_x'] = shifted_x - (shifted_x - viz_state['pan_x']) * ratio
            viz_state['pan_y'] = shifted_y - (shifted_y - viz_state['pan_y']) * ratio
            viz_state['zoom'] = new_zoom
            redraw_fn()

        def on_drag_start(event):
            viz_state['drag_start'] = (event.x, event.y)

        def on_drag_motion(event):
            if viz_state['drag_start'] is None:
                return
            dx = event.x - viz_state['drag_start'][0]
            dy = event.y - viz_state['drag_start'][1]
            viz_state['pan_x'] += dx
            viz_state['pan_y'] += dy
            viz_state['drag_start'] = (event.x, event.y)
            redraw_fn()

        def on_drag_end(event):
            viz_state['drag_start'] = None

        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>',
                   '<ButtonPress-1>', '<B1-Motion>', '<ButtonRelease-1>'):
            canvas.unbind(seq)
        canvas.bind('<MouseWheel>', on_zoom)      # Windows/macOS
        canvas.bind('<Button-4>', on_zoom)        # Linux — колесо вверх
        canvas.bind('<Button-5>', on_zoom)        # Linux — колесо вниз
        canvas.bind('<ButtonPress-1>', on_drag_start)
        canvas.bind('<B1-Motion>', on_drag_motion)
        canvas.bind('<ButtonRelease-1>', on_drag_end)

    def show_vector_visualization_2d(self, words, coords, query_word, vector_key=None, method_label="PCA", view=None):
        """Рисует 2D-график прямо в среднем окне — на месте обычного текста
           результатов (result_text прячется, показывается Canvas; любой
           следующий поиск возвращает обычный вид, см.
           hide_vector_visualization — вызывается в начале do_search).

           Колесо мыши — масштаб (приблизить/отдалить, с фиксацией той
           точки, что под курсором), перетаскивание левой кнопкой — сдвиг
           вида. Клик по слову — новый запрос этим словом (см.
           _on_viz_word_click) — эквивалентно тому, что пользователь сам
           ввёл его и нажал поиск, только сразу же снова показывает 2D для
           него. Оригинальные координаты (words/coords) не меняются —
           zoom/pan — это только то, как их сейчас рисуют на экране,
           каждая перерисовка (redraw) пересчитывает всё заново с текущим
           масштабом и сдвигом."""
        self._prepare_viz_canvas()

        canvas = self.app.vector_viz_canvas
        viz_state = self._new_viz_state(view)

        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = max(x_max - x_min, 1e-9)
        y_span = max(y_max - y_min, 1e-9)
        margin = 70

        def redraw():
            canvas.delete('all')
            w = canvas.winfo_width() or 700
            h = canvas.winfo_height() or 500
            zoom = viz_state['zoom']

            def scale(x, y):
                sx = margin + (x - x_min) / x_span * (w - 2 * margin) * zoom + viz_state['pan_x']
                sy = h - margin - (y - y_min) / y_span * (h - 2 * margin) * zoom + viz_state['pan_y']
                return sx, sy

            qx, qy = None, None
            for word, (x, y) in zip(words, coords):
                if word == query_word:
                    qx, qy = scale(x, y)

            for i, (word, (x, y)) in enumerate(zip(words, coords)):
                sx, sy = scale(x, y)
                is_query = (word == query_word)
                if not is_query and qx is not None:
                    canvas.create_line(qx, qy, sx, sy, fill='#cccccc')
                color = '#c0392b' if is_query else '#2a6fbf'
                r = 9 if is_query else 7
                tag = f"vizword_{i}"
                canvas.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline='', tags=(tag,))
                font = ('Arial', 15, 'bold') if is_query else ('Arial', 13)
                canvas.create_text(sx, sy - 18, text=word, font=font, tags=(tag,))
                if vector_key is not None:
                    # Клик по слову — новый запрос им (см. _on_viz_word_click).
                    # return "break" — чтобы не запускалось ЕЩЁ и
                    # перетаскивание всей картинки от того же клика (иначе
                    # оно сработало бы следом, уже по новой, только что
                    # перерисованной сцене).
                    def _make_click_handler(w=word):
                        def _handler(event):
                            self._on_viz_word_click(w, vector_key)
                            return "break"
                        return _handler
                    canvas.tag_bind(tag, '<Button-1>', _make_click_handler())
                    canvas.tag_bind(tag, '<Enter>', lambda e: canvas.config(cursor='hand2'))
                    canvas.tag_bind(tag, '<Leave>', lambda e: canvas.config(cursor=''))

            hint = "клик по слову: новый запрос им" if vector_key is not None else ""
            canvas.create_text(
                w // 2, 20,
                text=f"Векторная близость слов к «{query_word}» (2D, {method_label}) — "
                     f"колесо мыши: масштаб, перетаскивание: сдвиг" + (f", {hint}" if hint else ""),
                font=('Arial', 13, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas, lambda: (margin, (canvas.winfo_height() or 500) - margin), viz_state, redraw
        )
        redraw()
        self._register_viz(
            lambda v: self.show_vector_visualization_2d(words, coords, query_word, vector_key,
                                                        method_label, view=v),
            viz_state, query_word)

    def show_bar_chart(self, neighbors, query_word, title=None):
        """Столбчатая диаграмма близости — без проекции, ничего не
           огрубляется: те же числа, что и в окне "Совпадения", только
           нагляднее (горизонтальные столбики по убыванию). title — для
           случаев, когда числа не про близость к одному слову запроса
           (например, оценки центральности TextRank) — переопределяет
           заголовок по умолчанию."""
        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>',
                   '<ButtonPress-1>', '<B1-Motion>', '<ButtonRelease-1>'):
            canvas.unbind(seq)
        canvas.delete('all')

        w = canvas.winfo_width() or 700
        h = canvas.winfo_height() or 500
        sorted_neighbors = sorted(neighbors, key=lambda p: p[1], reverse=True)
        n = len(sorted_neighbors)

        canvas.create_text(w // 2, 20, text=title or f"Близость слов к «{query_word}»",
                           font=('Arial', 15, 'bold'), fill='#1a4a7a')
        if n == 0:
            canvas.create_text(w // 2, h // 2, text="Нет соседей для отображения", font=('Arial', 13))
            return

        top_margin, bottom_margin = 50, 20
        left_margin, right_margin = 160, 70
        bar_area_h = max(h - top_margin - bottom_margin, n * 10)
        gap = bar_area_h / n
        bar_h = min(16, gap - 10)
        max_score = max(s for _w, s in sorted_neighbors) or 1.0

        for i, (word, score) in enumerate(sorted_neighbors):
            y_center = top_margin + gap * i + gap / 2
            bar_len = (score / max_score) * (w - left_margin - right_margin)
            canvas.create_rectangle(left_margin, y_center - bar_h / 2,
                                    left_margin + bar_len, y_center + bar_h / 2,
                                    fill='#2a6fbf', outline='')
            canvas.create_text(left_margin - 10, y_center, text=word,
                               font=('Arial', 12), anchor='e')
            canvas.create_text(left_margin + bar_len + 8, y_center, text=f"{score:.3f}",
                               font=('Arial', 11), anchor='w')

    def show_heatmap(self, vectors, query_word):
        """Тепловая карта попарных близостей — сетка "слово x слово",
           каждая клетка закрашена по силе связи. В отличие от 2D/3D-
           проекции, показывает точное число для КАЖДОЙ пары, включая
           близость соседей МЕЖДУ СОБОЙ, не только со словом запроса."""
        words, sim = vector_visualization.compute_pairwise_similarity(vectors)
        if sim is None or len(words) < 2:
            return

        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>',
                   '<ButtonPress-1>', '<B1-Motion>', '<ButtonRelease-1>'):
            canvas.unbind(seq)
        canvas.delete('all')

        w = canvas.winfo_width() or 700
        h = canvas.winfo_height() or 500
        n = len(words)
        top_margin, bottom_margin = 50, 20
        left_margin, right_margin = 140, 20
        grid_w = w - left_margin - right_margin
        grid_h = h - top_margin - bottom_margin
        cell_w = grid_w / n
        cell_h = grid_h / n

        canvas.create_text(
            w // 2, 20,
            text=f"Попарная близость слов, близких к «{query_word}» (столбцы — в том же порядке, что строки)",
            font=('Arial', 13, 'bold'), fill='#1a4a7a'
        )

        def color_for(value):
            # Радужный спектр — не только оттенки одного цвета, а полный
            # круг тона (HSV), чтобы близкие ЧИСЛА близости давали близкие
            # ЦВЕТА (соседние по спектру), а непохожие числа — заметно
            # различающиеся, разные по тону цвета. -1..1 -> красный..
            # ...фиолетовый (через оранжевый/жёлтый/зелёный/синий).
            import colorsys
            v = max(-1.0, min(1.0, float(value)))
            hue = (v + 1.0) / 2.0 * 0.82  # 0.82, не 1.0 — чтобы не заворачивало обратно в красный
            r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.95)
            return f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'

        for i in range(n):
            for j in range(n):
                x0 = left_margin + j * cell_w
                y0 = top_margin + i * cell_h
                value = sim[i][j]
                canvas.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h,
                                        fill=color_for(value), outline='#e8e8e8')
                if cell_w > 30 and cell_h > 16:
                    canvas.create_text(x0 + cell_w / 2, y0 + cell_h / 2,
                                       text=f"{value:.2f}", font=('Arial', 8))
            is_query = (words[i] == query_word)
            canvas.create_text(left_margin - 8, top_margin + i * cell_h + cell_h / 2,
                               text=words[i], font=('Arial', 10, 'bold' if is_query else 'normal'),
                               anchor='e')

    def show_dendrogram_viz(self, vectors, query_word):
        """Дендрограмма — дерево, на каком "уровне похожести" слова
           объединяются в группы. Полезно, когда важнее структура (что с
           чем роднее), а не точные расстояния. Колесо мыши — масштаб (с
           фиксацией точки под курсором), перетаскивание — сдвиг."""
        words, Z = vector_visualization.compute_linkage(vectors)
        if Z is None:
            return
        from scipy.cluster.hierarchy import dendrogram as scipy_dendrogram
        dd = scipy_dendrogram(Z, labels=words, no_plot=True)

        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas

        viz_state = {'zoom': 1.0, 'pan_x': 0.0, 'pan_y': 0.0, 'drag_start': None}
        top_margin, bottom_margin = 50, 70
        left_margin, right_margin = 40, 40

        all_x = [x for seg in dd['icoord'] for x in seg]
        all_y = [y for seg in dd['dcoord'] for y in seg]
        x_min, x_max = min(all_x), max(all_x)
        y_max = max(all_y) or 1.0

        def redraw():
            canvas.delete('all')
            w = canvas.winfo_width() or 700
            h = canvas.winfo_height() or 500
            zoom = viz_state['zoom']

            def sx(x):
                return (left_margin + (x - x_min) / max(x_max - x_min, 1e-9)
                       * (w - left_margin - right_margin) * zoom + viz_state['pan_x'])

            def sy(y):
                return ((h - bottom_margin) - (y / y_max) * (h - top_margin - bottom_margin) * zoom
                       + viz_state['pan_y'])

            for icoord, dcoord in zip(dd['icoord'], dd['dcoord']):
                points = [(sx(x), sy(y)) for x, y in zip(icoord, dcoord)]
                for k in range(len(points) - 1):
                    canvas.create_line(points[k][0], points[k][1], points[k + 1][0], points[k + 1][1],
                                       fill='#2a6fbf', width=2)

            for i, word in enumerate(dd['ivl']):
                leaf_x = 5 + 10 * i
                x = sx(leaf_x)
                y = sy(0)
                is_query = (word == query_word)
                canvas.create_text(x, y + 8, text=word, anchor='n',
                                   font=('Arial', 10, 'bold' if is_query else 'normal'),
                                   fill='#c0392b' if is_query else 'black')

            canvas.create_text(
                w // 2, 20,
                text=f"Дендрограмма — группировка слов, близких к «{query_word}» — "
                     f"колесо мыши: масштаб, перетаскивание: сдвиг",
                font=('Arial', 14, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas,
            lambda: (left_margin, (canvas.winfo_height() or 500) - bottom_margin),
            viz_state, redraw
        )
        redraw()

    def show_network_graph(self, vectors, query_word, vector_key, threshold=0.4, view=None):
        """Граф-сеть — слова-узлы (расположены как в PCA-проекции, чтобы
           близкие по смыслу слова оказались рядом и на экране), линии
           только между парами с близостью выше threshold, толщина линии —
           сила связи. В отличие от облака точек, явно показывает СВЯЗИ, а
           не только взаимное расположение. Колесо мыши — масштаб (с
           фиксацией узла под курсором), перетаскивание — сдвиг. Клик по
           узлу — новый запрос этим словом, с перерисовкой ЭТОГО ЖЕ графа
           (не переключение на 2D-проекцию — см. _revisualize_network)."""
        words, coords = vector_visualization.reduce_to_dims(vectors, 2)
        _words_sim, sim = vector_visualization.compute_pairwise_similarity(vectors)
        if len(words) < 2:
            return

        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas

        viz_state = self._new_viz_state(view)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = max(x_max - x_min, 1e-9)
        y_span = max(y_max - y_min, 1e-9)
        margin = 70

        def redraw():
            canvas.delete('all')
            w = canvas.winfo_width() or 700
            h = canvas.winfo_height() or 500
            zoom = viz_state['zoom']

            def scale(x, y):
                sx = margin + (x - x_min) / x_span * (w - 2 * margin) * zoom + viz_state['pan_x']
                sy = h - margin - (y - y_min) / y_span * (h - 2 * margin) * zoom + viz_state['pan_y']
                return sx, sy

            positions = {word: scale(x, y) for word, (x, y) in zip(words, coords)}

            n = len(words)
            for i in range(n):
                for j in range(i + 1, n):
                    s = sim[i][j]
                    if s >= threshold:
                        x1, y1 = positions[words[i]]
                        x2, y2 = positions[words[j]]
                        width_px = max(1, min(2, round(s * 2)))
                        canvas.create_line(x1, y1, x2, y2, fill='#a0b8d0', width=width_px)

            for word in words:
                x, y = positions[word]
                is_query = (word == query_word)
                color = '#c0392b' if is_query else '#2a6fbf'
                r = 9 if is_query else 6
                tag = f"netnode_{word}"
                canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline='', tags=(tag,))
                canvas.create_text(x, y - 16, text=word,
                                   font=('Arial', 12, 'bold' if is_query else 'normal'), tags=(tag,))

                def _make_click(w=word):
                    def _h(event):
                        self._on_viz_word_click(
                            w, vector_key,
                            revisualize=lambda qw, nb, vk: self._revisualize_network(qw, nb, vk, threshold)
                        )
                        return "break"
                    return _h
                canvas.tag_bind(tag, '<Button-1>', _make_click())
                canvas.tag_bind(tag, '<Enter>', lambda e: canvas.config(cursor='hand2'))
                canvas.tag_bind(tag, '<Leave>', lambda e: canvas.config(cursor=''))

            canvas.create_text(
                w // 2, 20,
                text=f"Граф связей слов, близких к «{query_word}» (порог {threshold:.1f}) — "
                     f"колесо мыши: масштаб, перетаскивание: сдвиг, клик по узлу: новый запрос",
                font=('Arial', 13, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas, lambda: (margin, (canvas.winfo_height() or 500) - margin), viz_state, redraw
        )
        redraw()
        self._register_viz(
            lambda v: self.show_network_graph(vectors, query_word, vector_key, threshold, view=v),
            viz_state, query_word)

    def show_radial_layout(self, vectors, query_word, vector_key, view=None):
        """Радиальная раскладка — слово запроса в центре; расстояние от
           центра = обратная близость к запросу (ближе по смыслу — ближе к
           центру), а угол/секторы = группировка слов по их близости
           между собой (не только с запросом) — то есть похожие друг на
           друга соседи оказываются в одном "клине" круга, а не просто
           разбросаны по расстоянию. Колесо мыши — масштаб (с фиксацией
           точки под курсором), перетаскивание — сдвиг, клик по слову —
           новый запрос с перерисовкой того же типа."""
        words, coords = vector_visualization.compute_radial_layout(vectors, query_word)
        if len(words) < 2:
            return

        self._prepare_viz_canvas()
        canvas = self.app.vector_viz_canvas

        viz_state = self._new_viz_state(view)
        margin = 70

        def redraw():
            canvas.delete('all')
            w = canvas.winfo_width() or 700
            h = canvas.winfo_height() or 500
            zoom = viz_state['zoom']
            cx = w / 2 + viz_state['pan_x']
            cy = h / 2 + viz_state['pan_y']
            radius_px = (min(w, h) / 2 - margin) * zoom

            # Направляющие круги-подсказки — "ближе к запросу"/"дальше" —
            # чисто ориентир, без подписей чисел (это не точная шкала, в
            # отличие от тепловой карты или столбиков).
            for frac in (0.33, 0.66, 1.0):
                canvas.create_oval(cx - radius_px * frac, cy - radius_px * frac,
                                   cx + radius_px * frac, cy + radius_px * frac,
                                   outline='#e5e5e5')

            def scale(x, y):
                return cx + x * radius_px, cy - y * radius_px

            for i, (word, (x, y)) in enumerate(zip(words, coords)):
                sx, sy = scale(x, y)
                is_query = (word == query_word)
                if not is_query:
                    qx, qy = scale(0.0, 0.0)
                    canvas.create_line(qx, qy, sx, sy, fill='#eeeeee')
                color = '#c0392b' if is_query else '#2a6fbf'
                r = 9 if is_query else 6
                tag = f"radword_{i}"
                canvas.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline='', tags=(tag,))
                font = ('Arial', 14, 'bold') if is_query else ('Arial', 11)
                canvas.create_text(sx, sy - 14, text=word, font=font, tags=(tag,))

                def _make_click(w=word):
                    def _h(event):
                        self._on_viz_word_click(w, vector_key, revisualize=self._revisualize_radial)
                        return "break"
                    return _h
                canvas.tag_bind(tag, '<Button-1>', _make_click())
                canvas.tag_bind(tag, '<Enter>', lambda e: canvas.config(cursor='hand2'))
                canvas.tag_bind(tag, '<Leave>', lambda e: canvas.config(cursor=''))

            canvas.create_text(
                w // 2, 20,
                text=f"«{query_word}» в центре — расстояние: близость к запросу, "
                     f"сектор: похожесть слов между собой",
                font=('Arial', 13, 'bold'), fill='#1a4a7a'
            )

        self._setup_viz_zoom_pan(
            canvas,
            lambda: ((canvas.winfo_width() or 700) / 2, (canvas.winfo_height() or 500) / 2),
            viz_state, redraw
        )
        redraw()
        self._register_viz(
            lambda v: self.show_radial_layout(vectors, query_word, vector_key, view=v),
            viz_state, query_word)

    def _revisualize_radial(self, query_word, neighbors, vector_key):
        """revisualize-функция для клика внутри радиальной раскладки (см.
           _on_viz_word_click) — держит клик в пределах той же
           визуализации."""
        words = [query_word] + [w for w, _score in neighbors]
        vectors = self.app.vector_model_manager.get_word_vectors(vector_key, words)
        if len(vectors) < 2:
            return
        self.show_radial_layout(vectors, query_word, vector_key)

    # ---------- навигация "Назад" по уровням визуализации ----------
    # Клик по слову внутри визуализации открывает новый уровень (запрос этим
    # словом + перерисовка). Каждый такой переход кладёт в _viz_history снимок
    # уровня, с которого ушли; кнопка "Назад" снимает последний и возвращает
    # всё как было — вплоть до исходной визуализации (той, что открыта из меню
    # кнопки "3D/2D" или "Всё пространство", она начинает новую цепочку).
    # Повторный расчёт даёт ту же картинку: PCA, t-SNE и KMeans считаются с
    # random_state=0, так что снимок хранит не пиксели, а способ перерисовки.

    _VIZ_HISTORY_LIMIT = 100

    def _new_viz_state(self, view=None):
        """Масштаб и сдвиг для новой визуализации: по умолчанию вид "целиком";
           view — {'zoom','pan_x','pan_y'} ранее сохранённого вида (при
           возврате назад показываем уровень приближенным/сдвинутым ровно
           так, как его оставили — иначе, например, облако всего
           пространства пришлось бы заново приближать к нужному месту)."""
        state = {'zoom': 1.0, 'pan_x': 0.0, 'pan_y': 0.0, 'drag_start': None}
        if view:
            state['zoom'] = view.get('zoom', 1.0)
            state['pan_x'] = view.get('pan_x', 0.0)
            state['pan_y'] = view.get('pan_y', 0.0)
        return state

    def _prepare_viz_canvas(self):
        """Единый вход для ВСЕХ визуализаций на холсте: подменяет обычный
           текст результатов холстом. Визуализация, показанная вне перехода по
           уровням (выбрана из меню, а не получена кликом/"Назад"), —
           начало новой цепочки: прежняя история сбрасывается."""
        self.app.result_text.pack_forget()
        self.app.vector_viz_canvas.pack(side='top', fill=tk.BOTH, expand=True)
        self.app.vector_viz_canvas.update_idletasks()
        if self._viz_nav_mode is None:
            self._clear_viz_history()
        self._update_viz_back_button()

    def _register_viz(self, render, viz_state, label):
        """Визуализация сообщает, КАК её перерисовать (render(view)), где её
           живое состояние масштаба/сдвига (viz_state) и как назвать этот
           уровень на кнопке "Назад" (label). Вызывается в конце показа
           каждой визуализации с переходом по клику."""
        self._current_viz = {'render': render, 'view_state': viz_state, 'label': label}
        self._viz_registered = True
        self._update_viz_back_button()

    def _clear_viz_history(self):
        self._viz_history.clear()
        self._current_viz = None
        self._update_viz_back_button()

    def _push_current_viz(self):
        """Кладёт снимок показанного сейчас уровня в историю (вызывается
           перед переходом по клику)."""
        current = self._current_viz
        if current is None:
            return
        view_state = current['view_state']
        self._viz_history.append({
            'render': current['render'],
            'label': current['label'],
            'view': {k: view_state[k] for k in ('zoom', 'pan_x', 'pan_y')},
            'query_text': self.app.query_entry.get(),
        })
        del self._viz_history[:-self._VIZ_HISTORY_LIMIT]

    def _viz_go_back(self):
        """Кнопка "Назад": возвращает предыдущий уровень таким, каким его
           оставили — строка запроса, результаты и список "Совпадения" (как
           если бы запрос выполнили заново: это то же, что делает переход
           вперёд) и сама визуализация с прежними масштабом и сдвигом."""
        if not self._viz_history:
            return
        snapshot = self._viz_history.pop()
        self._viz_nav_mode = 'back'
        self._viz_registered = False
        try:
            self.app.query_entry.delete(0, tk.END)
            self.app.query_entry.insert(0, snapshot['query_text'])
            if snapshot['query_text'].strip():
                self.app.search_controller.do_search()
            else:
                # Исходная визуализация открыта без запроса (например, "Всё
                # пространство"): после перехода по слову в окне "Совпадения"
                # остались соседи кликнутого слова — возвращаем окно в
                # состояние "поиска ещё не было".
                self.app.word_panel.clear()
            snapshot['render'](snapshot['view'])
        finally:
            self._viz_nav_mode = None
            if self._viz_registered:
                self._update_viz_back_button()
            else:
                self._clear_viz_history()

    def _update_viz_back_button(self):
        """Кнопка "◀ Назад" — дочерний виджет холста визуализации, поэтому
           перерисовка холста (canvas.delete('all') при каждом масштабировании)
           её не стирает; показана, пока в истории есть куда возвращаться."""
        canvas = getattr(self.app, 'vector_viz_canvas', None)
        if canvas is None:
            return
        if self._viz_history:
            if self.btn_viz_back is None:
                self.btn_viz_back = tk.Button(canvas, command=self._viz_go_back,
                                              font=('Arial', 12, 'bold'), bg='#4a7a8a', fg='white',
                                              padx=8, pady=2, cursor='hand2')
            label = self._viz_history[-1]['label']
            text = f"◀ Назад: {label}" if label else "◀ Назад"
            if len(self._viz_history) > 1:
                text += f"  ({len(self._viz_history)})"
            self.btn_viz_back.config(text=text)
            # Внизу слева: сверху по центру у каждой визуализации длинный заголовок.
            self.btn_viz_back.place(x=10, rely=1.0, y=-10, anchor='sw')
            self.btn_viz_back.lift()
        elif self.btn_viz_back is not None:
            self.btn_viz_back.place_forget()

    def hide_vector_visualization(self):
        """Возвращает среднее окно к обычному виду (result_text) — вызывать
           перед показом любых обычных результатов, на случай если сейчас
           показана 2D-визуализация."""
        # Если это НЕ часть перехода по уровням (клик по слову, "Назад",
        # пересчёт словоформ — они ставят свой режим), значит, пользователь
        # просто выполнил обычный поиск: цепочка уровней закончена.
        if self._viz_nav_mode is None:
            self._clear_viz_history()
        if self.app.vector_viz_canvas.winfo_ismapped():
            self.app.vector_viz_canvas.pack_forget()
            self.app.result_text.pack(side='top', fill=tk.BOTH, expand=True)
