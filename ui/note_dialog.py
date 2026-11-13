"""Диалог «Своя мысль»: многострочный текст к выделенному слову или фрагменту (как в Синеве Mobile)."""
import tkinter as tk
from tkinter import scrolledtext


def ask_note(parent, fragment: str, initial: str = '', can_delete: bool = False):
    """Возвращает ('save', текст) | ('delete', '') | None (отмена)."""
    result = {'value': None}
    win = tk.Toplevel(parent)
    win.title("Своя мысль")
    win.transient(parent)
    win.resizable(True, True)
    shown = ' '.join(str(fragment or '').split())
    if len(shown) > 90:
        shown = shown[:87] + '…'
    tk.Label(win, text=f"К фрагменту: «{shown}»", font=('Arial', 11, 'bold'), anchor='w', justify='left',
             wraplength=520).pack(side='top', fill=tk.X, padx=10, pady=(10, 4))
    box = scrolledtext.ScrolledText(win, width=60, height=7, wrap=tk.WORD, font=('Arial', 12))
    box.pack(side='top', fill=tk.BOTH, expand=True, padx=10, pady=4)
    if initial:
        box.insert('1.0', initial)
    buttons = tk.Frame(win)
    buttons.pack(side='top', fill=tk.X, padx=10, pady=(4, 10))

    def close(value):
        result['value'] = value
        win.destroy()

    tk.Button(buttons, text="Сохранить", font=('Arial', 11, 'bold'), padx=8,
              command=lambda: close(('save', box.get('1.0', 'end-1c')))).pack(side='left')
    tk.Button(buttons, text="Отмена", font=('Arial', 11), padx=8, command=lambda: close(None)).pack(side='left', padx=6)
    if can_delete:
        tk.Button(buttons, text="Удалить мысль", font=('Arial', 11), padx=8, fg='#a00000',
                  command=lambda: close(('delete', ''))).pack(side='right')
    win.bind('<Escape>', lambda e: close(None))
    win.bind('<Control-Return>', lambda e: close(('save', box.get('1.0', 'end-1c'))))
    try:
        win.grab_set()
    except tk.TclError:
        pass
    box.focus_set()
    win.wait_window()
    return result['value']
