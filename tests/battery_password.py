import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, os, types, tempfile, hashlib, binascii
from datetime import datetime
import tkinter as tk
results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from utils import password as P
# ===== A. алгоритм =====
def old_hash(pw, salt):      # дословно как в прежней версии (search_engine.py)
    return binascii.hexlify(hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt.encode('utf-8'), 100000)).decode('utf-8')
salt = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
check('хеш совпадает с прежней версией (значения из старого конфига останутся действительны)', P.hash_password('секрет123', salt) == old_hash('секрет123', salt))
h, s = P.make_password_record('мой пароль')
check('make_password_record: соль 32 hex-символа, хеш 64, проверяется', len(s) == 32 and len(h) == 64 and P.hash_password('мой пароль', s) == h)
check('соль каждый раз новая', P.make_password_record('x')[1] != P.make_password_record('x')[1])
D = datetime(2026, 10, 7)
check('прежний пароль — день и месяц (7 октября -> 0710)', P.date_password(D) == '0710' and P.date_password(datetime(2026, 1, 31)) == '3101')
check('без сменного пароля работает только прежний', P.check_password('0710', now=D) and not P.check_password('1234', now=D) and not P.check_password('', now=D))
check('СО сменным: прежний (ДДММ) ВСЁ ЕЩЁ работает', P.check_password('0710', h, s, now=D))
check('СО сменным: сменный работает', P.check_password('мой пароль', h, s, now=D))
check('чужой и пустой пароль не проходят', not P.check_password('чужой', h, s, now=D) and not P.check_password('', h, s, now=D) and not P.check_password(None, h, s, now=D))
check('регистр важен', not P.check_password('Мой пароль', h, s, now=D))
check('хеш без соли (или соль без хеша) = сменного пароля нет, остаётся прежний', P.check_password('0710', h, '', now=D) and not P.check_password('мой пароль', h, '', now=D) and not P.check_password('мой пароль', '', s, now=D))
check('сменный пароль, совпавший с ДДММ другого дня, не ломает ничего', P.check_password('1234', *P.make_password_record('1234'), now=D))
check('пароль с пробелами и юникодом', P.check_password(' пароль с пробелами ✓ ', *P.make_password_record(' пароль с пробелами ✓ '), now=D))

# ===== B. конфигурация =====
import config
config.CONFIG_FILE = tempfile.mktemp(suffix='.ini')
c = config.load_config()
check('по умолчанию пароль не задан', c['password_hash'] == '' and c['password_salt'] == '')
c['password_hash'], c['password_salt'] = h, s; config.save_config(c)
c2 = config.load_config()
check('сменный пароль сохраняется и читается', c2['password_hash'] == h and c2['password_salt'] == s)
config.save_config({**c2, 'engine_type': 'manticore', 'merge_output_dir': 'X'})
c3 = config.load_config()
check('другое сохранение конфигурации пароль НЕ стирает', c3['password_hash'] == h and c3['password_salt'] == s and c3['engine_type'] == 'manticore')
raw = open(config.CONFIG_FILE, encoding='utf-8').read()
check('в файле нет самого пароля, только хеш и соль', 'мой пароль' not in raw and h in raw)
open(config.CONFIG_FILE, 'w', encoding='utf-8').write('\n'.join(l for l in raw.splitlines() if 'password' not in l))
check('старый mconfig.ini без ключей читается (пароля нет)', config.load_config()['password_hash'] == '')

# ===== C. окно авторизации sp.py =====
try:
    import sp
    sp_ok = True
except Exception as e:
    sp_ok = False; print("     sp не импортируется:", repr(e))
check('sp.py импортируется (импорт password.py не сломал запуск)', sp_ok)
if sp_ok:
    class FixedDT:
        @staticmethod
        def now(): return D
    sp.datetime = FixedDT
    shown = []
    sp.messagebox = types.SimpleNamespace(showerror=lambda t, m, **k: shown.append(m))
    class Parent(tk.Toplevel):
        def winfo_x(self): return 0
        def winfo_y(self): return 0
        def wait_window(self, dlg): self.hook()
    def attempt(typed, record):
        sp.load_config = (lambda: record) if not isinstance(record, Exception) else (lambda: (_ for _ in ()).throw(record))
        start = len(tk.CREATED); shown.clear(); par = Parent()
        def hook():
            ws = tk.CREATED[start:]
            entry = [w for w in ws if isinstance(w, tk.Entry)][0]
            entry.options['textvariable'].set(typed)
            [w for w in ws if isinstance(w, tk.Button) and w.options.get('text') == 'OK'][0].options['command']()
        par.hook = hook
        try: return sp.show_authorization_dialog(par)
        except SystemExit: return 'exit'
    rec = {'password_hash': h, 'password_salt': s}
    check('вход: прежний пароль (ДДММ), сменного нет', attempt('0710', {}) is True)
    check('вход: неверный пароль — сообщение и выход', attempt('9999', {}) == 'exit' and any('Неверный пароль' in m for m in shown))
    check('вход: сменный пароль задан, ПРЕЖНИЙ ДДММ всё равно работает', attempt('0710', rec) is True)
    check('вход: сменный пароль работает', attempt('мой пароль', rec) is True)
    check('вход: неверный при заданном сменном — выход', attempt('9999', rec) == 'exit')
    check('вход: конфигурация не читается — остаётся прежний пароль, а не блокировка', attempt('0710', OSError("битый ini")) is True)
    check('вход: конфигурация не читается и пароль неверный — выход', attempt('9999', OSError("битый ini")) == 'exit')

# ===== D. диалог смены пароля =====
import ui.app_window as aw
BG_ERR = '#cc0000'
def make_win(cfg=None, vmm_cfg=None):
    w = aw.AppWindow.__new__(aw.AppWindow)
    w.root = tk.Toplevel(); w.config = cfg if cfg is not None else {}
    w.vector_model_manager = types.SimpleNamespace(config_dict=vmm_cfg if vmm_cfg is not None else w.config)
    return w
saved, infos = [], []
aw.save_config = lambda c: saved.append(dict(c))
aw.messagebox = types.SimpleNamespace(showinfo=lambda t, m, **k: infos.append(m), showerror=lambda *a, **k: None)
def open_dialog(win):
    start = len(tk.CREATED); win.change_password_dialog(); ws = tk.CREATED[start:]
    entries = [w for w in ws if isinstance(w, tk.Entry)]
    d = {'top': ws[0], 'vars': [e.options['textvariable'] for e in entries], 'show': [e.options.get('show') for e in entries],
         'ok': [w for w in ws if isinstance(w, tk.Button) and 'Сменить' in w.options.get('text', '')][0],
         'cancel': [w for w in ws if isinstance(w, tk.Button) and 'Отмена' in w.options.get('text', '')][0],
         'err': [w for w in ws if isinstance(w, tk.Label) and w.options.get('fg') == BG_ERR][0]}
    return d
def fill(d, old, new, confirm):
    for v, t in zip(d['vars'], (old, new, confirm)): v.set(t)
    d['ok'].options['command']()

win = make_win(); d = open_dialog(win)
check('три поля ввода, все скрывают символы (show="*")', len(d['vars']) == 3 and d['show'] == ['*', '*', '*'])
fill(d, '', 'a', 'a'); check('пустое поле: «Заполните все поля!»', d['err'].options['text'] == 'Заполните все поля!' and not d['top'].destroyed and saved == [])
fill(d, P.date_password(), 'новый1', 'другой'); check('новые пароли не совпадают', 'не совпадают' in d['err'].options['text'] and saved == [])
fill(d, 'не тот', 'новый1', 'новый1'); check('неверный старый пароль', 'Неверный старый' in d['err'].options['text'] and saved == [])
fill(d, P.date_password(), 'новый1', 'новый1')
check('старый пароль = ДДММ (сменного ещё нет): пароль сменён, диалог закрыт, показано сообщение',
      d['top'].destroyed and len(saved) == 1 and infos and 'тоже работает' in infos[-1])
check('в конфигурацию попали хеш и соль, а не сам пароль', P.check_password('новый1', win.config['password_hash'], win.config['password_salt']) and 'новый1' not in str(saved[-1]))
check('после смены работают И новый, И прежний (ДДММ)', P.check_password('новый1', win.config['password_hash'], win.config['password_salt']) and P.check_password(P.date_password(), win.config['password_hash'], win.config['password_salt']))
first_hash = win.config['password_hash']

d = open_dialog(win); fill(d, 'новый1', 'второй2', 'второй2')
check('старым паролем может быть и текущий сменный', d['top'].destroyed and not P.check_password('новый1', win.config['password_hash'], win.config['password_salt']) and P.check_password('второй2', win.config['password_hash'], win.config['password_salt']))
check('соль и хеш при смене новые', win.config['password_hash'] != first_hash)
d = open_dialog(win); fill(d, P.date_password(), 'третий3', 'третий3')
check('старым паролем может быть и ДДММ при уже заданном сменном', d['top'].destroyed and P.check_password('третий3', win.config['password_hash'], win.config['password_salt']))
d = open_dialog(win); d['cancel'].options['command']()
check('«Отмена» закрывает окно, ничего не меняя', d['top'].destroyed and P.check_password('третий3', win.config['password_hash'], win.config['password_salt']))

# разные словари конфигурации (после смены движка VectorModelManager держит прежний)
a, b = {}, {}; win = make_win(a, b); d = open_dialog(win); n = len(saved); fill(d, P.date_password(), 'общий4', 'общий4')
check('обновляются ОБА живых словаря конфигурации (иначе его сохранение вернёт старый пароль)', a['password_hash'] == b['password_hash'] != '' and a['password_salt'] == b['password_salt'] and len(saved) == n + 1)

# сбой записи: откат
good = {'password_hash': h, 'password_salt': s}; v = {'password_hash': h, 'password_salt': s}
win = make_win(good, v); d = open_dialog(win); infos.clear()
def boom(c): raise OSError("диск только для чтения")
aw.save_config = boom
fill(d, 'мой пароль', 'новый5', 'новый5')
check('сбой записи: ошибка в самом окне, окно не закрыто, сообщения «Успех» нет', 'диск только для чтения' in d['err'].options['text'] and not d['top'].destroyed and infos == [])
check('сбой записи: прежний пароль остался в обоих словарях (несохранённый не «прилипает»)',
      good == {'password_hash': h, 'password_salt': s} and v == {'password_hash': h, 'password_salt': s} and P.check_password('мой пароль', good['password_hash'], good['password_salt']))
aw.save_config = lambda c: saved.append(dict(c))

src = open(os.path.join(env.ROOT, 'ui/app_window.py'), encoding='utf-8').read()
check('пункт «Сменить пароль» в меню «Настройки»', 'self.settings_menu.add_command(label="Сменить пароль", command=self.change_password_dialog)' in src)

# ===== E. раскладка кнопок =====
lay = aw.nav_toggle_layout(9)
check('9 px на позицию: «Кратко» на 5 позиций (45 px) левее — отступы 53 + 52 вместо 75 + 75', lay['underline_padx'] == (53, 0) and lay['brief_padx'] == (52, 3), str(lay))
check('«Ч» остаётся посередине убранного (разница отступов ≤ 1 px)', abs(lay['underline_padx'][0] - lay['brief_padx'][0]) <= 1)
check('общий сдвиг ровно 5 позиций', (75 + 75) - (lay['underline_padx'][0] + lay['brief_padx'][0]) == 45)
check('кнопка шире на 3 позиции: 6 знаков «Кратко» + 3 = 9', lay['brief_width'] == 9)
l150 = aw.nav_toggle_layout(13)
check('при другом масштабе «5 позиций» остаются пятью (13 px на позицию -> сдвиг 65 px)', (150 - (l150['underline_padx'][0] + l150['brief_padx'][0])) == 65, str(l150))
check('отступы не уходят в минус даже при огромном шрифте', min(aw.nav_toggle_layout(80)['underline_padx'][0], aw.nav_toggle_layout(80)['brief_padx'][0]) >= 0)
check('char_w=0 -> прежние отступы (защита от сбоя измерения)', aw.nav_toggle_layout(0)['underline_padx'] == (75, 0) and aw.nav_toggle_layout(0)['brief_padx'] == (75, 3))
check('в коде: ширина берётся из шрифта, раскладка применена к обеим кнопкам',
      "tkfont.Font(root=self.root, font=('Arial', 12, 'bold')).measure('0')" in src and "padx=toggle_layout['underline_padx']" in src
      and "padx=toggle_layout['brief_padx']" in src and "width=toggle_layout['brief_width']" in src)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
