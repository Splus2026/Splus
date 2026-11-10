"""Какие файлы считаются исходниками проекта.

   Нужно в двух местах: архивация при запуске (sp.py, backup_source_files) и автоматические
   проверки (tests/). Правило одно и живёт здесь, чтобы они не разошлись.

   ПРАВИЛО: .py-файлы в КОРНЕ проекта и во всех ПАКЕТАХ верхнего уровня — папках с
   __init__.py (engines, services, ui, utils, vector_engines и любой новый пакет, в том числе
   вложенные подпакеты). Всё остальное — виртуальное окружение (.venv лежит прямо в проекте),
   DB, Manticore, build, dist, .tmp, кэш — под правило не попадает САМО, без списка исключений:
   в корне у этих папок нет __init__.py. Список исключений устаревал бы при каждой новой папке
   (так и вышло: .venv в него не попал, и проверки пошли читать тысячи чужих файлов), а
   копирование «всего подряд» при каждом запуске программы потащило бы за собой окружение.

   Единственный случай, когда новый модуль не попадёт в архив: он лежит в новой папке БЕЗ
   __init__.py. Достаточно создать в ней пустой __init__.py (как в остальных пакетах проекта).

   Исключается папка tests: она копируется целиком отдельно (вместе с данными проверок)."""

import os


def project_sources(root):
    """Относительные пути (через «/») исходников проекта: корень и пакеты верхнего уровня."""
    result = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path) and name.endswith('.py'):
            result.append(name)
        elif os.path.isdir(path) and name != 'tests' and os.path.isfile(os.path.join(path, '__init__.py')):
            for dir_path, dir_names, file_names in os.walk(path):
                dir_names[:] = sorted(d for d in dir_names if d != '__pycache__')
                for file_name in sorted(file_names):
                    if file_name.endswith('.py'):
                        result.append(os.path.relpath(os.path.join(dir_path, file_name), root).replace(os.sep, '/'))
    return result
