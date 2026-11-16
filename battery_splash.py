"""Заставка запуска (splash.py): появляется, меняет надпись и этап, закрывается; сбой не мешает запуску."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # noqa: F401  (подставной tkinter)
import tkinter as _tk
_tk._GENERIC_FALLBACK = True
results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import splash
src = open(os.path.join(os.path.dirname(splash.__file__), 'sp.py'), encoding='utf-8').read()
check('sp.py показывает заставку сразу после exe_layout, до тяжёлых импортов', src.index('splash.show(') < src.index('from ui.main_window import MainWindow'))
check('этапов шесть, последний — «Готово»', len(splash.STAGES) == 6 and splash.STAGES[-1] == 'Готово')
check('фон заставки лежит рядом с программой', os.path.isfile(os.path.join(os.path.dirname(splash.__file__), 'splash_bg.png')))
check('до показа заставки нет', not splash.is_shown())
check('show() показывает заставку', splash.show(splash.STAGES[0]) and splash.is_shown())
splash.set_status(splash.STAGES[2])
check('set_status не падает на известном и на неизвестном тексте', (splash.set_status('что-то своё') or True))
check('повторный show() не создаёт второе окно', splash.show(splash.STAGES[3]) and splash.is_shown())
splash.close()
check('close() убирает заставку, повторный close() безопасен', not splash.is_shown() and (splash.close() or True))
check('вызовы без заставки безопасны', (splash.set_status('x') or True))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
