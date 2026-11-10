import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import filecmp, shutil

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import sp
from utils.project_files import project_sources

ROOT = env.ROOT

def read_bytes(path):
    with open(path, 'rb') as f: return f.read()

def new_project(files=None, with_tests=True):
    """Временная копия проекта: исходники (по правилу), mconfig.ini (если есть) и папка tests;
       files — дополнительные файлы {относительный путь: содержимое}."""
    proj = os.path.join(env.tmpdir('backup_'), 'proj'); os.makedirs(proj)
    def put(rel, data):
        path = os.path.join(proj, *rel.split('/')); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, 'wb').write(data)
    for rel in project_sources(ROOT) + (['mconfig.ini'] if os.path.exists(os.path.join(ROOT, 'mconfig.ini')) else []):
        put(rel, read_bytes(os.path.join(ROOT, rel)))
    if with_tests:
        for root, dirs, names in os.walk(os.path.join(ROOT, 'tests')):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in names:
                if not name.endswith('.pyc'):
                    full = os.path.join(root, name); put(os.path.relpath(full, ROOT).replace(os.sep, '/'), read_bytes(full))
    for rel, data in (files or {}).items(): put(rel, data)
    return proj

def run_backup(proj):
    """Запускает backup_source_files() как будто sp.py лежит в proj. Возвращает папку архива или None."""
    real_file = sp.__file__; sp.__file__ = os.path.join(proj, 'sp.py')
    try: sp.backup_source_files()
    finally: sp.__file__ = real_file
    tmp_root = os.path.join(proj, '.tmp'); folders = os.listdir(tmp_root) if os.path.isdir(tmp_root) else []
    return os.path.join(tmp_root, folders[0]) if len(folders) == 1 else None

def rel_files(base):
    return {os.path.relpath(os.path.join(r, f), base).replace(os.sep, '/') for r, d, fs in os.walk(base) for f in fs}

# ===== правило «что исходники» на настоящем проекте =====
sources = set(project_sources(ROOT))
core = ['sp.py', 'config.py', 'settings.py', 'ui/app_window.py', 'ui/main_window.py', 'services/search_controller.py', 'utils/password.py', 'utils/project_files.py', 'engines/base_engine.py']
check('в исходниках проекта есть основные модули (корень и пакеты)', all(m in sources for m in core), str([m for m in core if m not in sources]))
check('виртуальное окружение, DB, Manticore, .tmp, build и tests в исходники не входят', not any(s.split('/')[0] in ('.venv', 'venv', 'DB', 'Manticore', '.tmp', 'build', 'dist', 'tests') for s in sources))
orphans = []
for name in sorted(os.listdir(ROOT)):
    path = os.path.join(ROOT, name)
    if os.path.isdir(path) and not name.startswith('.') and name not in ('tests', '__pycache__') and not os.path.isfile(os.path.join(path, '__init__.py')) \
            and not os.path.isfile(os.path.join(path, 'pyvenv.cfg')):
        if any(f.endswith('.py') for _r, _d, fs in os.walk(path) for f in fs): orphans.append(name)
if orphans:
    print(f"     ПРИМЕЧАНИЕ: в папках {orphans} есть .py, но нет __init__.py — в архив при запуске они не попадут "
          "(если это ваш код — создайте в такой папке пустой __init__.py; build/dist и т. п. так и должны оставаться вне архива)")

# ===== сама процедура архивации =====
proj = new_project()
backup = run_backup(proj)
check('архив создан: одна папка .tmp/<время>', backup is not None)
backup = backup or env.tmpdir('empty_')
src_set = set(project_sources(proj))
check('в архив попали ВСЕ исходники проекта', all(os.path.exists(os.path.join(backup, s)) for s in src_set), str(sorted(s for s in src_set if not os.path.exists(os.path.join(backup, s)))[:5]))
check('копии совпадают с оригиналами', all(filecmp.cmp(os.path.join(proj, s), os.path.join(backup, s), shallow=False) for s in src_set if os.path.exists(os.path.join(backup, s))))
if os.path.exists(os.path.join(proj, 'mconfig.ini')):
    check('mconfig.ini (не исходник) тоже сохранён', os.path.exists(os.path.join(backup, 'mconfig.ini')))
for rel in ('tests/env.py', 'tests/battery_settings.py', 'tests/data/settings/full.ini', 'tests/data/settings/full.expected.json', 'tests/fake_tk/tkinter/__init__.py', 'tests/data/merger_src/a.txt'):
    check(f'папка tests/ скопирована целиком: {rel}', os.path.exists(os.path.join(backup, rel)))

# ===== главное: новый модуль попадает в архив БЕЗ правки sp.py (так ui/file_viewer.py был забыт) =====
fresh = {'ui/brand_new_viewer.py': b'x = 1\n',            # новый модуль в существующем пакете
         'newpkg/__init__.py': b'', 'newpkg/mod.py': b'y = 2\n',   # новый пакет
         'newpkg/sub/__init__.py': b'', 'newpkg/sub/deep.py': b'z = 3\n',  # вложенный подпакет
         'scratch_tool.py': b'print(1)\n'}                 # новый файл в корне
backup2 = run_backup(new_project(fresh))
check('новый модуль в существующем пакете (как ui/file_viewer.py) попал в архив без правки списка', backup2 and os.path.exists(os.path.join(backup2, 'ui', 'brand_new_viewer.py')))
check('новый пакет и вложенный подпакет попали в архив', backup2 and all(os.path.exists(os.path.join(backup2, *p.split('/'))) for p in ('newpkg/__init__.py', 'newpkg/mod.py', 'newpkg/sub/deep.py')))
check('новый файл в корне проекта попал в архив', backup2 and os.path.exists(os.path.join(backup2, 'scratch_tool.py')))

# ===== лишнего в архив не попадает =====
junk = {'.venv/pyvenv.cfg': b'home = x\n', '.venv/Lib/site-packages/pkg/__init__.py': b'', '.venv/Lib/site-packages/pkg/bad.py': b'# \xa4\xa5 not utf-8\n',
        'DB/book.py': b'1\n', 'build/x.py': b'1\n', 'Manticore/tool.py': b'1\n', 'scripts/tool.py': b'1\n',
        'tests/__pycache__/x.pyc': b'1', 'tests/junk.pyc': b'1'}
backup3 = run_backup(new_project(junk))
got = rel_files(backup3) if backup3 else set()
check('виртуальное окружение (.venv), DB, build и Manticore в архив не попадают', not any(g.startswith(('.venv', 'DB/', 'build/', 'Manticore/')) for g in got), str(sorted(g for g in got if g.startswith(('.venv', 'DB/', 'build/', 'Manticore/')))[:3]))
check('папка без __init__.py (scripts/) — вне правила, в архив не попадает (см. примечание в utils/project_files.py)', 'scripts/tool.py' not in got)
check('кэш и .pyc в архив не попадают', not any('__pycache__' in g or g.endswith('.pyc') for g in got))

# ===== устойчивость =====
real_sources = sp.project_sources
def broken(root): raise OSError("нет доступа к папке")
sp.project_sources = broken
try:
    backup4 = run_backup(new_project())
    ok = True
except Exception as e:
    ok, backup4 = False, None
finally:
    sp.project_sources = real_sources
check('сбой при копировании исходников не мешает запуску программы (предупреждение вместо падения)', ok and backup4 is not None)
check('при таком сбое остальное (tests/, mconfig.ini) всё равно сохраняется', backup4 and os.path.exists(os.path.join(backup4, 'tests', 'env.py')))

# запуск из сборки: копирование пропускается
proj5 = new_project(); sys.frozen = True; real_file = sp.__file__; sp.__file__ = os.path.join(proj5, 'sp.py')
try: sp.backup_source_files()
finally: del sys.frozen; sp.__file__ = real_file
check('запуск из сборки (frozen): копирование пропускается, ничего не создаётся', not os.path.exists(os.path.join(proj5, '.tmp')))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
