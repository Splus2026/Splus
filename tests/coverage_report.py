"""Покрытие кода автоматическими проверками (без сторонних пакетов — на стандартном trace).

       python tests/coverage_report.py

   Запускает каждую батарею в своём процессе под трассировкой, объединяет результаты и
   печатает по каждому модулю: сколько исполняемых строк и сколько из них выполнено
   проверками. Занимает около минуты-двух. Это ПОКРЫТИЕ СТРОК: «строка выполнена» не
   значит «поведение проверено» — но «не выполнена» значит, что поломку в ней проверки
   не заметят."""

import glob
import json
import os
import runpy
import subprocess
import sys
import tempfile
import trace

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)
from tests.sources import project_sources  # noqa: E402


def trace_one(battery, out_path):
    """Режим одной батареи (вызывается из дочернего процесса)."""
    tracer = trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix, sys.exec_prefix])

    def go():
        try:
            runpy.run_path(battery, run_name='__main__')
        except SystemExit:
            pass

    tracer.runfunc(go)
    executed = {}
    for (file_name, line), _count in tracer.results().counts.items():
        rel = os.path.relpath(file_name, ROOT) if file_name.startswith(ROOT) else None
        if rel and rel.replace(os.sep, '/').split('/')[0] != 'tests' and '__pycache__' not in rel:
            executed.setdefault(rel, []).append(line)
    with open(out_path, 'w') as f:
        json.dump(executed, f)


def main():
    union = {}
    work = tempfile.mkdtemp(prefix='cov_')
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    for battery in sorted(glob.glob(os.path.join(TESTS, 'battery_*.py'))):
        out_path = os.path.join(work, os.path.basename(battery) + '.json')
        subprocess.run([sys.executable, __file__, '--one', battery, out_path], cwd=ROOT, env=env,
                       capture_output=True, timeout=1800)
        if os.path.exists(out_path):
            with open(out_path) as f:
                for rel, lines in json.load(f).items():
                    union.setdefault(rel, set()).update(lines)
    rows = []
    for rel in project_sources(ROOT):
        executable = set(trace._find_executable_linenos(os.path.join(ROOT, rel)))
        rows.append((rel, len(executable), len(union.get(rel.replace('/', os.sep), set()) & executable)))
    rows.sort(key=lambda r: -(r[2] / r[1] if r[1] else 0))
    total_lines, total_hit = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"{'модуль':38s} {'строк':>6} {'выполнено':>10} {'покрытие':>9}")
    for rel, lines, hit in rows:
        print(f"{rel:38s} {lines:6d} {hit:10d} {100 * hit // lines if lines else 0:8d}%")
    print(f"{'ИТОГО':38s} {total_lines:6d} {total_hit:10d} {100 * total_hit // max(total_lines, 1):8d}%")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--one':
        trace_one(sys.argv[2], sys.argv[3])
    else:
        main()
