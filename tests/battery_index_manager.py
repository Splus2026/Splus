import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import tkinter as tk
tk._GENERIC_FALLBACK = True
class BooleanVar:
    """У подставного Tk нет «живых» переменных — нужна настоящая пара get/set, чтобы настоящий список индексов работал."""
    def __init__(self, master=None, value=False): self.v = value
    def get(self): return self.v
    def set(self, x): self.v = x
tk.BooleanVar = BooleanVar
from ui.index_check_list import IndexCheckList
import services.index_manager as imm
import stats_logger
from utils.text_processing import make_safe_index_name

# Управление списком индексов: показ имён под алиасами, отметка (с ПОРЯДКОМ отметки), удаление, предложение загрузить модель.
# Виджет IndexCheckList — НАСТОЯЩИЙ (он сам уведомляет менеджера при каждой перестройке списка — на этом держатся и порядок, и
# рекурсия). Движок, менеджер моделей, диалоги, подписи — заглушки, записывающие вызовы.
WORK = env.tmpdir('indexmgr_'); os.chdir(WORK)
LOG = []
def rec(name, ret=None): return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]
def calls(name): return [c for c in LOG if c[0] == name]
def statuses(): return [c[1] for c in LOG if c[0] == 'status']
class Box:
    answers = {}
    def __getattr__(self, kind):
        if kind.startswith('__'): raise AttributeError(kind)
        def show(*a, **k): LOG.append(('msg', kind, k.get('title'), k.get('message'), k.get('height'))); return Box.answers.get(kind, True)
        return show
imm.messagebox = Box(); stats_logger.STATS_ENABLED = False
class Clock:
    def __init__(self): self.t = 0.0
    def time(self): v = self.t; self.t += 0.017; return v
class Engine:
    def __init__(self, engine_type='manticore', indices=('a', 'b', 'c', 'd'), data_dir=None, select_ok=True, delete_result=None, list_raises=False):
        self.engine_type = engine_type; self.indices = list(indices); self.data_dir = data_dir; self.select_ok = select_ok; self.delete_result = delete_result or {}; self.list_raises = list_raises; self.selects = 0
    def list_indices(self):
        if self.list_raises: raise RuntimeError('нет связи')
        return list(self.indices)
    def select_index(self, name): self.selects += 1; LOG.append(('select_index', name)); return self.select_ok
    def delete_index(self, name):
        LOG.append(('delete_index', name)); r = self.delete_result.get(name, True)
        if isinstance(r, Exception): raise r
        if r: self.indices = [i for i in self.indices if i != name]
        return r
class VMM:
    def __init__(self, mtype='fasttext', loaded=False, aux=(), keys=('FT Модель',), delete=None):
        self.mtype = mtype; self.loaded = loaded; self.aux = set(aux); self.keys = list(keys); self.delete = delete or {}
    def is_vector_key(self, key): return key.startswith(('FT ', 'Mini '))
    def get_model_type(self, key): return 'minilm' if key.startswith('Mini ') else self.mtype
    def is_loaded(self, key): return self.loaded
    def preload_model_async(self, key): LOG.append(('preload', key))
    def get_auxiliary_indices(self): return set(self.aux)
    def list_display_keys(self): return list(self.keys)
    def delete_model(self, key): LOG.append(('delete_model', key)); return self.delete.get(key, (True, f'Модель {key} удалена'))

CONFIG = {'Книга.txt': ('Книга', 'N', ''), 'таблица.xlsx': ('Таблица', 'ExcelRow1', ''), 'нет_в_движке.txt': ('Нигде', 'N', '')}
def make(engine=None, vmm=None, config=None, label=True, parent='окно'):
    LOG.clear(); Box.answers = {}; imm.time = Clock()
    cl = IndexCheckList(None); eng = engine or Engine()
    im = imm.IndexManager(eng, CONFIG if config is None else config, cl, types.SimpleNamespace(config=rec('label')) if label else None, rec('status'),
                          clear_result_callback=rec('clear'), parent=parent, vector_model_manager=vmm)
    im.selection_changed_callback = rec('selection_changed'); im.preload_started_callback = rec('preload_started')
    return im, cl, eng
def tick(cl, *names):
    """Пользователь отмечает индексы по очереди (как кликами по чекбоксам)."""
    for name in names:
        var = cl.checkbuttons[name][0]; var.set(True); cl._on_check(name, var)
def untick(cl, name):
    var = cl.checkbuttons[name][0]; var.set(False); cl._on_check(name, var)
def label_text(): return [c[1:] for c in LOG if c[0] == 'label']

# ===================== A. имена индексов под алиасами =====================
safe_kniga = make_safe_index_name('Книга.txt', 'manticore')[1]; safe_tabl = make_safe_index_name('таблица.xlsx', 'manticore')[1]
im, cl, eng = make(Engine('manticore', indices=[safe_kniga, safe_tabl, 'чужой']))
check('Manticore: индексам из настроек сопоставлены алиасы (по безопасному имени файла); индекса нет в движке или нет в настройках — записи нет',
      im.index_display_map == {safe_kniga: 'Книга', safe_tabl: 'Таблица'}, str(im.index_display_map))
im, cl, eng = make(Engine('elasticsearch', indices=['ms_' + safe_kniga]))
check('Elastic: имена с префиксом ms_', im.index_display_map == {'ms_' + safe_kniga: 'Книга'}, str(im.index_display_map))
im, cl, eng = make(Engine('fts5', indices=['Книга']))
check('FTS5: карту алиасов менеджер не строит', im.index_display_map == {})
im, cl, eng = make(Engine('manticore', list_raises=True))
check('движок не отвечает при создании менеджера — карта пуста, без падения', im.index_display_map == {})
check('менеджер подписывается на выбор в списке индексов', cl.selection_callback == im._on_selection_changed)

# ===================== B. выбор индексов =====================
im, cl, eng = make(Engine('manticore')); im.update_index_list(); LOG.clear()
tick(cl, 'a', 'b')
check('отметка индекса: имена запомнены, надпись «(N)» обновлена, главное окно уведомлено о выборе', sorted(im.selected_indices_names) == ['a', 'b'] and label_text()[-1] == ((('text', '(2)'),)) and calls('selection_changed')[-1][1] in (['a', 'b'], ['b', 'a']), str(LOG[-3:]))
untick(cl, 'a'); check('снятие отметки: надпись «(1)»', im.selected_indices_names == ['b'] and label_text()[-1] == (('text', '(1)'),))
im, cl, eng = make(label=False); im.update_index_list(); tick(cl, 'a')
check('надписи нет — выбор работает без неё', im.selected_indices_names == ['a'])
im, cl, eng = make(Engine('manticore')); im.update_index_list(); tick(cl, 'a')
check('Manticore: переключения индекса в движке нет (ищется по всем отмеченным)', not calls('select_index'))
im, cl, eng = make(Engine('fts5', select_ok=False)); im.update_index_list(); LOG.clear(); tick(cl, 'a')
check('FTS5: индекс не переключился — «Не удалось переключиться на индекс a» (с окном-родителем), результаты не очищаются', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Не удалось переключиться на индекс a', None)] and not calls('clear'), str(calls('msg')))
im, cl, eng = make(Engine('fts5', indices=['a', 'b'])); im.update_index_list(); LOG.clear(); cl.select_all()
check('FTS5: отмечено два индекса сразу — движок не переключается', eng.selects == 0 and sorted(im.selected_indices_names) == ['a', 'b'])
im, cl, eng = make(Engine('fts5')); im.update_index_list(); LOG.clear()
try: tick(cl, 'a'); crashed = None
except RecursionError as e: crashed = e
check('FTS5: один отмеченный индекс — движок переключается ОДИН раз, результаты очищаются, список обновляется, без бесконечной рекурсии', crashed is None and eng.selects == 1 and len(calls('clear')) == 1,
            f'RecursionError: select_index вызван {eng.selects} раз' if crashed else f'select_index {eng.selects} раз, clear {len(calls("clear"))}')

# ===================== C. предложение загрузить модель =====================
def preload(selected, vmm, answer=True, im_=None):
    im, cl, eng = make(vmm=vmm); Box.answers = {'askyesno': answer}; LOG.clear(); im._maybe_offer_vector_preload(selected); return im
preload(['a'], None); check('нет менеджера моделей — ничего', not calls('msg'))
preload(['a', 'b'], VMM()); check('модель не отмечена — ничего', not calls('msg'))
preload(['FT Модель'], VMM('fasttext')); check('FastText без обычного индекса — ничего (ей нужен индекс для поиска)', not calls('msg'))
preload(['FT Модель', 'a'], VMM('fasttext'))
check('FastText + обычный индекс: вопрос «Загрузить векторную модель «…» сейчас?» (окно-родитель, высота 320)', len(calls('msg')) == 1 and calls('msg')[0][:3] == ('msg', 'askyesno', 'Загрузка модели') and '«FT Модель»' in calls('msg')[0][3] and calls('msg')[0][4] == 320, str(calls('msg')))
preload(['Mini Модель'], VMM()); check('MiniLM достаточно отметить одну (индекс определился при обучении) — вопрос задаётся', len(calls('msg')) == 1)
preload(['FT Модель', 'a'], VMM(loaded=True)); check('модель уже загружена — не спрашивается', not calls('msg'))
im = preload(['FT Модель', 'a'], VMM(), answer=True)
check('«Да»: загрузка в фоне и уведомление окна об индикаторе загрузки', calls('preload') == [('preload', 'FT Модель')] and calls('preload_started') == [('preload_started', 'FT Модель')])
im = preload(['FT Модель', 'a'], VMM(), answer=False)
check('«Нет»: ничего не загружается', not calls('preload') and not calls('preload_started'))
LOG.clear(); im._maybe_offer_vector_preload(['FT Модель', 'a'])
check('спрашивается не более одного раза за сеанс на модель (даже после «Нет»)', not calls('msg'))
im = preload(['FT Вторая', 'FT Модель', 'a'], VMM())
check('несколько моделей: речь о первой отмеченной', '«FT Вторая»' in calls('msg')[0][3], calls('msg')[0][3][:60])
im, cl, eng = make(vmm=VMM()); LOG.clear(); im.update_index_list(); tick(cl, 'a'); tick(cl, 'FT Модель')
check('через настоящий список: отметили модель после обычного индекса — вопрос задаётся один раз', len(calls('msg')) == 1, str(calls('msg')))

# ===================== D. обновление списка =====================
im, cl, eng = make(Engine('manticore', indices=['b', 'a'])); im.update_index_list()
check('список индексов в виджете — как вернул движок', sorted(cl.checkbuttons) == ['a', 'b'])
im, cl, eng = make(Engine('manticore', list_raises=True)); LOG.clear(); im.update_index_list()
check('движок не ответил: в строке состояния «❌ Ошибка обновления списка индексов: …», список не трогается', statuses() == ['❌ Ошибка обновления списка индексов: нет связи'] and cl.checkbuttons == {})
im = imm.IndexManager.__new__(imm.IndexManager); im.engine = None; im.check_list = IndexCheckList(None)
check('нет движка — ничего не происходит', im.update_index_list() is None)
im, cl, eng = make(Engine('manticore', indices=['a', 'model_aux', 'b']), vmm=VMM(aux=['model_aux'], keys=['FT Модель'])); im.update_index_list()
check('Manticore + модели: вспомогательные индексы «окон смысла» скрыты, модели показаны строками «FT …» в конце', list(cl.checkbuttons) == ['a', 'b', 'FT Модель'], str(list(cl.checkbuttons)))
im, cl, eng = make(Engine('fts5', indices=['a']), vmm=VMM()); im.update_index_list()
check('другие движки: строки моделей не добавляются', list(cl.checkbuttons) == ['a'])
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c'])); im.update_index_list(); tick(cl, 'a', 'c'); eng.indices = ['a', 'b']; im.update_index_list()
check('обновление: отмеченный индекс, который остался, остаётся отмеченным, исчезнувший — пропадает; надпись пересчитана', im.get_selected_indices() == ['a'] and label_text()[-1] == (('text', '(1)'),), str(im.get_selected_indices()))
im, cl, eng = make(Engine('manticore', indices=['a'])); im.update_index_list(); eng.indices = ['a', safe_kniga]; im.update_index_list()
check('новый индекс из настроек получает алиас при обновлении списка', im.index_display_map.get(safe_kniga) == 'Книга' and 'Книга' in cl.checkbuttons[safe_kniga][1].options.get('text', 'Книга'))
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'c', 'a', 'd', 'b'); im.update_index_list()
check('порядок отметки (от него зависит, какой файл в верхнем окне режима разделения) переживает обновление списка', im.get_selected_indices_ordered() == ['c', 'a', 'd', 'b'], f'после обновления: {im.get_selected_indices_ordered()}')
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'b', 'a')
check('get_selected_indices_ordered — в порядке отметки, get_selected_indices — то же множество', im.get_selected_indices_ordered() == ['b', 'a'] and sorted(im.get_selected_indices()) == ['a', 'b'])
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c'])); im.update_index_list(); im.toggle_select_all()
check('«выбрать все» по правому клику: отмечены все; повторно — снимаются', sorted(im.get_selected_indices()) == ['a', 'b', 'c'] and (im.toggle_select_all(), im.get_selected_indices() == [])[1])

# ===================== E. удаление индексов =====================
def delete(engine, vmm=None, selected=(), answer=True, stats=False):
    im, cl, eng = make(engine, vmm=vmm); im.update_index_list(); tick(cl, *selected); Box.answers = {'askokcancel': answer}; LOG.clear(); stats_logger.STATS_ENABLED = stats
    im.delete_selected_indices(); stats_logger.STATS_ENABLED = False; return im, cl, eng
im, cl, eng = delete(Engine('manticore'), selected=())
check('ничего не отмечено: предупреждение «Не выбран ни один индекс для удаления.»', LOG == [('msg', 'showwarning', 'Нет выбора', 'Не выбран ни один индекс для удаления.', None)], str(LOG))
im, cl, eng = delete(Engine('manticore'), selected=('a', 'b'), answer=False)
check('отказ в подтверждении: ничего не удалено, статусов нет', not calls('delete_index') and not statuses() and len(calls('msg')) == 1 and calls('msg')[0][2] == 'Удаление индексов')
im, cl, eng = delete(Engine('manticore'), selected=('a', 'b'))
q = calls('msg')[0]
check('подтверждение перечисляет индексы и предупреждает о необратимости', q[1] == 'askokcancel' and ('a, b' in q[3] or 'b, a' in q[3]) and 'необратимо' in q[3], q[3][:90])
check('успех: статус начала, удаление каждого индекса, список обновлён, результаты очищены, итог «Удалено N … за 17 мс»', statuses()[0] == '🗑️ Удаление 2 индексов...' and sorted(c[1] for c in calls('delete_index')) == ['a', 'b'] and calls('clear') and statuses()[-1] == '✅ Удалено 2 индексов за 17 мс' and sorted(cl.checkbuttons) == ['c', 'd'], str(statuses()))
check('после удаления отмеченных нет, надпись «(0)»', im.get_selected_indices() == [] and label_text()[-1] == (('text', '(0)'),))
im, cl, eng = make(Engine('manticore', indices=[safe_kniga, 'b']))
im.update_index_list(); tick(cl, safe_kniga); LOG.clear(); im.delete_selected_indices()
check('алиас удалённого индекса убирается из карты имён', safe_kniga not in im.index_display_map, str(im.index_display_map))
im, cl, eng = delete(Engine('manticore', delete_result={'a': False}), selected=('a', 'b'))
check('индекс не удалился (движок вернул False): «⚠️ Не удалось удалить индекс a», окно «Ошибка», итог «завершено с ошибками», результаты НЕ очищаются, список обновлён',
      '⚠️ Не удалось удалить индекс a' in statuses() and statuses()[-1] == '❌ Удаление индексов завершено с ошибками' and not calls('clear') and any(m[1] == 'showerror' and m[2] == 'Ошибка' for m in calls('msg')) and 'b' not in cl.checkbuttons, str(statuses()))
im, cl, eng = delete(Engine('manticore', delete_result={'a': RuntimeError('занят')}), selected=('a', 'b'))
check('исключение при удалении одного индекса: «⚠️ Ошибка удаления a: занят», остальные удаляются', '⚠️ Ошибка удаления a: занят' in statuses() and ('delete_index', 'b') in LOG and not calls('clear'))
vmm = VMM(keys=['FT Модель'])
im, cl, eng = delete(Engine('manticore'), vmm=vmm, selected=('a', 'FT Модель'))
check('модель «FT …» удаляется через менеджер моделей, а НЕ как индекс движка', calls('delete_model') == [('delete_model', 'FT Модель')] and calls('delete_index') == [('delete_index', 'a')] and '✅ Модель FT Модель удалена' in statuses(), str(LOG))
im, cl, eng = delete(Engine('manticore'), vmm=VMM(keys=['FT Модель'], delete={'FT Модель': (False, 'нельзя')}), selected=('a', 'FT Модель'))
check('не удалилась модель: «⚠️ нельзя» и общая ошибка, хотя обычный индекс удалён', '⚠️ нельзя' in statuses() and statuses()[-1] == '❌ Удаление индексов завершено с ошибками' and ('delete_index', 'a') in LOG)
im, cl, eng = delete(Engine('manticore'), vmm=None, selected=('a',))
check('без менеджера моделей все отмеченные — обычные индексы', calls('delete_index') == [('delete_index', 'a')])
# журнал удаления
stats_logger.log_index_deletion = rec('log_deletion')
os.makedirs('mdata', exist_ok=True); [open(os.path.join('mdata', n), 'wb').write(b'm' * s) for n, s in (('a.spd', 10), ('a.spa', 20), ('keep.spd', 5))]
im, cl, eng = make(Engine('manticore', data_dir='mdata')); im.update_index_list(); tick(cl, 'a'); LOG.clear(); stats_logger.STATS_ENABLED = True
class Deleting(Engine):
    def delete_index(self, name):
        for ext in ('spd', 'spa'):
            p = os.path.join('mdata', f'{name}.{ext}')
            if os.path.exists(p): os.remove(p)
        return super().delete_index(name)
im, cl, eng = make(Deleting('manticore', data_dir='mdata')); im.update_index_list(); tick(cl, 'a'); LOG.clear(); im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
kw = dict(calls('log_deletion')[0][1:]) if calls('log_deletion') else {}
check('журнал, Manticore: размер ДО — сумма файлов индекса (a.*), размер ПОСЛЕ — всё, что осталось в каталоге данных', kw.get('engine_type') == 'manticore' and kw.get('index_name') == 'a' and kw.get('index_size_bytes') == 30 and kw.get('total_index_size_after') == 5 and kw.get('deletion_time_ms') == 17.0, str(kw))
os.makedirs('indicies_fts5', exist_ok=True); open(os.path.join('indicies_fts5', 'x.db'), 'wb').write(b'x' * 100); open(os.path.join('indicies_fts5', 'y.db'), 'wb').write(b'y' * 40); open('z.db', 'wb').write(b'z' * 7)
class DeletingFts(Engine):
    def delete_index(self, name):
        for p in (os.path.join('indicies_fts5', f'{name}.db'),):
            if os.path.exists(p): os.remove(p)
        return super().delete_index(name)
im, cl, eng = make(DeletingFts('fts5', indices=['x', 'y', 'z'])); im.update_index_list(); LOG.clear(); cl.select_all(); LOG.clear(); stats_logger.STATS_ENABLED = True; im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
kw = dict(calls('log_deletion')[0][1:]) if calls('log_deletion') else {}
check('журнал, FTS5: размер ДО — файл индекса (indicies_fts5/имя.db, либо имя.db рядом с программой), размер ПОСЛЕ — все .db в indicies_fts5', kw.get('engine_type') == 'fts5' and kw.get('index_size_bytes') == 147 and kw.get('total_index_size_after') == 0 and sorted(kw.get('index_name', '').split(', ')) == ['x', 'y', 'z'], str(kw))
im, cl, eng = make(Engine('manticore')); im.update_index_list(); tick(cl, 'a'); LOG.clear(); stats_logger.STATS_ENABLED = True; im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
check('журнал, Manticore без каталога данных: размеры 0, запись всё равно сделана', dict(calls('log_deletion')[0][1:]).get('index_size_bytes') == 0 and dict(calls('log_deletion')[0][1:]).get('total_index_size_after') == 0)
im, cl, eng = make(Engine('manticore', delete_result={'a': False})); im.update_index_list(); tick(cl, 'a'); LOG.clear(); stats_logger.STATS_ENABLED = True; im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
check('журнал: при неудаче удаления не пишется', not calls('log_deletion'))
im, cl, eng = make(Engine('manticore'), vmm=VMM(keys=['FT Модель'])); im.update_index_list(); tick(cl, 'FT Модель'); LOG.clear(); stats_logger.STATS_ENABLED = True; im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
check('журнал: если удалялись только модели — не пишется (у них нет размера индекса)', not calls('log_deletion'))
# ===================== F. вложенные уведомления и порядок =====================
im, cl, eng = make(Engine('fts5', indices=['a', 'b'])); im.update_index_list(); LOG.clear(); tick(cl, 'a')
check('FTS5: переключение выполняется один раз; уведомления от обновления списка, вызванного самим переключением, обратный вызов окна не дублируют',
      eng.selects == 1 and len(calls('selection_changed')) == 1 and calls('selection_changed')[0][1] == ['a'], f'select_index {eng.selects}, обратных вызовов {len(calls("selection_changed"))}')
check('после переключения флаг обработки снят: следующая отметка снова работает', im._handling_selection is False and (tick(cl, 'b'), True)[1] and len(calls('selection_changed')) >= 2)
im, cl, eng = make(Engine('fts5', select_ok=False, indices=['a'])); im.update_index_list(); LOG.clear(); tick(cl, 'a')
check('если переключение не удалось, флаг обработки всё равно снят (иначе выбор перестал бы обрабатываться)', im._handling_selection is False)
im = imm.IndexManager.__new__(imm.IndexManager); im.engine = types.SimpleNamespace(engine_type='manticore'); im.selected_count_label = None; im.selection_changed_callback = rec('selection_changed'); im.vector_model_manager = None
LOG.clear(); im._on_selection_changed(['a'])
check('менеджер, созданный без __init__ (как в других проверках), обрабатывает выбор: флаг по умолчанию задан на уровне класса', calls('selection_changed') == [('selection_changed', ['a'])] and imm.IndexManager._handling_selection is False)
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'd', 'b', 'a')
for _ in range(4): im.update_index_list()
check('порядок отметки сохраняется при ЛЮБОМ числе обновлений списка', im.get_selected_indices_ordered() == ['d', 'b', 'a'], str(im.get_selected_indices_ordered()))
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c']), vmm=VMM(keys=['FT Модель'])); im.update_index_list(); tick(cl, 'c', 'FT Модель', 'a'); im.update_index_list()
check('порядок сохраняется и когда среди отмеченных строка модели «FT …»', im.get_selected_indices_ordered() == ['c', 'FT Модель', 'a'], str(im.get_selected_indices_ordered()))
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'b', 'c', 'a'); eng.indices = ['a', 'b', 'd']; im.update_index_list()
check('исчезнувший индекс выпадает из порядка, остальные сохраняют взаимный порядок', im.get_selected_indices_ordered() == ['b', 'a'], str(im.get_selected_indices_ordered()))
im, cl, eng = make(vmm=VMM()); im.update_index_list(); tick(cl, 'a'); tick(cl, 'FT Модель'); LOG.clear(); im.update_index_list()
check('обновление списка не повторяет вопрос о загрузке модели (спрашивалось один раз за сеанс)', not calls('msg'))
# ===================== G. удалённый индекс не остаётся в порядке отметки (по нему поиск выбирает индексы) =====================
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'a', 'b'); Box.answers = {'askokcancel': True}; im.delete_selected_indices()
check('после удаления отмеченных индексов порядок отметки пуст — поиск не получит удалённые индексы', im.get_selected_indices() == [] and im.get_selected_indices_ordered() == [], f'порядок: {im.get_selected_indices_ordered()}')
tick(cl, 'c')
check('и новая отметка даёт в порядке только существующий индекс', im.get_selected_indices_ordered() == ['c'], str(im.get_selected_indices_ordered()))
im, cl, eng = make(Engine('manticore', indices=['a', 'b', 'c', 'd'])); im.update_index_list(); tick(cl, 'a', 'b', 'c'); Box.answers = {'askokcancel': True}
untick(cl, 'b'); im.delete_selected_indices()
check('удалили часть отмеченных (a и c): остался порядок только тех, что есть', im.get_selected_indices_ordered() == [] and sorted(cl.checkbuttons) == ['b', 'd'], str(im.get_selected_indices_ordered()))
cl2 = IndexCheckList(None); cl2.set_indices(['a', 'b', 'c', 'd']); tick(cl2, 'c', 'a', 'd'); cl2.set_indices(['d', 'a', 'x'])
check('виджет: set_indices оставляет в порядке только отмеченные индексы нового списка, взаимный порядок сохраняется', cl2.get_selected_ordered() == ['a', 'd'] and cl2.get_selected() and sorted(cl2.get_selected()) == ['a', 'd'], str(cl2.get_selected_ordered()))
check('виджет: порядок и множество отмеченных всегда согласованы', set(cl2.get_selected_ordered()) == cl2.selected)
cl2.set_indices([]); check('виджет: пустой список индексов — пустой порядок', cl2.get_selected_ordered() == [] and cl2.get_selected() == [])
cl3 = IndexCheckList(None); cl3.set_indices(['a', 'b', 'c']); tick(cl3, 'b'); cl3.set_indices(['a', 'b', 'c', 'new'])
check('виджет: новый индекс в списке не отмечен, прежняя отметка сохранена', cl3.get_selected_ordered() == ['b'])
cl3.select_all(); check('виджет: «выбрать все» отмечает все индексы нового списка, порядок — без призраков', sorted(cl3.get_selected_ordered()) == ['a', 'b', 'c', 'new'] and len(cl3.get_selected_ordered()) == 4)
# ===================== H. журнал удаления: часть индексов остаётся =====================
os.makedirs('indicies_fts5', exist_ok=True)
for n_, size in (('x', 100), ('y', 40)): open(os.path.join('indicies_fts5', f'{n_}.db'), 'wb').write(b'q' * size)
open(os.path.join('indicies_fts5', 'заметка.txt'), 'wb').write(b'n' * 9)
im, cl, eng = make(DeletingFts('fts5', indices=['x', 'y'])); im.update_index_list(); cl.set_selected(['x']); LOG.clear(); stats_logger.STATS_ENABLED = True; Box.answers = {'askokcancel': True}; im.delete_selected_indices(); stats_logger.STATS_ENABLED = False
kw = dict(calls('log_deletion')[0][1:]) if calls('log_deletion') else {}
check('журнал, FTS5: удалён один индекс из двух — размер ДО = его файл (100), ПОСЛЕ = только оставшиеся .db (40; чужие файлы не считаются)', kw.get('index_name') == 'x' and kw.get('index_size_bytes') == 100 and kw.get('total_index_size_after') == 40, str(kw))
cl4 = IndexCheckList(None); cl4.set_indices(['a', 'b']); cl4.selected.add('b'); cl4.set_indices(['a', 'b', 'c'])
check('виджет: отмеченный индекс, у которого не было записи в порядке, не теряется из порядка (множество и порядок всегда согласованы)', cl4.get_selected_ordered() == ['b'] and cl4.selected == {'b'}, str(cl4.get_selected_ordered()))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
