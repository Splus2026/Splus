"""Заставка при запуске: небольшое окно без рамки, подтверждающее, что программа стартовала.

Модуль намеренно лёгкий (только tkinter), чтобы окно появилось сразу, ДО загрузки тяжёлых модулей.
Любая ошибка внутри заставки не должна мешать запуску программы — все вызовы безопасны.
Фон — файл splash_bg.png рядом с программой (нет файла — рисуется однотонный синий фон)."""
import os
import sys

WIDTH, HEIGHT = 462, 237
STAGES = (
    "Загрузка модулей…",
    "Чтение настроек…",
    "Запуск движка поиска…",
    "Подключение к базе…",
    "Построение интерфейса…",
    "Готово",
)

_win = None
_canvas = None
_bg = None
_ids = {}
_owns_root = False


def _bg_path():
    names = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'splash_bg.png')]
    if getattr(sys, 'frozen', False):
        names.insert(0, os.path.join(os.path.dirname(sys.executable), 'splash_bg.png'))
        names.append(os.path.join(getattr(sys, '_MEIPASS', ''), 'splash_bg.png'))
    return next((p for p in names if os.path.isfile(p)), None)


def show(status=None, master=None, version=''):
    """Показывает заставку (повторный вызов только обновляет надпись). master=None — своё окно Tk,
       иначе Toplevel главного окна. Возвращает True, если заставка на экране."""
    global _win, _canvas, _bg, _ids, _owns_root
    try:
        if _win is not None:
            set_status(status)
            return True
        import tkinter as tk
        if master is None:
            _win = tk.Tk(); _owns_root = True
        else:
            _win = tk.Toplevel(master); _owns_root = False
        _win.overrideredirect(True)
        _win.attributes('-topmost', True)
        x = (_win.winfo_screenwidth() - WIDTH) // 2
        y = (_win.winfo_screenheight() - HEIGHT) // 2
        if master is not None:
            # по центру окна, поверх которого показывается заставка (если оно уже имеет размер)
            try:
                master.update_idletasks()
                mw, mh = master.winfo_width(), master.winfo_height()
                if mw > 1 and mh > 1:
                    x = master.winfo_rootx() + (mw - WIDTH) // 2
                    y = master.winfo_rooty() + (mh - HEIGHT) // 2
            except Exception:
                pass
        _win.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
        c = _canvas = tk.Canvas(_win, width=WIDTH, height=HEIGHT, highlightthickness=0, bg='#2a6fbf')
        c.pack()
        path = _bg_path()
        if path:
            try:
                _bg = tk.PhotoImage(file=path, master=_win)
                c.create_image(0, 0, image=_bg, anchor='nw')
            except Exception:
                _bg = None
        cx = WIDTH // 2
        c.create_text(cx + 2, 72, text="Синева+", fill='#0a2a5e', font=('Arial', 26, 'bold'))
        c.create_text(cx, 70, text="Синева+", fill='white', font=('Arial', 26, 'bold'))
        c.create_text(cx, 112, text="платформа динамического поиска", fill='white', font=('Arial', 10))
        if version:
            c.create_text(WIDTH - 24, 188, text=f"версия {version}", anchor='e', fill='#0b2a55', font=('Arial', 8))
        _ids['status'] = c.create_text(24, 188, text='', anchor='w', fill='#0b2a55', font=('Arial', 9, 'bold'))
        c.create_rectangle(24, 204, WIDTH - 24, 212, fill='white', outline='#7fa6d6')
        _ids['bar'] = c.create_rectangle(24, 204, 24, 212, fill='#1f5fbf', outline='')
        set_status(status or STAGES[0])
        return True
    except Exception:
        _win = None
        return False


def set_status(text=None):
    """Меняет надпись; полоса показывает, какой по счёту этап из STAGES (по тексту)."""
    try:
        if _win is None or text is None:
            return
        _canvas.itemconfigure(_ids['status'], text=text)
        try:
            k = STAGES.index(text) + 1
        except ValueError:
            k = None
        if k:
            _canvas.coords(_ids['bar'], 24, 204, 24 + (WIDTH - 48) * k / len(STAGES), 212)
        _win.update()
    except Exception:
        pass


def close():
    global _win, _canvas, _bg, _ids
    try:
        if _win is not None:
            _win.destroy()
    except Exception:
        pass
    _win = _canvas = _bg = None
    _ids = {}


def is_shown():
    return _win is not None
