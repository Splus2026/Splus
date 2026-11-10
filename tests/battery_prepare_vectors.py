import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import ui.app_window as aw

# Запуск обучения векторной модели (кнопка «Векторы»): дообучение выбранной модели или создание новой, с диалогами, баннером,
# прогрессом и итогом. Окно создаётся без __init__ (нужны лишь атрибуты, которые читает метод); все собеседники — заглушки.
WORK = env.tmpdir('prepvec_'); os.chdir(WORK)
LOG = []
ns = types.SimpleNamespace
def calls(name): return [c for c in LOG if c[0] == name]
def names(): return [c[0] for c in LOG]
class Box:
    answers = {}
    def __getattr__(self, kind):
        if kind.startswith('__'): raise AttributeError(kind)
        def show(*a, **k): LOG.append(('msg', kind) + a + (tuple(sorted(k.items())) if k else ())); return Box.answers.get(kind, True)
        return show
class Simple:
    answer = None
    @staticmethod
    def askstring(*a, **k): LOG.append(('askstring',) + a + (tuple(sorted(k.items())),)); return Simple.answer
aw.messagebox = Box(); aw.simpledialog = Simple
CHOICE = {'model_type': 'fasttext', 'params': {'vector_size': 100}, 'semantic_window': None}
def fake_ask_vector_params(root, suggest_fn, mb, sentence_window_config=None):
    LOG.append(('ask_params', root, round(mb, 4), sentence_window_config)); suggest_fn('fasttext', mb); return CHOICE_BOX[0]
CHOICE_BOX = [CHOICE]; aw.ask_vector_params = fake_ask_vector_params

class VMM:
    def __init__(self, existing=(), result=(True, 'Модель обучена'), raises=None):
        self.existing = set(existing); self.result = result; self.raises = raises
    def is_vector_key(self, key): return key in self.existing
    def compute_display_key(self, mtype, files, names_by_file, name_suffix=None):
        LOG.append(('compute_key', mtype, tuple(files), dict(names_by_file), name_suffix))
        return 'FT ' + ', '.join(names_by_file[f] for f in files) + (f' [{name_suffix}]' if name_suffix else '')
    def suggest_params(self, mtype, total_bytes, mb): LOG.append(('suggest', mtype, total_bytes, round(mb, 4))); return {}
    def _run(self, kind, *a, **k):
        LOG.append((kind,) + a[:2] + tuple(sorted((key, v if key not in ('cancel_check', 'progress_callback') else '<fn>') for key, v in k.items())))
        self.last_kwargs = k
        if self.raises: raise self.raises
        return self.result
    def train(self, files, names_by_file, **k): return self._run('train', tuple(files), dict(names_by_file), **k)
    def continue_train(self, key, files, names_by_file, **k): return self._run('continue_train', key, tuple(files), **k)

def make(files=(), vmm=None, ticked=(), config=None, config_dict=None):
    LOG.clear(); Box.answers = {}; Simple.answer = None; CHOICE_BOX[0] = CHOICE
    win = aw.AppWindow.__new__(aw.AppWindow)
    win.file_manager = ns(selected_text_files=list(files)); win.config_dict = {} if config_dict is None else config_dict; win.config = {} if config is None else config
    win.index_manager = ns(get_selected_indices_ordered=lambda: list(ticked)); win.vector_model_manager = vmm or VMM(); win.root = 'ОКНО'
    win._show_training_banner = lambda text: (LOG.append(('banner', text)), ('БАННЕР', lambda: False))[1]
    win._hide_training_banner = lambda banner: LOG.append(('hide_banner', banner))
    win._show_progress = lambda **k: LOG.append(('show_progress',) + tuple(sorted(k.items())))
    win._update_progress = lambda v: LOG.append(('progress', v)); win._hide_progress = lambda: LOG.append(('hide_progress',))
    win.update_index_list = lambda: LOG.append(('update_index_list',))
    return win
def write(rel, size):
    open(rel, 'wb').write(b'x' * size); return rel
A = write('книга.txt', 1048576); B = write('вторая.txt', 524288); MISSING = 'нет_файла.txt'

# ===================== A. условия =====================
win = make([]); win.prepare_vectors()
check('файлы не выбраны: предупреждение «Не выбрано ни одного файла (в списке справа снизу).», ничего больше', LOG == [('msg', 'showwarning', 'Внимание', 'Не выбрано ни одного файла (в списке справа снизу).')], str(LOG))

# ===================== B. дообучение выбранной модели =====================
vmm = VMM(existing=['FT Модель'], result=(True, 'Дообучено'))
win = make([A, B], vmm, ticked=['a', 'FT Модель', 'FT Вторая'], config_dict={'книга.txt': ('Книга', 'N', '')}); vmm.existing |= {'FT Вторая'}
Box.answers = {'askyesno': True}; win.prepare_vectors()
q = calls('msg')[0]
check('дообучение: вопрос с названием модели и именами файлов (алиас из настроек, а без настроек — имя без расширения); модель берётся первая отмеченная',
      q[:3] == ('msg', 'askyesno', 'Дообучение модели') and '«FT Модель»' in q[3] and 'Книга, вторая' in q[3] and 'снимите галочку с «FT Модель»' in q[3], q[3][:140])
check('дообучение: диалог параметров НЕ показывается (параметры заданы при создании модели)', not calls('ask_params') and not calls('compute_key'))
ct = calls('continue_train')[0]
check('continue_train(ключ модели, файлы, имена), отмена и прогресс переданы функциями', ct[1] == 'FT Модель' and ct[2] == (A, B) and [k for k, v in ct[3:]] == ['cancel_check', 'progress_callback'], str(ct))
check('баннер «Дообучение модели, подождите... (Esc — прервать)», прогресс 0..100 (определённый), затем прогресс и баннер убираются', ('banner', 'Дообучение модели, подождите... (Esc — прервать)') in LOG and calls('show_progress') == [('show_progress', ('initial', 0), ('max_value', 100), ('mode', 'determinate'))] and names()[-5:-2] == ['continue_train', 'hide_progress', 'hide_banner'], str(names()))
check('успех: окно «Векторы» с сообщением менеджера, список индексов обновлён', calls('msg')[-1] == ('msg', 'showinfo', 'Векторы', 'Дообучено') and calls('update_index_list') and names()[-1] == 'update_index_list')
progress_fn = vmm.last_kwargs['progress_callback']; LOG.clear(); [progress_fn(f) for f in (0.0, 0.254, 0.999, 1.0)]
check('прогресс: доля превращается в целые проценты', calls('progress') == [('progress', 0), ('progress', 25), ('progress', 99), ('progress', 100)], str(calls('progress')))
vmm = VMM(existing=['FT Модель']); win = make([A], vmm, ticked=['FT Модель']); Box.answers = {'askyesno': False}; win.prepare_vectors()
check('«Нет» на вопрос о дообучении: ни баннера, ни обучения, ни обновления списка', not calls('continue_train') and not calls('banner') and not calls('update_index_list'))
vmm = VMM(existing=['FT Модель'], result=(False, 'Дообучение прервано пользователем.')); win = make([A], vmm, ticked=['FT Модель']); win.prepare_vectors()
check('неудача (в том числе прерывание по Esc): окно «Ошибка обучения» с сообщением менеджера, список не обновляется', calls('msg')[-1] == ('msg', 'showerror', 'Ошибка обучения', 'Дообучение прервано пользователем.') and not calls('update_index_list'))
vmm = VMM(existing=['FT Модель']); win = make([A], vmm, ticked=['a', 'b']); win.prepare_vectors()
check('отмечены только обычные индексы — это НЕ дообучение: открывается диалог параметров новой модели', calls('ask_params') and not calls('continue_train'))

# ===================== C. новая модель =====================
win = make([A, B], VMM(), config={'vector_sentences_before': 5, 'vector_sentences_after': 8}); win.prepare_vectors()
check('диалог параметров: окно, суммарный размер существующих файлов в МБ (1,5), «круги связи» из настроек программы (5 и 8)', calls('ask_params') == [('ask_params', 'ОКНО', 1.5, (5, 8))], str(calls('ask_params')))
win = make([A], VMM()); win.prepare_vectors()
check('«круги связи» по умолчанию — 7 предложений до и 10 после', calls('ask_params')[0][3] == (7, 10))
win = make([A, MISSING], VMM()); win.prepare_vectors()
check('несуществующие файлы в размер не входят (подсказка параметров получает размер в байтах)', calls('suggest') == [('suggest', 'fasttext', 1048576, 1.0)] and calls('ask_params')[0][2] == 1.0, str(calls('suggest')))
win = make([A], VMM()); CHOICE_BOX[0] = None; win.prepare_vectors()
check('отмена диалога параметров: ничего не обучается, баннера нет', not calls('train') and not calls('banner') and not calls('compute_key'))
win = make([A, B], VMM(result=(True, 'Готово')), config_dict={'книга.txt': ('Книга', 'N', '')}); CHOICE_BOX[0] = {'model_type': 'minilm', 'params': {'p': 1}, 'semantic_window': {'mode': 'sliding'}}; win.prepare_vectors()
tr = calls('train')[0]
check('train(файлы, имена по файлам, тип, параметры, окно смысла, без суффикса); баннер «Обучение модели…»; итог «Векторы» + обновление списка',
      tr[1] == (A, B) and tr[2] == {A: 'Книга', B: 'вторая'} and dict(tr[3:])['model_type'] == 'minilm' and dict(tr[3:])['model_params'] == {'p': 1} and dict(tr[3:])['semantic_window'] == {'mode': 'sliding'} and dict(tr[3:])['name_suffix'] is None
      and ('banner', 'Обучение модели, подождите... (Esc — прервать)') in LOG and calls('msg')[-1] == ('msg', 'showinfo', 'Векторы', 'Готово') and names()[-1] == 'update_index_list', str(tr))
win = make([A], VMM(result=(False, 'нет памяти'))); win.prepare_vectors()
check('новая модель, неудача: «Ошибка обучения» с сообщением, список не обновляется', calls('msg')[-1] == ('msg', 'showerror', 'Ошибка обучения', 'нет памяти') and not calls('update_index_list'))
win = make([A], VMM()); CHOICE_BOX[0] = {'model_type': 'fasttext', 'params': {}}; win.prepare_vectors()
check('в ответе диалога нет окна смысла — передаётся None', dict(calls('train')[0][3:])['semantic_window'] is None)

# ===================== D. модель с таким именем уже есть =====================
KEY = 'FT книга'
def conflict(decision, suffix=None, existing=(KEY,), second_exists=False):
    vmm = VMM(existing=existing, result=(True, 'Готово')); win = make([A], vmm, config_dict={}); Box.answers = {'ask_choice': decision}; Simple.answer = suffix
    if second_exists: vmm.existing |= {'FT книга [вар]'}
    win.prepare_vectors(); return vmm
conflict('Отмена')
check('имя занято: вопрос с тремя кнопками (Перезаписать / Другое имя / Отмена), предупреждение о потере дообучения; «Отмена» — ничего не обучается', calls('msg')[0][:4] == ('msg', 'ask_choice', 'Модель уже существует', calls('msg')[0][3]) and '«FT книга»' in calls('msg')[0][3] and 'СОТРЁТ' in calls('msg')[0][3]
      and ('buttons', ('Перезаписать', 'Другое имя', 'Отмена')) in calls('msg')[0] and ('height', 420) in calls('msg')[0] and not calls('train'), str(calls('msg')[0][4:]))
conflict(None); check('закрытие вопроса крестиком (None) = отмена', not calls('train'))
conflict('Перезаписать'); check('«Перезаписать»: обучение идёт без суффикса', dict(calls('train')[0][3:])['name_suffix'] is None)
conflict('Другое имя', suffix='  вар  ')
check('«Другое имя»: спрашивается уточнение (окно-родитель), пробелы по краям срезаются, обучение идёт с суффиксом; ключ проверяется с суффиксом',
      calls('askstring')[0][1:3] == ('Другое имя модели', 'Уточнение к имени модели (например: «вариант 2»):') and calls('askstring')[0][3] == (('parent', 'ОКНО'),) and dict(calls('train')[0][3:])['name_suffix'] == 'вар' and calls('compute_key')[1][4] == 'вар', str(calls('askstring')))
conflict('Другое имя', suffix=None); check('«Другое имя», но уточнение не введено (отмена ввода) — ничего не обучается', not calls('train'))
conflict('Другое имя', suffix='   '); check('уточнение из одних пробелов — ничего не обучается', not calls('train'))
conflict('Другое имя', suffix='вар', second_exists=True)
check('«Другое имя» тоже занято: «Имя всё равно занято» с новым ключом, обучения нет', calls('msg')[-1] == ('msg', 'showerror', 'Имя всё равно занято', 'Модель «FT книга [вар]» тоже уже существует — выберите другое уточнение.') and not calls('train'), str(calls('msg')[-1]))
conflict('Перезаписать', existing=()); check('имя свободно: вопроса о существовании нет вовсе', not calls('msg') or calls('msg')[0][1] != 'ask_choice')

# ===================== E. сбой во время обучения =====================
for label, ticked in (('новая модель', []), ('дообучение', ['FT Модель'])):
    vmm = VMM(existing=['FT Модель'], raises=RuntimeError('библиотека упала')); win = make([A], vmm, ticked=ticked); Box.answers = {'askyesno': True}
    try: win.prepare_vectors(); crashed = None
    except Exception as e: crashed = e
    check(f'{label}: если обучение БРОСАЕТ исключение, полоса прогресса и баннер всё равно убираются', 'hide_progress' in names() and 'hide_banner' in names(), str(names()))
    check(f'{label}: исключение из обучения не остаётся незамеченным — пользователь видит окно «Ошибка обучения», а не тишину и трассировку в консоли', crashed is None and calls('msg') and calls('msg')[-1][1:3] == ('showerror', 'Ошибка обучения'),
                f'исключение вышло наружу: {crashed!r}' if crashed else f'окон: {calls("msg")}')
# ===================== F. сообщение об ошибке и что НЕ глотается =====================
vmm = VMM(raises=RuntimeError('библиотека упала')); win = make([A], vmm); win.prepare_vectors()
check('исключение из обучения: текст — «Ошибка обучения: …» с причиной; список индексов не обновляется', calls('msg')[-1] == ('msg', 'showerror', 'Ошибка обучения', 'Ошибка обучения: библиотека упала') and not calls('update_index_list'), str(calls('msg')[-1]))
vmm = VMM(raises=MemoryError('мало памяти')); win = make([A], vmm); win.prepare_vectors()
check('нехватка памяти (MemoryError) — тоже сообщение, а не падение', calls('msg')[-1][1:3] == ('showerror', 'Ошибка обучения') and 'hide_banner' in names())
vmm = VMM(raises=KeyboardInterrupt()); win = make([A], vmm)
try: win.prepare_vectors(); swallowed = True
except KeyboardInterrupt: swallowed = False
check('KeyboardInterrupt НЕ глотается (программу можно прервать), но баннер и полоса всё равно убраны', swallowed is False and 'hide_progress' in names() and 'hide_banner' in names())
# ===================== G. шаги отдельно =====================
win = make([A], VMM(existing=['FT книга']))
Box.answers = {'ask_choice': 'Перезаписать'}
check('_resolve_model_name_conflict: имя свободно — (True, None) без вопросов; «Перезаписать» — (True, None)', make([A], VMM())._resolve_model_name_conflict('fasttext', [A], {A: 'книга'}) == (True, None) and win._resolve_model_name_conflict('fasttext', [A], {A: 'книга'}) == (True, None))
Box.answers = {'ask_choice': 'Отмена'}; check('_resolve_model_name_conflict: «Отмена» — (False, None)', win._resolve_model_name_conflict('fasttext', [A], {A: 'книга'}) == (False, None))
Box.answers = {'ask_choice': 'Другое имя'}; Simple.answer = ' вариант 2 '; check('_resolve_model_name_conflict: «Другое имя» — (True, уточнение без пробелов)', win._resolve_model_name_conflict('fasttext', [A], {A: 'книга'}) == (True, 'вариант 2'))
check('_display_names_for_files: алиас из настроек баз, иначе имя без расширения, ключи — исходные пути', make(config_dict={'a.txt': ('Альфа', 'N', '')})._display_names_for_files([os.path.join('DB', 'a.txt'), 'b.docx']) == {os.path.join('DB', 'a.txt'): 'Альфа', 'b.docx': 'b'})
check('_run_training возвращает результат менеджера как есть (успех и неудача)', make([A], VMM(result=(True, 'ок')))._run_training(None, [A], {A: 'к'}, 'fasttext', {}, None, None) == (True, 'ок') and make([A], VMM(result=(False, 'нет')))._run_training('FT М', [A], {A: 'к'}, None, None, None, None) == (False, 'нет'))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
