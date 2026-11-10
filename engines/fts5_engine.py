import sqlite3
import os
import re
import time
from typing import List, Dict, Any, Optional, Callable
from .base_engine import SearchEngine
from utils.text_processing import split_into_sections_by_separator, log_sections
from utils.query_parser import parse_query_words, compute_matches

FTS_TABLE = "docs"


class FTS5Engine(SearchEngine):
    def __init__(self, config: dict):
        self.db_path = config.get('db_path')
        self.conn = None
        self.cursor = None
        self.debug_log_enabled = config.get('debug_log_enabled', False)
        self.default_separator = config.get('default_separator', 'N1000')
        self._current_index = None
        self.engine_type = "fts5"
        self._current_file_name = None
        self._metadata_cache = {}

    def connect(self, source: str) -> bool:
        try:
            if self.conn:
                self.conn.close()
                self._metadata_cache.clear()
            self.conn = sqlite3.connect(source)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            self._create_fts_table()
            self.db_path = source
            self._current_index = source
            return True
        except Exception as e:
            print(f"Ошибка подключения к БД: {e}")
            return False

    def _create_fts_table(self):
        self.cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE}
            USING fts5(content, tokenize='trigram');
        """)
        self.cursor.execute("""
                            CREATE TABLE IF NOT EXISTS doc_metadata
                            (
                                rowid
                                INTEGER
                                PRIMARY
                                KEY,
                                file_name
                                TEXT,
                                position
                                TEXT
                            );
                            """)
        self.conn.commit()

    def _ensure_metadata_table(self):
        try:
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doc_metadata'")
            if not self.cursor.fetchone():
                self.cursor.execute("""
                                    CREATE TABLE doc_metadata
                                    (
                                        rowid     INTEGER PRIMARY KEY,
                                        file_name TEXT,
                                        position  TEXT
                                    );
                                    """)
                self.conn.commit()
        except Exception as e:
            print(f"Ошибка создания таблицы метаданных: {e}")

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
            self._current_index = None
            self._current_file_name = None
            self._metadata_cache.clear()

    def get_section_text(self, rowid: int) -> str:
        if not self.conn:
            return None
        try:
            self.cursor.execute(f"""
                SELECT content
                FROM {FTS_TABLE}
                WHERE rowid = ?
            """, (rowid,))
            row = self.cursor.fetchone()
            if row:
                return row[0]
        except:
            pass
        return None

    def get_section_info(self, rowid: int) -> Dict[str, Any]:
        if not self.conn:
            return None

        if rowid in self._metadata_cache:
            return self._metadata_cache[rowid]

        try:
            self.cursor.execute(f"""
                SELECT content
                FROM {FTS_TABLE}
                WHERE rowid = ?
            """, (rowid,))
            text_row = self.cursor.fetchone()
            if not text_row:
                return None

            self.cursor.execute("""
                                SELECT file_name, position
                                FROM doc_metadata
                                WHERE rowid = ?
                                """, (rowid,))
            meta_row = self.cursor.fetchone()

            result = {
                'text': text_row[0],
                'file_name': meta_row[0] if meta_row else '',
                'position': meta_row[1] if meta_row else '0'
            }

            self._metadata_cache[rowid] = result
            return result

        except Exception as e:
            print(f"Ошибка получения информации о топике: {e}")
        return None

    def index_file(self, file_path: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self._current_file_name = os.path.basename(file_path)
        print(f"📄 Индексация файла: {self._current_file_name}")

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
            raise Exception("Не удалось прочитать файл")
        result = self.index_text(text, separator, progress_callback)
        self._current_file_name = None
        return result

    def index_text(self, text: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        if not self.conn:
            raise Exception("Не подключено к БД")
        if separator is None:
            separator = self.default_separator

        start_time = time.time()
        print(f"🔨 Индексация текста, разделитель: {separator}")

        self._ensure_metadata_table()

        # Разбиение на топики
        split_start = time.time()
        lines = text.splitlines(keepends=False)
        sections = split_into_sections_by_separator(lines, separator)
        split_time = (time.time() - split_start) * 1000
        print(f"   ⏱ Разбиение на топики: {len(sections)} секций за {split_time:.1f} мс")

        if not sections:
            return 0

        if self.debug_log_enabled:
            log_sections(separator, sections, "index_debug.log")

        total = len(sections)
        if not self._current_file_name:
            self._current_file_name = 'indexed_file'

        file_name = self._current_file_name

        # Настройка для скорости
        self.cursor.execute("PRAGMA synchronous = OFF")
        self.cursor.execute("PRAGMA journal_mode = MEMORY")
        self.cursor.execute("PRAGMA cache_size = 10000")

        db_start = time.time()
        self.cursor.execute("BEGIN TRANSACTION")

        fts_data = []
        meta_data = []

        for i, section in enumerate(sections, 1):
            content = '\n'.join(section['lines'])
            position = str(section.get('start_line', 0))
            fts_data.append((content,))
            meta_data.append((file_name, position))

        # Вставка в FTS5
        fts_start = time.time()
        self.cursor.executemany(
            f"INSERT INTO {FTS_TABLE}(content) VALUES(?);",
            fts_data
        )
        fts_time = (time.time() - fts_start) * 1000
        print(f"   ⏱ Вставка в FTS5: {len(fts_data)} записей за {fts_time:.1f} мс")

        # Вставка метаданных
        meta_start = time.time()
        for i in range(total):
            rowid = self.cursor.lastrowid - total + i + 1
            self.cursor.execute(
                "INSERT INTO doc_metadata(rowid, file_name, position) VALUES(?, ?, ?);",
                (rowid, meta_data[i][0], meta_data[i][1])
            )
            if progress_callback and i % 100 == 0:
                progress_callback(i + 1, total)

        meta_time = (time.time() - meta_start) * 1000
        print(f"   ⏱ Вставка метаданных: {total} записей за {meta_time:.1f} мс")

        self.conn.commit()
        db_time = (time.time() - db_start) * 1000

        # Восстанавливаем настройки
        self.cursor.execute("PRAGMA synchronous = NORMAL")
        self.cursor.execute("PRAGMA journal_mode = DELETE")

        total_time = (time.time() - start_time) * 1000
        print(f"   ✅ Индексация завершена: {total} записей за {total_time:.1f} мс")
        print(f"      - Разбиение: {split_time:.1f} мс")
        print(f"      - Вставка FTS5: {fts_time:.1f} мс")
        print(f"      - Вставка метаданных: {meta_time:.1f} мс")
        print(f"      - Commit: {db_time - fts_time - meta_time:.1f} мс")

        if progress_callback:
            progress_callback(total, total)

        return total

    def list_indices(self) -> List[str]:
        files = []
        for f in os.listdir('.'):
            if f.lower().endswith('.db') and os.path.isfile(f):
                files.append(f)
        indices_dir = "indicies_fts5"
        if os.path.exists(indices_dir):
            for f in os.listdir(indices_dir):
                if f.lower().endswith('.db') and os.path.isfile(os.path.join(indices_dir, f)):
                    files.append(os.path.join(indices_dir, f))
        return files

    def select_index(self, name: str) -> bool:
        if not os.path.exists(name):
            return False
        self._metadata_cache.clear()
        return self.connect(name)

    def create_index(self, name: str):
        os.makedirs("indicies_fts5", exist_ok=True)
        db_path = os.path.join("indicies_fts5", name + ".db")
        if os.path.exists(db_path):
            os.remove(db_path)
        self.close()
        self.connect(db_path)
        return db_path

    def delete_index(self, name: str) -> bool:
        possible_paths = [name]
        base = os.path.basename(name)
        if not base.endswith('.db'):
            base = base + '.db'
        possible_paths.append(os.path.join("indicies_fts5", base))
        possible_paths.append(base)

        real_path = None
        for p in possible_paths:
            if os.path.exists(p):
                real_path = p
                break

        if real_path is None:
            return False

        if self._current_index:
            cur_norm = os.path.normpath(self._current_index)
            real_norm = os.path.normpath(real_path)
            if cur_norm == real_norm or os.path.basename(cur_norm) == os.path.basename(real_norm):
                self.close()

        try:
            os.remove(real_path)
            if self._current_index is None:
                self.db_path = None
                self.index = None
            return True
        except Exception as e:
            print(f"Ошибка удаления индекса {real_path}: {e}")
            return False

    def search(self, query: str, indices: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if indices and len(indices) > 0:
            if not self.select_index(indices[0]):
                return []
        if not self.conn:
            return []

        start_time = time.time()
        query_words_info = parse_query_words(query)
        if not query_words_info:
            return []

        fts_words = [info[0] for info in query_words_info]
        fts_query = " OR ".join(fts_words)

        # Поиск по FTS
        fts_start = time.time()
        try:
            self.cursor.execute(f"""
                SELECT rowid, content
                FROM {FTS_TABLE}
                WHERE content MATCH ?
                LIMIT 1000
            """, (fts_query,))
            rows = self.cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
        fts_time = (time.time() - fts_start) * 1000

        if not rows:
            # Fallback: LIKE поиск
            like_start = time.time()
            all_fragments = []
            for word, min_len, must_start in query_words_info:
                from utils.query_parser import get_fragments_with_levels
                for frag, level in get_fragments_with_levels(word, min_len):
                    all_fragments.append((frag, level, must_start))

            like_conditions = []
            for frag, level, must_start in all_fragments:
                escaped = frag.replace('%', '\\%').replace('_', '\\_')
                like_conditions.append(f"content LIKE '%{escaped}%' ESCAPE '\\'")
            like_clause = " OR ".join(like_conditions) if like_conditions else "1=0"
            sql = f"""
                SELECT rowid, content
                FROM {FTS_TABLE}
                WHERE {like_clause}
                LIMIT 1000
            """
            try:
                self.cursor.execute(sql)
                rows = self.cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []
            like_time = (time.time() - like_start) * 1000
            print(f"🔍 LIKE поиск: {len(rows)} результатов за {like_time:.1f} мс")
        else:
            print(f"🔍 FTS поиск: {len(rows)} результатов за {fts_time:.1f} мс")

        if not rows:
            return []

        # Получение метаданных
        meta_start = time.time()
        rowids = [row[0] for row in rows]
        metadata = {}
        if rowids:
            placeholders = ','.join(['?'] * len(rowids))
            try:
                self.cursor.execute(f"""
                    SELECT rowid, file_name, position
                    FROM doc_metadata
                    WHERE rowid IN ({placeholders})
                """, rowids)
                for meta_row in self.cursor.fetchall():
                    metadata[meta_row[0]] = {
                        'file_name': meta_row[1] or '',
                        'position': meta_row[2] or '0'
                    }
            except:
                pass
        meta_time = (time.time() - meta_start) * 1000

        # Вычисление совпадений
        match_start = time.time()
        results = []
        for row in rows:
            rowid = row[0]
            content = row[1]

            meta_data = metadata.get(rowid, {'file_name': '', 'position': '0'})

            meta = compute_matches(content, query_words_info)
            if meta is None:
                continue
            results.append({
                'rowid': rowid,
                'content': content,
                'meta': meta,
                'file_name': meta_data['file_name'],
                'position': meta_data['position']
            })
        match_time = (time.time() - match_start) * 1000

        total_time = (time.time() - start_time) * 1000
        print(
            f"⏱ Поиск занял {total_time:.1f} мс (FTS: {fts_time:.1f}, Мета: {meta_time:.1f}, Совпадения: {match_time:.1f})")

        return results