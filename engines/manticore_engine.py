import pymysql
import os
import subprocess
import time
import sys
from typing import List, Dict, Any, Optional, Callable
from .base_engine import SearchEngine
from utils.text_processing import split_into_sections_by_separator
from utils.query_parser import parse_query_words, compute_matches, compute_matches_unique

# Сообщения о том, что Manticore не удалось запустить. Текст знает про searchd.exe, поэтому живёт здесь, у движка;
# показывает его тот, у кого есть окно (см. on_startup_failure) — сам движок окон не создаёт.
STARTUP_FAILURE_TITLE = "Manticore не запускается"
STARTUP_FAILURE_MESSAGE = (
    "Не удалось запустить поисковый движок Manticore, даже после попытки "
    "автоматического восстановления (принудительное завершение процесса "
    "searchd.exe и очистка файла searchd.pid).\n\n"
    "Пожалуйста, перезапустите Синева+ — после этой очистки повторный "
    "запуск обычно помогает.\n\n"
    "Если проблема повторится, проверьте вручную через Диспетчер задач, "
    "не остался ли запущенным процесс searchd.exe."
)
MISSING_SEARCHD_TITLE = "Manticore не найден"
MISSING_SEARCHD_MESSAGE = (
    "Не найден файл поискового движка Manticore:\n{path}\n\n"
    "Проверьте, что папка Manticore лежит рядом с программой и не повреждена."
)
# После неудачного запуска (с восстановлением) повторно пробовать столько секунд не будем: сразу после создания
# движка программа вызывает connect() ещё раз, и без этого вся процедура (снятие процесса, 10 попыток по 0,5 с)
# и окно с ошибкой повторялись бы.
RESTART_COOLDOWN_SECONDS = 60


class ManticoreEngine(SearchEngine):
    # Значения по умолчанию на уровне класса — работают и у объекта, созданного без __init__.
    on_startup_failure = None       # вызывается как on_startup_failure(заголовок, текст) при неудачном запуске
    _last_start_failure = None      # время последней неудачной попытки запуска (None — неудач не было)

    def __init__(self, config: dict, on_startup_failure=None):
        self.host = config.get('host', 'localhost')
        self.port = int(config.get('port', 9306))
        self.index = config.get('index', 'documents')
        self.default_separator = config.get('default_separator', 'N1000')
        self._current_index = None
        self.conn = None
        self.cursor = None
        self.engine_type = "manticore"
        self.on_startup_failure = on_startup_failure
        self._current_file_name = None
        self.search_limit = config.get('manticore_search_limit', 200)   # <-- новый атрибут

        if getattr(sys, 'frozen', False):
            self.project_root = os.path.dirname(sys.executable)
            # Manticore лежит рядом с exe (на уровне DB); если там его нет — берём из _internal.
            self.internal_root = self.project_root
            if not os.path.isfile(os.path.join(self.project_root, 'Manticore', 'bin', 'searchd.exe')):
                self.internal_root = getattr(sys, '_MEIPASS', self.project_root)
        else:
            self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.internal_root = self.project_root

        self.manticore_bin = os.path.join(self.internal_root, 'Manticore', 'bin')
        self.conf_dir = os.path.join(self.project_root, 'Manticore', 'bin')
        self.manticore_log = os.path.join(self.project_root, 'Manticore', 'log')
        self.data_dir = os.path.join(self.project_root, 'indicies_mc')

        self.conf_path = os.path.join(self.conf_dir, 'manticore.conf')
        self.pid_file = os.path.join(self.conf_dir, 'searchd.pid')
        self.searchd_exe = os.path.join(self.manticore_bin, 'searchd.exe')

        self._started_by_us = False
        self._prepare_environment()

        connect_start = time.time()
        self.connect()
        connect_time = (time.time() - connect_start) * 1000
        print(f"⏱ Подключение к Manticore: {connect_time:.1f} мс")

    def _prepare_environment(self):
        os.makedirs(self.conf_dir, exist_ok=True)
        os.makedirs(self.manticore_log, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        if not os.path.exists(self.conf_path):
            conf_content = f"""
searchd {{
    listen = {self.host}:{self.port}:mysql
    listen = {self.host}:9308:http
    log = Manticore/log/searchd.log
    query_log = Manticore/log/query.log
    pid_file = Manticore/bin/searchd.pid
    data_dir = indicies_mc
    binlog_path = indicies_mc
}}
"""
            with open(self.conf_path, 'w', encoding='utf-8') as f:
                f.write(conf_content)
            print(f"✅ Создан конфиг Manticore: {self.conf_path}")

    def _win_path(self, path: str) -> str:
        return path.replace('/', '\\')

    def _is_running(self) -> bool:
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user='',
                password='',
                charset='utf8mb4',
                autocommit=True,
                connect_timeout=1
            )
            conn.close()
            return True
        except Exception:
            return False

    def _recently_failed(self) -> bool:
        failed_at = self._last_start_failure
        return failed_at is not None and time.time() - failed_at < RESTART_COOLDOWN_SECONDS

    def _start_manticore(self) -> bool:
        if self._recently_failed():
            print("⏭ Недавняя попытка запустить Manticore (с восстановлением) не удалась — "
                  "повторно не пробуем")
            return False

        if not os.path.exists(self.searchd_exe):
            print(f"❌ Не найден {self.searchd_exe}")
            self._last_start_failure = time.time()
            self._notify_startup_failure(MISSING_SEARCHD_TITLE, MISSING_SEARCHD_MESSAGE.format(path=self.searchd_exe))
            return False

        if self._is_running():
            print("✅ Manticore уже запущен")
            self._last_start_failure = None
            return True

        if self._try_launch_searchd():
            self._last_start_failure = None
            return True

        # Не запустился с первой попытки. Частая причина после аварийного
        # завершения компьютера (например, отключение питания) — "зависший"
        # searchd.pid с номером процесса, которого уже не существует: сам
        # searchd.exe из-за этого может отказаться запускаться повторно, либо
        # где-то мог остаться настоящий процесс-сирота. Пробуем восстановиться
        # автоматически: принудительно снимаем возможный процесс searchd.exe и
        # очищаем pid-файл, затем пробуем запустить ещё раз.
        print("⚠️ Manticore не запустился с первой попытки — пробуем восстановление "
              "(снятие процесса searchd.exe и очистка searchd.pid)...")
        self._kill_existing_searchd()
        self._clear_stale_pid_file()
        time.sleep(1)

        if self._try_launch_searchd():
            print("✅ Manticore запущен после автоматического восстановления")
            self._last_start_failure = None
            return True

        print("❌ Не удалось запустить Manticore даже после восстановления")
        self._last_start_failure = time.time()
        self._notify_startup_failure(STARTUP_FAILURE_TITLE, STARTUP_FAILURE_MESSAGE)
        return False

    def _try_launch_searchd(self) -> bool:
        print(f"🚀 Запуск Manticore из {self.searchd_exe}")
        start_time = time.time()
        try:
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            subprocess.Popen(
                [self.searchd_exe, '--config', self.conf_path],
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            for attempt in range(10):
                time.sleep(0.5)
                if self._is_running():
                    elapsed = (time.time() - start_time) * 1000
                    print(f"✅ Manticore успешно запущен за {elapsed:.1f} мс")
                    self._started_by_us = True
                    return True
            print("❌ Не удалось запустить Manticore (таймаут)")
            return False
        except Exception as e:
            print(f"❌ Ошибка запуска Manticore: {e}")
            return False

    def _kill_existing_searchd(self):
        """Принудительно завершает все процессы searchd.exe (аналог снятия
           задачи через Диспетчер задач) — только Windows, только на этот
           случай восстановления после сбоя."""
        if sys.platform != 'win32':
            return
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'searchd.exe'],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print("🛑 Процесс searchd.exe принудительно завершён (если был запущен)")
        except Exception as e:
            print(f"⚠️ Не удалось принудительно завершить searchd.exe: {e}")

    def _clear_stale_pid_file(self):
        """Удаляет устаревший searchd.pid, оставшийся после аварийного
           завершения компьютера — с номером процесса, которого уже не
           существует, но который иначе может мешать повторному запуску."""
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
                print(f"🧹 Удалён устаревший файл {self.pid_file}")
        except Exception as e:
            print(f"⚠️ Не удалось удалить {self.pid_file}: {e}")

    def _notify_startup_failure(self, title, message):
        """Сообщает, что Manticore запустить не удалось. Движок сам окон не создаёт: сообщение отдаётся тому, кто
           его создал (on_startup_failure(заголовок, текст) — окно программы показывает его пользователю). Без
           обработчика сообщение только печатается."""
        handler = self.on_startup_failure
        if handler is None:
            print(f"❌ {title}: {message}")
            return
        try:
            handler(title, message)
        except Exception as e:
            print(f"⚠️ Не удалось показать сообщение об ошибке запуска: {e}")

    def _stop_manticore(self):
        if not self._started_by_us:
            return
        print("🛑 Остановка Manticore...")
        try:
            subprocess.run(
                [self.searchd_exe, '--config', self.conf_path, '--stopwait'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            print("✅ Manticore остановлен")
        except Exception as e:
            print(f"⚠️ Ошибка при остановке Manticore: {e}")

    def connect(self, source: str = None) -> bool:
        if self.conn is not None:
            try:
                self.cursor.execute("SELECT 1")
                self.cursor.fetchone()
                if source:
                    self._current_index = source
                    self.index = source
                else:
                    self._current_index = self.index
                return True
            except Exception:
                self.conn = None
                self.cursor = None

        if not self._is_running():
            if not self._start_manticore():
                return False

        try:
            self.conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user='',
                password='',
                charset='utf8mb4',
                autocommit=True
            )
            self.cursor = self.conn.cursor()
            if source:
                self._current_index = source
                self.index = source
            else:
                self._current_index = self.index
            return True
        except Exception as e:
            print(f"❌ Ошибка подключения к Manticore: {e}")
            return False

    def close(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn:
            self.conn.close()
            self.conn = None
        self._stop_manticore()
        self._current_index = None

    def _escape_ident(self, name: str) -> str:
        if not name:
            return '``'
        name = name.replace('`', '``')
        return f"`{name}`"

    def _escape_string(self, s: str) -> str:
        if s is None:
            return ''
        if self.conn:
            esc = getattr(self.conn, 'escape_string', None)
            if esc is None:   # PyMySQL >= 1.1: метода у соединения нет
                from pymysql.converters import escape_string as esc
            return esc(s)
        return s.replace("'", "''").replace("\\", "\\\\")

    def list_indices(self) -> List[str]:
        if not self.conn:
            return []
        try:
            self.cursor.execute("SHOW TABLES")
            rows = self.cursor.fetchall()
            return [row[0] for row in rows if not row[0].startswith('.')]
        except Exception as e:
            print(f"Ошибка получения списка индексов: {e}")
            return []

    def select_index(self, name: str) -> bool:
        indices = self.list_indices()
        if name in indices:
            self.index = name
            self._current_index = name
            return True
        return False

    def _find_existing_index(self, name: str):
        """Настоящее имя индекса с таким названием (сравнение без учёта регистра — см. пояснение в
           utils.text_processing.make_safe_index_name про то, почему это важно) или None."""
        return next((idx for idx in self.list_indices() if idx.lower() == name.lower()), None)

    def _create_table(self, name: str):
        """Создаёт таблицу индекса (RT, инфиксы от 2 символов) — общая схема для обычных и вспомогательных индексов."""
        safe_name = self._escape_ident(name)
        sql = f"""
        CREATE TABLE {safe_name} (
            id bigint,
            section_id int,
            section_text text,
            file_name text,
            position text
        ) type='rt' charset_table='non_cjk' min_infix_len='2'
        """
        self.cursor.execute(sql)

    def create_index(self, name: str):
        if not self.conn:
            raise Exception("Нет соединения с Manticore")

        start_time = time.time()
        print(f"🔨 Создание индекса Manticore: {name}")

        existing_match = self._find_existing_index(name)
        if existing_match:
            print(f"   ⚠️ Индекс {name} уже существует, удаляем...")
            self.cursor.execute(f"DROP TABLE {self._escape_ident(existing_match)}")

        try:
            self._create_table(name)
            self.index = name
            self._current_index = name
            elapsed = (time.time() - start_time) * 1000
            print(f"   ✅ Индекс {name} создан за {elapsed:.1f} мс")
        except Exception as e:
            print(f"   ❌ Ошибка создания индекса: {e}")
            raise

    def index_text(self, text: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        if not self._current_index:
            raise Exception("Индекс не выбран.")

        if separator is None:
            separator = self.default_separator

        start_time = time.time()
        print(f"🔨 Индексация текста в Manticore, разделитель: {separator}")

        # Разбиение на топики
        split_start = time.time()
        lines = text.splitlines(keepends=False)
        sections = split_into_sections_by_separator(lines, separator)
        split_time = (time.time() - split_start) * 1000
        print(f"   ⏱ Разбиение на топики: {len(sections)} секций за {split_time:.1f} мс")

        if not sections:
            print("⚠️ Не найдено топиков для индексации.")
            return 0

        total = len(sections)
        if not self._current_file_name:
            self._current_file_name = 'indexed_file'

        insert_start = time.time()
        inserted = self._insert_sections(sections, self._escape_ident(self._current_index),
                                         self._current_file_name, progress_callback)

        insert_time = (time.time() - insert_start) * 1000
        print(f"   ⏱ Вставка {inserted} записей за {insert_time:.1f} мс")

        if progress_callback:
            progress_callback(total, total)

        total_time = (time.time() - start_time) * 1000
        print(f"   ✅ Индексация завершена: {total} записей за {total_time:.1f} мс")
        print(f"      - Разбиение: {split_time:.1f} мс")
        print(f"      - Вставка: {insert_time:.1f} мс")

        return inserted

    @staticmethod
    def _insert_sql(safe_index: str, values: list) -> str:
        return f"INSERT INTO {safe_index} (id, section_id, section_text, file_name, position) VALUES {', '.join(values)}"

    def _row_values(self, section_index: int, section: dict, file_name: str) -> str:
        """Одна строка VALUES (...) для секции: id и section_id — номер секции с 1, позиция — строка начала."""
        content = '\n'.join(section['lines'])
        position = str(section.get('start_line', 0))
        row_id = section_index + 1
        return f"({row_id}, {row_id}, '{self._escape_string(content)}', '{self._escape_string(file_name)}', '{position}')"

    def _insert_sections(self, sections, safe_index, file_name, progress_callback) -> int:
        """Записывает секции пакетами по 200 (без автофиксации — так быстрее). Пакет, который сервер не принял,
           досылается по одной строке, а запись ПРОДОЛЖАЕТСЯ со следующего пакета (раньше после такой досылки цикл
           обрывался, и вся остальная книга молча терялась). Автофиксация возвращается всегда, в том числе при сбое."""
        total = len(sections)
        batch_size = 200  # количество записей в одном пакете
        inserted = 0
        self.conn.autocommit(False)
        try:
            for i in range(0, total, batch_size):
                batch_end = min(i + batch_size, total)
                values = [self._row_values(j, sections[j], file_name) for j in range(i, batch_end)]
                try:
                    self.cursor.execute(self._insert_sql(safe_index, values))
                    inserted += (batch_end - i)
                    if progress_callback and i % 100 == 0:
                        progress_callback(i + (batch_end - i), total)
                except Exception as e:
                    print(f"   ⚠️ Ошибка вставки пакета {i // batch_size + 1}: {e}")
                    # Пытаемся вставить по одному (fallback) — только этот пакет
                    print("   🔄 Повторная вставка по одному...")
                    inserted += self._insert_one_by_one(sections, i, batch_end, safe_index, file_name,
                                                        total, progress_callback)
            self.conn.commit()
        finally:
            self.conn.autocommit(True)
        return inserted

    def _insert_one_by_one(self, sections, start, end, safe_index, file_name, total, progress_callback) -> int:
        inserted = 0
        for j in range(start, end):
            sql_single = self._insert_sql(safe_index, [self._row_values(j, sections[j], file_name)])
            try:
                self.cursor.execute(sql_single)
                inserted += 1
                if progress_callback and j % 100 == 0:
                    progress_callback(j + 1, total)
            except Exception as e2:
                print(f"   ❌ Ошибка вставки записи {j + 1}: {e2}")
        return inserted

    def index_file(self, file_path: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self._current_file_name = os.path.basename(file_path)
        print(f"📄 Индексация файла в Manticore: {self._current_file_name}")

        encodings = ['utf-8', 'cp1251', 'latin-1', 'koi8-r']
        text = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    text = f.read()
                print(f"   ✅ Кодировка: {enc}, размер: {len(text)} символов")
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise Exception("Не удалось прочитать файл ни в одной из поддерживаемых кодировок.")
        result = self.index_text(text, separator, progress_callback)
        self._current_file_name = None
        return result

    def get_section_text(self, rowid: int) -> Optional[str]:
        if not self._current_index:
            return None
        safe_index = self._escape_ident(self._current_index)
        sql = f"SELECT section_text FROM {safe_index} WHERE id = {rowid}"
        try:
            self.cursor.execute(sql)
            row = self.cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print(f"Ошибка получения текста топика: {e}")
            return None

    def get_section_info(self, rowid: int) -> Dict[str, Any]:
        if not self._current_index:
            return None
        return self.get_section_info_from(self._current_index, rowid)

    def get_section_info_from(self, index_name: str, rowid: int) -> Optional[Dict[str, Any]]:
        """То же самое, что get_section_info(), но по явно указанному
           индексу, а не по self._current_index — нужно для векторного
           поиска через MiniLM, где результаты могут приходить сразу из
           нескольких отмеченных вместе с моделью индексов."""
        safe_index = self._escape_ident(index_name)
        sql = f"SELECT section_text, file_name, position FROM {safe_index} WHERE id = {rowid}"
        try:
            self.cursor.execute(sql)
            row = self.cursor.fetchone()
            if row:
                return {
                    'text': row[0],
                    'file_name': row[1] or '',
                    'position': row[2] or '0'
                }
        except Exception as e:
            print(f"Ошибка получения информации о топике: {e}")
        return None

    def get_all_sections(self, index_name: str, batch_size: int = 500):
        """Возвращает ВСЕ топики индекса целиком: список (rowid, text,
           file_name) — постранично (id > последний, по возрастанию), а не
           одним SELECT. batch_size ЗАВЕДОМО меньше стандартного предела
           Manticore на выдачу за один запрос (max_matches, обычно 1000) —
           если запросить LIMIT больше этого предела, сервер тихо обрежет
           ответ до 1000 строк независимо от LIMIT. Поэтому конец данных
           определяется ТОЛЬКО по пустой странице, а не по «строк меньше
           batch_size» (иначе при размере пакета выше предела сервера
           чтение останавливалось бы на первой тысяче — ровно так терялись
           все топики книги сверх первой тысячи). Нужно для обучения
           векторной модели MiniLM: она кодирует уже готовые, существующие
           топики индекса, а не режет текст заново сама (см.
           services/vector_model_manager.py)."""
        safe_index = self._escape_ident(index_name)
        results = []
        last_id = 0
        while True:
            sql = (f"SELECT id, section_text, file_name FROM {safe_index} "
                  f"WHERE id > {last_id} ORDER BY id ASC LIMIT {batch_size}")
            try:
                self.cursor.execute(sql)
                rows = self.cursor.fetchall()
            except Exception as e:
                print(f"Ошибка получения топиков индекса {index_name}: {e}")
                break
            if not rows:
                break
            for row in rows:
                results.append((row[0], row[1], row[2] or ''))
            last_id = rows[-1][0]
        return results

    def ensure_chunk_index(self, index_name: str, drop_if_exists: bool = False) -> bool:
        """Создаёт вспомогательный индекс для уже готовых кусков текста
           (см. insert_chunks) — не трогает self._current_index/self.index,
           в отличие от create_index(), чтобы не путать состояние обычной,
           видимой пользователю индексации, пока идёт обучение модели
           "окнами смысла" (MiniLM). Возвращает True, если индекс СОЗДАН
           заново (drop_if_exists=True всегда пересоздаёт; иначе — только
           если его ещё не было; если уже существует и drop_if_exists=False
           — просто ничего не делает и возвращает False, для дообучения,
           где нужно ДОБАВИТЬ блоки к уже существующему индексу)."""
        if not self.conn:
            raise Exception("Нет соединения с Manticore")
        existing = self._find_existing_index(index_name)
        if existing:
            if not drop_if_exists:
                return False
            self.cursor.execute(f"DROP TABLE {self._escape_ident(existing)}")
        self._create_table(index_name)
        return True

    def insert_chunks(self, index_name: str, chunks, file_name: str) -> int:
        """Вставляет уже готовые куски текста (список строк) в
           существующий индекс — напрямую, без разбиения через separator
           (в отличие от index_text()). Продолжает нумерацию id с текущего
           максимума в индексе — чтобы дообучение ДОБАВЛЯЛО блоки, не
           перезаписывая уже вставленные ранее. Нужно для вспомогательных
           индексов "окон смысла" MiniLM (см.
           VectorModelManager._build_minilm_semantic_chunks)."""
        if not self.conn:
            raise Exception("Нет соединения с Manticore")
        if not chunks:
            return 0
        safe_index = self._escape_ident(index_name)
        try:
            self.cursor.execute(f"SELECT MAX(id) FROM {safe_index}")
            row = self.cursor.fetchone()
            next_id = (row[0] or 0) + 1
        except Exception:
            next_id = 1

        self.conn.autocommit(False)
        total = len(chunks)
        batch_size = 200
        inserted = 0
        escaped_file_name = self._escape_string(file_name)
        try:
            for i in range(0, total, batch_size):
                batch = chunks[i:i + batch_size]
                values = []
                for j, text in enumerate(batch):
                    row_id = next_id + i + j
                    escaped_content = self._escape_string(text)
                    values.append(f"({row_id}, {row_id}, '{escaped_content}', '{escaped_file_name}', '0')")
                sql = (f"INSERT INTO {safe_index} (id, section_id, section_text, file_name, position) "
                      f"VALUES {', '.join(values)}")
                self.cursor.execute(sql)
                inserted += len(batch)
            self.conn.commit()
        finally:
            self.conn.autocommit(True)
        return inserted

    def delete_index(self, name: str) -> bool:
        if not self.conn:
            return False
        try:
            start_time = time.time()
            self.cursor.execute(f"DROP TABLE {self._escape_ident(name)}")
            if self._current_index == name:
                self._current_index = None
                self.index = None
            elapsed = (time.time() - start_time) * 1000
            print(f"🗑️ Индекс {name} удалён за {elapsed:.1f} мс")
            return True
        except Exception as e:
            print(f"Ошибка удаления индекса {name}: {e}")
            return False

    @staticmethod
    def _match_expression(query_words_info) -> str:
        """Выражение для MATCH: слова запроса через « | »; слово из двух и более букв — с инфиксом *слово*."""
        match_terms = []
        for word, _, _ in query_words_info:
            if len(word) >= 2:
                match_terms.append(f"*{word}*")
            else:
                match_terms.append(word)
        return ' | '.join(match_terms)

    def search(self, query: str, indices: Optional[List[str]] = None,
               min_word_length: int = 3, unique_word_rating: bool = False) -> List[Dict[str, Any]]:
        if not self._current_index and not indices:
            return []

        if indices is None:
            indices = [self._current_index]
        else:
            indices = [idx for idx in indices if idx]

        if not indices:
            return []

        start_time = time.time()
        query_words_info = parse_query_words(query, min_word_length=min_word_length)
        if not query_words_info:
            return []

        safe_indices = [self._escape_ident(idx) for idx in indices]
        from_clause = ', '.join(safe_indices)
        match_query = self._match_expression(query_words_info)

        # Используем self.search_limit вместо жёсткого 200
        sql = f"""
        SELECT id, section_text, file_name, position, WEIGHT() as weight
        FROM {from_clause}
        WHERE MATCH('@(section_text) {match_query}')
        LIMIT {self.search_limit}     
        OPTION ranker=bm25, field_weights=(section_text=10)
        """

        try:
            query_start = time.time()
            self.cursor.execute(sql)
            rows = self.cursor.fetchall()
            query_time = (time.time() - query_start) * 1000
            print(f"🔍 Поиск в Manticore: {len(rows)} результатов за {query_time:.1f} мс")
        except Exception as e:
            print(f"Ошибка поиска: {e}")
            return []

        if not rows:
            return []

        match_start = time.time()
        results = self._rate_rows(rows, query_words_info, unique_word_rating)
        match_time = (time.time() - match_start) * 1000

        total_time = (time.time() - start_time) * 1000
        print(f"⏱ Поиск занял {total_time:.1f} мс (SQL: {query_time:.1f}, Совпадения: {match_time:.1f})")

        return results

    @staticmethod
    def _rate_rows(rows, query_words_info, unique_word_rating: bool) -> List[Dict[str, Any]]:
        """Строгий отбор и рейтинг ответа сервера: MATCH с инфиксами шире, чем правила программы (границы слова,
           минимальная длина, «слово с начала»), поэтому каждая строка перепроверяется compute_matches."""
        results = []
        for row in rows:
            rowid = row[0]
            content = row[1]
            file_name = row[2] if len(row) > 2 else ''
            position = row[3] if len(row) > 3 else '0'

            meta = compute_matches_unique(content, query_words_info) if unique_word_rating \
                else compute_matches(content, query_words_info)
            if meta is None:
                continue
            results.append({
                'rowid': rowid,
                'content': content,
                'meta': meta,
                'file_name': file_name,
                'position': position
            })
        return results