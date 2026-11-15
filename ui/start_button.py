"""Крупная стартовая кнопка «Добавить книги» в центре окна результатов (как в современных приложениях:
   пока показывать нечего, главное действие — по центру и крупно). Размер следует за размером окна."""
import tkinter as tk


def scaled_metrics(width, height):
    """(размер шрифта, отступ по горизонтали, по вертикали) для окна width×height пикселей:
       шрифт растёт с шириной окна, но не уже 14 и не крупнее 34 пунктов."""
    base = min(width, height * 1.6)
    font = max(14, min(34, int(base / 24)))
    return font, int(font * 2.2), int(font * 0.9)


class StartButton:
    def __init__(self, host, command, text="Добавить книги"):
        self.host = host
        self.visible = False
        self.button = tk.Button(host, text=text, command=command, bg='#2a6fbf', fg='white',
                                activebackground='#1f5a9e', activeforeground='white', cursor='hand2',
                                relief='flat', bd=0, font=('Arial', 16, 'bold'))
        host.bind('<Configure>', self._on_resize, add='+')

    def _on_resize(self, event=None):
        try:
            width, height = self.host.winfo_width(), self.host.winfo_height()
            font, padx, pady = scaled_metrics(width, height)
            self.button.config(font=('Arial', font, 'bold'), padx=padx, pady=pady)
        except tk.TclError:
            pass

    def show(self):
        if not self.visible:
            self.visible = True
            self._on_resize()
            self.button.place(relx=0.5, rely=0.5, anchor='center')

    def hide(self):
        if self.visible:
            self.visible = False
            self.button.place_forget()
