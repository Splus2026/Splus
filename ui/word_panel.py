import tkinter as tk
from tkinter import scrolledtext

class WordPanel:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app  # ссылка на главное окно (MainWindow)
        self.frame = tk.Frame(parent, bg='#d4e8f7', width=210, height=1)
        self.frame.pack(fill='both', expand=True, padx=5, pady=5)
        # pack_propagate(False) фиксирует ширину (иначе фрейм раздувается под
        # "естественную" ширину текстового виджета внутри — у Text/ScrolledText
        # это по умолчанию около 80 символов, что гораздо шире 180px). Высота
        # при этом взята минимальной (1px) специально — иначе тот же механизм
        # не даст фрейму сжаться меньше явно указанной высоты, а нам нужно,
        # чтобы в режиме разделения окна верхняя и нижняя панели могли
        # нормально разделить между собой высоту пополам.
        self.frame.pack_propagate(False)

        header_row = tk.Frame(self.frame, bg='#d4e8f7')
        header_row.pack(fill='x', pady=(0, 5))

        # Кнопка "3D/2D" — слева от надписи "Совпадения:", появляется
        # только когда эту панель заполняет word-embedding модель
        # (FastText, у неё есть отдельные векторы слов) — см.
        # update_vector_words() ниже и app_window.py. Скрыта по умолчанию:
        # ни в обычном поиске, ни у MiniLM/LSA (там нет отдельных векторов
        # слов) кнопка не нужна.
        self.viz_button = tk.Button(
            header_row, text="3D/2D", font=('Arial', 10, 'bold'),
            bg='#6a4a8a', fg='white', relief='raised',
            command=self._on_viz_button_click
        )
        # Не пакуется здесь — show_3d_button()/hide_3d_button() управляют
        # видимостью.

        label = tk.Label(header_row, text="Совпадения:",
                         font=('Arial', 12, 'bold'), bg='#d4e8f7', fg='#1a4a7a')
        label.pack(side='left', anchor='w', padx=(12, 0))
        self._header_label = label

        self.text = scrolledtext.ScrolledText(
            self.frame,
            wrap=tk.WORD,
            bg='white',
            fg='#1a2a3a',
            font=('Consolas', self.main_app.font_size)
        )
        self.text.pack(fill='both', expand=True)
        self.text.config(state='disabled')

        self.text.tag_config('exact', background='cyan', foreground='black')
        self.text.tag_config('prefix', background='light blue', foreground='black')
        self.text.tag_config('excluded', background='#ffcccc', foreground='black', overstrike=True)
        self.text.tag_config('selected', background='#aaccff', foreground='black')
        self.text.tag_config('word_base', foreground='black')

        self.text.bind('<Button-1>', self._on_word_click)
        self.text.bind('<Button-3>', self._on_right_click)

        self.word_positions = []
        self.all_excluded_flag = False

    def _on_right_click(self, event):
        if not self.word_positions:
            return
        all_words = [word for _, _, word in self.word_positions]
        excluded = self.main_app.excluded_words
        if all(w in excluded for w in all_words):
            for w in all_words:
                excluded.discard(w)
            self.all_excluded_flag = False
        else:
            for w in all_words:
                excluded.add(w)
            self.all_excluded_flag = True
        self.main_app.refresh_display()

    def _select_all_words(self):
        self.text.config(state='normal')
        self.text.tag_remove('selected', '1.0', tk.END)
        for start, end, word in self.word_positions:
            self.text.tag_add('selected', start, end)
        self.text.config(state='disabled')

    def _deselect_all_words(self):
        self.text.config(state='normal')
        self.text.tag_remove('selected', '1.0', tk.END)
        self.text.config(state='disabled')

    def update_words(self, exact_words, prefix_dict, word_counts=None, highlight_scheme='blue'):
        self.hide_3d_button()
        if highlight_scheme == 'yellow':
            exact_color = 'yellow'
            prefix_color = 'gold'
        else:
            exact_color = 'cyan'
            prefix_color = 'light blue'

        self.text.tag_config('exact', background=exact_color, foreground='black')
        self.text.tag_config('prefix', background=prefix_color, foreground='black')
        self.text.tag_config('excluded', background='#ffcccc', foreground='black', overstrike=True)

        # Положение прокрутки: при перерисовке того же списка (слово исключили/вернули кликом)
        # оно сохраняется, а не прыгает в начало; для нового списка слов — начинаем сверху.
        try:
            prev_top = self.text.yview()[0]
        except Exception:
            prev_top = 0.0
        self.text.config(state='normal')
        self.text.delete(1.0, tk.END)
        self.word_positions = []
        self.all_excluded_flag = False

        word_counts = word_counts or {}

        all_words = set(exact_words) | set(prefix_dict.keys())
        if not all_words:
            self._last_words_key = None
            self.text.insert(tk.END, "Нет совпавших слов")
            self.text.config(state='disabled')
            return

        def highlighted_len(word):
            # Длина подсвеченной части: для полнотекстового (точного) совпадения —
            # длина всего слова, для инфиксного/префиксного — длина найденного
            # фрагмента.
            if word in exact_words:
                return len(word)
            return len(prefix_dict.get(word, '') or '')

        def sort_key(word):
            # Сначала все полнотекстовые совпадения, потом все инфиксные;
            # внутри каждой группы — по убыванию длины подсвеченной части.
            is_infix = word not in exact_words
            return (is_infix, -highlighted_len(word), word)

        ordered_words = sorted(all_words, key=sort_key)
        words_key = tuple(ordered_words)

        excluded = self.main_app.excluded_words
        for idx, word in enumerate(ordered_words):
            start = self.text.index(tk.END)
            is_excluded = word in excluded
            tag_name = f"word_{idx}"

            if word in exact_words:
                if is_excluded:
                    self.text.insert(tk.END, word, ('excluded', tag_name))
                else:
                    self.text.insert(tk.END, word, ('exact', tag_name))
            elif word in prefix_dict:
                pref = prefix_dict[word]
                if pref and pref in word:
                    pos = word.find(pref)
                    if is_excluded:
                        self.text.insert(tk.END, word, ('excluded', tag_name))
                    else:
                        self.text.insert(tk.END, word[:pos])
                        self.text.insert(tk.END, word[pos:pos+len(pref)], ('prefix', tag_name))
                        self.text.insert(tk.END, word[pos+len(pref):], tag_name)
                else:
                    if is_excluded:
                        self.text.insert(tk.END, word, ('excluded', tag_name))
                    else:
                        self.text.insert(tk.END, word, tag_name)
            else:
                if is_excluded:
                    self.text.insert(tk.END, word, ('excluded', tag_name))
                else:
                    self.text.insert(tk.END, word, tag_name)

            # Количество вхождений слова в текстах — в скобках после слова
            count = word_counts.get(word, 0)
            if count:
                self.text.insert(tk.END, f" ({count})", tag_name)

            self.text.insert(tk.END, '\n')
            end = self.text.index(tk.END)
            self.word_positions.append((start, end, word))

            self.text.tag_bind(tag_name, '<Button-1>',
                               lambda e, w=word: self._on_word_click_tag(e, w))

        self.text.config(state='disabled')

        if words_key == getattr(self, '_last_words_key', None) and prev_top > 0:
            try:
                self.text.update_idletasks()   # без этого yview_moveto иногда не срабатывает
                self.text.yview_moveto(prev_top)
            except Exception:
                pass
        self._last_words_key = words_key

        if all_words and all(w in excluded for w in all_words):
            self._select_all_words()
            self.all_excluded_flag = True

    def update_vector_words(self, neighbors, query_word=None, vector_key=None):
        """Показывает список векторно-близких слов с их числовой близостью —
           для режима поиска по обученной векторной модели (кнопка
           "Векторы"). В отличие от update_words(), здесь нет подсветки
           "точное/частичное совпадение" и нет клика для исключения слова —
           просто список "слово (близость)", как и описывалось для этого
           режима.

           query_word/vector_key запоминаются для кнопки "3D/2D" — нужны,
           чтобы потом получить сами координаты векторов (не только их
           близость) для визуализации. Кнопка показывается только здесь —
           только у word-embedding моделей (FastText) есть отдельные
           векторы слов, у моделей уровня целых предложений (MiniLM/LSA)
           их нет."""
        self.text.config(state='normal')
        self.text.delete(1.0, tk.END)
        self.word_positions = []
        self.all_excluded_flag = False
        self._last_words_key = None   # другой режим панели: прокрутку списка слов не переносим

        if not neighbors:
            self.text.insert(tk.END, "Нет близких слов в модели")
            self.text.config(state='disabled')
            self.hide_3d_button()
            return

        for word, score in neighbors:
            self.text.insert(tk.END, f"{word} ({score:.3f})\n")

        self.text.config(state='disabled')

        self._last_neighbors = neighbors
        self._last_query_word = query_word
        self._last_vector_key = vector_key
        self.show_3d_button()

    def show_3d_button(self):
        self.viz_button.pack(side='left', padx=(8, 0), before=self._header_label)
        # "−В/+В" (исключение словоформ) появляется/прячется вместе с
        # "3D/2D" — они осмыслены в тех же условиях (только когда панель
        # заполнена соседями FastText, а не обычным поиском/MiniLM/LSA).
        if hasattr(self.main_app, 'show_variations_button'):
            self.main_app.show_variations_button()

    def hide_3d_button(self):
        self.viz_button.pack_forget()
        if hasattr(self.main_app, 'hide_variations_button'):
            self.main_app.hide_variations_button()

    def _on_viz_button_click(self):
        if not getattr(self, '_last_neighbors', None):
            return
        self.main_app.viz.show_vector_viz_menu(
            self._last_query_word, self._last_neighbors, self._last_vector_key
        )

    def _on_word_click_tag(self, event, word):
        if word in self.main_app.excluded_words:
            self.main_app.excluded_words.remove(word)
        else:
            self.main_app.excluded_words.add(word)
        self.main_app.refresh_display()

    def _on_word_click(self, event):
        pass

    def show_message(self, text):
        """Показывает произвольное сообщение вместо списка слов — например,
           когда для текущего режима поиска (семантический, MiniLM/LSA)
           список близких слов в принципе не предусмотрен, и пустая
           панель без пояснения выглядела бы как ошибка."""
        self.hide_3d_button()
        self.text.config(state='normal')
        self.text.delete(1.0, tk.END)
        self.text.insert(tk.END, text)
        self.text.config(state='disabled')
        self.word_positions = []
        self.all_excluded_flag = False
        self._last_words_key = None   # другой режим панели: прокрутку списка слов не переносим

    def clear(self):
        self.hide_3d_button()
        self.text.config(state='normal')
        self.text.delete(1.0, tk.END)
        self.text.insert(tk.END, " ")
        self.text.config(state='disabled')
        self.word_positions = []
        self.all_excluded_flag = False
        self._last_words_key = None   # другой режим панели: прокрутку списка слов не переносим

    def update_font_size(self, font_size):
        self.text.configure(font=('Consolas', font_size))
