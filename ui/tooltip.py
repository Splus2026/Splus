"""Всплывающие подсказки к виджетам Tk.

   ToolTip(widget, "текст") — подсказка появляется через полсекунды после
   наведения мыши и исчезает при уходе курсора, нажатии на виджет и когда
   виджет скрыт или уничтожен.

   Текст можно передать и ФУНКЦИЕЙ без аргументов: она вызывается в момент
   показа, а не при создании подсказки. Так подсказка следует за кнопкой,
   которая меняет смысл (например, "−В/+В" в ui/app_window.py: подсказка
   всегда описывает то, что кнопка сделает при нажатии сейчас).

   Подсказка не заходит за край экрана: у правого края сдвигается влево, а
   если снизу не хватает места — показывается над виджетом."""

import tkinter as tk

_BG = '#ffffe0'
_FONT = ('Arial', 11)


class ToolTip:
    def __init__(self, widget, text, delay_ms=500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        # add='+': не затираем обработчики, которые уже есть у виджета.
        widget.bind('<Enter>', self._on_enter, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')
        # Unmap: кнопка скрыта через pack_forget() (так делает "−В/+В") — иначе
        # показанная подсказка осталась бы висеть сама по себе.
        widget.bind('<Unmap>', self._hide, add='+')
        widget.bind('<Destroy>', self._hide, add='+')

    def _current_text(self):
        return self.text() if callable(self.text) else self.text

    def _on_enter(self, event=None):
        self._cancel_pending()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel_pending(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None:
            return
        text = self._current_text()
        if not text:
            return
        widget = self.widget
        tip = tk.Toplevel(widget)
        tip.withdraw()  # до расстановки по месту — невидимо, иначе мелькнёт в углу экрана
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        tk.Label(tip, text=text, justify='left', bg=_BG, relief='solid', borderwidth=1,
                 font=_FONT, padx=6, pady=3).pack()
        tip.update_idletasks()
        tip_w, tip_h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        screen_w, screen_h = widget.winfo_screenwidth(), widget.winfo_screenheight()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 6   # под виджетом, не под курсором
        x = max(0, min(x, screen_w - tip_w - 4))
        if y + tip_h > screen_h - 4:
            y = max(0, widget.winfo_rooty() - tip_h - 6)       # снизу нет места — над виджетом
        tip.geometry(f"+{x}+{y}")
        tip.deiconify()
        self._tip = tip

    def _hide(self, event=None):
        self._cancel_pending()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
