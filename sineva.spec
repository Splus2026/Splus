# -*- mode: python ; coding: utf-8 -*-
"""Сборка Синевы+ в папку с Sineva.exe (режим onedir: рядом с exe лежит _internal).

Вариант выбирается переменной окружения SINEVA_VARIANT (её ставит build_exe.bat):
  full    — всё, включая модель MiniLM (PM): sentence-transformers + PyTorch, это сотни мегабайт;
  compact — без MiniLM и без прочего лишнего. FastText (FT) и LSA работают как обычно;
            при выборе MiniLM программа покажет понятное сообщение (см. vector_engines/minilm_model.py).

Запуск вручную из корня проекта:
    set SINEVA_VARIANT=compact
    python -m PyInstaller --noconfirm --clean sineva.spec
"""
import os

VARIANT = os.environ.get('SINEVA_VARIANT', 'full').strip().lower()
if VARIANT not in ('full', 'compact'):
    raise SystemExit("SINEVA_VARIANT должен быть full или compact, а не %r" % VARIANT)

root = os.path.abspath(SPECPATH)


def _add_file(datas, name, dest='.'):
    path = os.path.join(root, name)
    if os.path.isfile(path):
        datas.append((path, dest))
    else:
        print("[sineva.spec] файла нет, пропускаю: " + name)


def _add_dir(datas, name):
    path = os.path.join(root, name)
    if os.path.isdir(path):
        datas.append((path, name))
    else:
        print("[sineva.spec] папки нет, пропускаю: " + name)


# mconfig.ini, readme.txt, key_concepts.txt, DB/ и Manticore/ кладутся НЕ в _internal,
# а рядом с Sineva.exe (копируются после COLLECT, см. конец файла): так их видно и можно править.
datas = []
binaries = []

# gensim (FastText) содержит скомпилированные модули и подгружает их динамически, поэтому
# PyInstaller сам их не находит: собираем пакет целиком вместе с зависимостями.
from PyInstaller.utils.hooks import collect_all
_gh = []
for _pkg in ('gensim', 'smart_open', 'scipy'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        # тесты и служебные скрипты пакетов не нужны — только раздувают сборку
        _gh += [m for m in _h if '.test' not in m and '.scripts' not in m]
    except Exception as _e:
        print("[sineva.spec] collect_all(%s) не удалось: %s" % (_pkg, _e))
# vector_models/ и indicies_* в сборку не кладём: это ваши данные, они создаются рядом с exe.

# Модули, подключаемые лениво (внутри функций) и по имени — подстраховка для анализатора.
hiddenimports = [
    'exe_layout',
    'pymysql', 'psutil', 'openpyxl', 'docx', 'pypdf', 'PyPDF2',
    'keyboard', 'pyperclip',
    'nltk', 'nltk.stem.snowball', 'nltk.tokenize',
    'gensim', 'gensim.models',
    'sklearn.decomposition', 'sklearn.feature_extraction.text', 'sklearn.cluster', 'sklearn.manifold',
    'scipy.cluster.hierarchy', 'scipy.spatial.distance',
    'elasticsearch', 'elasticsearch.helpers',
]
hiddenimports += _gh
if VARIANT == 'full':
    hiddenimports += ['sentence_transformers', 'torch', 'transformers']

# Всегда лишнее: не нужно ни одному модулю проекта.
excludes = [
    'matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook', 'pytest',
    'tests', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx', 'numba', 'tensorboard',
]
if VARIANT == 'compact':
    # Всё, что тянет MiniLM (PM), и сам PyTorch.
    excludes += [
        'sentence_transformers', 'torch', 'torchvision', 'torchaudio', 'transformers',
        'tokenizers', 'safetensors', 'huggingface_hub', 'tensorflow', 'keras', 'onnxruntime',
    ]

a = Analysis(
    ['sp.py'],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Sineva',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,       # без чёрного окна; чтобы видеть print() при отладке — поставьте True
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Sineva_' + VARIANT,
)


# Копируем ресурсы рядом с Sineva.exe (на уровень папки DB), а не в _internal.
import shutil
_out = os.path.join(os.path.abspath(DISTPATH), 'Sineva_' + VARIANT)
for _name in ('mconfig.ini', 'readme.txt', 'key_concepts.txt'):
    _src = os.path.join(root, _name)
    if os.path.isfile(_src):
        shutil.copy2(_src, os.path.join(_out, _name))
    else:
        print("[sineva.spec] файла нет, пропускаю: " + _name)
for _name in ('DB', 'Manticore'):
    _src = os.path.join(root, _name)
    _dst = os.path.join(_out, _name)
    if os.path.isdir(_src):
        if os.path.isdir(_dst):
            shutil.rmtree(_dst)
        shutil.copytree(_src, _dst)
    else:
        print("[sineva.spec] папки нет, пропускаю: " + _name)
