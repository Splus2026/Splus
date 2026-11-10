"""Запуск всех автоматических проверок проекта.

   Из корня проекта:
       python tests/run_all.py              # все батареи, со сводкой
       python tests/run_all.py marks keyc   # только те, в чьём имени есть эти слова
       python tests/battery_marks.py        # одна батарея напрямую (подробный вывод)
       python -m unittest tests.test_batteries   # то же через unittest

   Батарея — файл tests/battery_*.py: последовательность проверок check(описание, условие).
   Каждая запускается в СВОЁМ процессе, потому что подменяет модули (tkinter, messagebox,
   пути в config и т. д.), и в одном процессе они мешали бы друг другу.
   Код возврата 0 — все проверки всех батарей прошли."""

import glob
import os
import re
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
SUMMARY_RE = re.compile(r'Проверок:\s*(\d+),\s*провалено:\s*(\d+)')
KNOWN_PREFIX = 'ИЗВЕСТНАЯ ОШИБКА'  # ошибка, о которой известно: прогон не ломает; после исправления проверка сама станет обычной


def find_batteries(words=()):
    paths = sorted(glob.glob(os.path.join(TESTS, 'battery_*.py')))
    if words:
        paths = [p for p in paths if any(w in os.path.basename(p) for w in words)]
    return paths


def run_battery(path, timeout=600):
    """Запускает одну батарею. Возвращает словарь: name, checks, failed, fail_lines, ok, tail, seconds.
       Батарея без итоговой строки «Проверок: N, провалено: M» (упала до конца) считается проваленной."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')  # консоль Windows бывает cp1251, а проект печатает эмодзи
    started = time.time()
    try:
        done = subprocess.run([sys.executable, path], cwd=ROOT, env=env, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=timeout)
        output, code = (done.stdout or '') + (done.stderr or ''), done.returncode
    except subprocess.TimeoutExpired:
        output, code = f'Превышено время ожидания ({timeout} с)', -1
    match = SUMMARY_RE.findall(output)
    checks, failed = (int(match[-1][0]), int(match[-1][1])) if match else (0, 0)
    fail_lines = [line for line in output.splitlines() if line.startswith('FAIL')]
    known = [line for line in output.splitlines() if line.startswith(KNOWN_PREFIX)]
    ok = bool(match) and failed == 0 and code == 0 and not fail_lines  # FAIL-строка после итога — от предохранителя запуска программ
    return {'name': os.path.basename(path)[len('battery_'):-3], 'checks': checks, 'failed': failed,
            'fail_lines': fail_lines, 'known': known, 'ok': ok, 'seconds': time.time() - started,
            'tail': '\n'.join(output.strip().splitlines()[-15:]) if not ok else ''}


def main(argv):
    paths = find_batteries(argv)
    if not paths:
        print('Батарей не найдено.')
        return 1
    results = []
    for path in paths:
        r = run_battery(path)
        results.append(r)
        mark = 'OK  ' if r['ok'] else 'FAIL'
        print(f"{mark} {r['name']:<22} проверок: {r['checks']:4d}  провалено: {r['failed']:3d}  ({r['seconds']:.1f} с)")
        for line in r['fail_lines']:
            print('       ' + line)
        if r['known']:
            print(f"       известных ошибок: {len(r['known'])}")
        if not r['ok'] and not r['fail_lines']:
            print('       Батарея не дошла до конца:\n' + '\n'.join('         ' + l for l in r['tail'].splitlines()))
    total = sum(r['checks'] for r in results)
    known_all = [(r['name'], line[len(KNOWN_PREFIX):].strip()) for r in results for line in r['known']]
    if known_all:
        print(f"\nИзвестные ошибки в коде проекта ({len(known_all)}) — прогон не ломают, исчезнут из списка сами после исправления:")
        for name, text in known_all:
            print(f"  [{name}] {text[:150]}")
    bad = [r for r in results if not r['ok']]
    print(f"\nИтого: {len(results)} батарей, {total} проверок, "
          + ('все прошли.' if not bad else f"НЕ прошли батареи: {', '.join(r['name'] for r in bad)}."))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
