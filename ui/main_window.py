import os
import tkinter as tk
from tkinter import ttk
from ui.custom_dialogs import messagebox
import time
import socket
from .app_window import AppWindow
from config import save_config, create_engine
import stats_logger


class MainWindow(AppWindow):
    """Главное окно приложения для работы с поисковыми движками."""

    def __init__(self, root, engine, config):
        super().__init__(root, engine, config)
        self._after_id = None
        self.engine_type = getattr(engine, 'engine_type', 'fts5')

        # Словарь для отображения названий движков в меню
        self.engine_display_map = {
            'fts5': 'FTS5',
            'elastic': 'ELASTICSEARCH',
            'manticore': 'MANTICORE'
        }
        self.engine_reverse_map = {v: k for k, v in self.engine_display_map.items()}

        engine_display = self._get_engine_display_name()
        self.root.title(f"Синева+ | {engine_display}")

        self.query_entry.bind('<KeyRelease>', self._on_key_release)

        # --- Выбор движка теперь пункты подменю "Настройки" -> "Выбор движка" ---
        self.engine_var = tk.StringVar()
        self.engine_var.set(self.engine_display_map.get(self.engine_type, 'FTS5'))

        engine_options = ["FTS5", "ELASTICSEARCH", "MANTICORE"]
        for option in engine_options:
            self.engine_submenu.add_radiobutton(
                label=option,
                variable=self.engine_var,
                value=option,
                command=lambda opt=option: self.on_engine_selected(opt)
            )

        # Параметры для ограничения частоты поиска (throttle) – берём из конфига
        self._last_search_time = 0
        self._search_delay = config.get('search_delay_ms', 300)   # <-- новое

        # Параметры для сбора статистики нажатий
        self._typing_timestamps = []   # список (timestamp_ms, char)
        self._prev_query_len = 0

    def _get_engine_display_name(self):
        return self.engine_display_map.get(self.engine_type, 'FTS5')

    def _on_key_release(self, event):
        # ---- Сбор статистики нажатий ----
        current_text = self.query_entry.get()
        current_len = len(current_text)
        if current_len < self._prev_query_len:
            # Пользователь удалил символы – сбрасываем статистику
            self._typing_timestamps = []
        elif current_len > self._prev_query_len:
            added_chars = current_text[self._prev_query_len:]
            now = time.time() * 1000
            if not self._typing_timestamps:
                # Начинаем новую сессию
                self._typing_timestamps.append((now, added_chars[0]))
                for ch in added_chars[1:]:
                    self._typing_timestamps.append((now, ch))
            else:
                for ch in added_chars:
                    self._typing_timestamps.append((now, ch))
        self._prev_query_len = current_len
        if current_len == 0:
            self._typing_timestamps = []

        # ---- Существующая логика throttle ----
        query = self.query_entry.get().strip()
        if query == self.search_controller.BROWSE_QUERY:
            # "**" — режим просмотра одного файла (SearchController.
            # _do_single_file_browse): включается сразу, как введена вторая
            # звёздочка. Ветка для короткого запроса ниже стёрла бы блоки файла
            # (меньше 3 символов — это справка), поэтому "**" обрабатывается
            # раньше. Повторные вызовы на тот же текст (отпускание Enter, Shift,
            # стрелки) безвредны: режим идемпотентен и не листает заново.
            if self._after_id:
                self.root.after_cancel(self._after_id)
                self._after_id = None
            self.do_search()
            return
        if len(query) < 3:
            if self._after_id:
                self.root.after_cancel(self._after_id)
                self._after_id = None
            self._show_help_text()
            self.word_panel.clear()
            self.search_controller.all_filtered_topics = []
            self.search_controller.results_page = 0
            self.search_controller.exit_browse_mode()  # удалили звёздочку — режим просмотра файла закончен
            self.search_controller._update_nav_buttons()
            return

        now = time.time() * 1000
        if now - self._last_search_time >= self._search_delay:
            self.do_search()
            self._last_search_time = now
            if self._after_id:
                self.root.after_cancel(self._after_id)
                self._after_id = None
        else:
            if self._after_id:
                self.root.after_cancel(self._after_id)
            remain = self._search_delay - (now - self._last_search_time)
            self._after_id = self.root.after(int(remain), self._throttled_search)

    def _throttled_search(self):
        self._after_id = None
        self._last_search_time = time.time() * 1000
        self.do_search()

    def do_search(self):
        """
        Переопределяем метод родителя, чтобы передать статистику нажатий в контроллер.
        """
        # Формируем строку статистики нажатий
        query = self.query_entry.get().strip()
        typing_stats_str = ""
        typing_total_ms = 0
        if self._typing_timestamps:
            first_time = self._typing_timestamps[0][0]
            parts = []
            prev_time = first_time
            for i, (ts, ch) in enumerate(self._typing_timestamps):
                if i == 0:
                    parts.append(f"0-{ch}")
                else:
                    diff = ts - prev_time
                    parts.append(f"{diff:.0f}-{ch}")
                    prev_time = ts
            typing_stats_str = "-".join(parts)
            typing_total_ms = self._typing_timestamps[-1][0] - first_time

        # Передаём статистику в контроллер
        self.search_controller.set_typing_stats(typing_stats_str, typing_total_ms)

        # Вызываем родительский метод (он запускает поиск через контроллер)
        super().do_search()

    def check_elasticsearch_running(self, host='localhost', port=9200, timeout=2):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _show_info_no_sound(self, title, message):
        """Показывает информационное окно без системного звука."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("400x150")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Центрируем относительно главного окна
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 150) // 2
        dialog.geometry(f"+{x}+{y}")

        # Метка с сообщением
        label = ttk.Label(dialog, text=message, wraplength=350, justify='center', font=('Arial', 11))
        label.pack(pady=30, padx=20)

        # Кнопка OK
        ok_btn = ttk.Button(dialog, text="OK", command=dialog.destroy)
        ok_btn.pack(pady=10)

        dialog.bind('<Return>', lambda e: dialog.destroy())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        dialog.focus_set()
        ok_btn.focus_set()

        # Ожидание закрытия (блокирующее)
        dialog.wait_window()

    def on_engine_selected(self, new_display_name):
        new_engine_type = self.engine_reverse_map.get(new_display_name)
        if new_engine_type is None or new_engine_type == self.engine_type:
            return

        # Временная заглушка – используем бесшумный диалог
        if new_engine_type != 'manticore':
            self._show_info_no_sound(
                "Временное ограничение",
                "В настоящее время доступен только движок Manticore.\n"
                "Переключение на другие движки временно отключено для отладки."
            )
            self.engine_var.set(self._get_engine_display_name())
            return

        if new_engine_type == 'elastic':
            host = self.config.get('elastic_host', 'localhost')
            port = int(self.config.get('elastic_port', 9200))
            if not self.check_elasticsearch_running(host, port, timeout=2):
                # Здесь будет диалог о недоступности
                pass

        from_engine = self.engine_type
        start_time = time.time()

        self._show_progress(mode='indeterminate')
        self.progress_bar.start(10)

        success = True
        try:
            if self.engine_type != 'manticore':
                self.engine.close()

            self.config['engine_type'] = new_engine_type
            save_config(self.config)
            self.config.reload()  # на месте: VectorModelManager и остальные держатели настроек видят то же
                                  # (раньше self.config подменялся новым словарём, а у них оставался прежний)
            self.engine = create_engine(self.config['engine_type'], self.config['engine_params'],
                                        on_startup_failure=lambda title, text: messagebox.showerror(title, text, parent=self.root))

            self.engine_type = self.engine.engine_type
            self.index_manager.index_display_map.clear()

            engine_display = self._get_engine_display_name()
            self.root.title(f"Синева+ | Движок {engine_display}")

            self.update_index_list()
            self.result_text.delete(1.0, tk.END)
            self.word_panel.clear()
            self.search_controller.all_filtered_topics = []
            self.search_controller.all_filtered_topics_b = []
            self.search_controller.results_page = 0
            self.btn_back.config(state='disabled')
            self.btn_forward.config(state='disabled')
            self.btn_first.config(state='disabled')
            self.btn_last.config(state='disabled')
            self.excluded_words.clear()
            self.result_text_2.delete(1.0, tk.END)
            self.word_panel_2.clear()
            self._set_split_view_active(False)
            self.engine_var.set(new_display_name)

            self._show_help_text()

        except Exception as e:
            success = False
            messagebox.showerror("Ошибка", f"Ошибка переключения: {e}")
        finally:
            self.progress_bar.stop()
            self._hide_progress()

        if hasattr(stats_logger, 'STATS_ENABLED') and stats_logger.STATS_ENABLED:
            end_time = time.time()
            switch_time_ms = (end_time - start_time) * 1000
            stats_logger.log_engine_switch(
                from_engine=from_engine,
                to_engine=new_engine_type,
                switch_time_ms=switch_time_ms,
                success=success
            )