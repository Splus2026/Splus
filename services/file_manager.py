import glob
import os
import re
import time
import sys
import subprocess
import tkinter as tk
from services.dialogs import messagebox
import stats_logger
from utils.text_processing import read_text_file, make_safe_index_name
from utils.excel_processing import read_excel_as_text

# Подпись файла в списке: "имя.расширение", затем, если файл описан в настройках, " (алиас)". Имя всегда
# заканчивается расширением — поэтому "a (1).txt" и "Отчёт (копия).docx" разбираются верно, а не обрезаются по
# первой " (" (раньше выбор такого файла давал путь "a" и ошибку "файл не найден").
_LISTBOX_ENTRY_RE = re.compile(r'^(.*?\.(?:txt|docx|xlsx))(?: \(.*\))?$', re.IGNORECASE | re.DOTALL)


def parse_listbox_entry(display):
    """Имя файла из подписи списка (без алиаса). Подпись вида "/имя" (файл из DB) сохраняет "/" в начале."""
    match = _LISTBOX_ENTRY_RE.match(display)
    return match.group(1) if match else display


# Служебные файлы проекта: лежат рядом с программой, но книгами для индексации не являются.
EXCLUDED_FILE_NAMES = frozenset({'readme.txt', 'requirements.txt', 'requirements-compact.txt'})

class FileManager:
    """Управление файлами: сканирование, выбор, индексация, открытие."""

    def __init__(self, engine, config_dict, default_separator, text_listbox,
                 update_status_callback, index_display_map,
                 update_index_list_callback):
        self.engine = engine
        self.config_dict = config_dict
        self.default_separator = default_separator
        self.text_listbox = text_listbox
        self.update_status = update_status_callback
        self.index_display_map = index_display_map
        self.update_index_list = update_index_list_callback

        self.selected_text_files = []
        # Подпись в списке -> (подпапка, имя файла): заполняется при обновлении списка, по ней выбор определяется
        # точно, без разбора текста подписи.
        self._listed_entries = {}

    def _scan_text_files(self):
        files = []
        for f in os.listdir('.'):
            if self._is_indexable_name(f) and os.path.isfile(f):
                files.append(('', f))
        db_dir = "DB"
        if os.path.exists(db_dir):
            for f in os.listdir(db_dir):
                if self._is_indexable_name(f) and os.path.isfile(os.path.join(db_dir, f)):
                    files.append((db_dir, f))
        return files

    @staticmethod
    def _is_indexable_name(name):
        """Файл для индексации: txt/docx/xlsx, но не служебный файл Word "~$имя.docx" (он существует, пока
           документ открыт в Word, и прочитать его нельзя — только лишняя ошибка в итоге индексации)."""
        lowered = name.lower()
        return (lowered.endswith(('.txt', '.docx', '.xlsx')) and not name.startswith('~$')
                and lowered not in EXCLUDED_FILE_NAMES)

    def _update_selected_text_files(self):
        if self.text_listbox is None:
            self.selected_text_files = []
            return
        selection = self.text_listbox.curselection()
        files = []
        for idx in selection:
            display = self.text_listbox.get(idx)
            if display in self._listed_entries:
                subdir, fname = self._listed_entries[display]
                files.append(os.path.join(subdir, fname) if subdir else fname)
                continue
            raw = parse_listbox_entry(display)
            if raw.startswith('/'):
                fname = raw[1:]
                files.append(os.path.join("DB", fname))
            else:
                files.append(raw)
        self.selected_text_files = files

    def _read_file_content(self, file_path):
        # Историческое поведение этого места: пустые абзацы .docx пропускаются
        # (в отличие от просмотра файла по гиперссылке в search_controller.py,
        # где они сохраняются как пустые строки) — сохраняем это через параметр.
        return read_text_file(file_path, keep_empty_docx_paragraphs=False)

    def update_text_list(self):
        if self.text_listbox is None:
            return
        files = self._scan_text_files()
        self.text_listbox.delete(0, tk.END)
        self._listed_entries = {}
        for subdir, fname in files:
            display = f"/{fname}" if subdir else fname
            base_name = os.path.basename(fname)
            if base_name in self.config_dict:
                display_name, _, _ = self.config_dict[base_name]
                display = f"{display} ({display_name})"
            self._listed_entries[display] = (subdir, fname)
            self.text_listbox.insert(tk.END, display)

    def on_text_select(self, event):
        self._update_selected_text_files()

    def on_text_right_click(self, event):
        all_files = self._scan_text_files()
        if not all_files:
            return
        selected = self.text_listbox.curselection()
        if len(selected) == len(all_files):
            self.text_listbox.selection_clear(0, tk.END)
        else:
            self.text_listbox.selection_set(0, tk.END)
        self._update_selected_text_files()

    # ---------- индексация ----------
    def add_to_index(self, show_progress_callback, update_progress_callback, hide_progress_callback):
        """Индексирует выбранные файлы по очереди. Сбой одного файла (в том числе неожиданный — например, движок
           не ответил) попадает в итоговое сообщение и не мешает остальным; полоса прогресса скрывается всегда."""
        if not self.selected_text_files:
            messagebox.showwarning("Нет выбора",
                                   "Выберите файлы в списке 'Файлы' (используйте Ctrl+клик или Shift+клик).")
            return
        missing = [f for f in self.selected_text_files if not os.path.exists(f)]
        if missing:
            messagebox.showerror("Ошибка", f"Следующие файлы не найдены:\n" + "\n".join(missing))
            return

        engine_type = getattr(self.engine, 'engine_type', 'fts5')
        total_files = len(self.selected_text_files)
        total_indexed = 0
        errors = []

        show_progress_callback(max_value=total_files, initial=0, mode='determinate')
        try:
            for i, file_path in enumerate(self.selected_text_files, 1):
                try:
                    if self._index_one_file(file_path, i, total_files, engine_type, errors):
                        total_indexed += 1
                except Exception as e:
                    errors.append(f"{file_path}: ошибка индексации – {e}")
                update_progress_callback(i)
        finally:
            hide_progress_callback()
        self.update_index_list()
        self.update_text_list()

        messagebox.showinfo("Результат индексации", self._indexing_summary(total_files, total_indexed, errors))

    def _index_one_file(self, file_path, i, total_files, engine_type, errors):
        """Индексирует один файл. Возвращает True, если индекс создан; причины неудачи дописывает в errors."""
        base_name = os.path.basename(file_path)
        ext = os.path.splitext(base_name)[1].lower()
        display_name, separator, exclude_substring = self._index_settings(base_name, ext)
        safe_name, expected_name = self._index_names(engine_type, base_name, display_name)

        if self._index_exists(engine_type, expected_name, display_name):
            if not messagebox.askyesno("Перезапись",
                                       f"Индекс '{display_name}' уже существует. Перезаписать?\n(Файл {i} из {total_files})"):
                return False

        try:
            text = self._read_source_text(file_path, ext, exclude_substring)
        except Exception as e:
            errors.append(f"{file_path}: {e}")
            return False

        if not text or not text.strip():
            errors.append(f"{file_path}: файл пуст")
            return False

        build_start = time.time()
        indexed = False
        try:
            count = self._build_index(engine_type, safe_name, display_name, base_name, text, separator)
            build_time_ms = (time.time() - build_start) * 1000
            indexed = True
            self.update_status(f"Время создания индекса: {build_time_ms:.0f} мс | Индекс '{display_name}' создан ({count} записей)")

            if stats_logger.STATS_ENABLED:
                self._log_index_creation(engine_type, file_path, base_name, safe_name, display_name,
                                         separator, count, build_time_ms)
        except Exception as e:
            errors.append(f"{file_path}: ошибка индексации – {e}")
        return indexed

    def _index_settings(self, base_name, ext):
        """(название, разделитель, подстрока-исключение) — из настроек файла, а для файла вне настроек — по умолчанию."""
        if base_name in self.config_dict:
            return self.config_dict[base_name]
        display_name = os.path.splitext(base_name)[0]
        # Для Excel-файлов, не описанных явно в конфигурации,
        # разделитель по умолчанию — "один топик = одна строка",
        # а не общий default_separator (он для текстовых форматов).
        separator = "ExcelRow1" if ext == '.xlsx' else self.default_separator
        return display_name, separator, ''

    @staticmethod
    def _index_names(engine_type, base_name, display_name):
        """(имя для создания индекса, полное имя индекса). Manticore и Elastic — безопасное имя из имени файла."""
        if engine_type in ('manticore', 'elasticsearch'):
            return make_safe_index_name(base_name, engine_type)
        return display_name, display_name

    def _index_exists(self, engine_type, expected_name, display_name):
        if engine_type in ('manticore', 'elasticsearch'):
            indices = self.engine.list_indices()
            # Сравнение без учёта регистра: Manticore сам хранит имена
            # индексов в нижнем регистре, поэтому уже существующий индекс
            # мог быть создан (в т.ч. до этого исправления) в другом
            # регистре, чем только что вычисленный expected_name.
            return expected_name.lower() in {idx.lower() for idx in indices}
        db_path = os.path.join("indicies_fts5", f"{display_name}.db")
        return os.path.exists(db_path) or os.path.exists(f"{display_name}.db")

    def _read_source_text(self, file_path, ext, exclude_substring):
        if ext == '.xlsx':
            return read_excel_as_text(file_path, exclude_substring)
        return self._read_file_content(file_path)

    def _set_engine_file_name(self, value):
        """Имя файла-источника в движке — пока идёт запись, чтобы топики знали свой файл."""
        if hasattr(self.engine, '_current_file_name'):
            self.engine._current_file_name = value

    def _build_index(self, engine_type, safe_name, display_name, base_name, text, separator):
        """Создаёт индекс и записывает в него текст. Имя файла в движке сбрасывается ВСЕГДА (в том числе после
           сбоя записи): иначе оно оставалось бы за чужими записями. Возвращает число записей."""
        if engine_type in ('manticore', 'elasticsearch'):
            full_name = self.engine.create_index(safe_name)
            self.index_display_map[full_name] = display_name
        else:
            full_name = self.engine.create_index(display_name)
        self._set_engine_file_name(base_name)
        try:
            return self.engine.index_text(text, separator)
        finally:
            self._set_engine_file_name(None)

    def _log_index_creation(self, engine_type, file_path, base_name, safe_name, display_name, separator, count, build_time_ms):
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        index_size = 0
        if engine_type == 'fts5':
            idx_path = os.path.join("indicies_fts5", f"{display_name}.db")
            if os.path.exists(idx_path):
                index_size = os.path.getsize(idx_path)
        elif engine_type == 'manticore':
            pattern = os.path.join(self.engine.data_dir, f"{safe_name}.*")
            index_size = sum(os.path.getsize(f) for f in glob.glob(pattern))
        else:
            index_size = 0
        stats_logger.log_index_creation(
            engine_type=engine_type,
            source_filename=base_name,
            file_size_bytes=file_size,
            separator=separator,
            blocks_count=count,
            index_size_bytes=index_size,
            build_time_ms=build_time_ms
        )

    @staticmethod
    def _indexing_summary(total_files, total_indexed, errors):
        msg = f"Индексация завершена.\nОбработано файлов: {total_files}\nУспешно: {total_indexed}"
        if errors:
            msg += f"\nОшибок: {len(errors)}\n\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                msg += f"\n... и ещё {len(errors) - 5} ошибок"
        return msg

    def open_selected_file(self):
        """Открывает первый выбранный файл во внешней программе. Возвращает
           True, если файл действительно открыт, и False при любой неудаче
           (ничего не выбрано, файла нет, не удалось запустить) — по этому
           результату кнопка "Редактировать" решает, включать ли нумератор
           разбивки (ui/app_window.py)."""
        if not self.selected_text_files:
            messagebox.showwarning("Нет выбора", "Сначала выберите один или несколько файлов в списке 'Файлы'.")
            return False
        file_path = self.selected_text_files[0]
        if not os.path.exists(file_path):
            messagebox.showerror("Ошибка", f"Файл {file_path} не найден!")
            return False
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            else:
                subprocess.Popen(['xdg-open', file_path])
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")
            return False
        return True
