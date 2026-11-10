import os
import sys
import platform
import psutil
from datetime import datetime
import glob

STATS_ENABLED = False
LOG_FILE = None
_status_callback = None  # функция для обновления поля сообщений (принимает текст без даты)

def enable_stats():
    global STATS_ENABLED, LOG_FILE
    STATS_ENABLED = True
    tmp_dir = os.path.join(os.path.dirname(__file__), '.tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    LOG_FILE = os.path.join(tmp_dir, 'stats.log')

def set_status_callback(callback):
    """Устанавливает функцию для дублирования логов в интерфейс (без временной метки)."""
    global _status_callback
    _status_callback = callback

def _write_log(message: str):
    if not STATS_ENABLED or LOG_FILE is None:
        return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    full_msg = f"{message} [{timestamp}]"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(full_msg + "\n")
    if _status_callback:
        _status_callback(message)

def _get_system_info():
    info = {}
    try:
        info['cpu'] = platform.processor() or platform.machine()
        info['os'] = platform.system() + " " + platform.release()
        mem = psutil.virtual_memory()
        info['ram_total'] = mem.total // (1024 * 1024)
        info['ram_free'] = mem.available // (1024 * 1024)
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        info['disk_free'] = disk.free // (1024 * 1024)
    except Exception:
        info['cpu'] = 'unknown'
        info['os'] = 'unknown'
        info['ram_total'] = 0
        info['ram_free'] = 0
        info['disk_free'] = 0
    return info

def get_index_sizes(engine):
    sizes = {}
    if engine is None:
        return sizes
    engine_type = getattr(engine, 'engine_type', None)
    if engine_type == 'fts5':
        total = 0
        for f in os.listdir('.'):
            if f.endswith('.db'):
                total += os.path.getsize(f)
        indices_dir = "indicies_fts5"
        if os.path.exists(indices_dir):
            for f in os.listdir(indices_dir):
                if f.endswith('.db'):
                    total += os.path.getsize(os.path.join(indices_dir, f))
        sizes['fts5'] = total
    elif engine_type == 'elasticsearch':
        try:
            if engine.client:
                stats = engine.client.indices.stats(index='_all')
                total = stats['_all']['primaries']['store']['size_in_bytes']
                sizes['elastic'] = total
            else:
                sizes['elastic'] = 0
        except:
            sizes['elastic'] = 0
    elif engine_type == 'manticore':
        data_dir = getattr(engine, 'data_dir', None)
        if data_dir and os.path.exists(data_dir):
            total = 0
            for f in os.listdir(data_dir):
                fp = os.path.join(data_dir, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
            sizes['manticore'] = total
        else:
            sizes['manticore'] = 0
    return sizes

def get_db_folder_size():
    db_dir = "DB"
    if not os.path.exists(db_dir):
        return 0
    total = 0
    for root, dirs, files in os.walk(db_dir):
        for f in files:
            fp = os.path.join(root, f)
            total += os.path.getsize(fp)
    return total

def log_startup(startup_duration_ms: float, engine=None, version="?"):
    if not STATS_ENABLED:
        return
    info = _get_system_info()
    index_sizes = get_index_sizes(engine) if engine else {}
    size_str = ", ".join(f"{k}: {v/(1024*1024):.2f} МБ" for k, v in index_sizes.items() if v > 0)
    db_size = get_db_folder_size()
    msg = (f"Время загрузки GUI: {startup_duration_ms:.1f} мс | "
           f"Версия: {version} | Процессор: {info['cpu']} | "
           f"ОЗУ всего: {info['ram_total']} МБ | ОЗУ свободно: {info['ram_free']} МБ | "
           f"Свободно на диске: {info['disk_free']} МБ | ОС: {info['os']} | "
           f"Размеры индексов: {size_str if size_str else 'нет'} | "
           f"Размер DB: {db_size/(1024*1024):.2f} МБ")
    _write_log(msg)

def log_search(engine_type: str, query: str, index_name: str, search_time_ms: float):
    if not STATS_ENABLED:
        return
    msg = (f"Время поиска: {search_time_ms:.1f} мс | "
           f"Движок: {engine_type} | Индекс: {index_name} | Запрос: '{query}'")
    _write_log(msg)

def log_exclusions(query: str, excluded_words: set):
    if not STATS_ENABLED:
        return
    excluded_list = list(excluded_words)
    msg = (f"Исключения при поиске | Запрос: '{query}' | "
           f"Исключённые слова: {excluded_list if excluded_list else 'нет'}")
    _write_log(msg)

def log_index_creation(engine_type: str, source_filename: str, file_size_bytes: int,
                       separator: str, blocks_count: int, index_size_bytes: int,
                       build_time_ms: float):
    if not STATS_ENABLED:
        return
    info = _get_system_info()
    file_size_mb = file_size_bytes / (1024 * 1024)
    index_size_mb = index_size_bytes / (1024 * 1024)
    build_time_sec = build_time_ms / 1000.0
    if build_time_sec > 0:
        mb_per_sec = file_size_mb / build_time_sec
        sec_per_mb = build_time_sec / file_size_mb if file_size_mb > 0 else 0
    else:
        mb_per_sec = 0
        sec_per_mb = 0
    msg = (f"Время создания индекса: {build_time_ms:.1f} мс | "
           f"Движок: {engine_type} | Исходный файл: {source_filename} ({file_size_mb:.2f} МБ) | "
           f"Разделитель: {separator} | Блоков: {blocks_count} | Размер индекса: {index_size_mb:.2f} МБ | "
           f"Скорость: {mb_per_sec:.3f} МБ/с, {sec_per_mb:.3f} с/МБ | "
           f"ОЗУ свободно: {info['ram_free']} МБ | Свободно на диске: {info['disk_free']} МБ")
    _write_log(msg)

def log_index_deletion(engine_type: str, index_name: str, index_size_bytes: int,
                       deletion_time_ms: float, total_index_size_after: int):
    if not STATS_ENABLED:
        return
    info = _get_system_info()
    index_size_mb = index_size_bytes / (1024 * 1024)
    total_after_mb = total_index_size_after / (1024 * 1024)
    msg = (f"Время удаления индекса: {deletion_time_ms:.1f} мс | "
           f"Движок: {engine_type} | Индекс: {index_name} | Размер удалённого индекса: {index_size_mb:.2f} МБ | "
           f"Размер индексов движка после удаления: {total_after_mb:.2f} МБ | "
           f"ОЗУ свободно: {info['ram_free']} МБ | Свободно на диске: {info['disk_free']} МБ")
    _write_log(msg)

def log_engine_switch(from_engine: str, to_engine: str, switch_time_ms: float, success: bool):
    if not STATS_ENABLED:
        return
    status = "успешно" if success else "неудачно"
    msg = (f"Время переключения движка: {switch_time_ms:.1f} мс | "
           f"С: {from_engine} на: {to_engine} | Статус: {status}")
    _write_log(msg)

# ИСПРАВЛЕННАЯ ФУНКЦИЯ – убраны ненужные поля
def log_file_open(file_path: str, total_time_ms: float, read_time_ms: float, pos_time_ms: float,
                  insert_time_ms: float, scroll_time_ms: float, highlight_time_ms: float,
                  file_size_mb: float, display_size_chars: int, highlight_area_chars: int,
                  intervals_found: int, tags_applied: int):
    if not STATS_ENABLED:
        return
    msg = (f"Время открытия файла: {total_time_ms:.1f} мс | "
           f"Файл: {os.path.basename(file_path)} | "
           f"Чтение: {read_time_ms:.1f} мс | "
           f"Размер файла: {file_size_mb:.2f} МБ | "
           f"Область отображения: {display_size_chars} симв. | "
           f"Область подсветки: {highlight_area_chars} симв. | "
           f"Найдено интервалов: {intervals_found} | Применено тегов: {tags_applied}")
    _write_log(msg)

def log_shutdown():
    if not STATS_ENABLED:
        return
    msg = "Завершение работы программы"
    _write_log(msg)

def log_display_page(total_ms: float, phase_times: dict, topic_count: int):
    if not STATS_ENABLED:
        return
    parts = []
    for name, val in phase_times.items():
        parts.append(f"{name}: {val:.1f} мс")
    details = ", ".join(parts)
    msg = (f"Время отображения страницы: {total_ms:.1f} мс | "
           f"топиков: {topic_count} | {details}")
    _write_log(msg)

def get_stats_log_content():
    if LOG_FILE is None or not os.path.exists(LOG_FILE):
        return "Лог-файл статистики не найден."
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return "Ошибка чтения лог-файла."

def log_typing_stats(query: str, typing_stats_str: str, typing_total_ms: float,
                     search_time_ms: float, display_time_ms: float):
    if not STATS_ENABLED:
        return
    msg = (f"Статистика ввода: '{query}' | "
           f"Интервалы,мс: {typing_stats_str} | "
           f"Общее время ввода: {typing_total_ms:.0f} мс | "
           f"Время поиска: {search_time_ms:.0f} мс | "
           f"Время отображения: {display_time_ms:.0f} мс")
    _write_log(msg)