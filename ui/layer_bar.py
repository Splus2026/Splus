"""Вторая строка кнопок над окном результатов: слои поверх подчёркнутого (как в Синеве Mobile) —
   «Ч», крупный шрифт, цвет, свои мысли (слева) и режимы показа «Все/Кратко/Отметки» (справа). Вынесено из AppWindow."""
import tkinter as tk
from ui.custom_dialogs import messagebox
from ui.note_dialog import ask_note
from ui.tooltip import ToolTip


class LayerBar:
    MODE_ON = '#1a4a5a'     # выбранный режим показа
    MODE_OFF = '#4a7a8a'

    def __init__(self, window):
        self.w = window
        self.btn_underline = self.btn_big = self.btn_color = self.btn_note = None
        self.mode_buttons = {}

    def build(self, center_frame):
        """Вторая строка кнопок над окном результатов: слои поверх подчёркнутого (как в Синеве Mobile) —
           «Ч», крупный шрифт, цвет, свои мысли (слева) и режимы показа «Все/Кратко/Отметки» (справа). Отдельная строка, потому что
           первая занята навигацией, а правая кнопка мыши — под конспект."""
        bar = tk.Frame(center_frame, bg='#d4e8f7')
        bar.pack(side='top', fill=tk.X, padx=5, pady=(0, 4))
        font = ('Arial', 12, 'bold')
        # Левая группа: Ч, A+, Цвет, Мысль — правка отметок.
        self.btn_underline = tk.Button(bar, text="Ч", command=self.w._toggle_underline,
                                       font=('Arial', 12, 'bold underline'), bg='#6a4a8a', fg='white',
                                       padx=6, pady=1)
        self.btn_underline.pack(side='left', padx=(0, 4))
        ToolTip(self.btn_underline, "Подчеркнуть")
        self.btn_big = tk.Button(bar, text="A+", command=lambda: self.style_selection('big'),
                                 font=('Arial', 13, 'bold'), bg='#6a4a8a', fg='white', padx=8, pady=1)
        self.btn_big.pack(side='left', padx=4)
        ToolTip(self.btn_big, "Крупный шрифт (внутри подчёркнутого)")
        self.btn_color = tk.Button(bar, text="Цвет", command=lambda: self.style_selection('color'),
                                   font=font, bg='#8a00a6', fg='white', padx=6, pady=1)
        self.btn_color.pack(side='left', padx=4)
        ToolTip(self.btn_color, "Цветом (внутри подчёркнутого)")
        self.btn_note = tk.Button(bar, text="Мысль", command=self.edit_note_for_selection,
                                  font=font, bg='#1a6a3a', fg='white', padx=6, pady=1)
        self.btn_note.pack(side='left', padx=4)
        ToolTip(self.btn_note, "Своя мысль к выделенному")
        # Правая группа: что показывать — Все / Кратко / Отметки (пакуются справа налево, видны слева направо).
        self.mode_buttons = {}
        for mode, text, tip in (('marks', "Отметки", "Только подчёркнутое, выделенное и мысли"),
                                ('brief', "Кратко", "Только предложения с подсветками"),
                                ('all', "Все", "Полный текст")):
            btn = tk.Button(bar, text=text, command=lambda m=mode: self.set_mode(m),
                            font=font, bg=self.MODE_OFF, fg='white', padx=6, pady=1, width=8)
            btn.pack(side='right', padx=(4, 0))
            ToolTip(btn, tip)
            self.mode_buttons[mode] = btn
        self.mode_buttons['all'].config(bg=self.MODE_ON, relief='sunken')

    def layer_blocked(self):
        """True (и подсказка), если слои сейчас недоступны: разделение окна или показано не окно результатов."""
        if getattr(self.w.search_controller, 'split_mode_active', False):
            self.w._show_temporary_notification("Нет в режиме разделения", duration_ms=900)
            return True
        if self.w.vector_viz_canvas.winfo_ismapped():
            self.w._show_temporary_notification("Откройте окно результатов", duration_ms=900)
            return True
        return False

    HINTS = {
        'no_selection': "Сначала выделите текст",
        'outside': "Выделите текст внутри блока",
        'empty': "Выделены только пробелы",
        'unsupported': "Здесь недоступно",
        'unavailable': "Хранилище отметок недоступно",
        'marks_only': "В режиме «Только отмеченное» правка выключена",
        'need_mark': "Сначала подчеркните это место («Ч»)",
    }

    def style_selection(self, kind):
        """Кнопки «A+» и «Цвет»: оформляют выделенное, уже подчёркнутое; повторное нажатие снимает."""
        if self.layer_blocked():
            return
        try:
            status = self.w.results_renderer.style_selection(kind)
        except Exception as e:
            messagebox.showerror("Оформление", f"Не удалось сохранить:\n{e}")
            return
        name = "Крупный шрифт" if kind == 'big' else "Цвет"
        if status in self.HINTS:
            self.w._show_temporary_notification(self.HINTS[status], duration_ms=1200)
        elif status == 'on':
            self.w._update_log_field(f"✏️ {name}: включён")
        elif status == 'off':
            self.w._update_log_field(f"{name}: снят")

    def edit_note_for_selection(self):
        """Кнопка «Мысль»: к выделенному фрагменту — добавить мысль (или поправить уже существующую)."""
        if self.layer_blocked():
            return
        renderer = self.w.results_renderer
        status, nid = renderer.selection_note()
        if status != 'ok':
            self.w._show_temporary_notification(self.HINTS.get(status, "Здесь недоступно"), duration_ms=1200)
            return
        note = self.w.marks_store.get_note(nid) if nid is not None else None
        try:
            fragment = renderer.result_text.get('sel.first', 'sel.last')
        except Exception:
            fragment = note.fragment if note else ''
        answer = ask_note(self.w.root, fragment, note.text if note else '', can_delete=note is not None)
        if answer is None:
            return
        try:
            if answer[0] == 'delete':
                renderer.delete_note(nid)
                self.w._update_log_field("Мысль удалена")
            else:
                result = renderer.add_note(answer[1])
                if result == 'empty':
                    self.w._show_temporary_notification("Пустая мысль не сохраняется", duration_ms=1200)
                else:
                    self.w._update_log_field("💭 Мысль сохранена")
        except Exception as e:
            messagebox.showerror("Мысль", f"Не удалось сохранить:\n{e}")

    def on_note_clicked(self, nid):
        """Клик по тексту мысли в окне результатов: правка или удаление."""
        if self.w.results_renderer.marks_only:
            return
        note = self.w.marks_store.get_note(nid)
        if note is None:
            return
        answer = ask_note(self.w.root, note.fragment, note.text or '', can_delete=True)
        if answer is None:
            return
        try:
            if answer[0] == 'delete':
                self.w.results_renderer.delete_note(nid)
            else:
                self.w.results_renderer.edit_note(nid, answer[1])
        except Exception as e:
            messagebox.showerror("Мысль", f"Не удалось сохранить:\n{e}")

    def set_mode(self, mode):
        """Кнопки «Все» / «Кратко» / «Отметки»: что показывать в окне результатов."""
        self.w.search_controller.set_view_mode(mode)
        for name, btn in self.mode_buttons.items():
            on = name == mode
            btn.config(bg=self.MODE_ON if on else self.MODE_OFF, relief='sunken' if on else 'raised')
