"""Диалог нумератора разбивки (services/numerator.py): формат разделителя,
   номер и текстовая часть.

   Открывается по F7 из ЛЮБОЙ программы — в том числе поверх Word, поэтому окно
   "поверх всех" (topmost) и НЕ модальное: без transient/grab_set, чтобы не
   мешать работе в документе и не зависеть от главного окна Синевы+. Выбора
   файла здесь нет — файл уже открыт.

   Отличия от диалога прежней программы:
   - Поле номера заполняется СЛЕДУЮЩИМ номером (тем, что вставит F9), а не
     стартовым. Иначе, открыв диалог по F7 посреди документа только чтобы
     сменить формат, и нажав OK, пришлось бы заново вводить текущий номер —
     а при забывчивости счётчик молча сбрасывался на стартовый.
   - Ошибки ввода показываются в самом окне красной строкой, а не отдельным
     модальным сообщением: сообщение, открытое поверх topmost-окна, легко
     оказывается за ним.
   - Кнопка "Выключить нумератор": пока клавиши F7/F8/F9 перехвачены, они не
     работают ни в одной программе (у Word на них свои функции, а у файловых
     менеджеров — свои); эта кнопка возвращает их."""

import tkinter as tk

from services.numerator import FORMAT_NUMBER_TEXT, FORMAT_TEXT_NUMBER, compose

BG = '#d4e8f7'
FG_TITLE = '#1a4a7a'
FG_HINT = '#4a7a9a'


def show_numerator_dialog(parent, controller):
    """Показывает диалог. Если он уже открыт — выводит его на передний план
       (повторный F7), а не создаёт второй. Возвращает окно диалога."""
    existing = controller.dialog_window
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return existing
        except tk.TclError:
            pass
        controller.dialog_window = None  # ссылка устарела (окно уже уничтожено)

    fmt, number, text = controller.state.dialog_prefill()

    dialog = tk.Toplevel(parent)
    dialog.title("Настройка нумератора разбивки")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    width, height = 600, 500
    x = (dialog.winfo_screenwidth() - width) // 2
    y = max(0, (dialog.winfo_screenheight() - height) // 3)
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    dialog.attributes('-topmost', True)
    # Ссылка выставляется сразу: пока она есть, контроллер игнорирует F9/F8
    # (иначе Ctrl+V вставил бы номер в поле этого же окна).
    controller.dialog_window = dialog

    format_var = tk.StringVar(value=fmt)
    number_var = tk.StringVar(value=number)
    text_var = tk.StringVar(value=text)

    tk.Label(dialog, text="Номер и вид разделителя блоков", font=('Arial', 14, 'bold'),
             bg=BG, fg=FG_TITLE).pack(pady=(15, 5))

    format_frame = tk.LabelFrame(dialog, text="Формат разделителя", bg=BG,
                                 font=('Arial', 12, 'bold'), padx=10, pady=5)
    format_frame.pack(fill='x', padx=20, pady=5)
    tk.Radiobutton(format_frame, text="НОМЕР.ТЕКСТ", variable=format_var, value=FORMAT_NUMBER_TEXT,
                   bg=BG, font=('Arial', 12)).pack(anchor='w', padx=10, pady=2)
    tk.Radiobutton(format_frame, text="ТЕКСТ.НОМЕР", variable=format_var, value=FORMAT_TEXT_NUMBER,
                   bg=BG, font=('Arial', 12)).pack(anchor='w', padx=10, pady=2)

    input_frame = tk.Frame(dialog, bg=BG)
    input_frame.pack(fill='x', padx=20, pady=10)
    tk.Label(input_frame, text="Номер (с ведущими нулями):", bg=BG,
             font=('Arial', 12)).grid(row=0, column=0, sticky='e', padx=5, pady=5)
    number_entry = tk.Entry(input_frame, textvariable=number_var, font=('Arial', 12), width=15)
    number_entry.grid(row=0, column=1, padx=5, pady=5, sticky='w')
    tk.Label(input_frame, text="Текстовая часть:", bg=BG,
             font=('Arial', 12)).grid(row=1, column=0, sticky='e', padx=5, pady=5)
    tk.Entry(input_frame, textvariable=text_var, font=('Arial', 12), width=25).grid(
        row=1, column=1, padx=5, pady=5, sticky='w')

    example_label = tk.Label(dialog, text="", font=('Arial', 12, 'bold'), bg=BG, fg=FG_TITLE)
    example_label.pack(pady=5)

    def update_example(*_):
        num = number_var.get().strip()
        txt = text_var.get().strip()
        if not num or not txt:
            example_label.config(text="Пример: (заполните поля)")
        elif not (num.isascii() and num.isdigit()) or int(num) < 1:
            example_label.config(text="⚠️ Номер должен быть целым числом ≥ 1")
        else:
            example_label.config(text=f"Пример: {compose(format_var.get(), num, txt)}")

    for var in (format_var, number_var, text_var):
        var.trace_add('write', update_example)
    update_example()

    tk.Label(dialog, text="Ширина номера определяется количеством введённых цифр.",
             font=('Arial', 11), bg=BG, fg=FG_HINT).pack(pady=(5, 0))
    tk.Label(dialog, text="В поле «Номер» — СЛЕДУЮЩИЙ номер, который вставит F9.",
             font=('Arial', 11), bg=BG, fg=FG_HINT).pack()
    tk.Label(dialog, text="F9 — вставить следующий номер   |   F8 — откат   |   F7 — это окно",
             font=('Arial', 11, 'bold'), bg=BG, fg=FG_HINT).pack(pady=(8, 0))

    error_label = tk.Label(dialog, text="", font=('Arial', 11, 'bold'), bg=BG, fg='#b84a4a')
    error_label.pack(pady=(8, 0))

    def close():
        controller.dialog_window = None
        try:
            dialog.destroy()
        except tk.TclError:
            pass

    def on_ok():
        try:
            controller.apply_settings(format_var.get(), number_var.get(), text_var.get())
        except ValueError as e:
            error_label.config(text=f"⚠️ {e}")
            return
        close()

    def on_disable():
        controller.deactivate()
        close()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=15)
    tk.Button(btn_frame, text="OK", command=on_ok, bg='#3a8a4a', fg='white',
              font=('Arial', 12, 'bold'), padx=20).pack(side='left', padx=8)
    tk.Button(btn_frame, text="Отмена", command=close, bg='#4a7a8a', fg='white',
              font=('Arial', 12, 'bold'), padx=20).pack(side='left', padx=8)
    tk.Button(btn_frame, text="Выключить нумератор", command=on_disable, bg='#b84a4a', fg='white',
              font=('Arial', 12, 'bold'), padx=12).pack(side='left', padx=8)

    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.bind('<Return>', lambda e: on_ok())
    dialog.bind('<Escape>', lambda e: close())

    # Окно открыто глобальной клавишей, пока активна другая программа (Word):
    # выводим поверх и забираем фокус, чтобы можно было сразу печатать.
    dialog.lift()
    dialog.focus_force()
    number_entry.focus_set()
    number_entry.select_range(0, tk.END)
    return dialog
