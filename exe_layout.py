"""Раскладка файлов в собранной программе (PyInstaller). Импортируется ПЕРВЫМ в sp.py.

PyInstaller складывает ресурсы в _internal. Здесь при запуске из exe они переносятся
на один уровень с Sineva.exe и папкой DB: Manticore/, mconfig.ini, readme.txt, key_concepts.txt.
Уже существующее рядом с exe не трогаем (настройки и индексы пользователя).
"""
import os
import shutil
import sys

_ITEMS = ('Manticore', 'mconfig.ini', 'readme.txt', 'key_concepts.txt')


def ensure_layout():
    if not getattr(sys, 'frozen', False):
        return
    inner = getattr(sys, '_MEIPASS', None)
    if not inner:
        return
    root = os.path.dirname(sys.executable)
    if os.path.normcase(os.path.abspath(inner)) == os.path.normcase(os.path.abspath(root)):
        return
    for name in _ITEMS:
        src = os.path.join(inner, name)
        dst = os.path.join(root, name)
        if not os.path.exists(src):
            continue
        try:
            if os.path.exists(dst):
                continue                      # у пользователя уже есть своё
            try:
                shutil.move(src, dst)         # переносим: второй копии в _internal не остаётся
            except Exception:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        except Exception as e:
            print("Не удалось разложить %s рядом с exe: %s" % (name, e))


ensure_layout()
