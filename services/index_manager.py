import os
import time
import glob
from typing import List, TYPE_CHECKING
from services.dialogs import messagebox
import stats_logger
from utils.text_processing import make_safe_index_name
from vector_engines import CHUNK_BASED_MODEL_TYPES

if TYPE_CHECKING:  # только для аннотации типа: сам виджет передаёт окно, сервису его импортировать незачем
    from ui.index_check_list import IndexCheckList


class IndexManager:
    # True, пока обрабатывается смена выбора: список индексов сообщает о выборе при КАЖДОЙ перестройке, в том числе из
    # update_index_list(), который сам вызывается при переключении индекса FTS5 (см. _on_selection_changed). Значение по
    # умолчанию — на уровне класса: флаг работает и у объекта, созданного без __init__.
    _handling_selection = False

    def __init__(self, engine, config_dict, check_list: 'IndexCheckList',
                 selected_count_label, update_status_callback,
                 clear_result_callback=None, parent=None, vector_model_manager=None):
        self.engine = engine
        self.config_dict = config_dict
        self.check_list = check_list
        self.selected_count_label = selected_count_label
        self.update_status = update_status_callback
        self.clear_result_callback = clear_result_callback
        self.parent = parent
        # Заполняется в app_window.py после создания VectorModelManager —
        # позволяет подмешать "FT <имя>" псевдо-индексы обученных векторных
        # моделей в общий список индексов (см. update_index_list).
        self.vector_model_manager = vector_model_manager
        # Заполняется в app_window.py — запускает индикатор загрузки и
        # отслеживание готовности модели (см. _maybe_offer_vector_preload).
        self.preload_started_callback = None
        # Вызывается при каждой смене отмеченных индексов (selected — список имён) —
        # главное окно использует это для режима просмотра одного файла ("**").
        self.selection_changed_callback = None

        self.selected_indices_names = []
        self.index_display_map = {}
        self._populate_index_display_map()
        # Модели, для которых пользователь уже ответил на вопрос о
        # предзагрузке в этой сессии — чтобы не спрашивать повторно при
        # каждом изменении отметок (см. _on_selection_changed).
        self._vector_preload_asked = set()

        self.check_list.selection_callback = self._on_selection_changed

    def _populate_index_display_map(self):
        engine_type = getattr(self.engine, 'engine_type', 'fts5')
        if engine_type not in ('manticore', 'elasticsearch'):
            return
        try:
            indices = self.engine.list_indices()
        except Exception:
            return
        for filename, (display_name, _, _) in self.config_dict.items():
            _, expected = make_safe_index_name(filename, engine_type)
            if expected in indices:
                self.index_display_map[expected] = display_name

    def _on_selection_changed(self, selected: List[str]):
        self.selected_indices_names = selected
        self._update_selected_indices_display()
        # Вложенные уведомления (от update_index_list, который мы сами вызвали ниже) только обновляют имена и надпись:
        # иначе переключение индекса вызывало бы обновление списка, оно — уведомление о выборе, а оно — снова
        # переключение, и так до переполнения стека (в режиме FTS5 при одном отмеченном индексе).
        if self._handling_selection:
            return
        self._handling_selection = True
        try:
            self._maybe_offer_vector_preload(selected)

            if getattr(self.engine, 'engine_type', 'fts5') == 'fts5' and len(selected) == 1:
                self._switch_fts5_index(selected[0])
            if self.selection_changed_callback:
                self.selection_changed_callback(selected)
        finally:
            self._handling_selection = False

    def _switch_fts5_index(self, idx):
        """FTS5 работает с одним индексом за раз: переключает на него движок и обновляет окно."""
        if self.engine.select_index(idx):
            if self.clear_result_callback:
                self.clear_result_callback()
            self.update_index_list()
        else:
            messagebox.showerror(parent=self.parent, title="Ошибка",
                                 message=f"Не удалось переключиться на индекс {idx}")

    def _maybe_offer_vector_preload(self, selected: List[str]):
        """Предлагает загрузить модель заранее, в фоне, не дожидаясь
           первого реального поиска (единственная по-настоящему медленная
           часть векторного поиска — сама загрузка модели с диска; все
           последующие запросы после неё уже быстрые за счёт кеша).
           Спрашивается не более одного раза за сессию на модель.

           Для FastText — только если ОДНОВРЕМЕННО отмечены и модель, и
           хотя бы один обычный индекс (ей нужен индекс для поиска). Для
           MiniLM индекс не нужно отмечать отдельно — он определился при
           обучении и берётся из конфигурации, поэтому достаточно отметить
           только саму модель."""
        if not self.vector_model_manager:
            return
        vector_key = None
        has_real_index = False
        for key in selected:
            if self.vector_model_manager.is_vector_key(key):
                vector_key = vector_key or key
            else:
                has_real_index = True

        if not vector_key:
            return
        if self.vector_model_manager.get_model_type(vector_key) not in CHUNK_BASED_MODEL_TYPES and not has_real_index:
            return
        if self.vector_model_manager.is_loaded(vector_key):
            return
        if vector_key in self._vector_preload_asked:
            return
        self._vector_preload_asked.add(vector_key)

        if messagebox.askyesno(
            parent=self.parent,
            title="Загрузка модели",
            message=f"Загрузить векторную модель «{vector_key}» сейчас?\n\n"
                    "Это ускорит первый поиск по ней (иначе она загрузится "
                    "при самом первом запросе, с задержкой).",
            height=320
        ):
            self.vector_model_manager.preload_model_async(vector_key)
            if self.preload_started_callback:
                self.preload_started_callback(vector_key)

    def _update_selected_indices_display(self):
        # Число выбранных индексов показывается наверху, сразу после надписи
        # "Выбор индекса:" — в виде "(N)".
        if not self.selected_count_label:
            return
        count = len(self.selected_indices_names)
        self.selected_count_label.config(text=f"({count})")

    def update_index_list(self):
        if not self.engine or self.check_list is None:
            return
        try:
            self._populate_index_display_map()
            indices = self.engine.list_indices()
        except Exception as e:
            self.update_status(f"❌ Ошибка обновления списка индексов: {e}")
            return

        # Подмешиваем "FT <имя>" псевдо-индексы обученных векторных моделей —
        # они не настоящие индексы Manticore, поэтому не через
        # _populate_index_display_map (у них уже готовое отображаемое имя).
        # Только для движка Manticore — векторный поиск сейчас реализован
        # только для него (см. services/vector_model_manager.py).
        if self.vector_model_manager and getattr(self.engine, 'engine_type', 'fts5') == 'manticore':
            # Вспомогательные индексы "окон смысла" (model_...) принадлежат
            # только своей модели — не показываем их отдельной строкой,
            # иначе их можно случайно удалить отдельно от модели (и тогда
            # удаление самой модели упадёт с ошибкой — индекс уже удалён).
            aux_indices = self.vector_model_manager.get_auxiliary_indices()
            indices = [idx for idx in indices if idx not in aux_indices]
            indices = list(indices) + self.vector_model_manager.list_display_keys()

        self.check_list.set_indices(indices, self.index_display_map)
        # Отметки восстанавливаются В ПОРЯДКЕ ОТМЕТКИ (get_selected_ordered): selected_indices_names приходит из множества
        # (порядок случайный), и от порядка зависит, какой файл окажется в верхнем окне режима разделения.
        self.check_list.set_selected(self.check_list.get_selected_ordered())
        self._update_selected_indices_display()

    def toggle_select_all(self):
        self.check_list._on_right_click(None)

    def delete_selected_indices(self):
        """Удаляет выбранные индексы с подтверждением."""
        selected = self.check_list.get_selected()
        if not selected:
            messagebox.showwarning(parent=self.parent, title="Нет выбора",
                                   message="Не выбран ни один индекс для удаления.")
            return

        if not messagebox.askokcancel(
            parent=self.parent,
            title="Удаление индексов",
            message=f"Вы уверены, что хотите удалить выбранные индексы?\n{', '.join(selected)}\nЭто действие необратимо."
        ):
            return

        self.update_status(f"🗑️ Удаление {len(selected)} индексов...")

        # "FT ..." — это не настоящие индексы Manticore, а зарегистрированные
        # векторные модели (кнопка "Векторы"); удаляются отдельно, через
        # VectorModelManager, а не через engine.delete_index() — иначе
        # получалась ошибка синтаксиса: движок пытался удалить таблицу с
        # именем вида "FT Библия" (пробелы/кириллица), которой на самом деле
        # не существует — реальный индекс называется иначе (например
        # "ft_bibliya") и уже удаляется внутри delete_model().
        ft_keys = [name for name in selected
                  if self.vector_model_manager and self.vector_model_manager.is_vector_key(name)]
        real_indices = [name for name in selected if name not in ft_keys]

        ft_success_all = self._delete_vector_models(ft_keys)

        engine_type = getattr(self.engine, 'engine_type', 'unknown')
        index_size_before = self._indices_size_on_disk(engine_type, real_indices)  # размер до удаления

        start_time = time.time()
        success_all = self._delete_real_indices(real_indices)
        deletion_time_ms = (time.time() - start_time) * 1000
        success_all = success_all and ft_success_all

        if success_all:
            self._finish_successful_deletion(selected, real_indices, engine_type, index_size_before, deletion_time_ms)
        else:
            self._report_failed_deletion()

    def _delete_vector_models(self, ft_keys):
        """Удаляет векторные модели ("FT ..."). True, если удалились все."""
        success_all = True
        for key in ft_keys:
            success, message = self.vector_model_manager.delete_model(key)
            if success:
                self.update_status(f"✅ {message}")
            else:
                success_all = False
                self.update_status(f"⚠️ {message}")
        return success_all

    def _indices_size_on_disk(self, engine_type, real_indices):
        """Размер файлов удаляемых индексов на диске (для журнала статистики)."""
        size = 0
        if engine_type == 'fts5':
            for name in real_indices:
                possible = [name, os.path.join("indicies_fts5", name + ".db"), name + ".db"]
                for p in possible:
                    if os.path.exists(p):
                        size += os.path.getsize(p)
                        break
        elif engine_type == 'manticore':
            data_dir = getattr(self.engine, 'data_dir', None)
            if data_dir:
                for name in real_indices:
                    pattern = os.path.join(data_dir, f"{name}.*")
                    size += sum(os.path.getsize(f) for f in glob.glob(pattern))
        return size

    def _delete_real_indices(self, real_indices):
        """Удаляет настоящие индексы движка по одному, не останавливаясь на сбое. True, если удалились все."""
        success_all = True
        for name in real_indices:
            try:
                if not self.engine.delete_index(name):
                    success_all = False
                    self.update_status(f"⚠️ Не удалось удалить индекс {name}")
            except Exception as e:
                success_all = False
                self.update_status(f"⚠️ Ошибка удаления {name}: {e}")
        return success_all

    def _finish_successful_deletion(self, selected, real_indices, engine_type, index_size_before, deletion_time_ms):
        # Принудительно обновляем список
        self.update_index_list()
        # Удаляем из маппинга отображаемых имён
        for name in real_indices:
            if name in self.index_display_map:
                del self.index_display_map[name]
        if self.clear_result_callback:
            self.clear_result_callback()

        # Логирование (только по настоящим индексам — у "FT ..." записей
        # нет своего размера в терминах индекса Manticore, который здесь
        # считается)
        if stats_logger.STATS_ENABLED and real_indices:
            self._log_deletion(engine_type, real_indices, index_size_before, deletion_time_ms)

        self._update_selected_indices_display()
        self.update_status(f"✅ Удалено {len(selected)} индексов за {deletion_time_ms:.0f} мс")

    def _log_deletion(self, engine_type, real_indices, index_size_before, deletion_time_ms):
        total_after = 0
        if engine_type == 'fts5':
            indices_dir = "indicies_fts5"
            if os.path.exists(indices_dir):
                total_after = sum(
                    os.path.getsize(os.path.join(indices_dir, f))
                    for f in os.listdir(indices_dir) if f.endswith('.db')
                )
        elif engine_type == 'manticore':
            data_dir = getattr(self.engine, 'data_dir', None)
            if data_dir:
                total_after = sum(
                    os.path.getsize(os.path.join(data_dir, f))
                    for f in os.listdir(data_dir)
                    if os.path.isfile(os.path.join(data_dir, f))
                )
        stats_logger.log_index_deletion(
            engine_type=engine_type,
            index_name=", ".join(real_indices),
            index_size_bytes=index_size_before,
            deletion_time_ms=deletion_time_ms,
            total_index_size_after=total_after
        )

    def _report_failed_deletion(self):
        self.update_index_list()
        messagebox.showerror(parent=self.parent, title="Ошибка",
                             message="Не удалось удалить один или несколько индексов.\n"
                                     "Проверьте статус в строке состояния.")
        self.update_status("❌ Удаление индексов завершено с ошибками")

    def get_selected_indices(self) -> List[str]:
        return self.check_list.get_selected()

    def get_selected_indices_ordered(self) -> List[str]:
        """Как get_selected_indices(), но в порядке, в котором индексы были
           отмечены — нужно для режима разделения окна результатов, чтобы
           знать, какой индекс "первый выбранный", а какой "второй"."""
        return self.check_list.get_selected_ordered()