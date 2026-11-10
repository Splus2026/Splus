# ui/custom_dialogs.py
import tkinter as tk
from tkinter import ttk

def _create_dialog(parent, title, message, buttons=('OK',), default=None, height=250):
    """
    Создаёт модальное окно с заданными кнопками.
    height – высота окна в пикселях (по умолчанию 250).
    """
    if parent is None:
        # Единственное окно Tk в приложении Tkinter отслеживает сам как
        # "default root" — используем его, если вызывающий код явно не
        # передал parent (так вызывают все существующие места в проекте).
        parent = tk._default_root
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    parent.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
    y = parent.winfo_y() + (parent.winfo_height() - height) // 2
    dialog.geometry(f"400x{height}+{x}+{y}")

    label = ttk.Label(dialog, text=message, wraplength=350, justify='center',
                      anchor='center', font=('Arial', 13))
    label.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

    result = [None]

    def on_click(value):
        result[0] = value
        dialog.destroy()

    btn_frame = ttk.Frame(dialog)
    btn_frame.pack(pady=10)

    for btn_text in buttons:
        btn = ttk.Button(btn_frame, text=btn_text, command=lambda v=btn_text: on_click(v))
        btn.pack(side='left', padx=5)
        if default and btn_text == default:
            btn.focus_set()

    dialog.bind('<Return>', lambda e: on_click(buttons[0] if buttons else 'OK'))
    dialog.bind('<Escape>', lambda e: on_click(None))

    dialog.focus_set()
    dialog.wait_window()

    if buttons == ('OK',):
        return result[0] == 'OK'
    elif buttons == ('OK', 'Cancel'):
        return result[0] == 'OK'
    elif buttons == ('Да', 'Нет'):
        return result[0] == 'Да'
    else:
        return result[0]

# Сигнатура (title, message, parent=None) — та же, что у стандартного
# tkinter.messagebox (там parent передаётся именованным аргументом в **options).
# Благодаря этому существующие вызовы вида messagebox.showerror("Ошибка", "...")
# работают безо всяких изменений при переключении импорта с tkinter.messagebox
# на этот беззвучный модуль.
def showinfo(title="", message="", parent=None, height=250):
    return _create_dialog(parent, title, message, ('OK',), height=height)

def showwarning(title="", message="", parent=None, height=250):
    return _create_dialog(parent, title, message, ('OK',), height=height)

def showerror(title="", message="", parent=None, height=250):
    return _create_dialog(parent, title, message, ('OK',), height=height)

def askyesno(title="", message="", parent=None, height=250):
    return _create_dialog(parent, title, message, ('Да', 'Нет'), height=height)

def askokcancel(title="", message="", parent=None, height=250):
    return _create_dialog(parent, title, message, ('OK', 'Cancel'), height=height)

def ask_choice(title="", message="", buttons=(), parent=None, height=250):
    """Диалог с произвольным набором кнопок (больше двух) — возвращает
       точный текст нажатой кнопки, либо None при закрытии/Escape. Для
       обычных да/нет/ок-отмена лучше подходят askyesno/askokcancel — эта
       функция для случаев вроде "Перезаписать / Другое имя / Отмена"."""
    return _create_dialog(parent, title, message, tuple(buttons), height=height)

class SilentMessageBox:
    @staticmethod
    def showinfo(*args, **kwargs):
        return showinfo(*args, **kwargs)
    @staticmethod
    def showwarning(*args, **kwargs):
        return showwarning(*args, **kwargs)
    @staticmethod
    def showerror(*args, **kwargs):
        return showerror(*args, **kwargs)
    @staticmethod
    def askyesno(*args, **kwargs):
        return askyesno(*args, **kwargs)
    @staticmethod
    def askokcancel(*args, **kwargs):
        return askokcancel(*args, **kwargs)
    @staticmethod
    def ask_choice(*args, **kwargs):
        return ask_choice(*args, **kwargs)

messagebox = SilentMessageBox()