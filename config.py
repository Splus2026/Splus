import os
import sys
from settings import Settings
from engines.fts5_engine import FTS5Engine
from engines.elastic_engine import ElasticEngine

def resource_path(relative_path):
    """Получить абсолютный путь к ресурсу, работает как для разработки, так и для PyInstaller."""
    if getattr(sys, 'frozen', False):
        # В сборке файлы лежат рядом с exe; если там нет — запасной вариант в _internal.
        near_exe = os.path.join(os.path.dirname(sys.executable), relative_path)
        if os.path.exists(near_exe):
            return near_exe
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        inner = os.path.join(base_path, relative_path)
        return inner if os.path.exists(inner) else near_exe
    return os.path.join(os.path.abspath("."), relative_path)

CONFIG_FILE = resource_path("mconfig.ini")
DEBUG_LOG = resource_path("index_debug.log")

# Путь к конспекту теперь в папке DB (относительно текущей рабочей директории)
CONSPECT_FILE = os.path.join("DB", "0_Конспект.txt")
# Подчёркнутые фрагменты (кнопка "Ч", см. services/marks.py): небольшой файл SQLite
# рядом с mconfig.ini.
MARKS_DB_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "marks.db")
# Словарь ключевых понятий (кнопка "КП", см. utils/key_concepts.py): обычный текстовый файл
# рядом с mconfig.ini, по слову на строке — его можно править вручную.
KEY_CONCEPTS_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "key_concepts.txt")

def load_config():
    """Загружает настройки из mconfig.ini и возвращает Settings — словарь с прежним
       набором ключей (settings['x'], settings.get('x', ...)), а также доступом
       атрибутом (settings.key_concepts_only), схемой, сохранением и перечитыванием на
       месте. Если файла нет, он создаётся с настройками по умолчанию. Подробности
       и список настроек — в settings.py."""
    return Settings.load(CONFIG_FILE)


def save_config(config_dict):
    """Сохраняет настройки в mconfig.ini. Принимает Settings или обычный словарь с
       теми же ключами (недостающие пишутся значениями по умолчанию). Незнакомые ключи
       и секции файла сохраняются, запись атомарная — см. settings.py."""
    settings = config_dict if isinstance(config_dict, Settings) else Settings(config_dict)
    settings.save(CONFIG_FILE)


def create_engine(engine_type, params, on_startup_failure=None):
    """Фабрика движков. on_startup_failure(заголовок, текст) — что сделать, если поисковый движок не удалось
       запустить (сейчас это только Manticore, он запускает свой сервер сам): движок окон не создаёт, он сообщает,
       а показать сообщение пользователю — дело того, у кого есть окно."""
    if engine_type == 'fts5':
        return FTS5Engine(params)
    elif engine_type == 'elastic':
        elastic_params = {
            'host': params.get('elastic_host', 'localhost'),
            'port': params.get('elastic_port', 9200),
            'index': params.get('elastic_index', 'documents'),
            'default_separator': params.get('default_separator', 'N1000'),
            'debug_log_enabled': params.get('debug_log_enabled', False)
        }
        return ElasticEngine(elastic_params)
    elif engine_type == 'manticore':
        manticore_params = {
            'host': params.get('manticore_host', 'localhost'),
            'port': params.get('manticore_port', 9306),
            'index': params.get('manticore_index', 'documents'),
            'default_separator': params.get('default_separator', 'N1000'),
            'manticore_search_limit': params.get('manticore_search_limit', 200)
        }
        try:
            from engines.manticore_engine import ManticoreEngine
            return ManticoreEngine(manticore_params, on_startup_failure=on_startup_failure)
        except ImportError as e:
            raise ImportError(f"Не удалось загрузить ManticoreEngine: {e}")
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")