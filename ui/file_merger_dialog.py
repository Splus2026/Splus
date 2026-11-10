"""Окно кнопки "Собрать базу": склейка нескольких файлов (.txt / .docx / .pdf)
   в один. Сделано по образцу окна "Сборка баз/конспектов" (FileMergerApp)
   из прежнего проекта, со следующими отличиями:

   - Запоминаются папки: откуда в последний раз выбирали файлы (следующий
     диалог выбора откроется там же) и куда сохраняли результат (по
     умолчанию подкаталог DB; если сохранили в другую папку — именно она
     становится папкой по умолчанию при следующем открытии окна).
     Запоминание идёт через колбэк on_dirs_changed (его реализует главное
     окно — ui/app_window.py, там же оно попадает в mconfig.ini).
   - Поле "Строка-разделитель": по умолчанию там пунктирная линия; поле
     можно очистить — тогда файлы разделяются просто пустой строкой. В итоговый
     файл больше НЕ добавляется ничего (раньше окно писало шапку, имена и
     пути файлов, пометки страниц PDF и "КОНЕЦ ФАЙЛА") — сама склейка
     описана в utils/file_merger.py.
   - Галочка "Открыть объединённый файл" при каждом открытии окна стоит по
     умолчанию.
   - Склейка выполняется в рабочем потоке, но поток НЕ обращается к
     виджетам Tk напрямую (Tkinter не потокобезопасен — прежний вариант
     писал в журнал и показывал messagebox прямо из потока): он только
     кладёт события в очередь, а обрабатывает их главный поток (_poll_events).
   - Перед перезаписью существующего файла спрашивается подтверждение;
     выходной файл не может совпадать с одним из исходных."""

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog

from ui.custom_dialogs import messagebox
from utils import file_merger

FONT_LABEL = ('Arial', 13)
FONT_LABEL_BOLD = ('Arial', 13, 'bold')
FONT_SMALL = ('Arial', 11)
FONT_BUTTON = ('Arial', 12, 'bold')
FONT_MONO = ('Consolas', 11)
FONT_LOG = ('Consolas', 10)

COLOR_ACTION = '#6a4a8a'   # те же цвета, что у кнопок главного окна
COLOR_DANGER = '#b84a4a'
COLOR_NEUTRAL = '#4a7a8a'

DEFAULT_OUTPUT_DIR = 'DB'  # подкаталог DB — как везде в проекте (относительно рабочей папки)


def _existing_dir(path: str) -> str:
    """Ближайшая СУЩЕСТВУЮЩАЯ папка для подсказки диалогу выбора: если
       запомненная папка с тех пор исчезла (удалена, отключён диск), поднимаемся
       выше по пути; пустая строка, если подходящей нет."""
    p = path or ''
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return ''
        p = parent
    return p


def _storage_dir(path: str) -> str:
    """Вид папки для запоминания: подкаталог DB хранится как "DB" (путь
       относительно рабочей папки, как везде в проекте — абсолютный путь
       испортился бы при переносе программы в другое место), остальные — как
       абсолютные."""
    if file_merger.normalize_path_key(path) == file_merger.normalize_path_key(DEFAULT_OUTPUT_DIR):
        return DEFAULT_OUTPUT_DIR
    return os.path.abspath(path)


class FileMergerDialog:
    def __init__(self, parent, initial_source_dir='', initial_output_dir=DEFAULT_OUTPUT_DIR,
                 on_dirs_changed=None, on_merged=None, on_files_moved=None):
        """on_files_moved(paths) — после кнопки "Копировать в папку DB" (главное окно
           обновляет список файлов справа внизу).
           on_dirs_changed(source_dir=None, output_dir=None) — вызывается,
           когда нужно запомнить папку (None — этот параметр не менялся).
           on_merged(output_path) — после успешной склейки (главное окно
           обновляет список файлов, если результат попал в DB)."""
        self.parent = parent
        self.source_dir = initial_source_dir or ''
        self.output_dir = initial_output_dir or DEFAULT_OUTPUT_DIR
        self.on_dirs_changed = on_dirs_changed
        self.on_merged = on_merged
        self.on_files_moved = on_files_moved

        self.files = []          # полные пути, в порядке склейки
        self._file_keys = set()  # normalize_path_key() каждого — для проверки дубликатов
        self._is_processing = False
        self._cancel_event = threading.Event()
        self._close_after_finish = False
        self._events = queue.Queue()  # рабочий поток -> главный поток

        self.root = tk.Toplevel(parent)
        self.root.title("Собрать базу — объединение файлов")
        self.root.transient(parent)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        self.output_format = tk.StringVar(value='txt')
        self.open_after_merge = tk.BooleanVar(value=True)  # по умолчанию галочка стоит
        self.separator_var = tk.StringVar(value=file_merger.DEFAULT_SEPARATOR)
        self.output_file = tk.StringVar(value=self._default_output_path('txt'))

        self._build_widgets()
        self._place_window()
        self._regrab()
        self._check_libraries()

    # ---------- служебное ----------

    def _default_output_path(self, fmt: str) -> str:
        return os.path.join(self.output_dir, f"{file_merger.DEFAULT_OUTPUT_NAME}.{fmt}")

    def _regrab(self):
        """Модальность окна. Вложенное модальное окно (наши messagebox из
           ui/custom_dialogs.py тоже берут grab) при закрытии НЕ возвращает
           захват предыдущему — без повторного захвата главное окно за этим
           стало бы снова доступным, пока это окно ещё открыто."""
        try:
            self.root.grab_set()
        except tk.TclError:
            pass

    def _msg(self, kind: str, title: str, message: str, height: int = 250):
        """Обёртка над ui.custom_dialogs.messagebox с возвратом модальности."""
        func = getattr(messagebox, kind)
        try:
            return func(title, message, parent=self.root, height=height)
        finally:
            self._regrab()

    def _notify_dirs(self, source_dir=None, output_dir=None):
        if self.on_dirs_changed is None:
            return
        try:
            self.on_dirs_changed(source_dir=source_dir, output_dir=output_dir)
        except Exception as e:
            print(f"⚠️ Не удалось запомнить папку сборки базы: {e}")

    def _place_window(self):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(900, sw - 80)
        h = min(820, sh - 100)
        try:
            x = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
            y = self.parent.winfo_rooty() + (self.parent.winfo_height() - h) // 2
        except tk.TclError:
            x, y = (sw - w) // 2, (sh - h) // 2
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h - 40))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(700, 600)

    def _check_libraries(self):
        warnings = []
        if not file_merger.pdf_reader_available():
            warnings.append("чтение PDF недоступно (pip install pypdf)")
        if not file_merger.docx_available():
            warnings.append("работа с DOCX недоступна (pip install python-docx)")
        if warnings:
            self.status_label.config(text="⚠️ " + "; ".join(warnings), fg='#c0392b')

    # ---------- построение окна ----------

    def _button(self, parent, text, command, bg, padx=4):
        btn = tk.Button(parent, text=text, command=command, bg=bg, fg='white',
                        font=FONT_BUTTON, padx=12, pady=4)
        btn.pack(side='left', padx=padx)
        return btn

    def _build_widgets(self):
        root = self.root

        title_frame = tk.Frame(root)
        title_frame.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(title_frame, text="СБОРКА БАЗЫ: ОБЪЕДИНЕНИЕ ФАЙЛОВ",
                 font=('Arial', 15, 'bold'), fg='#2c3e50').pack(side='left')
        self.status_label = tk.Label(title_frame, text="✅ Готов к работе", font=FONT_SMALL,
                                     fg='#27ae60', wraplength=430, justify='right')
        self.status_label.pack(side='right', padx=10)

        # --- выбор файлов ---
        file_frame = tk.Frame(root)
        file_frame.pack(fill='x', padx=10, pady=4)
        tk.Label(file_frame, text="Файлы для объединения (порядок в списке = порядок в итоговом файле):",
                 font=FONT_LABEL_BOLD).pack(anchor='w')
        btn_row = tk.Frame(file_frame)
        btn_row.pack(fill='x', pady=4)
        self._file_buttons = [
            self._button(btn_row, "➕ Добавить файлы", self.add_files, COLOR_ACTION),
            self._button(btn_row, "➕ Добавить папку", self.add_folder, COLOR_ACTION),
            self._button(btn_row, "🗑️ Удалить выбранные", self.remove_selected, COLOR_DANGER),
            self._button(btn_row, "🧹 Очистить все", self.clear_all, COLOR_NEUTRAL),
        ]

        list_frame = tk.Frame(root)
        list_frame.pack(fill='both', expand=True, padx=10, pady=4)
        list_container = tk.Frame(list_frame, bd=1, relief='solid')
        list_container.pack(fill='both', expand=True)
        self.file_listbox = tk.Listbox(list_container, font=FONT_LOG, selectmode=tk.EXTENDED,
                                       height=8, activestyle='none')
        self.file_listbox.pack(side='left', fill='both', expand=True)
        scrollbar = tk.Scrollbar(list_container, command=self.file_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        self.file_listbox.bind('<Delete>', lambda e: self.remove_selected())

        info_frame = tk.Frame(root)
        info_frame.pack(fill='x', padx=10, pady=2)
        self.file_count_label = tk.Label(info_frame, text="Файлов: 0", font=FONT_LABEL_BOLD)
        self.file_count_label.pack(side='left', padx=10)
        self.total_size_label = tk.Label(info_frame, text="Общий размер: 0 байт", font=FONT_LABEL_BOLD)
        self.total_size_label.pack(side='left', padx=10)

        # --- формат результата и "открыть после" ---
        format_frame = tk.Frame(root)
        format_frame.pack(fill='x', padx=10, pady=4)
        tk.Label(format_frame, text="Формат результата:", font=FONT_LABEL_BOLD).pack(side='left', padx=5)
        for text, value in (("TXT", 'txt'), ("DOCX", 'docx')):
            tk.Radiobutton(format_frame, text=text, variable=self.output_format, value=value,
                           font=FONT_LABEL_BOLD, command=self._on_format_changed).pack(side='left', padx=10)
        tk.Checkbutton(format_frame, text="📂 Открыть объединённый файл", variable=self.open_after_merge,
                       font=FONT_LABEL_BOLD).pack(side='right', padx=20)

        # --- строка-разделитель ---
        sep_frame = tk.Frame(root)
        sep_frame.pack(fill='x', padx=10, pady=(6, 0))
        tk.Label(sep_frame, text="Строка-разделитель между файлами:", font=FONT_LABEL_BOLD).pack(side='left', padx=5)
        self.separator_entry = tk.Entry(sep_frame, textvariable=self.separator_var, font=FONT_MONO,
                                        relief='solid', bd=1)
        self.separator_entry.pack(side='left', fill='x', expand=True, padx=8)
        tk.Label(root, text="Поле можно очистить — тогда файлы разделяются просто пустой строкой. "
                            "В итоговый файл больше ничего не добавляется.",
                 font=FONT_SMALL, fg='#555555', anchor='w', justify='left',
                 wraplength=840).pack(fill='x', padx=16, pady=(0, 4))

        # --- выходной файл ---
        output_frame = tk.Frame(root)
        output_frame.pack(fill='x', padx=10, pady=4)
        tk.Label(output_frame, text="Выходной файл:", font=FONT_LABEL_BOLD).pack(side='left', padx=5)
        self.output_entry = tk.Entry(output_frame, textvariable=self.output_file, font=FONT_LABEL,
                                     relief='solid', bd=1)
        self.output_entry.pack(side='left', fill='x', expand=True, padx=8)
        self._button(output_frame, "📁 Выбрать", self.select_output_file, COLOR_NEUTRAL, padx=5)

        # --- запуск, прогресс, журнал ---
        action_frame = tk.Frame(root)
        action_frame.pack(fill='x', padx=10, pady=8)
        action_inner = tk.Frame(action_frame)
        action_inner.pack(expand=True)
        self.process_btn = tk.Button(action_inner, text="🚀 ОБЪЕДИНИТЬ ФАЙЛЫ", command=self.process_files,
                                     bg=COLOR_ACTION, fg='white', font=FONT_BUTTON, padx=30, pady=8)
        self.process_btn.pack(side='left')
        self.move_btn = tk.Button(action_inner, text="📥 Копировать в папку DB", command=self.move_to_db,
                                  bg=COLOR_NEUTRAL, fg='white', font=FONT_BUTTON, padx=20, pady=8)
        self.move_btn.pack(side='left', padx=(12, 0))
        self._file_buttons.append(self.move_btn)   # блокируется на время склейки вместе с остальными

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(root, variable=self.progress_var, maximum=100, length=400)
        self.progress_bar.pack(fill='x', padx=10, pady=(2, 0))
        self.progress_label = tk.Label(root, text="", font=FONT_SMALL, fg='#7f8c8d')
        self.progress_label.pack()

        log_frame = tk.Frame(root)
        log_frame.pack(fill='both', expand=True, padx=10, pady=(2, 8))
        tk.Label(log_frame, text="Журнал операций:", font=FONT_LABEL_BOLD).pack(anchor='w', pady=2)
        self.log_text = scrolledtext.ScrolledText(log_frame, font=FONT_LOG, wrap=tk.WORD, height=7,
                                                  relief='solid', borderwidth=1)
        self.log_text.pack(fill='both', expand=True)
        self.log_text.tag_config('success', foreground='#27ae60')
        self.log_text.tag_config('error', foreground='#e74c3c')
        self.log_text.tag_config('warning', foreground='#d68910')
        self.log_text.tag_config('info', foreground='#2471a3')
        self.log_text.tag_config('header', foreground='#2c3e50', font=('Arial', 12, 'bold'))

    # ---------- журнал, прогресс, статистика ----------

    def log(self, message: str, tag=None):
        """Только из ГЛАВНОГО потока (рабочий поток шлёт события в очередь)."""
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {message}\n"
        # Не передаём None третьим аргументом: в настоящем Tk он превратился бы
        # в тег с именем "None".
        if tag:
            self.log_text.insert(tk.END, line, tag)
        else:
            self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    def _set_progress(self, value: float, text=None):
        self.progress_var.set(value)
        if text is not None:
            self.progress_label.config(text=text)

    def update_stats(self):
        total = 0
        for path in self.files:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        self.file_count_label.config(text=f"Файлов: {len(self.files)}")
        self.total_size_label.config(text=f"Общий размер: {self._format_size(total)}")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} байт"
        if size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} КБ"
        return f"{size_bytes / (1024 ** 2):.1f} МБ"

    # ---------- список файлов ----------

    @staticmethod
    def _display_name(path: str) -> str:
        # Имя и папка: файлы можно брать из разных папок, и одинаковые имена
        # иначе нельзя было бы отличить друг от друга.
        return f"{os.path.basename(path)}    —    {os.path.dirname(path)}"

    def _add_paths(self, paths):
        """Добавляет в список; возвращает (добавлено, уже_были, не_поддерживается)."""
        added = duplicates = unsupported = 0
        for path in paths:
            path = os.path.abspath(path)
            if not file_merger.is_supported_file(path):
                unsupported += 1
                continue
            key = file_merger.normalize_path_key(path)
            if key in self._file_keys:
                duplicates += 1
                continue
            self._file_keys.add(key)
            self.files.append(path)
            self.file_listbox.insert(tk.END, self._display_name(path))
            added += 1
        return added, duplicates, unsupported

    def _log_added(self, added, duplicates, unsupported, source=''):
        parts = [f"добавлено: {added}"]
        if duplicates:
            parts.append(f"уже были в списке: {duplicates}")
        if unsupported:
            parts.append(f"пропущено (формат не поддерживается): {unsupported}")
        self.log(("✅ " if added else "⚠️ ") + source + ", ".join(parts), 'success' if added else 'warning')
        self.update_stats()

    def add_files(self):
        patterns = ' '.join('*' + ext for ext in file_merger.SUPPORTED_EXTENSIONS)
        filetypes = [("Все поддерживаемые файлы", patterns), ("Текстовые файлы", "*.txt"),
                     ("DOCX файлы", "*.docx"), ("PDF файлы", "*.pdf"), ("Все файлы", "*.*")]
        options = dict(parent=self.root, title="Выберите файлы для объединения", filetypes=filetypes)
        start_dir = _existing_dir(self.source_dir)
        if start_dir:
            options['initialdir'] = start_dir
        try:
            chosen = filedialog.askopenfilenames(**options)
        finally:
            self._regrab()
        if isinstance(chosen, str):  # в некоторых сборках Tk приходит строкой, а не кортежем
            chosen = self.root.tk.splitlist(chosen)
        if not chosen:
            return
        added, duplicates, unsupported = self._add_paths(chosen)
        # Запоминаем папку выбора, даже если все файлы оказались дубликатами —
        # пользователь всё равно уже побывал именно там.
        self.source_dir = os.path.dirname(os.path.abspath(chosen[0]))
        self._notify_dirs(source_dir=self.source_dir)
        self._log_added(added, duplicates, unsupported)

    def add_folder(self):
        options = dict(parent=self.root, title="Выберите папку с файлами")
        start_dir = _existing_dir(self.source_dir)
        if start_dir:
            options['initialdir'] = start_dir
        try:
            folder = filedialog.askdirectory(**options)
        finally:
            self._regrab()
        if not folder:
            return
        folder = os.path.abspath(folder)
        self.source_dir = folder
        self._notify_dirs(source_dir=folder)
        try:
            found = file_merger.list_supported_files(folder)
        except OSError as e:
            self.log(f"❌ Не удалось прочитать папку {folder}: {e}", 'error')
            return
        if not found:
            self.log(f"⚠️ В папке нет файлов {', '.join(file_merger.SUPPORTED_EXTENSIONS)}: {folder}", 'warning')
            return
        added, duplicates, unsupported = self._add_paths(found)
        self._log_added(added, duplicates, unsupported, source="из папки: ")

    def remove_selected(self):
        selected = self.file_listbox.curselection()
        if not selected:
            self.log("⚠️ Не выбрано ни одного файла для удаления", 'warning')
            return
        for index in sorted(selected, reverse=True):
            self._file_keys.discard(file_merger.normalize_path_key(self.files[index]))
            del self.files[index]
            self.file_listbox.delete(index)
        self.log(f"🗑️ Удалено из списка: {len(selected)}", 'info')
        self.update_stats()

    def clear_all(self):
        if not self.files:
            return
        count = len(self.files)
        self.files = []
        self._file_keys = set()
        self.file_listbox.delete(0, tk.END)
        self.log(f"🧹 Список очищен ({count})", 'info')
        self.update_stats()

    # ---------- копирование файлов в DB ----------

    def move_to_db(self):
        """Копирует (исходные файлы остаются на месте) файлы списка в подкаталог DB.
           Уже лежащие там пропускаются; при совпадении имён спрашивается разрешение заменить.
           (Имя метода осталось прежним — от первой версии, где файлы переносились.)"""
        if self._is_processing:
            return
        if not self.files:
            self._msg('showwarning', "Предупреждение", "Не выбрано ни одного файла!")
            return
        db_dir = os.path.abspath(DEFAULT_OUTPUT_DIR)
        db_key = file_merger.normalize_path_key(db_dir)
        todo = [p for p in self.files
                if file_merger.normalize_path_key(os.path.dirname(p)) != db_key]
        already = len(self.files) - len(todo)
        if not todo:
            self._msg('showinfo', "Копирование в DB", "Все файлы списка уже находятся в папке DB.")
            return
        clashes = [p for p in todo if os.path.exists(os.path.join(db_dir, os.path.basename(p)))]
        text = f"Скопировать файлов в папку DB: {len(todo)}?\nИсходные файлы останутся на месте."
        if clashes:
            names = ', '.join(os.path.basename(p) for p in clashes[:5]) + (' ...' if len(clashes) > 5 else '')
            text += f"\n\nВ DB уже есть файлы с такими именами ({len(clashes)}): {names}.\nОни будут ЗАМЕНЕНЫ."
        if not self._msg('askyesno', "Копирование в DB", text, height=320 if clashes else 260):
            return
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError as e:
            self.log(f"❌ Не удалось создать папку DB: {e}", 'error')
            return
        copied, errors = [], []
        for path in todo:
            dest = os.path.join(db_dir, os.path.basename(path))
            try:
                shutil.copy2(path, dest)
            except Exception as e:
                errors.append(os.path.basename(path))
                self.log(f"❌ {os.path.basename(path)}: {e}", 'error')
                continue
            copied.append(dest)
            self.log(f"📥 {os.path.basename(path)} → DB", 'success')
        tail = f", уже были в DB: {already}" if already else ""
        self.log(f"📥 Скопировано: {len(copied)}{tail}" + (f", с ошибками: {len(errors)}" if errors else ""),
                 'warning' if errors else 'success')
        if copied and self.on_files_moved is not None:
            try:
                self.on_files_moved(copied)
            except Exception as e:
                print(f"⚠️ Ошибка обработчика копирования в DB: {e}")

    # ---------- выходной файл ----------

    def _on_format_changed(self):
        current = self.output_file.get().strip()
        if current:
            self.output_file.set(file_merger.ensure_extension(current, self.output_format.get()))

    def select_output_file(self):
        fmt = self.output_format.get()
        filetypes = ([("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")] if fmt == 'txt'
                     else [("DOCX файлы", "*.docx"), ("Все файлы", "*.*")])
        current = self.output_file.get().strip().strip('"')
        options = dict(parent=self.root, title="Сохранить как...", defaultextension='.' + fmt,
                       filetypes=filetypes)
        start_dir = _existing_dir(os.path.dirname(current) or self.output_dir)
        if start_dir:
            options['initialdir'] = start_dir
        options['initialfile'] = (os.path.basename(current)
                                  or f"{file_merger.DEFAULT_OUTPUT_NAME}.{fmt}")
        try:
            path = filedialog.asksaveasfilename(**options)
        finally:
            self._regrab()
        if path:
            self.output_file.set(os.path.normpath(path))
            self.log(f"📁 Выходной файл: {os.path.normpath(path)}", 'info')

    def _resolve_output_path(self):
        """(как показать в поле, абсолютный путь) либо (None, None), если имя
           не задано."""
        raw = self.output_file.get().strip().strip('"')  # путь, скопированный из проводника, бывает в кавычках
        if not raw:
            return None, None
        if not os.path.dirname(raw):
            # Задано только имя без папки — кладём в текущую "папку по умолчанию".
            raw = os.path.join(self.output_dir, raw)
        shown = file_merger.ensure_extension(raw, self.output_format.get())
        return shown, os.path.abspath(shown)

    # ---------- запуск склейки ----------

    def process_files(self):
        if self._is_processing:
            return
        if not self.files:
            self._msg('showwarning', "Предупреждение", "Не выбрано ни одного файла!")
            return
        shown, output_path = self._resolve_output_path()
        if not output_path:
            self._msg('showwarning', "Предупреждение", "Укажите имя выходного файла!")
            return
        self.output_file.set(shown)

        # Результат не должен совпасть с одним из исходных файлов: после
        # подтверждения перезаписи он затёр бы исходник.
        if file_merger.normalize_path_key(output_path) in self._file_keys:
            self._msg('showerror', "Ошибка",
                      "Выходной файл совпадает с одним из исходных файлов в списке.\n"
                      "Выберите другое имя, чтобы не затереть исходный файл.", height=280)
            return
        if os.path.exists(output_path):
            if not self._msg('askyesno', "Файл уже существует",
                             f"Файл уже существует:\n{output_path}\n\nПерезаписать?", height=300):
                return

        fmt = self.output_format.get()
        files = list(self.files)
        separator = self.separator_var.get()

        self._is_processing = True
        self._cancel_event.clear()
        self.process_btn.config(text="⏳ ОБРАБОТКА...", state='disabled')
        for btn in self._file_buttons:
            btn.config(state='disabled')
        self._set_progress(0, "")
        self.log_text.delete('1.0', tk.END)
        self.log("🚀 Начало объединения файлов", 'header')
        self.log(f"📁 Выходной файл: {output_path}", 'info')
        self.log(f"📄 Файлов в списке: {len(files)}", 'info')

        threading.Thread(target=self._worker, args=(files, separator, output_path, fmt),
                         daemon=True).start()
        self.root.after(50, self._poll_events)

    def _worker(self, files, separator, output_path, fmt):
        """Рабочий поток. К виджетам Tk НЕ обращается — только кладёт события в
           очередь ('log' | 'progress' | 'done' | 'error' | 'cancelled'), а
           разбирает их главный поток (_poll_events). Любой выход из этой
           функции кончается ровно одним завершающим событием — иначе окно
           навсегда осталось бы в состоянии "идёт обработка"."""
        put = self._events.put
        try:
            total = len(files)
            texts = []
            skipped = []  # имена файлов, из которых текст не получен
            for i, path in enumerate(files, 1):
                if self._cancel_event.is_set():
                    put(('cancelled',))
                    return
                name = os.path.basename(path)
                put(('progress', (i - 1) / total * 90, f"Чтение: {name}"))
                put(('log', f"📖 [{i}/{total}] {name}", 'info'))
                try:
                    text = file_merger.read_source_text(path)
                except Exception as e:
                    put(('log', f"❌ {name}: {e}", 'error'))
                    skipped.append(name)
                    continue
                if not text.strip():
                    put(('log', f"⚠️ {name}: пустой или текст не извлечён (например, скан без "
                                f"текстового слоя) — пропущен", 'warning'))
                    skipped.append(name)
                    continue
                texts.append(text)
                put(('log', f"✅ {name}: добавлен ({len(text)} символов)", 'success'))

            if not texts:
                put(('error', "Ни из одного файла не удалось получить текст — объединять нечего."))
                return
            if self._cancel_event.is_set():
                put(('cancelled',))
                return

            put(('progress', 92, "Склейка и запись..."))
            merged = file_merger.merge_texts(texts, separator)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            file_merger.write_merged(merged, output_path, fmt)
            put(('done', {'output_path': output_path, 'fmt': fmt, 'merged': len(texts),
                          'total': total, 'skipped': skipped, 'chars': len(merged)}))
        except Exception as e:
            put(('error', f"{type(e).__name__}: {e}"))

    def _poll_events(self):
        """Главный поток: разбирает события рабочего потока и перепланирует
           себя, пока обработка не завершится."""
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == 'log':
                    self.log(event[1], event[2])
                elif kind == 'progress':
                    self._set_progress(event[1], event[2])
                elif kind == 'done':
                    self._on_done(event[1])
                    return
                elif kind == 'error':
                    self._on_error(event[1])
                    return
                elif kind == 'cancelled':
                    self._on_cancelled()
                    return
        except queue.Empty:
            pass
        if self._is_processing:
            self.root.after(50, self._poll_events)

    def _finish_processing(self):
        self._is_processing = False
        self.process_btn.config(text="🚀 ОБЪЕДИНИТЬ ФАЙЛЫ", state='normal')
        for btn in self._file_buttons:
            btn.config(state='normal')

    def _destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _on_done(self, info):
        self._finish_processing()
        output_path = info['output_path']
        self._set_progress(100, "✅ Готово!")
        self.log("✅ ОБЪЕДИНЕНИЕ ЗАВЕРШЕНО", 'success')
        self.log(f"📁 Файл сохранён: {output_path}", 'info')
        self.log(f"📊 Размер: {info['chars']} символов", 'info')

        # Папку результата запоминаем только теперь, когда файл действительно
        # сохранён (а не в момент выбора в диалоге) — "по умолчанию" меняется
        # лишь той папкой, куда реально что-то записали.
        self.output_dir = _storage_dir(os.path.dirname(output_path))
        self._notify_dirs(output_dir=self.output_dir)
        if self.on_merged is not None:
            try:
                self.on_merged(output_path)
            except Exception as e:
                print(f"⚠️ Ошибка обработчика завершения сборки базы: {e}")

        if self._close_after_finish:
            self._destroy()
            return

        skipped = info['skipped']
        lines = [f"Объединено файлов: {info['merged']} из {info['total']}",
                 f"Размер: {info['chars']} символов",
                 f"Формат: {info['fmt'].upper()}",
                 f"Сохранено: {output_path}"]
        if skipped:
            shown = ', '.join(skipped[:5]) + (' ...' if len(skipped) > 5 else '')
            lines.append(f"\nПРОПУЩЕНО файлов: {len(skipped)} ({shown}).\nПодробности — в журнале окна.")
        # Сообщение — ДО открытия файла: открытый внешней программой файл вышел бы
        # на передний план и спрятал бы это модальное окно за собой.
        self._msg('showwarning' if skipped else 'showinfo',
                  "Готово, но не все файлы" if skipped else "Готово",
                  "\n".join(lines), height=340 if skipped else 290)
        if self.open_after_merge.get():
            self._open_file(output_path)

    def _on_error(self, message):
        self._finish_processing()
        self.log(f"❌ {message}", 'error')
        self._set_progress(0, "")
        if self._close_after_finish:
            self._destroy()
            return
        self._msg('showerror', "Ошибка", message, height=300)

    def _on_cancelled(self):
        self._finish_processing()
        self.log("⏹ Объединение прервано — файл не создан", 'warning')
        self._set_progress(0, "")
        if self._close_after_finish:
            self._destroy()

    def _open_file(self, path):
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', path], check=False)
            else:
                subprocess.run(['xdg-open', path], check=False)
            self.log(f"📂 Файл открыт: {path}", 'info')
        except Exception as e:
            self.log(f"⚠️ Не удалось открыть файл: {e}", 'warning')

    def _on_close(self):
        if self._is_processing:
            if self._msg('askyesno', "Идёт объединение",
                         "Объединение ещё выполняется. Прервать и закрыть окно?"):
                self._close_after_finish = True
                self._cancel_event.set()
                self.log("⏹ Запрошено прерывание — окно закроется после окончания чтения "
                         "текущего файла...", 'warning')
            return
        self._destroy()


def open_file_merger_dialog(parent, initial_source_dir='', initial_output_dir=DEFAULT_OUTPUT_DIR,
                            on_dirs_changed=None, on_merged=None, on_files_moved=None):
    """Открывает окно "Собрать базу" (модальное; сам вызов не блокирует)."""
    return FileMergerDialog(parent, initial_source_dir, initial_output_dir,
                            on_dirs_changed, on_merged, on_files_moved)
