"""Настройки программы (mconfig.ini).

   Раньше настройки были обычным словарём, а каждая настройка описывалась в
   ТРЁХ местах config.py: в шаблоне нового файла, в load_config() (чтение) и в
   save_config() (запись). Забыть запись значило молча стирать настройку при любом
   другом сохранении (save_config собирал файл с нуля), а значения читались и
   писались по-разному у разных настроек.

   Теперь:
   - все плоские настройки объявлены ОДИН раз — в таблице FIELDS (ключ, секция и
     имя в файле, вид значения, значение по умолчанию); шаблон нового файла,
     чтение и запись строятся из неё, поэтому новая настройка — это одна
     строка в таблице;
   - Settings — подкласс dict: весь прежний код (settings.get('x', ...),
     settings['x'], **settings, isinstance(settings, dict)) работает без правок;
     дополнительно — доступ атрибутом (settings.key_concepts_only): опечатка в
     имени даёт AttributeError, а не молчаливое значение по умолчанию;
   - reload() перечитывает файл НА МЕСТЕ: вложенные словари (bases,
     vector_models, ...) остаются теми же объектами, поэтому все, кто на них
     держит ссылки (IndexManager, SearchController, VectorModelManager), видят
     свежие данные, а не устаревшую копию;
   - незнакомые ключи и секции, дописанные в mconfig.ini вручную (или более
     новой версией программы), при сохранении НЕ теряются;
   - файл записывается через временный и атомарно подменяется: сбой посреди
     записи не оставит полупустой mconfig.ini вместо всех настроек и баз.

   Что НЕ изменилось: формат файла, секции и их порядок, вид словаря (те же ключи
   и значения), порядок разбора баз и векторных моделей. Единственное отличие в
   поведении — на заведомо неверном вводе: нечисловое значение числовой
   настройки раньше роняло запуск (ValueError), теперь берётся значение по
   умолчанию; одиночный "%" в значении читается как есть."""

import configparser
import os
from dataclasses import dataclass
from typing import Any

# Слова, которыми "включается" флаг у настроек вида 'flag' (регистр не важен).
_TRUE_WORDS = ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Field:
    """Одна плоская настройка.

       kind — как читается и пишется значение:
         'str'             строка как есть
         'text'            строка без пробелов по краям
         'text_or_default' то же, но пустая строка заменяется значением по умолчанию
         'optional'        пустая строка читается как None (None пишется как пустая)
         'int'             целое; нечисловое значение -> значение по умолчанию
         'flag1'           флаг, "включён" только при значении 1
         'flag'            флаг, "включён" при 1/true/yes/on (регистр не важен)
       ('flag1' и 'flag' различаются только строгостью чтения — так было в прежнем
       коде для разных настроек; оба пишутся как 1/0.)"""
    key: str
    section: str
    option: str
    kind: str
    default: Any


# Порядок записей — порядок строк в файле (и в прежнем save_config).
FIELDS = (
    Field('default_separator', 'Settings', 'default_separator', 'str', 'N1000'),
    Field('debug_log_enabled', 'Settings', 'debug_log_enabled', 'flag1', False),
    Field('last_db', 'Settings', 'last_db', 'optional', None),
    Field('highlight_context_size', 'Settings', 'highlight_context_size', 'int', 500),
    Field('max_display_chars', 'Settings', 'max_display_chars', 'int', 50000),
    Field('search_delay_ms', 'Settings', 'search_delay_ms', 'int', 300),
    Field('excel_split_view_enabled', 'Settings', 'excel_split_view_enabled', 'flag1', False),
    Field('excel_split_page_size', 'Settings', 'excel_split_page_size', 'int', 20),
    # Векторный поиск (кнопка "Векторы"): тип модели вынесен в настройки, чтобы можно
    # было попробовать другую без переделки кода — достаточно добавить реализацию в
    # vector_engines/ и указать её имя здесь.
    Field('vector_model_type', 'Settings', 'vector_model_type', 'str', 'fasttext'),
    Field('vector_model_topn', 'Settings', 'vector_model_topn', 'int', 15),
    Field('vector_models_dir', 'Settings', 'vector_models_dir', 'str', 'vector_models'),
    # "Круги связи" слова при подготовке обучающих данных: сколько предложений до и
    # после текущего включать (не выходя за границы абзаца) — см.
    # services/vector_model_manager.py, _build_training_sentences().
    Field('vector_sentences_before', 'Settings', 'vector_sentences_before', 'int', 7),
    Field('vector_sentences_after', 'Settings', 'vector_sentences_after', 'int', 10),
    # Окно "Собрать базу": откуда в последний раз выбирали файлы и куда сохраняли.
    Field('merge_source_dir', 'Settings', 'merge_source_dir', 'text', ''),
    Field('merge_output_dir', 'Settings', 'merge_output_dir', 'text_or_default', 'DB'),
    # Сменный пароль входа: хеш и соль (utils/password.py). Пусто — только прежний
    # пароль (день и месяц, ДДММ).
    Field('password_hash', 'Settings', 'password_hash', 'text', ''),
    Field('password_salt', 'Settings', 'password_salt', 'text', ''),
    # 1 — "Т", "Ц", "Сгущение понятий" и "Всё пространство" показывают только слова
    # словаря ключевых понятий и их вариации (utils/key_concepts.py).
    Field('key_concepts_only', 'Settings', 'key_concepts_only', 'flag', False),
    # 1 — после "Редактировать" включается нумератор разбивки (services/numerator.py).
    # Читается как строка, а не как число: опечатка вроде "да" не должна ронять запуск.
    Field('enable_numerator_on_update', 'Settings', 'enable_numerator_on_update', 'flag', False),
    Field('engine_type', 'Engine', 'type', 'str', 'fts5'),
    Field('elastic_host', 'Elastic', 'host', 'str', 'localhost'),
    Field('elastic_port', 'Elastic', 'port', 'str', '9200'),
    Field('elastic_index', 'Elastic', 'index', 'str', 'documents'),
    Field('manticore_host', 'Manticore', 'host', 'str', 'localhost'),
    Field('manticore_port', 'Manticore', 'port', 'str', '9306'),
    Field('manticore_index', 'Manticore', 'index', 'str', 'documents'),
    Field('manticore_search_limit', 'Manticore', 'search_limit', 'int', 200),
)

SCALAR_KEYS = frozenset(f.key for f in FIELDS)
# Вложенные структуры: целиком заменяются на месте в reload(), а не подменяются новым объектом.
NESTED_KEYS = ('bases', 'vector_models', 'vector_model_params', 'vector_semantic_window', 'engine_params')

_VECTOR_PARAM_OPTIONS = ('vector_size', 'window', 'min_count', 'epochs', 'sg', 'workers')
_SEMANTIC_INT_OPTIONS = ('target_chars', 'overlap_chars', 'sentences_before', 'sentences_after')
_FLAT_SECTIONS = ('Settings', 'Engine', 'Elastic', 'Manticore')
_STRUCTURED_SECTIONS = ('Bases', 'VectorModels')
_STRUCTURED_PREFIXES = ('VectorParams:', 'VectorSemanticWindow:')


def _read_value(kind, raw, default):
    if raw is None:
        return default
    if kind == 'str':
        return raw
    if kind == 'text':
        return raw.strip()
    if kind == 'text_or_default':
        return raw.strip() or default
    if kind == 'optional':
        return raw or None
    if kind == 'int':
        try:
            return int(raw)
        except ValueError:
            return default
    if kind == 'flag1':
        return raw.strip() == '1'
    if kind == 'flag':
        return raw.strip().lower() in _TRUE_WORDS
    raise ValueError(f"Неизвестный вид настройки: {kind}")


def _write_value(kind, value):
    if kind in ('flag1', 'flag'):
        return '1' if value else '0'
    if kind == 'int':
        return str(value)
    if kind == 'optional':
        text = value or ''
    else:
        text = '' if value is None else str(value)
    # ConfigParser читает значения с интерполяцией: одиночный "%" (например, в пути
    # "D:/100%/books") роняет чтение, поэтому "%" в записываемых строках удваивается.
    return text.replace('%', '%%')


def _new_parser():
    parser = configparser.ConfigParser()
    # По умолчанию ConfigParser приводит имена ключей к нижнему регистру, и имя файла в
    # секции [Bases] ("Номенклатура.xlsx", как его возвращает os.path.basename) не
    # совпадало бы с ключом словаря конфигурации — терялись бы алиас, разделитель и
    # подстрока-исключение для любого файла с заглавными буквами в имени.
    parser.optionxform = str
    return parser


def _get_raw(parser, section, option):
    """Значение опции или None, если её (или секции) нет. Значение с одиночным "%"
       (его могли дописать вручную) читается как есть, а не роняет программу."""
    try:
        return parser.get(section, option, fallback=None)
    except configparser.Error:
        return parser.get(section, option, raw=True, fallback=None)


def _items(parser, section):
    try:
        return parser.items(section)
    except configparser.Error:
        return parser.items(section, raw=True)


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_entry(value):
    return [part.strip() for part in value.split(',')]


def _parse_bases(parser, default_separator):
    bases = {}
    if parser.has_section('Bases'):
        for key, value in _items(parser, 'Bases'):
            parts = _split_entry(value)
            if len(parts) >= 3:
                display_name, separator, exclude_substring = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                display_name, separator, exclude_substring = parts[0], parts[1], ''
            else:
                display_name, separator, exclude_substring = value, default_separator, ''
            # Третье поле используется только для Excel-файлов: строки, содержащие эту
            # подстроку, исключаются из индекса/поиска/результатов.
            bases[key] = (display_name, separator, exclude_substring)
    return bases


def _parse_vector_models(parser):
    """display_name (в списке индексов с префиксом "FT ") -> (имя индекса Manticore с
       топиками для модели, тип модели, путь к файлу модели)."""
    models = {}
    if parser.has_section('VectorModels'):
        for key, value in _items(parser, 'VectorModels'):
            parts = _split_entry(value)
            if len(parts) >= 3:
                models[key] = (parts[0], parts[1], parts[2])
    return models


def _parse_vector_params(parser):
    """Параметры обучения каждой модели хранятся в СВОЕЙ секции VectorParams:<имя>:
       они подбираются один раз в диалоге настроек и переиспользуются при дообучении."""
    result = {}
    for section in parser.sections():
        if section.startswith('VectorParams:'):
            params = {}
            for opt in _VECTOR_PARAM_OPTIONS:
                if parser.has_option(section, opt):
                    try:
                        params[opt] = int(parser.get(section, opt))
                    except ValueError:
                        pass
            if params:
                result[section[len('VectorParams:'):]] = params
    return result


def _parse_semantic_windows(parser):
    """"Окно смысла" MiniLM: каким способом получены блоки текста для модели и по каким
       индексам модель ищет (хранится, чтобы не отмечать индекс заново при каждом поиске
       и чтобы дообучение знало, куда добавлять новые блоки)."""
    result = {}
    for section in parser.sections():
        if section.startswith('VectorSemanticWindow:'):
            entry = {'mode': parser.get(section, 'mode', fallback='existing_index')}
            indices_raw = parser.get(section, 'indices', fallback='')
            entry['indices'] = [i.strip() for i in indices_raw.split(',') if i.strip()]
            for opt in _SEMANTIC_INT_OPTIONS:
                if parser.has_option(section, opt):
                    try:
                        entry[opt] = int(parser.get(section, opt))
                    except ValueError:
                        pass
            result[section[len('VectorSemanticWindow:'):]] = entry
    return result


def _derive_engine_params(data):
    """Параметры движков — производные от остальных настроек, в файл не пишутся."""
    elastic_port = _to_int(data['elastic_port'], 9200)
    return {
        'db_path': data['last_db'],
        'debug_log_enabled': data['debug_log_enabled'],
        'default_separator': data['default_separator'],
        'elastic_host': data['elastic_host'],
        'elastic_port': elastic_port,
        'elastic_index': data['elastic_index'],
        'manticore_host': data['manticore_host'],
        'manticore_port': _to_int(data['manticore_port'], 9306),
        'manticore_index': data['manticore_index'],
        'manticore_search_limit': data['manticore_search_limit'],
        # Для обратной совместимости (старые ключи).
        'host': data['elastic_host'],
        'port': elastic_port,
        'index': data['elastic_index'],
    }


def _collect_extras(parser):
    """Всё, чего нет в схеме: незнакомые ключи известных секций и незнакомые секции
       целиком (в "сыром" виде, как в файле) — чтобы не терять их при сохранении."""
    known = {}
    for field in FIELDS:
        known.setdefault(field.section, set()).add(field.option)
    extras = {}
    for section in parser.sections():
        if section in _STRUCTURED_SECTIONS or section.startswith(_STRUCTURED_PREFIXES):
            continue
        raw_items = parser.items(section, raw=True)
        if section in _FLAT_SECTIONS:
            unknown = {opt: value for opt, value in raw_items if opt not in known.get(section, set())}
        else:
            unknown = dict(raw_items)
        if unknown or section not in _FLAT_SECTIONS:
            extras[section] = unknown
    return extras


def _set_raw(parser, section, option, value):
    try:
        parser.set(section, option, value)
    except ValueError:
        parser.set(section, option, value.replace('%', '%%'))  # одиночный "%" из чужого файла


class Settings(dict):
    """Настройки программы: словарь с прежним набором ключей плюс схема, чтение,
       запись и перечитывание на месте (см. описание модуля)."""

    def __init__(self, *args, path=None, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, '_path', path)
        object.__setattr__(self, '_extras', {})

    # ---------- доступ атрибутом: settings.key_concepts_only ----------
    def __getattr__(self, name):
        if name in SCALAR_KEYS and name in self:
            return self[name]
        raise AttributeError(f"У настроек нет параметра «{name}»")

    def __setattr__(self, name, value):
        if name in SCALAR_KEYS:
            self[name] = value
        else:
            object.__setattr__(self, name, value)

    @property
    def path(self):
        return self._path

    # ---------- чтение ----------
    @classmethod
    def defaults(cls):
        """Настройки без файла: значения по умолчанию и пустые вложенные структуры."""
        data = {field.key: field.default for field in FIELDS}
        data.update(bases={}, vector_models={}, vector_model_params={}, vector_semantic_window={})
        data['engine_params'] = _derive_engine_params(data)
        return cls(data)

    @classmethod
    def load(cls, path):
        """Читает mconfig.ini; если файла нет — сначала создаёт его с настройками по
           умолчанию (как делал load_config)."""
        if not os.path.exists(path):
            cls._write_template(path)
        parser = _new_parser()
        parser.read(path, encoding='utf-8')
        data = {}
        for field in FIELDS:
            data[field.key] = _read_value(field.kind, _get_raw(parser, field.section, field.option), field.default)
        data['bases'] = _parse_bases(parser, data['default_separator'])
        data['vector_models'] = _parse_vector_models(parser)
        data['vector_model_params'] = _parse_vector_params(parser)
        data['vector_semantic_window'] = _parse_semantic_windows(parser)
        data['engine_params'] = _derive_engine_params(data)
        settings = cls(data, path=path)
        object.__setattr__(settings, '_extras', _collect_extras(parser))
        return settings

    def reload(self):
        """Перечитывает файл НА МЕСТЕ: тот же объект, те же вложенные словари (их
           содержимое обновляется, а не подменяется) — все, кто держит на них ссылки,
           увидят свежие данные."""
        if not self._path:
            raise ValueError("У этих настроек нет файла (path не задан)")
        fresh = Settings.load(self._path)
        for key, value in fresh.items():
            current = self.get(key)
            if key in NESTED_KEYS and isinstance(current, dict):
                current.clear()
                current.update(value)
            else:
                self[key] = value
        for key in [k for k in self if k not in fresh]:
            del self[key]
        object.__setattr__(self, '_extras', fresh._extras)

    # ---------- запись ----------
    @classmethod
    def _write_template(cls, path):
        """Новый mconfig.ini: все настройки по умолчанию, одна пробная база, пустой список моделей."""
        parser = _new_parser()
        parser.add_section('Settings')
        for field in FIELDS:
            if field.section == 'Settings':
                parser.set('Settings', field.option, _write_value(field.kind, field.default))
        parser.add_section('Bases')
        parser.set('Bases', 'bibl.txt', 'Библия, N1000')
        parser.add_section('VectorModels')
        for section in ('Engine', 'Elastic', 'Manticore'):
            parser.add_section(section)
            for field in FIELDS:
                if field.section == section:
                    parser.set(section, field.option, _write_value(field.kind, field.default))
        cls._write_atomic(parser, path)

    @staticmethod
    def _write_atomic(parser, path):
        tmp_path = path + '.part'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                parser.write(f)
            os.replace(tmp_path, path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise

    def save(self, path=None):
        """Записывает настройки в mconfig.ini. Ключ, которого нет в словаре, пишется со
           значением по умолчанию. Незнакомые ключи и секции файла сохраняются."""
        path = path or self._path
        if not path:
            raise ValueError("Не указан файл для сохранения настроек")
        parser = _new_parser()

        def write_fields(section):
            for field in FIELDS:
                if field.section == section:
                    parser.set(section, field.option, _write_value(field.kind, self.get(field.key, field.default)))
            for option, value in self._extras.get(section, {}).items():
                if not parser.has_option(section, option):
                    _set_raw(parser, section, option, value)

        parser.add_section('Settings')
        write_fields('Settings')
        parser.add_section('Engine')
        write_fields('Engine')

        parser.add_section('Bases')
        for key, value in self.get('bases', {}).items():
            display, separator = value[0], value[1]
            exclude = value[2] if len(value) >= 3 else ''
            parser.set('Bases', key, f"{display}, {separator}, {exclude}" if exclude else f"{display}, {separator}")

        parser.add_section('VectorModels')
        for key, value in self.get('vector_models', {}).items():
            parser.set('VectorModels', key, f"{value[0]}, {value[1]}, {value[2]}")

        for display_key, params in self.get('vector_model_params', {}).items():
            section = f"VectorParams:{display_key}"
            parser.add_section(section)
            for opt in _VECTOR_PARAM_OPTIONS:
                if opt in params:
                    parser.set(section, opt, str(params[opt]))

        for display_key, entry in self.get('vector_semantic_window', {}).items():
            section = f"VectorSemanticWindow:{display_key}"
            parser.add_section(section)
            parser.set(section, 'mode', entry.get('mode', 'existing_index'))
            parser.set(section, 'indices', ', '.join(entry.get('indices', [])))
            for opt in _SEMANTIC_INT_OPTIONS:
                if opt in entry:
                    parser.set(section, opt, str(entry[opt]))

        parser.add_section('Elastic')
        write_fields('Elastic')
        parser.add_section('Manticore')
        write_fields('Manticore')

        for section, options in self._extras.items():
            if section in _FLAT_SECTIONS:
                continue
            if not parser.has_section(section):
                parser.add_section(section)
            for option, value in options.items():
                _set_raw(parser, section, option, value)

        self._write_atomic(parser, path)
