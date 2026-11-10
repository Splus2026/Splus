import tkinter as tk
from tkinter import ttk
from typing import List


class IndexCheckList(ttk.Frame):
    """Виджет со списком индексов в виде чекбоксов с поддержкой скролла и масштабирования.

    Раньше жил в services/index_manager.py — перенесён в ui/, так как это чисто
    Tkinter-виджет (View), а не бизнес-логика. Бизнес-логика выбора индексов
    (IndexManager) осталась в services/index_manager.py и использует этот
    виджет через переданную ссылку, как и раньше."""

    def __init__(self, parent, selection_callback=None, single_select=False, font_size=10, **kwargs):
        super().__init__(parent, **kwargs)
        self.selection_callback = selection_callback
        self.single_select = single_select
        self.font_size = font_size
        self.checkbuttons = {}
        self.selected = set()
        # Порядок, в котором индексы были отмечены — нужен только для режима
        # разделения окна результатов на два файла (см. get_selected_ordered),
        # сам self.selected (множество) не трогаем, чтобы не менять остальную
        # логику виджета.
        self.selection_order = []
        self.display_map = {}
        self._create_widgets()

    def _create_widgets(self):
        self.canvas = tk.Canvas(self, highlightthickness=0, bg='white')
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Обычный tk.Frame (а не ttk.Frame), чтобы можно было явно задать белый
        # фон — иначе за более короткими строками списка индексов виднелась
        # серая "заливка" системного цвета до правого края окна.
        self.inner_frame = tk.Frame(self.canvas, bg='white')
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw",
                                  width=self.canvas.winfo_width())

        self.inner_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Порядок важен: полосу прокрутки (фиксированной ширины) нужно
        # упаковать РАНЬШЕ, чем canvas с expand=True — иначе canvas немедленно
        # забирает себе всю доступную ширину, и полосе прокрутки, упакованной
        # следом, не остаётся места (она сжимается до нулевой ширины и
        # становится невидимой). Именно поэтому список индексов не скроллился,
        # хотя все чекбоксы реально создавались.
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(1, width=event.width)

    def _mark_selected(self, name):
        self.selected.add(name)
        if name in self.selection_order:
            self.selection_order.remove(name)
        self.selection_order.append(name)

    def _mark_deselected(self, name):
        self.selected.discard(name)
        if name in self.selection_order:
            self.selection_order.remove(name)

    def set_indices(self, indices: List[str], display_map: dict = None):
        if display_map is not None:
            self.display_map = display_map
        current_selected = self.selected.copy()
        previous_order = self.selection_order
        for widget in self.inner_frame.winfo_children():
            widget.destroy()
        self.checkbuttons.clear()
        self.selected.clear()

        for idx_name in indices:
            var = tk.BooleanVar()
            if idx_name in current_selected:
                var.set(True)
                self.selected.add(idx_name)
            display_text = idx_name
            alias = self.display_map.get(idx_name)
            if alias:
                display_text = f"{idx_name} ({alias})"
            cb = tk.Checkbutton(
                self.inner_frame,
                text=display_text,
                variable=var,
                command=lambda name=idx_name, v=var: self._on_check(name, v),
                bg='white',
                anchor='w',
                font=('Arial', self.font_size)
            )
            cb.pack(anchor="w", fill=tk.X, padx=2, pady=1)
            self.checkbuttons[idx_name] = (var, cb)

        # Порядок отметки — только для индексов, которые остались в НОВОМ списке и отмечены. Раньше порядок
        # фильтровался по прежнему выбору, и удалённый индекс оставался в нём «призраком»: get_selected_ordered()
        # (по нему поиск выбирает индексы) продолжал называть его, и поиск шёл по несуществующей таблице.
        self.selection_order = [n for n in previous_order if n in self.selected]
        self.selection_order += [n for n in indices if n in self.selected and n not in self.selection_order]

        self.inner_frame.bind("<Button-3>", self._on_right_click)
        self._notify()

    def _on_check(self, name: str, var: tk.BooleanVar):
        if self.single_select and var.get():
            for other_name, (other_var, _) in self.checkbuttons.items():
                if other_name != name and other_var.get():
                    other_var.set(False)
                    self._mark_deselected(other_name)
            self._mark_selected(name)
        else:
            if var.get():
                self._mark_selected(name)
            else:
                self._mark_deselected(name)
        self._notify()

    def _on_right_click(self, event):
        if len(self.selected) == len(self.checkbuttons):
            self.deselect_all()
        else:
            self.select_all()

    def select_all(self):
        for name, (var, _) in self.checkbuttons.items():
            var.set(True)
            self._mark_selected(name)
        self._notify()

    def deselect_all(self):
        for name, (var, _) in self.checkbuttons.items():
            var.set(False)
            self._mark_deselected(name)
        self._notify()

    def get_selected(self) -> List[str]:
        return list(self.selected)

    def get_selected_ordered(self) -> List[str]:
        """Как get_selected(), но в порядке, в котором индексы были отмечены
           (нужно для режима разделения окна результатов: "первый выбранный
           файл" / "второй выбранный файл")."""
        return list(self.selection_order)

    def set_selected(self, names: List[str]):
        for name, (var, _) in self.checkbuttons.items():
            var.set(False)
            self._mark_deselected(name)
        for name in names:
            if name in self.checkbuttons:
                self.checkbuttons[name][0].set(True)
                self._mark_selected(name)
        self._notify()

    def update_font_size(self, font_size: int):
        self.font_size = font_size
        for _, (_, cb) in self.checkbuttons.items():
            cb.config(font=('Arial', font_size))

    def _notify(self):
        if self.selection_callback:
            self.selection_callback(list(self.selected))
