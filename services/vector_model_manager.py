"""Обучение и дообучение векторных (word-embedding) моделей — кнопка
   "Векторы". Обучается "с нуля" (или дообучается) на тексте выбранных в
   правом нижнем окне книг (том же списке, что и для обычной индексации).

   Архитектура после пересмотра (см. обсуждение с пользователем):
   - модель НЕ создаёт и не использует собственный "вспомогательный" индекс
     Manticore для выдачи результатов — она только подсказывает, какие
     слова близки к запросу; сам поиск и подсветка топиков идут по уже
     существующим индексам, отмеченным галочками ВМЕСТЕ с моделью (их
     создают обычной кнопкой "В индекс" — так гиперссылка на файл-источник
     у результатов векторного поиска тоже работает, в отличие от прежней
     схемы с отдельным ft_-индексом);
   - обучающие данные строятся не из топиков поиска (они нарезаны так,
     чтобы не разрывать слова/фрагменты — для смыслового обучения это не
     подходит), а из "окон" вокруг каждого предложения: само предложение +
     до N предложений до и до M предложений после (не выходя за границы
     абзаца) — это даёт словам из одного предложения куда больше шансов
     повлиять друг на друга при обучении, чем далёким словам, естественным
     образом ослабляя связь с расстоянием без специальной весовой модели;
   - модель можно дообучать (continue_train) на дополнительных файлах,
     сохраняя историю обучения в текстовом файле рядом с моделью."""

import os
import re
import threading
from datetime import datetime
from config import save_config
from utils.text_processing import read_text_file, make_safe_index_name, split_sentences
from vector_engines import create_vector_model, MODEL_TYPE_PREFIXES, CHUNK_BASED_MODEL_TYPES
from vector_engines.base_vector_model import TrainingCancelled

_WORD_RE = re.compile(r'[а-яА-ЯёЁa-zA-Z0-9]+')

# Суффикс, который добавляется к имени модели ТОЛЬКО в списке индексов
# правого верхнего окна (чтобы наглядно отличать модели от индексов) — сам
# ключ модели в конфигурации/внутри программы этот суффикс не содержит, см.
# _normalize_key(), который снимает его при получении отметок из списка.
_MODEL_LIST_SUFFIX = " [модель]"


# Ступени "суммарный размер файлов -> параметры обучения". Вынесены в
# список (а не if/elif), чтобы можно было сдвинуться на ступень вверх целиком,
# когда планируется дальнейшее дообучение (см. suggest_vector_params) — все
# пять параметров в нашей реализации фиксируются на весь срок жизни модели
# (при дообучении переиспользуются автоматически, не спрашиваются заново),
# поэтому для растущей модели правильнее ориентироваться не на текущий, а на
# ожидаемый в будущем объём.
_VECTOR_PARAM_TIERS = [
    (10, {'vector_size': 100, 'window': 5, 'min_count': 1, 'epochs': 20, 'sg': 1, 'workers': 4}),
    (50, {'vector_size': 150, 'window': 5, 'min_count': 2, 'epochs': 12, 'sg': 1, 'workers': 4}),
    (150, {'vector_size': 200, 'window': 5, 'min_count': 3, 'epochs': 8, 'sg': 1, 'workers': 4}),
    (float('inf'), {'vector_size': 300, 'window': 5, 'min_count': 5, 'epochs': 5, 'sg': 0, 'workers': 4}),
]


# Определение "вариации слова" живёт в utils/key_concepts.py и импортируется сюда под прежним
# именем: тем же определением пользуется фильтр "ключевые понятия" (кнопка "КП", параметр
# key_concepts_only) — слова, которые "−В" убирает из окна "Совпадения", и слова, которые
# фильтр включает, не должны расходиться.
from utils.key_concepts import words_are_variations as _words_are_variations, expand_dictionary


def dedupe_word_variations(neighbors):
    """neighbors — [(слово, близость), ...], уже отсортированы по убыванию
       близости. Возвращает (kept, removed_count) — kept: по одному,
       самому рейтинговому представителю на группу словоформ; removed_count
       — сколько слов отсеяно как словоформа уже сохранённого."""
    kept = []
    removed_count = 0
    for word, score in neighbors:
        if any(_words_are_variations(word, kw) for kw, _ks in kept):
            removed_count += 1
        else:
            kept.append((word, score))
    return kept, removed_count


def suggest_vector_params(model_type: str, total_bytes: int, planned_total_mb: float = None) -> dict:
    """Предлагает стартовые параметры обучения по суммарному размеру
       выбранных для обучения файлов — большие корпуса требуют других
       настроек, чем маленькая книга. Для FastText: меньше эпох (данных и
       так много), выше порог отсечения редких слов (иначе словарь
       раздувается опечатками и обрывками), можно себе позволить вектор
       побольше. Для MiniLM (готовая, не обучаемая с нуля модель) ступеней
       по объёму нет — единственный практичный параметр здесь — размер
       пакета при кодировании корпуса.
       Это именно ОТПРАВНАЯ ТОЧКА для диалога настроек при создании модели,
       не жёсткое правило — пользователь может изменить любое значение.

       planned_total_mb: если пользователь заранее знает ожидаемый суммарный
       объём файлов, на которых модель будет дообучена в будущем (не только
       сейчас) — рекомендации считаются по НЕМУ, если он больше текущего
       размера, поскольку изменить эти параметры позже уже не получится
       (для FastText; на MiniLM это не влияет)."""
    if model_type == 'minilm':
        return {'batch_size': 32}
    if model_type == 'lsa':
        # LSA обучается на самом корпусе (как FastText) — размерность
        # пространства и порог отсечения редких слов (min_df) имеет смысл
        # растить вместе с объёмом текста: больше текста — больше реальных
        # тематических направлений можно содержательно выделить, и можно
        # позволить себе отсекать более редкие термины как шум.
        mb = total_bytes / (1024 * 1024)
        if planned_total_mb is not None and planned_total_mb > mb:
            mb = planned_total_mb
        if mb < 10:
            return {'dim': 100, 'min_df': 2}
        elif mb < 50:
            return {'dim': 200, 'min_df': 3}
        elif mb < 150:
            return {'dim': 320, 'min_df': 4}
        else:
            return {'dim': 400, 'min_df': 5}
    mb = total_bytes / (1024 * 1024)
    if planned_total_mb is not None and planned_total_mb > mb:
        mb = planned_total_mb
    for threshold, params in _VECTOR_PARAM_TIERS:
        if mb < threshold:
            return dict(params)
    return dict(_VECTOR_PARAM_TIERS[-1][1])


def _split_sentences(text: str) -> list:
    """Тонкая обёртка над utils.text_processing.split_sentences — оставлена
       здесь как есть, чтобы не переписывать остальной код файла; сама
       логика теперь общая (см. утилиту) — переиспользуется и в
       utils/semantic_chunking.py для "окон смысла" MiniLM."""
    return split_sentences(text)


class VectorModelManager:
    def __init__(self, engine, config_dict, update_status_callback):
        self.engine = engine
        self.config_dict = config_dict
        self.update_status = update_status_callback
        self._loaded_models = {}   # display_key -> BaseVectorModel (кеш в памяти)
        # Ключи моделей, которые сейчас грузятся в фоновом потоке — по
        # этому множеству вызывающий код (см. ui/app_window.py,
        # _poll_vector_preload) опросом узнаёт, завершилась ли загрузка,
        # вместо того чтобы полагаться на сигнал из фонового потока.
        self._preloading = set()
        # Загрузка модели с диска — единственная по-настоящему медленная
        # часть векторного поиска (после неё все следующие запросы уже
        # быстрые за счёт кеша выше). Лок на каждую модель — чтобы если
        # фоновая предзагрузка (см. preload_model_async) и реальный поиск
        # совпали по времени, второй вызов ПОДОЖДАЛ первую загрузку вместо
        # того, чтобы начинать читать тот же файл с диска ещё раз.
        self._model_locks = {}

    # ---------- Список для правого верхнего окна ----------
    def _normalize_key(self, key: str) -> str:
        """Снимает суффикс '[модель]' (если есть) — записи в списке индексов
           показываются с ним (см. list_display_keys), а внутренний ключ в
           конфигурации/кеше — без него. Все публичные методы, принимающие
           display_key, вызывают это первым делом, чтобы работать что с
           "сырым" ключом, что с тем, что реально пришёл из списка."""
        if key.endswith(_MODEL_LIST_SUFFIX):
            return key[:-len(_MODEL_LIST_SUFFIX)]
        return key

    def list_display_keys(self):
        """Возвращает список 'FT <имя> [модель]' / 'PM <имя> [модель]' — по
           одному на каждую зарегистрированную в конфигурации векторную
           модель. Эти строки подмешиваются в общий список индексов (см.
           IndexManager) — суффикс "[модель]" только для наглядности в
           списке, сам ключ модели (без него) хранится в конфигурации."""
        return [key + _MODEL_LIST_SUFFIX for key in self.config_dict.get('vector_models', {}).keys()]

    def is_vector_key(self, key: str) -> bool:
        return self._normalize_key(key) in self.config_dict.get('vector_models', {})

    def compute_display_key(self, model_type: str, selected_files, display_names_by_file,
                           name_suffix: str = None) -> str:
        """Вычисляет, каким получится ключ модели ("FT ..."/"PM ...") для
           ДАННОГО набора файлов и типа — той же логикой, что использует
           train() при регистрации, но без побочных эффектов. Нужно, чтобы
           заранее (до самого обучения) проверить, не существует ли уже
           модель с таким именем — см. ui/app_window.py, prepare_vectors().
           name_suffix — уточнение (кнопка "Другое имя"), чтобы на одном и
           том же файле можно было держать несколько моделей одновременно."""
        names = [display_names_by_file.get(f, os.path.basename(f)) for f in selected_files]
        display_name = " + ".join(names)
        if name_suffix:
            display_name = f"{display_name} ({name_suffix})"
        prefix = MODEL_TYPE_PREFIXES.get(model_type, 'FT')
        return f"{prefix} {display_name}"

    def _cleanup_aux_index_on_cancel(self, model_type, associated_indices, semantic_window):
        """При прерывании ОБУЧЕНИЯ НОВОЙ модели (Esc) — если для "окна
           смысла" (режимы 2-4) уже успел создаться вспомогательный
           индекс, удаляем его: модель так и не зарегистрировалась в
           конфигурации, и без этой очистки индекс остался бы висеть на
           диске никому не принадлежащим, осиротевшим."""
        if model_type not in CHUNK_BASED_MODEL_TYPES or not associated_indices:
            return
        if semantic_window and semantic_window.get('mode') == 'existing_index':
            return  # реальные файловые индексы не создавались нами — не трогаем
        for idx_name in associated_indices:
            try:
                self.engine.delete_index(idx_name)
            except Exception:
                pass

    def is_loaded(self, display_key: str) -> bool:
        """Уже загружена ли модель в память (кеш) — используется, чтобы не
           показывать лишний раз диалог подтверждения загрузки (см.
           IndexManager._maybe_offer_vector_preload)."""
        display_key = self._normalize_key(display_key)
        return display_key in self._loaded_models

    # ---------- Подготовка обучающих данных ("круги связи") ----------
    def _build_training_sentences(self, selected_files):
        """Строит обучающие "предложения" для gensim: для каждого реального
           предложения текста — окно из него самого плюс до
           vector_sentences_before предложений до и до
           vector_sentences_after предложений после, не выходя за границы
           абзаца. Соседние окна перекрываются — это и даёт словам из
           одного предложения больше общих обучающих контекстов, чем
           далёким словам, без явного взвешивания.
           Возвращает (sentences, error_message)."""
        sentences_before = self.config_dict.get('vector_sentences_before', 7)
        sentences_after = self.config_dict.get('vector_sentences_after', 10)

        all_windows = []
        for file_path in selected_files:
            try:
                # keep_empty_docx_paragraphs=False — как при обычной индексации,
                # не как при просмотре файла (см. services/file_manager.py).
                text = read_text_file(file_path, keep_empty_docx_paragraphs=False)
            except Exception as e:
                return None, f"Ошибка чтения файла {file_path}: {e}"

            # В .docx абзац — отдельная строка (пустые абзацы при чтении отброшены, поэтому пустой строки между
            # абзацами нет); в .txt абзацы разделены пустой строкой. Иначе окно «кругов связи» в .docx
            # переходило бы через абзацы, хотя обещано «не выходя за границы абзаца».
            if os.path.splitext(file_path)[1].lower() == '.docx':
                paragraphs = text.split('\n')
            else:
                paragraphs = re.split(r'\n\s*\n', text)
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                sentences = _split_sentences(para)
                tokenized = [_WORD_RE.findall(s.lower()) for s in sentences]
                tokenized = [t for t in tokenized if t]
                n = len(tokenized)
                for i in range(n):
                    lo = max(0, i - sentences_before)
                    hi = min(n, i + sentences_after + 1)
                    window = []
                    for j in range(lo, hi):
                        window.extend(tokenized[j])
                    if window:
                        all_windows.append(window)

        if not all_windows:
            return None, "Не удалось выделить предложения для обучения — файл(ы) пусты?"
        return all_windows, None

    def _build_minilm_sections(self, selected_files):
        """Для MiniLM: вместо нарезки текста заново забирает уже готовые
           топики из существующих индексов Manticore выбранных файлов —
           этой модели не нужны пословные окна контекста (как FastText),
           она кодирует целые куски текста, и топики, уже нарезанные
           обычной индексацией, для этого вполне подходят: их не нужно
           резать ещё раз отдельным, парал­лельным способом.

           Поэтому файлы должны быть УЖЕ проиндексированы (кнопка "В
           индекс") — иначе для них попросту нет готовых топиков. Если
           какие-то из выбранных файлов ещё не проиндексированы —
           возвращается понятная ошибка с их именами, а не тихий пропуск.

           Возвращает (sections, error); sections — список
           (index_name, rowid, text)."""
        engine_type = getattr(self.engine, 'engine_type', 'manticore')
        if engine_type != 'manticore':
            return None, "Обучение MiniLM поддерживается только для движка Manticore."

        try:
            existing_indices = set(self.engine.list_indices())
        except Exception as e:
            return None, f"Не удалось получить список индексов: {e}"

        sections = []
        not_indexed = []
        for f in selected_files:
            filename = os.path.basename(f)
            _safe_name, index_name = make_safe_index_name(filename, engine_type)
            if index_name not in existing_indices:
                not_indexed.append(filename)
                continue
            rows = self.engine.get_all_sections(index_name)
            for rowid, text, _file_name in rows:
                sections.append((index_name, rowid, text))

        if not_indexed:
            names = ", ".join(not_indexed)
            return None, (f"Эти файлы ещё не проиндексированы, готовых топиков для кодирования "
                          f"нет: {names}. Сначала проиндексируйте их кнопкой «В индекс», затем "
                          f"обучите модель.")

        if not sections:
            return None, "В выбранных индексах не нашлось ни одного топика."

        return sections, None

    def _build_minilm_semantic_chunks(self, selected_files, chunk_mode, chunk_params, aux_index_name, append=False):
        """Режимы 2-4 "окон смысла" (см. ui/vector_params_dialog.py):
           вместо готовых топиков реального индекса режет текст файлов
           заново — способом, выбранным ДЛЯ ЭТОЙ модели — и складывает
           результат во вспомогательный индекс (имя начинается с "model_",
           чтобы отличать от обычных, файловых индексов в общем списке).

           append=True — для дообучения: вставляет новые блоки в УЖЕ
           существующий вспомогательный индекс вместо того, чтобы
           пересоздавать его, и возвращает только НОВЫЕ блоки (не все —
           иначе уже закодированные ранее блоки задвоились бы в векторах
           модели при повторном кодировании).

           Возвращает (sections, error); sections — список
           (index_name, rowid, text), index_name везде один и тот же —
           aux_index_name."""
        engine_type = getattr(self.engine, 'engine_type', 'manticore')
        if engine_type != 'manticore':
            return None, "Обучение MiniLM поддерживается только для движка Manticore."

        from utils.semantic_chunking import chunk_by_sentence_window, chunk_by_overlap, chunk_by_paragraphs

        try:
            self.engine.ensure_chunk_index(aux_index_name, drop_if_exists=not append)
        except Exception as e:
            return None, f"Не удалось создать вспомогательный индекс «{aux_index_name}»: {e}"

        existing_ids = set()
        if append:
            try:
                existing_ids = {r[0] for r in self.engine.get_all_sections(aux_index_name)}
            except Exception as e:
                return None, f"Не удалось прочитать вспомогательный индекс «{aux_index_name}»: {e}"

        total_inserted = 0
        for f in selected_files:
            try:
                text = read_text_file(f)
            except Exception as e:
                return None, f"Не удалось прочитать файл {os.path.basename(f)}: {e}"

            if chunk_mode == 'sentence_window':
                sentences_before = chunk_params.get(
                    'sentences_before', self.config_dict.get('vector_sentences_before', 7)
                )
                sentences_after = chunk_params.get(
                    'sentences_after', self.config_dict.get('vector_sentences_after', 10)
                )
                chunks = chunk_by_sentence_window(text, sentences_before, sentences_after)
            elif chunk_mode == 'char_overlap':
                target = chunk_params.get('target_chars', 900)
                overlap = chunk_params.get('overlap_chars', 150)
                chunks = chunk_by_overlap(text, target=target, overlap=overlap)
            elif chunk_mode == 'paragraphs':
                chunks = chunk_by_paragraphs(text)
            else:
                return None, f'Неизвестный режим "окна смысла": {chunk_mode}'

            if not chunks:
                continue
            try:
                total_inserted += self.engine.insert_chunks(aux_index_name, chunks, os.path.basename(f))
            except Exception as e:
                return None, f"Не удалось вставить блоки в «{aux_index_name}»: {e}"

        if total_inserted == 0:
            return None, "Не удалось выделить ни одного смыслового блока из выбранных файлов."

        try:
            rows = self.engine.get_all_sections(aux_index_name)
        except Exception as e:
            return None, f"Не удалось прочитать вспомогательный индекс «{aux_index_name}»: {e}"

        if append:
            rows = [r for r in rows if r[0] not in existing_ids]
        sections = [(aux_index_name, rowid, text) for rowid, text, _file_name in rows]
        return sections, None

    def _indices_of_other_models(self, display_key):
        """Индексы (вспомогательные и реальные), записанные за ДРУГИМИ моделями."""
        taken = set()
        for key, entry in self.config_dict.get('vector_semantic_window', {}).items():
            if key != display_key:
                taken.update(entry.get('indices', []))
        return taken

    def _aux_index_name_for(self, model_display_key, append):
        """Имя вспомогательного индекса «окна смысла» (режимы 2-4).
           Дообучение (append) продолжает ТОТ индекс, что сохранён за моделью: имя, вычисленное заново, у модели,
           созданной прежней версией, могло оказаться другим, и новые блоки ушли бы в чужой, пустой индекс.
           Новая модель получает model_<безопасное имя ключа>; если это имя уже занято индексом ДРУГОЙ модели
           (названия «Книга 1» и «Книга-1» дают одно безопасное имя), добавляется номер — иначе создание новой
           модели стёрло бы вспомогательный индекс прежней."""
        if append:
            stored = self.get_associated_indices(model_display_key)
            if stored:
                return stored[0]
        safe_base, _ = make_safe_index_name(model_display_key, 'manticore')
        name = f"model_{safe_base}"
        taken = self._indices_of_other_models(model_display_key)
        candidate, number = name, 2
        while candidate in taken:
            candidate = f"{name}_{number}"
            number += 1
        return candidate

    def build_minilm_training_data(self, selected_files, semantic_window, model_display_key, append=False):
        """Общая точка входа для обеих веток "окон смысла" — вызывается из
           train()/continue_train() для MiniLM. semantic_window — словарь
           {'mode': 'existing_index'|'sentence_window'|'char_overlap'|
           'paragraphs', 'params': {...}} (выбран в диалоге создания
           модели и сохранён вместе с ней — см. _append_semantic_window_
           config).

           Возвращает (sections, associated_indices, error) —
           associated_indices запоминается в конфигурации модели: именно
           по нему при ПОИСКЕ определяется, какой индекс использовать, не
           спрашивая пользователя отметить его галочкой ещё раз (см.
           ui/app_window.py)."""
        mode = semantic_window.get('mode', 'existing_index')
        if mode == 'existing_index':
            sections, error = self._build_minilm_sections(selected_files)
            if error:
                return None, None, error
            associated = sorted(set(s[0] for s in sections))
            return sections, associated, None

        aux_index_name = self._aux_index_name_for(model_display_key, append)
        sections, error = self._build_minilm_semantic_chunks(
            selected_files, mode, semantic_window.get('params', {}), aux_index_name, append=append
        )
        if error:
            return None, None, error
        return sections, [aux_index_name], None

    # ---------- История обучения ----------
    def _history_path(self, model_path: str) -> str:
        base, _ext = os.path.splitext(model_path)
        return base + "_history.txt"

    def _append_history(self, model_path, action, selected_files, display_names_by_file, detailed_log=None):
        names = ", ".join(display_names_by_file.get(f, os.path.basename(f)) for f in selected_files)
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {action}: {names}\n"
        try:
            with open(self._history_path(model_path), 'a', encoding='utf-8') as f:
                f.write(line)
                if detailed_log:
                    f.write("\n".join(detailed_log))
                    f.write("\n\n" + "=" * 70 + "\n\n")
        except Exception as e:
            self.update_status(f"⚠️ Не удалось записать историю обучения модели: {e}")

    # ---------- Подробный лог обучения (для файла истории) ----------
    def _build_detailed_training_log(self, model, sentences, extra_params):
        """Формирует подробный, наглядный лог того, что происходило при
           обучении: параметры модели, первые 7 обучающих окон и 7 окон из
           середины процесса — с текстом окна, парами (слово, контекст) в
           пределах window (как их формирует skip-gram) и итоговыми
           векторами слов ПОСЛЕ полного обучения (промежуточные векторы по
           ходу обучения gensim не отдаёт — веса меняются пакетно внутри
           оптимизированного C-кода, а не окно за окном)."""
        params = {}
        if hasattr(model, 'get_params'):
            params = dict(model.get_params())
        params.update(extra_params)
        window_size = params.get('window', 5)

        lines = ["Параметры модели:"]
        for key, value in params.items():
            lines.append(f"  {key} = {value}")
        lines.append(f"  Обучающих окон всего: {len(sentences)}")
        try:
            vocab_size = len(model.model.wv.key_to_index)
            lines.append(f"  Слов в словаре после обучения: {vocab_size}")
        except Exception:
            pass
        lines.append("")
        lines.append("(Векторы ниже — итоговые, после полного обучения на всех окнах и всех "
                     "эпохах; промежуточное состояние по ходу обучения gensim не сохраняет. "
                     "Пары показаны для МАКСИМАЛЬНОГО размера окна — сам gensim иногда "
                     "случайно берёт окно чуть меньше заданного, это его штатное поведение.)")

        n = len(sentences)
        first_n = min(7, n)
        first_windows = list(enumerate(sentences[:first_n]))
        lines.append("")
        lines.extend(self._describe_windows(
            f"--- Первые {first_n} обучающих окон (из {n}) ---", first_windows, model, window_size
        ))

        if n > first_n:
            mid_start = max(first_n, n // 2 - 3)
            mid_end = min(n, mid_start + 7)
            mid_windows = list(enumerate(sentences[mid_start:mid_end], start=mid_start))
            lines.append("")
            lines.extend(self._describe_windows(
                f"--- {len(mid_windows)} окон в районе середины обучения "
                f"(окна {mid_start + 1}-{mid_end} из {n}) ---",
                mid_windows, model, window_size
            ))

        return lines

    @staticmethod
    def _describe_windows(title, indexed_windows, model, window_size):
        lines = [title]
        for idx, tokens in indexed_windows:
            lines.append(f"\nОкно №{idx + 1}: {tokens}")

            pairs = []
            n = len(tokens)
            for i, word in enumerate(tokens):
                lo = max(0, i - window_size)
                hi = min(n, i + window_size + 1)
                for j in range(lo, hi):
                    if j != i:
                        pairs.append((word, tokens[j]))
            lines.append(f"  Пары (слово, контекст), window={window_size}:")
            if pairs:
                lines.append("    " + ", ".join(f"({w}, {c})" for w, c in pairs))
            else:
                lines.append("    (нет пар — окно из одного слова)")

            lines.append("  Итоговые векторы слов этого окна (после полного обучения):")
            seen = set()
            for word in tokens:
                if word in seen:
                    continue
                seen.add(word)
                try:
                    vec = model.model.wv[word]
                    vec_str = "[" + ", ".join(f"{v:.4f}" for v in vec.tolist()) + "]"
                except Exception:
                    vec_str = "(вектор недоступен)"
                lines.append(f"    {word}: {vec_str}")
        return lines

    def _build_minilm_detailed_log(self, model, sections, extra_params, embedding_offset=0):
        """То же самое, что _build_detailed_training_log, но для MiniLM —
           по образцу FastText: параметры, первые 7 смысловых блоков и 7
           блоков из середины, только вместо "пар слов в окне" показываем
           сам текст блока (у MiniLM нет пар — она кодирует блок целиком),
           а вектор — итоговый, из model.embeddings по тому же индексу,
           что и блок в исходном списке (порядок сохраняется при
           кодировании, см. MiniLMModel.train). embedding_offset — при
           дообучении sections содержит только НОВЫЕ блоки, а
           model.embeddings — старые+новые вместе, поэтому индекс в
           массиве векторов смещён на число уже бывших там блоков."""
        params = {}
        if hasattr(model, 'get_params'):
            params = dict(model.get_params())
        params.update(extra_params)

        lines = ["Параметры модели:"]
        for key, value in params.items():
            lines.append(f"  {key} = {value}")
        lines.append(f"  Смысловых блоков всего: {len(sections)}")
        lines.append("")
        lines.append("(Векторы ниже — итоговые, после кодирования. Каждое число — одна из "
                     "координат вектора этого блока в многомерном пространстве смысла — как "
                     "и у FastText, по отдельности координаты не читаются, смысл появляется "
                     "только при сравнении векторов целиком, см. поиск.)")

        n = len(sections)
        first_n = min(7, n)
        first_blocks = list(enumerate(sections[:first_n]))
        lines.append("")
        lines.extend(self._describe_minilm_blocks(
            f"--- Первые {first_n} смысловых блоков (из {n}) ---", first_blocks, model, embedding_offset
        ))

        if n > first_n:
            mid_start = max(first_n, n // 2 - 3)
            mid_end = min(n, mid_start + 7)
            mid_blocks = list(enumerate(sections[mid_start:mid_end], start=mid_start))
            lines.append("")
            lines.extend(self._describe_minilm_blocks(
                f"--- {len(mid_blocks)} блоков в районе середины (блоки {mid_start + 1}-{mid_end} из {n}) ---",
                mid_blocks, model, embedding_offset
            ))

        return lines

    @staticmethod
    def _describe_minilm_blocks(title, indexed_blocks, model, embedding_offset=0):
        lines = [title]
        for idx, (index_name, rowid, text) in indexed_blocks:
            preview = text if len(text) <= 400 else text[:400] + "…"
            lines.append(f"\nБлок №{idx + 1} (индекс «{index_name}», rowid {rowid}):")
            lines.append(f"  Текст: {preview}")
            try:
                vec = model.embeddings[embedding_offset + idx]
                vec_str = "[" + ", ".join(f"{v:.4f}" for v in vec.tolist()) + "]"
            except Exception:
                vec_str = "(вектор недоступен)"
            lines.append(f"  Итоговый вектор: {vec_str}")
        return lines

    # ---------- Обучение "с нуля" ----------
    def suggest_params(self, model_type: str, total_bytes: int, planned_total_mb: float = None) -> dict:
        return suggest_vector_params(model_type, total_bytes, planned_total_mb)

    def train(self, selected_files, display_names_by_file, model_type=None, model_params=None,
             semantic_window=None, name_suffix=None, cancel_check=None, progress_callback=None):
        """selected_files — список путей к выбранным файлам (как для обычной
           индексации). display_names_by_file — {file_path: display_name},
           чтобы дать модели понятное имя. model_type — внутренний ключ типа
           модели (например 'fasttext'), выбранный пользователем в диалоге;
           если не задан — берётся общая настройка vector_model_type.
           model_params — параметры обучения (vector_size/window/min_count/
           epochs/sg/workers), обычно выбранные пользователем в том же
           диалоге; если не заданы — берутся рекомендованные по размеру
           файлов. semantic_window — только для MiniLM: словарь {'mode':
           'existing_index'|'sentence_window'|'char_overlap'|'paragraphs',
           'params': {...}} — какой способ получения смысловых блоков
           выбран (см. build_minilm_training_data); если не задан —
           используется 'existing_index' (прежнее поведение). name_suffix —
           уточнение к имени модели (см. ui/app_window.py, кнопка "Другое
           имя" в диалоге "модель уже существует") — добавляется в скобках
           к имени файлов, чтобы для одного и того же файла можно было
           держать несколько моделей с разными параметрами одновременно, не
           перезаписывая друг друга (и с разными вспомогательными
           индексами, если они есть). cancel_check — необязательный
           вызываемый без аргументов, возвращающий True при запросе
           прерывания (Esc) — проверяется по ходу обучения (не реже раза в
           минуту), при срабатывании обучение прерывается, ничего не
           регистрируется в конфигурации, а созданный для "окна смысла"
           вспомогательный индекс (если был) удаляется. Возвращает (успех:
           bool, сообщение: str)."""
        error = self._unsupported_files_error(selected_files)
        if error:
            return False, error

        names = [display_names_by_file.get(f, os.path.basename(f)) for f in selected_files]
        display_name = " + ".join(names)
        if name_suffix:
            display_name = f"{display_name} ({name_suffix})"
        model_type = model_type or self.config_dict.get('vector_model_type', 'fasttext')
        display_key = self.compute_display_key(model_type, selected_files, display_names_by_file,
                                               name_suffix=name_suffix)

        if model_params is None:
            total_bytes = sum(os.path.getsize(f) for f in selected_files if os.path.exists(f))
            model_params = self.suggest_params(model_type, total_bytes)

        if progress_callback:
            progress_callback(0.1)

        associated_indices = None
        if model_type in CHUNK_BASED_MODEL_TYPES:
            semantic_window = semantic_window or {'mode': 'existing_index', 'params': {}}
            sentences, associated_indices, error = self.build_minilm_training_data(
                selected_files, semantic_window, display_key, append=False
            )
        else:
            sentences, error = self._build_training_sentences(selected_files)
        if error:
            return False, error

        if progress_callback:
            progress_callback(0.4)

        model, failure = self._fit_new_model(model_type, sentences, model_params, cancel_check,
                                             associated_indices, semantic_window)
        if failure:
            return False, failure

        if progress_callback:
            progress_callback(0.9)

        model_path = self._prepare_model_path(model_type, display_name, display_key)
        try:
            model.save(model_path)
        except Exception as e:
            return False, f"Ошибка сохранения модели на диск: {e}"

        self._register_model(display_key, model, model_type, model_path, model_params,
                             semantic_window, associated_indices)
        self._append_training_history(model, model_type, sentences, semantic_window, model_path,
                                      selected_files, display_names_by_file)

        if progress_callback:
            progress_callback(1.0)

        unit_word = "топиках" if model_type in CHUNK_BASED_MODEL_TYPES else "обучающих окнах"
        return True, f"Модель «{display_key}» обучена на {len(sentences)} {unit_word}."

    @staticmethod
    def _unsupported_files_error(selected_files, require_files=True):
        """Сообщение, если выбранные файлы не годятся для обучения (нет файлов, Excel), иначе None."""
        if require_files and not selected_files:
            return "Не выбрано ни одного файла."
        for f in selected_files:
            if f.lower().endswith('.xlsx'):
                return ("Обучение векторной модели поддерживается только для текстовых "
                        "книг (.txt/.docx) — Excel-файлы для этого не подходят.")
        return None

    def _fit_new_model(self, model_type, sentences, model_params, cancel_check, associated_indices, semantic_window):
        """Создаёт модель и обучает её. Возвращает (модель, None) или (None, сообщение об ошибке)."""
        try:
            model = create_vector_model(model_type)
            model.train(sentences, cancel_check=cancel_check, **model_params)
        except TrainingCancelled:
            self._cleanup_aux_index_on_cancel(model_type, associated_indices, semantic_window)
            return None, "Обучение прервано пользователем."
        except ImportError as e:
            return None, str(e)
        except Exception as e:
            return None, f"Ошибка обучения модели: {e}"
        return model, None

    def _free_model_path(self, model_path, display_key):
        """Путь файла модели, не занятый ДРУГОЙ зарегистрированной моделью. Названия вроде «Книга 1» и «Книга-1»
           дают одно безопасное имя, и вторая модель молча затирала бы файл первой (запись о первой продолжала
           бы указывать на файл с чужими данными) — поэтому к имени добавляется номер."""
        used = {entry[2] for key, entry in self.config_dict.get('vector_models', {}).items()
                if key != display_key and entry[2]}
        if model_path not in used:
            return model_path
        base, ext = os.path.splitext(model_path)
        number = 2
        while f"{base}_{number}{ext}" in used:
            number += 1
        return f"{base}_{number}{ext}"

    def _prepare_model_path(self, model_type, display_name, display_key):
        """Папка моделей (создаётся), путь файла новой модели и уборка файлов прежней модели с тем же ключом."""
        models_dir = self.config_dict.get('vector_models_dir', 'vector_models')
        os.makedirs(models_dir, exist_ok=True)
        # make_safe_index_name() уже транслитерирует кириллицу перед
        # очисткой — без этого разные кириллические названия книг (без
        # единой латинской буквы/цифры) схлопывались в одно и то же имя
        # файла "model", и модели незаметно затирали файлы друг друга на
        # диске (именно это и оказалось причиной "нет близких слов" сразу
        # у нескольких моделей одновременно).
        safe_base, _ = make_safe_index_name(display_name, 'manticore')
        file_prefix = MODEL_TYPE_PREFIXES.get(model_type, 'FT').lower()
        model_path = self._free_model_path(os.path.join(models_dir, f"{file_prefix}_{safe_base}.model"), display_key)

        # Если под этим же именем уже была модель (например, пользователь
        # создаёт "FT Библия" заново, забыв сначала удалить старую запись)
        # — подчищаем её старый файл на диске перед перезаписью в реестре,
        # а не оставляем его тихо висеть/путаться с новым.
        old_entry = self.config_dict.get('vector_models', {}).get(display_key)
        if old_entry:
            _old_index_name, _old_model_type, old_model_path = old_entry
            if old_model_path and old_model_path != model_path:
                for path in (old_model_path, self._history_path(old_model_path)):
                    try:
                        if path and os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        self.update_status(f"⚠️ Не удалось удалить старый файл модели {path}: {e}")
            self._loaded_models.pop(display_key, None)
        return model_path

    def _register_model(self, display_key, model, model_type, model_path, model_params, semantic_window, associated_indices):
        """Запись обученной модели в кеш и в конфигурацию (с сохранением конфигурации)."""
        self._loaded_models[display_key] = model
        # Третье поле раньше было именем вспомогательного индекса Manticore —
        # теперь модель им не пользуется (результаты выдаются через индексы,
        # отмеченные вместе с моделью), поле оставлено пустым для
        # совместимости формата на случай, если он понадобится будущим
        # типам моделей.
        self.config_dict.setdefault('vector_models', {})[display_key] = ('', model_type, model_path)
        self.config_dict.setdefault('vector_model_params', {})[display_key] = dict(model_params)
        if model_type in CHUNK_BASED_MODEL_TYPES and associated_indices is not None:
            sw_entry = {'mode': semantic_window.get('mode', 'existing_index'), 'indices': associated_indices}
            sw_entry.update(semantic_window.get('params', {}))
            self.config_dict.setdefault('vector_semantic_window', {})[display_key] = sw_entry
        save_config(self.config_dict)

    def _append_training_history(self, model, model_type, sentences, semantic_window, model_path,
                                 selected_files, display_names_by_file):
        if model_type in CHUNK_BASED_MODEL_TYPES:
            detailed_log = self._build_minilm_detailed_log(model, sentences, {
                'model_type': model_type,
                'semantic_window_mode': semantic_window.get('mode') if semantic_window else None,
                **(semantic_window.get('params', {}) if semantic_window else {}),
            })
        else:
            detailed_log = self._build_detailed_training_log(model, sentences, {
                'model_type': model_type,
                'vector_sentences_before': self.config_dict.get('vector_sentences_before', 7),
                'vector_sentences_after': self.config_dict.get('vector_sentences_after', 10),
            })
        self._append_history(model_path, "обучение", selected_files, display_names_by_file,
                             detailed_log=detailed_log)

    # ---------- Дообучение ----------
    def continue_train(self, display_key, selected_files, display_names_by_file,
                       cancel_check=None, progress_callback=None):
        display_key = self._normalize_key(display_key)
        entry = self.config_dict.get('vector_models', {}).get(display_key)
        if not entry:
            return False, f"Модель «{display_key}» не найдена в конфигурации."

        error = self._unsupported_files_error(selected_files, require_files=False)
        if error:
            return False, error

        model = self._get_model(display_key)
        if model is None:
            return False, f"Не удалось загрузить модель «{display_key}» для дообучения."

        _index_name, model_type, model_path = entry

        if progress_callback:
            progress_callback(0.1)

        sentences, mode, params, error = self._continue_training_data(display_key, model_type, selected_files)
        if error:
            return False, error

        if progress_callback:
            progress_callback(0.4)

        try:
            model.continue_train(sentences, cancel_check=cancel_check)
        except TrainingCancelled:
            # Новые блоки могли уже попасть во вспомогательный индекс
            # (append=True вставляет их ДО кодирования) — сам индекс не
            # трогаем (модель остаётся зарегистрированной и рабочей на
            # прежних данных), но предупреждаем: эти конкретные новые
            # блоки не закодированы и не участвуют в поиске, пока модель
            # не будет дообучена повторно.
            return False, ("Дообучение прервано пользователем. Модель осталась в прежнем "
                           "состоянии; чтобы всё же добавить эти файлы — запустите дообучение "
                           "ещё раз.")
        except Exception as e:
            return False, f"Ошибка дообучения модели: {e}"

        if progress_callback:
            progress_callback(0.9)

        try:
            model.save(model_path)
        except Exception as e:
            return False, f"Ошибка сохранения модели на диск: {e}"

        self._loaded_models[display_key] = model

        if model_type in CHUNK_BASED_MODEL_TYPES and mode == 'existing_index':
            self._merge_associated_indices(display_key, sentences)

        self._append_continue_history(model, model_type, sentences, mode, params, model_path,
                                      selected_files, display_names_by_file)

        if progress_callback:
            progress_callback(1.0)

        names = ", ".join(display_names_by_file.get(f, os.path.basename(f)) for f in selected_files)
        return True, f"Модель «{display_key}» дообучена на: {names}."

    def _continue_training_data(self, display_key, model_type, selected_files):
        """Данные для дообучения: (предложения/блоки, режим окна смысла, его параметры, ошибка). Режим и параметры —
           только для моделей уровня блоков (MiniLM), для остальных None."""
        if model_type not in CHUNK_BASED_MODEL_TYPES:
            sentences, error = self._build_training_sentences(selected_files)
            return sentences, None, None, error
        semantic_window = self.config_dict.get('vector_semantic_window', {}).get(
            display_key, {'mode': 'existing_index'}
        )
        mode = semantic_window.get('mode', 'existing_index')
        params = {k: v for k, v in semantic_window.items() if k not in ('mode', 'indices')}
        sentences, _new_indices, error = self.build_minilm_training_data(
            selected_files, {'mode': mode, 'params': params}, display_key, append=True
        )
        return sentences, mode, params, error

    def _merge_associated_indices(self, display_key, sections):
        """Для готового индекса при дообучении новыми файлами могли появиться и новые реальные индексы —
           дополняем список, не затирая уже сохранённый."""
        existing_list = self.config_dict.get('vector_semantic_window', {}).get(display_key, {}).get('indices', [])
        merged = sorted(set(existing_list) | set(s[0] for s in sections))
        sw_entry = {'mode': 'existing_index', 'indices': merged}
        self.config_dict.setdefault('vector_semantic_window', {})[display_key] = sw_entry
        save_config(self.config_dict)

    def _append_continue_history(self, model, model_type, sentences, mode, params, model_path,
                                 selected_files, display_names_by_file):
        if model_type in CHUNK_BASED_MODEL_TYPES:
            offset = len(model.embeddings) - len(sentences) if model.embeddings is not None else 0
            detailed_log = self._build_minilm_detailed_log(model, sentences, {
                'model_type': model_type,
                'semantic_window_mode': mode,
                **params,
            }, embedding_offset=offset)
        else:
            # Подробный лог (пары слов, векторы) осмыслен только для
            # word-embedding моделей вроде FastText — для MiniLM входные
            # данные это уже не окна слов, а целые топики, показывать их
            # тем же способом было бы бессмысленно.
            detailed_log = self._build_detailed_training_log(model, sentences, {
                'model_type': model_type,
                'vector_sentences_before': self.config_dict.get('vector_sentences_before', 7),
                'vector_sentences_after': self.config_dict.get('vector_sentences_after', 10),
            })
        self._append_history(model_path, "дообучение", selected_files, display_names_by_file,
                             detailed_log=detailed_log)

    # ---------- Удаление ----------
    def delete_model(self, display_key: str):
        """Удаляет зарегистрированную векторную модель: файл модели (и файл
           истории обучения) на диске, вспомогательный индекс Manticore
           (если он у неё был) и запись в конфигурации. Возвращает (успех:
           bool, сообщение: str). Ошибка на любом отдельном шаге не
           прерывает остальные — удаляем всё, что получается."""
        display_key = self._normalize_key(display_key)
        entry = self.config_dict.get('vector_models', {}).get(display_key)
        if not entry:
            return False, f"Модель «{display_key}» не найдена в конфигурации."

        index_name, _model_type, model_path = entry
        problems = []

        if index_name:
            try:
                self.engine.delete_index(index_name)
            except Exception as e:
                problems.append(f"индекс {index_name}: {e}")

        # Вспомогательный индекс "окна смысла" (режимы 2-4 у MiniLM,
        # имена начинаются с "model_") принадлежит только этой модели —
        # удаляем вместе с ней. Реальные файловые индексы (режим 1) не
        # трогаем — ими может пользоваться обычный поиск помимо модели.
        sw_entry = self.config_dict.get('vector_semantic_window', {}).get(display_key)
        print(f"🔍 delete_model(«{display_key}»): запись окна смысла = {sw_entry}")
        if sw_entry and sw_entry.get('mode') != 'existing_index':
            for idx_name in sw_entry.get('indices', []):
                print(f"🗑️ Удаляю вспомогательный индекс «{idx_name}»...")
                try:
                    ok = self.engine.delete_index(idx_name)
                    print(f"   Результат delete_index: {ok}")
                except Exception as e:
                    problems.append(f"вспомогательный индекс {idx_name}: {e}")
                    print(f"   Исключение: {e}")

        for path in (model_path, self._history_path(model_path) if model_path else None):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                problems.append(f"файл {path}: {e}")

        self._loaded_models.pop(display_key, None)
        self.config_dict.get('vector_models', {}).pop(display_key, None)
        self.config_dict.get('vector_model_params', {}).pop(display_key, None)
        self.config_dict.get('vector_semantic_window', {}).pop(display_key, None)
        save_config(self.config_dict)

        if problems:
            return False, f"Модель «{display_key}» удалена из списка, но с ошибками: " + "; ".join(problems)
        return True, f"Модель «{display_key}» удалена."

    # ---------- Использование при поиске ----------
    def _get_model(self, display_key: str):
        display_key = self._normalize_key(display_key)
        if display_key in self._loaded_models:
            return self._loaded_models[display_key]
        lock = self._model_locks.setdefault(display_key, threading.Lock())
        with lock:
            # Могла успеть загрузиться, пока мы ждали лок (например,
            # параллельно шла фоновая предзагрузка) — тогда просто отдаём
            # уже готовый результат, не читая файл модели повторно.
            if display_key in self._loaded_models:
                return self._loaded_models[display_key]
            entry = self.config_dict.get('vector_models', {}).get(display_key)
            if not entry:
                print(f"❌ Модель «{display_key}» отсутствует в конфигурации "
                     f"(зарегистрированы: {list(self.config_dict.get('vector_models', {}).keys())})")
                return None
            _index_name, model_type, model_path = entry
            try:
                model = create_vector_model(model_type)
                model.load(model_path)
            except Exception as e:
                self.update_status(f"❌ Не удалось загрузить векторную модель «{display_key}»: {e}")
                print(f"❌ Не удалось загрузить векторную модель «{display_key}» "
                     f"(файл: {model_path}, тип: {model_type}): {type(e).__name__}: {e}")
                return None
            self._loaded_models[display_key] = model
            return model

    def preload_model_async(self, display_key: str):
        """Запускает загрузку модели в фоновом потоке заранее — вызывается,
           как только пользователь отмечает её галочкой в списке индексов
           (см. IndexManager._on_selection_changed), не дожидаясь первого
           реального поиска. Загрузка с диска — единственная действительно
           медленная часть векторного поиска; если она успеет завершиться
           до того, как пользователь наберёт запрос и нажмёт поиск —
           заметного подвисания на первом запросе не будет вовсе.

           Сам фоновый поток здесь НИЧЕГО не обновляет в интерфейсе
           напрямую (даже через root.after — на практике это оказалось
           ненадёжным: такие вызовы, случалось, "застревали" в очереди
           Tkinter, пока что-то ещё — например, ввод в поле запроса — не
           "будило" цикл событий). Вместо этого поток только выставляет
           отметку "идёт загрузка" (is_preloading) и кладёт модель в кеш по
           готовности; отслеживание готовности и обновление интерфейса
           (полоска, статус) — на стороне вызывающего, через периодический
           опрос из главного потока (см. ui/app_window.py,
           _poll_vector_preload) — это единственный вариант, который
           поведёт себя предсказуемо."""
        display_key = self._normalize_key(display_key)
        if display_key in self._loaded_models:
            return
        if display_key in self._preloading:
            return
        self._preloading.add(display_key)

        def _worker():
            try:
                self._get_model(display_key)
            finally:
                self._preloading.discard(display_key)

        threading.Thread(target=_worker, daemon=True).start()

    def is_preloading(self, display_key: str) -> bool:
        return self._normalize_key(display_key) in self._preloading

    def get_model_type(self, display_key: str):
        """Тип зарегистрированной модели ('fasttext'/'minilm') — нужно
           SearchController, чтобы выбрать правильный способ поиска: список
           близких слов (FastText) или прямое сравнение векторов топиков
           (MiniLM, см. search_semantic). None, если модель не найдена."""
        display_key = self._normalize_key(display_key)
        entry = self.config_dict.get('vector_models', {}).get(display_key)
        return entry[1] if entry else None

    def get_associated_indices(self, display_key: str) -> list:
        """Индекс(ы), по которым модель ищет — определяется при обучении
           ("окно смысла", см. build_minilm_training_data) и не требует
           отдельной отметки галочкой в списке индексов при поиске: для
           готового индекса (режим 1) это реальные файловые индексы, для
           остальных режимов — единственный вспомогательный индекс
           "model_...". Пустой список, если для модели ничего не
           сохранено (например, модель типа, для которого это не
           применимо, как FastText)."""
        display_key = self._normalize_key(display_key)
        entry = self.config_dict.get('vector_semantic_window', {}).get(display_key)
        return list(entry.get('indices', [])) if entry else []

    def get_auxiliary_indices(self) -> set:
        """Все вспомогательные индексы "окон смысла" (режимы 2-4, имена
           начинаются с "model_") по ВСЕМ моделям сразу — эти индексы
           принадлежат только своей модели и не должны показываться в
           общем списке индексов как обычные, отдельно выбираемые записи
           (иначе их можно случайно выбрать и удалить отдельно от модели —
           тогда при удалении самой модели удаление того же индекса
           повторится и упадёт с ошибкой "unknown table"). Индексы режима
           1 (готовый индекс) сюда не входят — они настоящие, независимые
           от модели файловые индексы."""
        result = set()
        for entry in self.config_dict.get('vector_semantic_window', {}).values():
            if entry.get('mode') != 'existing_index':
                result.update(entry.get('indices', []))
        return result

    def search_semantic(self, display_key: str, query_text: str, topn: int = None):
        """Прямой семантический поиск (MiniLM) — возвращает список
           (index_name, rowid, близость), отсортированный по убыванию
           близости. Аналог get_neighbors(), но для моделей уровня целых
           предложений, у которых нет смысла в "близких словах"."""
        model = self._get_model(display_key)
        if model is None:
            return []
        topn = topn or self.config_dict.get('vector_model_topn', 15)
        try:
            return model.search_passages(query_text, topn=topn)
        except NotImplementedError as e:
            self.update_status(f"❌ {e}")
            return []
        except Exception as e:
            self.update_status(f"❌ Ошибка семантического поиска: {e}")
            print(f"❌ Ошибка search_passages() для «{self._normalize_key(display_key)}»: "
                 f"{type(e).__name__}: {e}")
            return []

    def get_word_vectors(self, display_key: str, words) -> dict:
        """Возвращает {слово: вектор} для списка слов — для визуализации
           (кнопка "3D/2D"). Слова, для которых вектор не удалось получить
           (например, пустой корпус), просто пропускаются, а не прерывают
           весь запрос — визуализация покажет то, что получилось."""
        model = self._get_model(display_key)
        if model is None:
            return {}
        result = {}
        for word in words:
            try:
                result[word] = model.get_vector(word)
            except Exception:
                continue
        return result

    def get_vocabulary_vectors(self, display_key: str, max_words: int = 3000,
                              min_word_length: int = 3, min_frequency: int = 2,
                              key_words=None) -> dict:
        """Возвращает {слово: вектор} для (части) словаря модели целиком —
           не соседей одного запроса, а образец всего пространства сразу.
           Нужно для поиска самых "насыщенных понятиями" областей (кнопка
           "3D/2D" -> "Сгущения понятий"). Отфильтровывает короткие слова
           (обычно служебные — предлоги, союзы) и слишком редкие (min_frequency
           — модель мало что успела о них "понять", они просто шумят). Если
           словарь после отсева всё ещё больше max_words — берёт выборку из
           САМЫХ ЧАСТЫХ слов (не случайную): у них векторы обучены надёжнее
           (больше примеров употребления), и анализ на них честнее, а заодно
           ограничивает объём попарных сравнений (N² операций) разумным
           пределом для словарей в десятки тысяч слов.

           key_words — слова словаря ключевых понятий (кнопка "КП"): тогда в
           выборку попадают ТОЛЬКО слова модели, совпадающие с ними или являющиеся
           их вариациями (см. utils/key_concepts.py). Отсев по длине и редкости
           при этом не применяется — эти слова выбрал сам пользователь, и
           короткое или редкое ключевое слово не должно пропадать из картины.
           None — обычная выборка."""
        model = self._get_model(display_key)
        if model is None or not hasattr(model, 'get_vocabulary_words'):
            return {}
        words = model.get_vocabulary_words()
        candidates = []
        if key_words is not None:
            for word in expand_dictionary(key_words, words):
                candidates.append((word, model.get_word_frequency(word)))
        else:
            for word in words:
                if len(word) < min_word_length:
                    continue
                freq = model.get_word_frequency(word)
                if freq < min_frequency:
                    continue
                candidates.append((word, freq))
        candidates.sort(key=lambda x: -x[1])
        candidates = candidates[:max_words]

        result = {}
        for word, _freq in candidates:
            try:
                result[word] = model.get_vector(word)
            except Exception:
                continue
        return result

    def get_neighbors(self, display_key: str, query_word: str, topn: int = None):
        """Возвращает список (слово, близость) из модели — для левого окна
           и для построения расширенного запроса к обычному индексу."""
        normalized_key = self._normalize_key(display_key)
        model = self._get_model(display_key)
        if model is None:
            # Точная причина (отсутствует в конфигурации / не удалось
            # загрузить файл, и почему) печатается внутри _get_model —
            # здесь дублировать не нужно.
            return []

        topn = topn or self.config_dict.get('vector_model_topn', 15)
        query_word = query_word.strip().lower()
        if not query_word:
            return []

        try:
            neighbors = model.most_similar(query_word, topn=topn)
        except Exception as e:
            self.update_status(f"❌ Ошибка векторного поиска: {e}")
            print(f"❌ Ошибка most_similar() для «{normalized_key}», слово «{query_word}»: {e}")
            return []

        if not neighbors:
            print(f"⚠️ Модель «{normalized_key}» не нашла соседей для слова «{query_word}» "
                 f"(most_similar вернул пустой список — слова нет в словаре модели, "
                 f"и даже через n-граммы вектор не построился)")
        return neighbors

    def get_neighbors_deduplicated(self, display_key: str, query_word: str, target_count: int = None):
        """То же самое, что get_neighbors(), но без явных словоформ одного
           и того же слова (например, "равновесие"/"равновесием"/
           "равновесию") — оставляет по одному, самому рейтинговому
           представителю на такую группу, и дозапрашивает у модели БОЛЬШЕ
           слов (пока хватает попыток — на случай, если словоформ много),
           чтобы после отсеивания всё равно набралось target_count (по
           умолчанию — vector_model_topn) уникальных слов. Используется
           кнопкой "−В/+В" у окна "Совпадения" (см. ui/app_window.py)."""
        target_count = target_count or self.config_dict.get('vector_model_topn', 15)
        fetch_count = target_count
        kept = []
        for _attempt in range(5):
            raw = self.get_neighbors(display_key, query_word, topn=fetch_count)
            kept, _removed = dedupe_word_variations(raw)
            if len(kept) >= target_count or len(raw) < fetch_count:
                break
            fetch_count *= 2
        return kept[:target_count]
