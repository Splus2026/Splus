import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import json, re, shutil, tempfile, configparser

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from settings import Settings, Field, FIELDS, SCALAR_KEYS, NESTED_KEYS
import config

D = os.path.join(env.DATA, 'settings')
WORK = env.tmpdir('settings_')
def read(path): return open(path, encoding='utf-8').read()
def norm(d): return json.loads(json.dumps(d, ensure_ascii=False, sort_keys=True))   # кортежи -> списки, как в JSON
def copy_fixture(name, to=None):
    target = to or os.path.join(WORK, name + '.ini'); shutil.copy(os.path.join(D, name + '.ini'), target); return target
def write(path, text): open(path, 'w', encoding='utf-8', newline='\n').write(text)

# ===== A. схема =====
keys = [f.key for f in FIELDS]; options = [(f.section, f.option) for f in FIELDS]
check('ключи схемы не повторяются, пары (секция, имя в файле) тоже', len(keys) == len(set(keys)) and len(options) == len(set(options)))
check('у каждой настройки известный вид значения', all(f.kind in ('str', 'text', 'text_or_default', 'optional', 'int', 'flag1', 'flag') for f in FIELDS))
check('значения по умолчанию подходят виду (int — число, флаги — bool)',
      all(isinstance(f.default, int) and not isinstance(f.default, bool) for f in FIELDS if f.kind == 'int')
      and all(isinstance(f.default, bool) for f in FIELDS if f.kind in ('flag', 'flag1')))
defaults = Settings.defaults()
check('defaults(): есть все ключи схемы и все вложенные структуры', SCALAR_KEYS <= set(defaults) and set(NESTED_KEYS) <= set(defaults))

# ===== B/C. золотые файлы: результат ПРЕЖНЕГО load_config/save_config =====
# Фикстуры *.expected.json и *.saved.ini получены прежней реализацией (config.py до Settings) на
# ini-файлах из tests/data/settings; новый код обязан воспроизводить их один в один.
for name in ('default', 'legacy_user', 'full', 'edge'):
    path = copy_fixture(name)
    loaded = Settings.load(path)
    expected = json.load(open(os.path.join(D, name + '.expected.json'), encoding='utf-8'))
    detail = [k for k in sorted(set(expected) | set(norm(loaded))) if expected.get(k) != norm(loaded).get(k)]
    check(f'{name}.ini: разбор совпадает с результатом прежнего load_config (все {len(expected)} ключей)', norm(loaded) == expected, str(detail))
    out = os.path.join(WORK, name + '.saved.ini'); loaded.save(out)
    check(f'{name}.ini: сохранённый файл совпадает с тем, что записал прежний save_config (текст в текст)', read(out) == read(os.path.join(D, name + '.saved.ini')))
    check(f'{name}.ini: загрузка -> сохранение -> загрузка ничего не меняет', norm(Settings.load(out)) == norm(loaded))
new_path = os.path.join(WORK, 'brand_new.ini'); fresh = Settings.load(new_path)
check('нет файла: создаётся тот же шаблон, что создавал прежний код (текст в текст)', read(new_path) == read(os.path.join(D, 'default.ini')))
check('и читается как настройки по умолчанию (кроме пробной базы bibl.txt)', {k: v for k, v in fresh.items() if k != 'bases'} == {k: v for k, v in defaults.items() if k != 'bases'} and list(fresh['bases']) == ['bibl.txt'])

# ===== D. совместимость со словарём =====
s = Settings.load(copy_fixture('full', os.path.join(WORK, 'compat.ini')))
check('Settings — это dict (isinstance, .get, [], in, **, dict())', isinstance(s, dict) and s.get('engine_type') == 'manticore' and s['merge_output_dir'] == 'D:/Склейка'
      and 'bases' in s and {**s} == dict(s) and s.get('нет такого', 'по умолчанию') == 'по умолчанию')
check('вложенные структуры — обычные словари с прежним видом значений (кортежи)', s['bases']['Номенклатура.xlsx'] == ('Номенклатура', '---', 'служебная')
      and s['vector_models']['FT Библия'] == ('bible_idx', 'fasttext', 'vector_models/bible.model') and s['vector_model_params']['FT Библия']['sg'] == 1
      and s['vector_semantic_window']['MiniLM Библия']['indices'] == ['model_bible', 'bibl'])
check('имена файлов в [Bases] сохраняют регистр (Номенклатура.xlsx, а не номенклатура.xlsx)', 'Номенклатура.xlsx' in s['bases'] and 'номенклатура.xlsx' not in s['bases'])
check('производные параметры движков вычислены (порты — числа)', s['engine_params']['manticore_port'] == 9307 and s['engine_params']['elastic_port'] == 9201 and s['engine_params']['db_path'] == 'C:/data/books.db')

# атрибутом
check('доступ атрибутом: settings.key_concepts_only', s.key_concepts_only is True and s.merge_output_dir == 'D:/Склейка')
s.key_concepts_only = False
check('запись атрибутом попадает в словарь', s['key_concepts_only'] is False)
try: s.key_concept_only; raised = False
except AttributeError: raised = True
check('опечатка в имени — AttributeError, а не молчаливое значение по умолчанию (как у .get("..", False))', raised and not hasattr(s, 'key_concept_only'))
s.my_runtime_note = 'x'
check('произвольный служебный атрибут не попадает в словарь настроек', 'my_runtime_note' not in s and s.my_runtime_note == 'x')

# save_config: Settings и обычный словарь
plain_path = os.path.join(WORK, 'plain.ini'); config.CONFIG_FILE = plain_path
config.save_config({'engine_type': 'manticore', 'key_concepts_only': True, 'bases': {'Книга.txt': ('Книга', 'N1')}})
back = config.load_config()
check('save_config принимает обычный словарь; недостающие настройки пишутся по умолчанию', back['engine_type'] == 'manticore' and back['key_concepts_only'] is True
      and back['search_delay_ms'] == 300 and back['bases'] == {'Книга.txt': ('Книга', 'N1', '')} and isinstance(back, Settings))
check('load_config читает ТЕКУЩИЙ config.CONFIG_FILE на момент вызова', config.load_config().path == plain_path)

# ===== E. каждая настройка из схемы сохраняется (причина появления класса) =====
base_path = copy_fixture('default', os.path.join(WORK, 'each.ini'))
ok, failed = True, []
for f in FIELDS:
    cur = Settings.load(base_path)
    if f.kind in ('flag', 'flag1'): new = not cur[f.key]
    elif f.kind == 'int': new = cur[f.key] + 7
    elif f.kind == 'optional': new = 'C:/x/база.db'
    else: new = f'значение-{f.key}'
    others = {k: v for k, v in cur.items() if k != f.key and k != 'engine_params'}
    cur[f.key] = new; cur.save(base_path)
    back = Settings.load(base_path)
    good = back[f.key] == new and {k: v for k, v in back.items() if k != f.key and k != 'engine_params'} == others
    if not good: failed.append(f.key)
    ok &= good
    cur[f.key] = Settings.load(copy_fixture('default', os.path.join(WORK, 'reset.ini')))[f.key]; cur.save(base_path)
check(f'КАЖДАЯ из {len(FIELDS)} настроек схемы переживает сохранение и не задевает остальные (забыть запись нельзя)', ok, str(failed))

# ===== F. перечитывание на месте =====
rp = copy_fixture('full', os.path.join(WORK, 'reload.ini'))
s = Settings.load(rp)
alias_bases, alias_models, alias_params = s['bases'], s['vector_models'], s['engine_params']
text = read(rp).replace('Гита.docx = Бхагавад-гита, ===', 'Новая.txt = Новая книга, N7').replace('search_limit = 500', 'search_limit = 999').replace('key_concepts_only = 1', 'key_concepts_only = 0')
write(rp, text)
s.reload()
check('reload: значения обновились', s['key_concepts_only'] is False and s['manticore_search_limit'] == 999 and 'Новая.txt' in s['bases'] and 'Гита.docx' not in s['bases'])
check('reload: вложенные словари — ТЕ ЖЕ объекты (держатели ссылок не остаются с устаревшей копией)', s['bases'] is alias_bases and s['vector_models'] is alias_models and s['engine_params'] is alias_params)
check('reload: через старую ссылку видны свежие данные', 'Новая.txt' in alias_bases and alias_params['manticore_search_limit'] == 999)
check('reload: объект настроек остаётся тем же и сохраняет путь', s.path == rp)
try: Settings.defaults().reload(); raised = False
except ValueError: raised = True
check('reload без файла — понятная ошибка', raised)
s['extra_runtime'] = 1; s.reload()
check('reload убирает ключи, которых нет на диске (состояние = файл)', 'extra_runtime' not in s)

# ===== G. незнакомые ключи и секции не теряются =====
up = copy_fixture('full', os.path.join(WORK, 'unknown.ini'))
t = read(up).replace('[Engine]', 'my_custom_flag = 42\nweird = 50% готово\n\n[Engine]', 1).replace('[Elastic]', '[Elastic]\ntimeout = 30', 1) + '\n[MyTools]\nx = 1\ny = a%%b\n'
write(up, t)
s = Settings.load(up)
check('незнакомые ключи и секции читаются без падения (даже с одиночным «%»)', s['key_concepts_only'] is True)
s.save(up); saved1 = read(up)
p = configparser.ConfigParser(); p.optionxform = str; p.read(up, encoding='utf-8')
check('после сохранения они на месте: ключ в [Settings], ключ в [Elastic], секция [MyTools]', p.get('Settings', 'my_custom_flag') == '42' and p.get('Elastic', 'timeout') == '30' and p.get('MyTools', 'x') == '1' and p.get('MyTools', 'y') == 'a%b')
Settings.load(up).save(up)
check('повторная загрузка и сохранение стабильны (файл не «плывёт»)', read(up) == saved1)
check('известные настройки при этом не изменились', norm(Settings.load(up)) == norm(Settings.load(copy_fixture('full', os.path.join(WORK, 'orig.ini')))))
pc = os.path.join(WORK, 'percent.ini'); write(pc, '[Settings]\nmerge_source_dir = D:/100%/книги\n')
check('одиночный «%» в значении читается как есть (раньше ронял чтение)', Settings.load(pc)['merge_source_dir'] == 'D:/100%/книги')
s = Settings.load(pc); s.save(pc)
check('и записывается так, что читается обратно', Settings.load(pc)['merge_source_dir'] == 'D:/100%/книги')

# ===== H. неверные числа =====
iv = Settings.load(copy_fixture('invalid_numbers'))
check('нечисловые значения числовых настроек -> значения по умолчанию (раньше — ValueError при запуске)',
      (iv['highlight_context_size'], iv['max_display_chars'], iv['search_delay_ms'], iv['excel_split_page_size'], iv['vector_model_topn'],
       iv['vector_sentences_before'], iv['vector_sentences_after'], iv['manticore_search_limit']) == (500, 50000, 300, 20, 15, 7, 10, 200), str(dict(iv)))
check('порты движков в engine_params — числа, при мусоре — стандартные', iv['engine_params']['elastic_port'] == 9200 and iv['engine_params']['manticore_port'] == 9306)
check('сам текст порта в настройках сохраняется как написан (его правит пользователь)', iv['elastic_port'] == 'порт')

# ===== I. запись атомарна =====
ap = copy_fixture('full', os.path.join(WORK, 'atomic.ini')); s = Settings.load(ap); before = read(ap)
s['search_delay_ms'] = 999; s.save(ap)
check('после успешной записи временного файла не остаётся', not os.path.exists(ap + '.part') and Settings.load(ap)['search_delay_ms'] == 999)
before = read(ap); original_replace = os.replace
def boom(a, b): raise OSError("диск полон")
os.replace = boom
try:
    s['search_delay_ms'] = 111; s.save(ap); raised = False
except OSError: raised = True
finally: os.replace = original_replace
check('сбой при подмене файла: исключение, прежний mconfig.ini цел, временный файл убран', raised and read(ap) == before and not os.path.exists(ap + '.part'))
try: s.save(os.path.join(WORK, 'нет_такой_папки', 'x.ini')); raised = False
except OSError: raised = True
check('нельзя записать (нет папки): исключение, ничего не создано', raised and not os.path.exists(os.path.join(WORK, 'нет_такой_папки')))
try: Settings.defaults().save(); raised = False
except ValueError: raised = True
check('save без пути — понятная ошибка', raised)

# ===== J. ключи настроек по всему проекту описаны в схеме (ловит опечатки) =====
pat = [re.compile(r"""\b(?:self\.)?(?:config|config_dict|_config)\.get\(\s*['"]([A-Za-z_0-9]+)['"]"""),
       re.compile(r"""\b(?:self\.)?(?:config|config_dict|_config)\[\s*['"]([A-Za-z_0-9]+)['"]\s*\]""")]
known = set(SCALAR_KEYS) | set(NESTED_KEYS); unknown = {}
from tests.sources import project_sources  # только исходники проекта (в корне проекта может лежать .venv с тысячами чужих файлов)
for rel in project_sources(env.ROOT):
    if rel == 'settings.py' or rel.startswith('engines/'): continue  # у движков свои параметры (db_path, host, port, index)
    text = open(os.path.join(env.ROOT, rel), encoding='utf-8', errors='replace').read()
    for rx in pat:
        for m in rx.finditer(text):
            if m.group(1) not in known: unknown.setdefault(m.group(1), set()).add(rel)
check('все ключи настроек, к которым обращается код (кроме движков — у них свои параметры), описаны в схеме', not unknown, str({k: sorted(v) for k, v in unknown.items()}))

# ===== J2. config_dict там, где он — словарь файлов-баз, не читает настройки =====
# Имя config_dict значит в разных классах разное: в VectorModelManager это полные настройки, а в SearchController, FileManager,
# IndexManager и окне — только словарь баз {файл: (алиас, разделитель, исключение)}. Перепутать их — прежняя ошибка: настройка
# молча заменялась значением по умолчанию (vector_model_topn, vector_sentences_before/after были так «потеряны»).
BASES_DICT_MODULES = ('services/search_controller.py', 'services/file_manager.py', 'services/index_manager.py', 'ui/app_window.py')
leaks = []
for rel in BASES_DICT_MODULES:
    for i, line in enumerate(read(os.path.join(env.ROOT, rel)).splitlines(), 1):
        for m in re.finditer(r"""\bconfig_dict\.get\(\s*['"](\w+)['"]""", line):
            if m.group(1) in SCALAR_KEYS: leaks.append(f'{rel}:{i}: {m.group(1)}')
check('там, где config_dict — словарь баз (SearchController, FileManager, IndexManager, окно), настройки по нему не читаются: они лежат в self.config', not leaks, str(leaks))

# ===== K. подключение =====
mw = read(os.path.join(env.ROOT, 'ui', 'main_window.py'))
check('смена движка перечитывает настройки на месте (self.config.reload()), а не подменяет объект', 'self.config.reload()' in mw and 'self.config = load_config()' not in mw)
cfg_src = read(os.path.join(env.ROOT, 'config.py'))
check('config.py — тонкая обёртка: разбора файла и схемы в нём больше нет', 'configparser' not in cfg_src and cfg_src.count('Settings.load(CONFIG_FILE)') == 1)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
