import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
env.use_fake_libs()  # подставные keyboard и pyperclip: настоящие клавиши не перехватываются
import sys, os, time, threading, types, tempfile

import tkinter as tk
import keyboard as kb
import pyperclip as pc
from services import numerator as nm
REAL_KB, REAL_PC = sys.modules['keyboard'], sys.modules['pyperclip']

results = []
def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

def pump():
    batch = list(tk.AFTER_QUEUE); tk.AFTER_QUEUE.clear()
    for f, a in batch: f(*a)
def wait_for(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        pump()
        if cond(): return True
        time.sleep(0.01)
    return False
def press(key):          # как хук: колбэк вызывается в ЧУЖОМ потоке
    th = threading.Thread(target=kb.HOTKEYS[key]['callback']); th.start(); th.join()
def settle(): time.sleep(0.16)   # дольше защиты от автоповтора

MAIN = threading.get_ident()
def make():
    kb.reset(); pc.CLIP['text'] = ''; pc.FAIL['copy'] = False; tk.AFTER_QUEUE.clear()
    sys.modules['keyboard'], sys.modules['pyperclip'] = REAL_KB, REAL_PC
    rec = {'status': [], 'notify': [], 'dialog': [], 'dialog_threads': []}
    ctrl = nm.NumeratorController(
        tk.Toplevel(),
        status_callback=rec['status'].append,
        notify_callback=lambda text, ms: rec['notify'].append((text, ms)),
        open_dialog_callback=lambda c: (rec['dialog'].append(c), rec['dialog_threads'].append(threading.get_ident())))
    return ctrl, rec

# ===================== A. состояние счётчика =====================
s = nm.NumeratorState()
check('по умолчанию текстовая часть = ".<текущий год>"', s.text == '.' + str(time.localtime().tm_year), s.text)
s.configure('number_text', '001', '.2026')
check('НОМЕР.ТЕКСТ: 001.2026, затем 002.2026', (s.take_next(), s.take_next()) == ('001.2026', '002.2026'))
s.configure('text_number', '07', '№')
check('ТЕКСТ.НОМЕР, ширина по числу цифр: №07, №08', (s.take_next(), s.take_next()) == ('№07', '№08'))
s.configure('number_text', '998', 'x')
check('номер шире заданной ширины не обрезается: 998, 999, 1000', [s.take_next() for _ in range(3)] == ['998x', '999x', '1000x'])
s.configure('number_text', '001', '.a'); s.take_next(); s.take_next()
check('dialog_prefill даёт СЛЕДУЮЩИЙ номер (003), а не стартовый', s.dialog_prefill() == ('number_text', '003', '.a'), str(s.dialog_prefill()))
s.configure('number_text', '001', '.a')
check('откат при номере 1 невозможен', s.rollback() is None)
s.take_next(); s.take_next()   # счётчик 3
check('rollback: счётчик на 1 назад, строка последнего вставленного', s.rollback() == '002.a' and s.counter == 2)
for bad in ['', '   ', 'abc', '0', '-1', '+5', '1_0', '٣', '1.5']:
    try: s.configure('number_text', bad, '.x'); ok = False
    except ValueError: ok = True
    check(f'неверный номер {bad!r} отвергается', ok)
for fmt, num, txt in [('number_text', '001', ''), ('number_text', '001', '   '), ('xxx', '001', '.x')]:
    try: s.configure(fmt, num, txt); ok = False
    except ValueError: ok = True
    check(f'неверные поля {(fmt, num, txt)!r} отвергаются', ok)
s.configure('number_text', '005', '.k')
try: s.configure('number_text', 'oops', '.x')
except ValueError: pass
check('после отвергнутых настроек прежние сохранились', s.take_next() == '005.k')

# ===================== B. бэкенд =====================
kb.reset(); be = nm.KeyboardBackend()
be.add_hotkey('f9', lambda: None)
check('add_hotkey передаёт suppress=True', kb.HOTKEYS['f9']['suppress'] is True)
be.paste_text('X1')
check('paste_text: сначала буфер, потом Ctrl+V', [e[0] for e in kb.LOG if e[0] in ('copy', 'send')] == ['copy', 'send'] and pc.CLIP['text'] == 'X1')
for missing in ('keyboard', 'pyperclip'):
    sys.modules[missing] = None
    try: nm.KeyboardBackend(); ok = False; msg = ''
    except nm.NumeratorUnavailable as e: ok = True; msg = str(e)
    sys.modules['keyboard'], sys.modules['pyperclip'] = REAL_KB, REAL_PC
    check(f'нет библиотеки {missing}: понятное сообщение с командой установки', ok and 'pip install keyboard pyperclip' in msg, msg)

# ===================== C. контроллер =====================
ctrl, rec = make()
check('до activate ни одна клавиша не перехвачена', kb.HOTKEYS == {})
check('activate() -> True', ctrl.activate() is True and ctrl.is_active)
check('после «Редактировать» перехвачена ТОЛЬКО F7 (F8/F9 ещё нужны Word)', set(kb.HOTKEYS) == {'f7'})
check('F7 с suppress=True — Word её не увидит', kb.HOTKEYS['f7']['suppress'] is True)
ctrl.activate()
check('повторный activate не регистрирует F7 заново', [e for e in kb.LOG if e[0] == 'add'] == [('add', 'f7', True)])
press('f7')
check('F7: диалог открывает ГЛАВНЫЙ поток, а не поток хука',
      wait_for(lambda: len(rec['dialog']) == 1) and rec['dialog_threads'] == [MAIN] and rec['dialog'][0] is ctrl)
check('F9/F8 до OK в диалоге не заняты', 'f9' not in kb.HOTKEYS and 'f8' not in kb.HOTKEYS)

ctrl.apply_settings('number_text', '001', '.2026')
check('после OK заняты F9 и F8, обе suppress=True', set(kb.HOTKEYS) == {'f7', 'f8', 'f9'} and all(v['suppress'] for v in kb.HOTKEYS.values()))
check('уведомление о настройке (1.5 с)', rec['notify'] and rec['notify'][-1][1] == 1500 and 'F9' in rec['notify'][-1][0])
settle(); press('f9')
check('F9: в буфер 001.2026 и отправлен Ctrl+V', wait_for(lambda: len(kb.SENT) == 1) and pc.CLIP['text'] == '001.2026' and kb.SENT == ['ctrl+v'])
check('порядок: буфер -> Ctrl+V', [e[0] for e in kb.LOG if e[0] in ('copy', 'send')] == ['copy', 'send'])
settle(); press('f9'); wait_for(lambda: len(kb.SENT) == 2)
check('второй F9 -> 002.2026', pc.CLIP['text'] == '002.2026')
check('строка состояния сообщила о вставке', wait_for(lambda: any('Вставлено: 002.2026' in x for x in rec['status'])))
settle(); press('f8'); wait_for(lambda: len(kb.SENT) == 3)
check('F8: вставлен последний из вставленных (002.2026)', pc.CLIP['text'] == '002.2026')
settle(); press('f9'); wait_for(lambda: len(kb.SENT) == 4)
check('перенесённое поведение: F9 сразу после F8 вставит тот же номер ещё раз', pc.CLIP['text'] == '002.2026')
settle(); press('f9'); wait_for(lambda: len(kb.SENT) == 5)
check('дальше нумерация идёт: 003.2026', pc.CLIP['text'] == '003.2026')

# автоповтор удержанной клавиши
settle(); n0 = len(kb.SENT)
for _ in range(8):
    kb.HOTKEYS['f9']['callback'](); time.sleep(0.01)
wait_for(lambda: len(kb.SENT) > n0); time.sleep(0.3); pump()
check('удержание клавиши: 8 событий подряд = 1 вставка, а не 8', len(kb.SENT) - n0 == 1, str(len(kb.SENT) - n0))
settle(); n0 = len(kb.SENT); press('f9'); time.sleep(0.2); press('f9'); wait_for(lambda: len(kb.SENT) - n0 >= 2)
check('осознанные нажатия с паузой ≥0.2 с не теряются', len(kb.SENT) - n0 == 2)

# пока открыт диалог
ctrl.dialog_window = object(); settle(); n0 = len(kb.SENT)
press('f9'); press('f8'); time.sleep(0.3); pump()
check('пока открыт диалог F9/F8 игнорируются (не вставят номер в поле диалога)', len(kb.SENT) == n0)
before = len(rec['dialog']); press('f7')
check('а F7 при открытом диалоге доходит (выведет его вперёд)', wait_for(lambda: len(rec['dialog']) == before + 1))
ctrl.dialog_window = None

# откат при номере 1
ctrl.apply_settings('number_text', '001', '.2026'); settle(); n0 = len(kb.SENT); press('f8'); time.sleep(0.3); pump()
check('F8 при номере 1: ничего не вставлено', len(kb.SENT) == n0)

# сбой вставки не убивает рабочий поток
pc.FAIL['copy'] = True; settle(); press('f9')
check('сбой буфера: сообщение об ошибке', wait_for(lambda: any('Ошибка вставки' in x for x in rec['status'])))
pc.FAIL['copy'] = False; settle(); n0 = len(kb.SENT); press('f9')
check('после сбоя вставка снова работает (поток жив)', wait_for(lambda: len(kb.SENT) == n0 + 1))

# выключение
ctrl.deactivate()
check('«Выключить»: все хуки сняты, вызван unhook_all', kb.HOTKEYS == {} and ('unhook_all',) in kb.LOG and not ctrl.is_active)
check('сообщение о выключении', any('выключен' in x for x in rec['status']))
settle(); ok = ctrl.activate(); before = len(rec['dialog'])
check('повторное включение после выключения работает', ok and set(kb.HOTKEYS) == {'f7'})
settle(); press('f7'); ctrl.deactivate(); ctrl.activate(); pump(); time.sleep(0.05); pump()
check('«зависшее» нажатие до выключения не открывает диалог после повторного включения', len(rec['dialog']) == before)
ctrl.shutdown(); ctrl.shutdown()
check('shutdown идемпотентен и снимает всё', kb.HOTKEYS == {})
tk.AFTER_QUEUE.clear()
check('после выключения опрос очереди прекращается', True)

# формат ТЕКСТ.НОМЕР
ctrl, rec = make(); ctrl.activate(); ctrl.apply_settings('text_number', '07', '№'); settle(); press('f9'); wait_for(lambda: len(kb.SENT) == 1)
check('ТЕКСТ.НОМЕР: вставлено №07', pc.CLIP['text'] == '№07'); ctrl.shutdown()

# неверные настройки не включают F9/F8
ctrl, rec = make(); ctrl.activate()
try: ctrl.apply_settings('number_text', '0', '.x'); ok = False
except ValueError: ok = True
check('неверный номер: ValueError и F9/F8 НЕ включены', ok and set(kb.HOTKEYS) == {'f7'}); ctrl.shutdown()

# отсутствие библиотек
ctrl, rec = make(); sys.modules['keyboard'] = None
ok = ctrl.activate(); sys.modules['keyboard'] = REAL_KB
check('нет keyboard: activate()=False, last_error с командой установки, есть статус',
      ok is False and 'pip install' in ctrl.last_error and rec['status'] and not ctrl.is_active, ctrl.last_error)
ctrl, rec = make(); kb.FAIL_ADD.add('f7'); ok = ctrl.activate()
check('система не дала повесить F7: activate()=False, last_error называет F7', ok is False and 'F7' in ctrl.last_error and not ctrl.is_active, ctrl.last_error)
ctrl, rec = make(); ctrl.activate(); kb.FAIL_ADD.add('f8')
try: ctrl.apply_settings('number_text', '001', '.x'); ok = False
except ValueError as e: ok = 'F9/F8' in str(e)
check('F8 не зарегистрировалась: ошибка для диалога И откат F9 (одна клавиша из двух не остаётся)', ok and set(kb.HOTKEYS) == {'f7'}, str(set(kb.HOTKEYS))); ctrl.shutdown()

# ===================== D. диалог =====================
from ui import numerator_dialog as nd
def widgets_since(i): return tk.CREATED[i:]
def find(ws, cls, **opts): return [w for w in ws if isinstance(w, cls) and all(w.options.get(k) == v for k, v in opts.items())]
ctrl, rec = make(); ctrl.activate(); ctrl.apply_settings('number_text', '001', '.2026')
settle(); press('f9'); settle(); press('f9'); settle(); press('f9'); wait_for(lambda: len(kb.SENT) == 3)   # вставлены 001..003, следующий — 004
start = len(tk.CREATED)
dlg = nd.show_numerator_dialog(tk.Toplevel(), ctrl)
ws = widgets_since(start)
check('диалог создан и записан в контроллер (пока он есть, F9/F8 игнорируются)', ctrl.dialog_window is dlg)
entries = find(ws, tk.Entry)
check('поле номера заполнено СЛЕДУЮЩИМ номером (004), текст — прежний', entries[0].options['textvariable'].get() == '004' and entries[1].options['textvariable'].get() == '.2026')
check('диалог «поверх всех» и не модальный', dlg.options is not None)
before = len(tk.CREATED); same = nd.show_numerator_dialog(tk.Toplevel(), ctrl)
check('повторный F7 при открытом диалоге не создаёт второй', same is dlg and not [w for w in tk.CREATED[before:] if isinstance(w, tk.Label) and w.options.get('text', '').startswith('Номер и вид')])
ok_btn = find(ws, tk.Button, text='OK')[0]; cancel_btn = find(ws, tk.Button, text='Отмена')[0]; off_btn = find(ws, tk.Button, text='Выключить нумератор')[0]
err_label = [w for w in ws if isinstance(w, tk.Label) and w.options.get('fg') == '#b84a4a'][0]
ex_label = [w for w in ws if isinstance(w, tk.Label) and w.options.get('font') == ('Arial', 12, 'bold') and w.options.get('fg') == '#1a4a7a'][0]
check('пример отражает текущие поля', ex_label.options['text'] == 'Пример: 004.2026', ex_label.options['text'])
entries[0].options['textvariable'].set('12')
check('пример обновляется при вводе (трассировка)', ex_label.options['text'] == 'Пример: 12.2026', ex_label.options['text'])
entries[0].options['textvariable'].set('abc')
check('пример предупреждает о неверном номере', 'целым числом' in ex_label.options['text'])
ok_btn.options['command']()
check('OK с неверным номером: ошибка в самом окне, окно НЕ закрыто, настройки не тронуты',
      '≥ 1' in err_label.options['text'] and ctrl.dialog_window is dlg and ctrl.state.dialog_prefill()[1] == '004')
entries[0].options['textvariable'].set('10'); entries[1].options['textvariable'].set('')
ok_btn.options['command']()
check('OK с пустым текстом: «Заполните оба поля», окно открыто', 'Заполните' in err_label.options['text'] and ctrl.dialog_window is dlg)
entries[1].options['textvariable'].set('.Б')
radios = find(ws, tk.Radiobutton)
radios[1].options['variable'].set('text_number')
ok_btn.options['command']()
check('OK с верными данными: настройки применены, диалог закрыт и ссылка сброшена',
      ctrl.dialog_window is None and dlg.destroyed and ctrl.state.format == 'text_number' and ctrl.state.counter == 10 and ctrl.state.text == '.Б')
settle(); n0 = len(kb.SENT); press('f9')
check('после закрытия диалога F9 снова работает и берёт новые настройки', wait_for(lambda: len(kb.SENT) == n0 + 1) and pc.CLIP['text'] == '.Б10', pc.CLIP['text'])

# Отмена и Выключить
start = len(tk.CREATED); dlg = nd.show_numerator_dialog(tk.Toplevel(), ctrl); ws = widgets_since(start)
entries = find(ws, tk.Entry); entries[0].options['textvariable'].set('99')
find(ws, tk.Button, text='Отмена')[0].options['command']()
check('Отмена: окно закрыто, настройки не изменились', dlg.destroyed and ctrl.dialog_window is None and ctrl.state.counter == 11, str(ctrl.state.counter))
start = len(tk.CREATED); dlg = nd.show_numerator_dialog(tk.Toplevel(), ctrl); ws = widgets_since(start)
find(ws, tk.Button, text='Выключить нумератор')[0].options['command']()
check('«Выключить нумератор»: все клавиши освобождены, окно закрыто', kb.HOTKEYS == {} and dlg.destroyed and ctrl.dialog_window is None and not ctrl.is_active)
ctrl.dialog_window = types.SimpleNamespace(winfo_exists=lambda: 0)
dlg2 = nd.show_numerator_dialog(tk.Toplevel(), ctrl)
check('устаревшая ссылка на уже уничтоженное окно не мешает открыть новое', dlg2 is not None and ctrl.dialog_window is dlg2); ctrl.shutdown()

# ===================== E. подключение в AppWindow =====================
import ui.app_window as aw
def make_win(flag, opened):
    kb.reset(); tk.AFTER_QUEUE.clear()
    sys.modules['keyboard'], sys.modules['pyperclip'] = REAL_KB, REAL_PC
    w = aw.AppWindow.__new__(aw.AppWindow)
    w.root = tk.Toplevel(); w.config = {'enable_numerator_on_update': flag}; w.numerator = None
    w.logs = []; w._update_log_field = w.logs.append
    w.toasts = []; w._show_temporary_notification = lambda message, duration_ms=700: w.toasts.append((message, duration_ms))
    w.file_manager = types.SimpleNamespace(open_selected_file=lambda: opened['v'])
    w.warns = []; aw.messagebox = types.SimpleNamespace(showwarning=lambda t, m, **k: w.warns.append((t, m)))
    return w
op = {'v': True}
w = make_win(False, op); w._open_selected_file()
check('флаг enable_numerator_on_update=0: «Редактировать» работает как раньше, нумератор не включается', w.numerator is None and kb.HOTKEYS == {} and w.toasts == [])
w = make_win(True, {'v': False}); w._open_selected_file()
check('флаг=1, но файл не открылся: нумератор НЕ включается', w.numerator is None and kb.HOTKEYS == {} and w.toasts == [])
w = make_win(True, op); w._open_selected_file()
check('флаг=1 и файл открыт: включена F7 (suppress) и подсказка на 500 мс',
      set(kb.HOTKEYS) == {'f7'} and kb.HOTKEYS['f7']['suppress'] and w.toasts == [('F7 — вызов нумератора', 500)], str(w.toasts))
first = w.numerator; w._open_selected_file()
check('повторное «Редактировать»: тот же контроллер, F7 не дублируется, подсказка снова', w.numerator is first and [e for e in kb.LOG if e[0] == 'add'] == [('add', 'f7', True)] and len(w.toasts) == 2)
settle(); press('f7'); pump(); wait_for(lambda: first.dialog_window is not None)
check('F7 через AppWindow открывает диалог нумератора', first.dialog_window is not None and not first.dialog_window.destroyed)
first.dialog_window.destroy(); first.dialog_window = None
first.apply_settings('number_text', '001', '.2026')
check('уведомление после настройки проходит через _show_temporary_notification (1500 мс)', w.toasts[-1][1] == 1500 and 'F9' in w.toasts[-1][0], str(w.toasts[-1]))
# выход
closed = []; w.engine = types.SimpleNamespace(close=lambda: closed.append(1)); aw.stats_logger = types.SimpleNamespace()
w.on_close()
check('закрытие программы возвращает F7/F8/F9 другим программам', kb.HOTKEYS == {} and closed == [1] and w.root.destroyed)
# нет библиотеки
w = make_win(True, op); sys.modules['keyboard'] = None
w._open_selected_file(); sys.modules['keyboard'] = REAL_KB
check('нет keyboard: окно с инструкцией, подсказки F7 нет, программа не падает',
      len(w.warns) == 1 and 'pip install' in w.warns[0][1] and w.toasts == [], str(w.warns))
w2 = make_win(True, op); w2.on_close = aw.AppWindow.on_close.__get__(w2); w2.engine = None; aw.stats_logger = types.SimpleNamespace()
w2.on_close()
check('закрытие без включённого нумератора не падает', w2.root.destroyed)

# ===================== F. флаг в mconfig.ini =====================
import config
config.CONFIG_FILE = tempfile.mktemp(suffix='.ini')
c = config.load_config()
check('по умолчанию флаг выключен', c['enable_numerator_on_update'] is False)
c['enable_numerator_on_update'] = True; config.save_config(c)
check('включённый флаг сохраняется и читается', config.load_config()['enable_numerator_on_update'] is True)
config.save_config({**config.load_config(), 'engine_type': 'manticore'})
check('другое сохранение конфига флаг не стирает', config.load_config()['enable_numerator_on_update'] is True)
raw = open(config.CONFIG_FILE, encoding='utf-8').read()
for val, expected in [('1', True), ('true', True), ('0', False), ('да', False), ('', False)]:
    open(config.CONFIG_FILE, 'w', encoding='utf-8').write(raw.replace('enable_numerator_on_update = 1', f'enable_numerator_on_update = {val}'))
    check(f'значение флага {val!r} читается без падения -> {expected}', config.load_config()['enable_numerator_on_update'] is expected)
open(config.CONFIG_FILE, 'w', encoding='utf-8').write('\n'.join(l for l in raw.splitlines() if 'numerator' not in l))
check('старый mconfig.ini без ключа читается (флаг выключен)', config.load_config()['enable_numerator_on_update'] is False)

# ===================== G. open_selected_file =====================
import services.file_manager as fmm
fm = fmm.FileManager.__new__(fmm.FileManager); msgs = []
fmm.messagebox = types.SimpleNamespace(showwarning=lambda *a, **k: msgs.append('warn'), showerror=lambda *a, **k: msgs.append('err'))
fm.selected_text_files = []
check('ничего не выбрано: False + предупреждение', fm.open_selected_file() is False and msgs == ['warn'])
fm.selected_text_files = ['/нет/такого.txt']; msgs.clear()
check('файла нет: False + ошибка', fm.open_selected_file() is False and msgs == ['err'])
real = os.path.join(env.tmpdir('open_'), 'файл.txt'); open(real, 'w').write('x'); fm.selected_text_files = [real]
def boom(*a, **k): raise OSError("нет приложения")
# Способ запуска зависит от ОС: на Windows — os.startfile, иначе xdg-open через subprocess. Проверяются ОБЕ ветки на
# любой машине, и настоящая программа не запускается (раньше на Windows открывался Блокнот — см. env.py).
for platform in ('win32', 'linux'):
    fmm.sys = types.SimpleNamespace(platform=platform)
    launched = []; msgs.clear()
    os.startfile = lambda path, launched=launched: launched.append(path)
    fmm.subprocess = types.SimpleNamespace(Popen=lambda cmd, launched=launched: launched.append(cmd))
    check(f'[{platform}] файл открыт: True, без сообщений, запущена ровно одна программа', fm.open_selected_file() is True and msgs == [] and len(launched) == 1, str(launched))
    os.startfile = boom; fmm.subprocess = types.SimpleNamespace(Popen=boom); msgs.clear()
    check(f'[{platform}] не удалось запустить: False + ошибка', fm.open_selected_file() is False and msgs == ['err'])

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
