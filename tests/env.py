"""Окружение автоматических проверок. Каждая батарея (battery_*.py) импортирует
   этот модуль ПЕРВЫМ — до любого импорта проекта:

   - ставит корень проекта и подставной tkinter (tests/fake_tk) в начало
     sys.path: проверки идут без окон и без настоящего Tk, быстро и одинаково на
     любой машине (в том числе без экрана);
   - подменяет elasticsearch пустой заглушкой (в проекте он нужен только движку
     Elastic, который проверки не используют);
   - даёт ROOT (корень проекта), DATA (tests/data) и tmpdir();
   - ставит ПРЕДОХРАНИТЕЛЬ: код проекта и самих проверок не может запустить внешнюю
     программу (os.startfile, subprocess, os.system, webbrowser) — вместо этого
     RuntimeError. Проверка, которой нужен такой вызов, подменяет его сама (см. README).

   Батарея ПОДМЕНЯЕТ модули (tk.Button, tk.Toplevel, messagebox в окнах, пути в
   config...) и потому всегда запускается в СВОЁМ процессе: tests/run_all.py и
   tests/test_batteries.py делают именно так. Запуск одной батареи:
       python tests/battery_marks.py"""

import atexit
import os
import subprocess
import sys
import tempfile
import types
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, 'tests')
DATA = os.path.join(TESTS, 'data')

for _path in (os.path.join(TESTS, 'fake_tk'), ROOT):  # ROOT окажется первым, fake_tk — вторым
    if _path not in sys.path:
        sys.path.insert(0, _path)

_elastic = types.ModuleType('elasticsearch')
_elastic.Elasticsearch = object
_elastic.NotFoundError = Exception
_elastic_helpers = types.ModuleType('elasticsearch.helpers')
_elastic_helpers.bulk = lambda *a, **k: None
sys.modules['elasticsearch'] = _elastic
sys.modules['elasticsearch.helpers'] = _elastic_helpers


def use_fake_libs():
    """Подставные keyboard и pyperclip (нумератор разбивки): без них проверки
       перехватывали бы настоящие клавиши на машине разработчика."""
    path = os.path.join(TESTS, 'fake_libs')
    if path not in sys.path:
        sys.path.insert(0, path)


def tmpdir(prefix='t_'):
    return tempfile.mkdtemp(prefix=prefix)


# ---------- предохранитель от запуска внешних программ ----------
# Случай из жизни: проверка «Редактировать» подменяла запуск программ только для Linux, а на
# Windows код использует os.startfile — и на машине разработчика по-настоящему открылся
# Блокнот. Тесты не должны запускать ничего реального (а проект умеет запускать и сервер
# Manticore), поэтому такой вызов теперь — ошибка.
#
# Блокируются только вызовы, которые НАПРЯМУЮ делает код ПРОЕКТА или проверок: сторонние
# библиотеки (numpy, asyncio...) вправе запускать процессы, и класс subprocess.Popen должен
# оставаться классом (от него наследуются, например, asyncio на Windows) — поэтому подменяется
# его __init__, а не сам класс.

def _is_ours(file_name):
    path = os.path.abspath(file_name)
    return path.startswith(ROOT + os.sep) and not any(
        part in ('site-packages', '.venv', 'venv') for part in path.split(os.sep))


def _called_from_ours(skip_files=()):
    """Кто ВЫЗВАЛ запуск: берётся ближайший вызывающий кадр (служебные кадры из skip_files —
       например, сам subprocess.py при subprocess.run -> Popen — пропускаются). Смотреть на
       ЛЮБОЙ кадр стека нельзя: тогда «наш код вызвал библиотеку, а та запустила процесс» стало
       бы запуском из проекта, и библиотеки перестали бы работать."""
    try:
        frame = sys._getframe(2)  # 0 — эта функция, 1 — обёртка-предохранитель, 2 — тот, кто вызвал обёртку
    except ValueError:
        return False
    while frame is not None and os.path.basename(frame.f_code.co_filename) in skip_files:
        frame = frame.f_back
    return frame is not None and _is_ours(frame.f_code.co_filename)


BLOCKED = []  # попытки запуска, остановленные предохранителем (видны в итоге, даже если код проекта поймал исключение)


def _report_blocked():
    for what in dict.fromkeys(BLOCKED):
        print(f"FAIL проверка пыталась запустить внешнюю программу ({what}) — подмените вызов в батарее (tests/README.md)", flush=True)


atexit.register(_report_blocked)


def _blocked(what):
    BLOCKED.append(what)
    raise RuntimeError(f"Проверка (или код проекта в ней) попыталась запустить внешнюю программу: {what}. "
                       "Подмените этот вызов в самой батарее — см. tests/README.md.")


def _guard_function(owner, name, label):
    original = getattr(owner, name, None)
    if original is None:
        return

    def guarded(*args, **kwargs):
        if _called_from_ours():
            _blocked(label)
        return original(*args, **kwargs)
    guarded.__name__ = name
    setattr(owner, name, guarded)


_original_popen_init = subprocess.Popen.__init__


def _guarded_popen_init(self, *args, **kwargs):
    if _called_from_ours(skip_files=('subprocess.py',)):
        _blocked('subprocess.Popen / run / call')
    return _original_popen_init(self, *args, **kwargs)


def install_launch_guard():
    subprocess.Popen.__init__ = _guarded_popen_init
    _guard_function(os, 'startfile', 'os.startfile')   # есть только на Windows
    _guard_function(os, 'system', 'os.system')
    _guard_function(os, 'popen', 'os.popen')
    for name in ('open', 'open_new', 'open_new_tab'):
        _guard_function(webbrowser, name, f'webbrowser.{name}')
    try:
        import winsound  # только Windows: проверки не должны пищать
        for name in ('Beep', 'MessageBeep', 'PlaySound'):
            setattr(winsound, name, lambda *a, **k: None)
    except ImportError:
        pass


install_launch_guard()
