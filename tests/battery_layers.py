import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import json, random, tempfile, time
from services import marks as M
from services.marks import MarksStore
from services import sync_folder as S

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))
def tmp(): return tempfile.mkdtemp(prefix='layers_')
def tmpdb(): return os.path.join(tmp(), 'marks.db')

# ===================== A. хранилище слоёв =====================
st = MarksStore(tmpdb())
st.add_style('DB\\Bibl.txt', 'big', 'слово', 'до ', ' после'); st.add_style('bibl.txt', 'color', 'слово', 'до ', ' после')
nid = st.add_note('bibl.txt', 'слово', 'до ', ' после', 'моя мысль', 'u')
check('стили: по виду и всего', len(st.styles_for_file('bibl.txt')) == 2 and len(st.styles_for_file('bibl.txt', 'big')) == 1)
check('мысль: текст и флаги', st.get_note(nid).text == 'моя мысль' and st.get_note(nid).flags == 'u')
st.update_note(nid, text='новая'); check('правка мысли', st.notes_for_file('bibl.txt')[0].text == 'новая')
snap = st.snapshot_file('bibl.txt')
st.delete_note(nid); st.delete_styles([x.id for x in st.styles_for_file('bibl.txt')])
check('удаление слоёв', not st.notes_for_file('bibl.txt') and not st.styles_for_file('bibl.txt'))
st.restore_file('bibl.txt', snap)
check('восстановление снимка файла', len(st.styles_for_file('bibl.txt')) == 2 and st.notes_for_file('bibl.txt')[0].text == 'новая')
check('uid стиля и мысли — как в Синева Mobile (по содержимому)',
      M.style_uid('big', 'bibl.txt', 'слово', 'до ', ' после') == M.mark_uid('style:big\x1ebibl.txt', 'слово', 'до ', ' после')
      and M.note_uid('bibl.txt', 'слово', 'до ', ' после') == M.mark_uid('note\x1ebibl.txt', 'слово', 'до ', ' после'))

# ===================== B. встраивание мыслей в текст =====================
rnd = random.Random(7); ok = True
for _ in range(300):
    content = ''.join(rnd.choice('абвг ддд') for _ in range(rnd.randint(5, 60)))
    segs = [(0, 0, len(content))]
    ivs, cur = [], 0
    for _k in range(rnd.randint(0, 3)):
        if cur >= len(content) - 1: break
        a = rnd.randint(cur, len(content) - 1); b = rnd.randint(a + 1, len(content)); ivs.append((a, b, 2)); cur = b
    notes = [(rnd.randint(0, len(content)), 'м%d' % i) for i in range(rnd.randint(0, 3))]
    text, nivs, nsegs, rngs = M.embed_notes(content, ivs, segs, notes)
    rebuilt = ''.join(text[d:d + l] for d, c, l in nsegs)
    ok &= rebuilt == content and all(text[d:d + l] == content[c:c + l] for d, c, l in nsegs)
    ok &= all(text[a:b].startswith(' (м') for a, b in rngs) and len(rngs) == len(notes)
    covered_old = sorted(set(i for a, b, _p in ivs for i in range(a, b)))
    covered_new = ''.join(text[i] for a, b, _p in nivs for i in range(a, b))
    ok &= covered_new == ''.join(content[i] for i in covered_old)
check('embed_notes: 300 случайных случаев — текст, карта кусков и подсветка сохраняются, вставки на месте', ok)

# ===================== C. рендерер =====================
class FakeText:
    def __init__(self): self.text = ''; self.tags = {}
    def config(self, **k): pass
    configure = config
    def update_idletasks(self): pass
    def tag_config(self, *a, **k): pass
    def tag_bind(self, *a, **k): pass
    def yview(self, *a): return (0.0, 1.0)
    def yview_moveto(self, *a): pass
    def mark_set(self, *a): pass
    def focus_set(self): pass
    def _lines(self): return self.text.split('\n')
    def _to_off(self, idx):
        idx = str(idx)
        if idx == 'end': return len(self.text) + 1
        if idx == 'end-1c': return len(self.text)
        line, col = idx.split('.'); lines = self._lines(); line = int(line)
        col = len(lines[line - 1]) if col == 'end' else int(col)
        return sum(len(l) + 1 for l in lines[:line - 1]) + col
    def _to_idx(self, off):
        lines = self._lines(); n = 0
        for i, l in enumerate(lines, 1):
            if off <= n + len(l): return f"{i}.{off - n}"
            n += len(l) + 1
        return f"{len(lines)}.{len(lines[-1])}"
    def index(self, spec): return self._to_idx(self._to_off(spec))
    def delete(self, a, b=None): self.text = ''; self.tags = {}
    def insert(self, where, text, *tags):
        start = len(self.text); self.text += text
        for group in tags:
            for t in ((group,) if isinstance(group, str) else group):
                self.tags.setdefault(t, []).append((start, len(self.text)))
    def get(self, a, b=None): return self.text[self._to_off(a):self._to_off(b) if b else None]
    def tag_add(self, tag, a, b): self.tags.setdefault(tag, []).append((self._to_off(a), self._to_off(b)))
    def tag_remove(self, tag, a, b): self.tags.pop(tag, None)
    def tag_ranges(self, tag):
        r = self.tags.get(tag, [])
        return (self._to_idx(r[0][0]), self._to_idx(r[0][1])) if r else ()
    def tagged(self, tag): return sorted(self.text[a:b] for a, b in self.tags.get(tag, []))
    def select(self, a, b): self.tags['sel'] = [(a, b)]
    def select_text(self, sub, nth=0):
        pos = -1
        for _ in range(nth + 1): pos = self.text.index(sub, pos + 1)
        self.select(pos, pos + len(sub)); return pos

from ui.results_renderer import ResultsRenderer
def make():
    w = FakeText(); r = ResultsRenderer(w); r.marks_store = MarksStore(tmpdb()); return w, r
def tps(*contents, file='bibl.txt'):
    return [{'global_idx': i, 'rowid': 100 + i, 'header': f'Файл: {file}', 'content': c, 'file_name': file} for i, c in enumerate(contents)]
def page(r, t): r.render_results_page(t, 0, len(t), [], [], False)

T = ["Alpha beta gamma delta. Second line here.", "Epsilon zeta eta theta."]
w, r = make(); page(r, tps(*T))
w.select_text('beta gamma'); check('«A+» вне подчёркнутого: need_mark', r.style_selection('big') == 'need_mark')
w.select_text('beta gamma'); r.toggle_underline()
w.select_text('beta'); check('«A+» внутри подчёркнутого: on', r.style_selection('big') == 'on' and w.tagged('user_big') == ['beta'])
w.select_text('beta'); check('повторно: off', r.style_selection('big') == 'off' and w.tagged('user_big') == [])
w.select_text('gamma'); check('«Цвет»: on, независимо от размера', r.style_selection('color') == 'on' and w.tagged('user_color') == ['gamma'])
w.select_text('beta gamma'); check('снятие «Ч» снимает и цвет', r.toggle_underline() == ('removed', 1) and w.tagged('user_color') == [] and not r.marks_store.styles_for_file('bibl.txt'))
w.select_text('beta gamma'); r.toggle_underline(); w.select_text('beta'); r.style_selection('big')
page(r, tps(*T)); check('после перерисовки слои на месте', w.tagged('user_big') == ['beta'] and w.tagged('user_mark') == ['beta gamma'])

# мысли
w.select_text('gamma'); check('selection_note: мысли ещё нет', r.selection_note() == ('ok', None))
check('мысль добавляется', r.add_note('важно\nочень') == 'added')
check('мысль в тексте — курсивом в скобках сразу за фрагментом', 'gamma (важно очень) delta' in w.text and w.tagged('user_note') == [' (важно очень)'])
check('карта кусков: текст мысли не принадлежит исходному тексту',
      ''.join(r.regions[0]['display'][d:d + l] for d, c, l in r.regions[0]['segments']) == T[0])
w.select_text('delta'); check('«Ч» после вставки мысли работает по тексту', r.toggle_underline() == ('added', 1) and w.tagged('user_mark')[-1] == 'delta')
check('у мысли есть место на экране', r.note_at(w._to_idx(w.text.index('важно'))) is not None)
nid = r.marks_store.notes_for_file('bibl.txt')[0].id
w.select_text('gamma'); check('повторная мысль к тому же фрагменту заменяет текст', r.add_note('другая') == 'updated' and len(r.marks_store.notes_for_file('bibl.txt')) == 1 and '(другая)' in w.text)
r.edit_note(nid, 'правка'); check('правка мысли перерисовывает', '(правка)' in w.text and '(другая)' not in w.text)
w.select_text('(правка)'); check('выделенная мысль без своего фрагмента — «Ч» не создаёт отметку на тексте мысли', r.toggle_underline()[0] in ('empty', 'outside', 'added') and 'правка' not in ' '.join(m.fragment for m in r.marks_store.marks_for_file('bibl.txt')))

# режим «только отмеченное»
r.marks_only = True; page(r, tps(*T))
check('«только отмеченное»: подчёркнутое, склеенное « … », без остального', 'Second line' not in w.text and 'beta gamma' in w.text, w.text)
w.select_text('beta'); check('в этом режиме правка выключена', r.toggle_underline() == ('marks_only', 0) and r.style_selection('big') == 'marks_only' and r.add_note('x') == 'marks_only')
r.marks_only = False; page(r, tps("Пустой блок без отметок", "gamma"))
r.marks_only = True; page(r, tps("Пустой блок без отметок")); check('нет отметок — «(отметок нет)»', '(отметок нет)' in w.text)
r.marks_only = False; w, r = make(); page(r, tps(*T)); r.replay(); check('replay без правок даёт тот же текст', w.text.count('Alpha') == 1)

# ===================== D. синхронизация слоёв =====================
t = tmp(); drive = os.path.join(t, 'drive'); os.makedirs(drive)
A, B = MarksStore(os.path.join(t, 'a.db')), MarksStore(os.path.join(t, 'b.db'))
ka, kb = os.path.join(t, 'ka.txt'), os.path.join(t, 'kb.txt')
A.add_mark('bibl.txt', 'слово', 'до ', ' после'); A.add_style('bibl.txt', 'big', 'слово', 'до ', ' после'); A.add_note('bibl.txt', 'слово', 'до ', ' после', 'мысль А', 'b')
rep = S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba'))
check('файл слоёв sineva_extra.json в папке, формат как у телефона', os.path.exists(os.path.join(drive, 'sineva_extra.json'))
      and {x['type'] for x in json.load(open(os.path.join(drive, 'sineva_extra.json'), encoding='utf-8'))['records']} == {'style', 'note'})
rep = S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb'))
check('слои пришли на второе устройство', rep['extra_added'] == 2 and B.styles_for_file('bibl.txt', 'big') and B.notes_for_file('bibl.txt')[0].text == 'мысль А' and B.notes_for_file('bibl.txt')[0].flags == 'b')
time.sleep(1.1)
B.update_note(B.notes_for_file('bibl.txt')[0].id, text='мысль Б')
S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb')); S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba'))
check('правка мысли доходит до первого устройства (побеждает более поздняя)', A.notes_for_file('bibl.txt')[0].text == 'мысль Б' and len(A.notes_for_file('bibl.txt')) == 1)
time.sleep(1.1)
A.delete_styles([x.id for x in A.styles_for_file('bibl.txt')])
S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba')); rep = S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb'))
check('снятие размера доходит до другого устройства, мысль остаётся', rep['extra_removed'] == 1 and not B.styles_for_file('bibl.txt') and B.notes_for_file('bibl.txt'))
check('подчёркивание не пострадало от обмена слоями', len(A.all_marks()) == 1 and len(B.all_marks()) == 1)
# файл, записанный «мобильной» стороной вручную
mobile = {'version': 1, 'records': [{'uid': M.style_uid('color', 'm.txt', 'x', 'a ', ' b'), 'type': 'style', 'kind': 'color', 'file_key': 'm.txt',
          'file_label': 'm.txt', 'fragment': 'x', 'before': 'a ', 'after': ' b', 'created': '2026-01-01T00:00:00'}], 'deleted': {}}
d2 = os.path.join(t, 'drive2'); os.makedirs(d2); open(os.path.join(d2, 'sineva_extra.json'), 'w', encoding='utf-8').write(json.dumps(mobile))
C = MarksStore(os.path.join(t, 'c.db')); S.sync_with_folder(d2, C, os.path.join(t, 'kc.txt'), os.path.join(t, 'bc'))
check('данные телефона (sineva_extra.json) читаются', [(s.kind, s.fragment) for s in C.styles_for_file('m.txt')] == [('color', 'x')])
open(os.path.join(d2, 'sineva_extra.json'), 'w').write('{плохой json')
try: S.sync_with_folder(d2, C, os.path.join(t, 'kc.txt'), os.path.join(t, 'bc')); bad = False
except ValueError: bad = True
check('повреждённый файл слоёв — понятная ошибка, данные не затираются', bad and C.styles_for_file('m.txt'))

# ===================== E. mconfig: первая строка книги =====================
from utils import mconfig, text_processing
check('parse: обычная строка', mconfig.parse('mconfig=" isida_1.docx = Разоблаченная Изида, N2000"') == ('isida_1.docx', 'Разоблаченная Изида', 'N2000'))
check('parse: типографские кавычки и название с запятой', mconfig.parse('mconfig=“a.txt = Книга, часть 1, N500”') == ('a.txt', 'Книга, часть 1', 'N500'))
check('parse: мусор не строка mconfig', mconfig.parse('Обычный текст') is None and mconfig.parse('mconfig="a.txt = Только имя"') is None)
d = tmp(); p = os.path.join(d, 'isida_1.txt')
open(p, 'w', encoding='utf-8-sig').write('mconfig=" isida_1.txt = Разоблаченная Изида, N2000"\nПервая строка книги\nВторая')
check('read: совпадает имя -> (название, разделитель)', mconfig.read(p) == (('Разоблаченная Изида', 'N2000'), ''))
check('строка в тексте книги скрыта (индексация, просмотр)', text_processing.read_text_file(p) == 'Первая строка книги\nВторая')
open(os.path.join(d, 'other.txt'), 'w', encoding='utf-8').write('mconfig="zzz.txt = Не та, N1"\nТекст')
cfg, note = mconfig.read(os.path.join(d, 'other.txt')); check('read: имя не совпало -> строка пропущена с пояснением', cfg is None and 'не совпадает' in note)
open(os.path.join(d, 'plain.txt'), 'w', encoding='utf-8').write('Просто текст'); check('книга без mconfig', mconfig.read(os.path.join(d, 'plain.txt')) == (None, '') and text_processing.read_text_file(os.path.join(d, 'plain.txt')) == 'Просто текст')

from services.file_manager import FileManager
cd = {'plain.txt': ('Простая', 'N1000', '')}
logs = []
fm = FileManager(None, cd, 'N1000', None, logs.append, {}, lambda: None); saved = []
fm.save_config_callback = lambda: saved.append(1)
ch = fm.apply_book_configs([p, os.path.join(d, 'other.txt'), os.path.join(d, 'plain.txt')])
check('новая книга: название и разделитель попали в настройки, настройки сохранены', cd.get('isida_1.txt') == ('Разоблаченная Изида', 'N2000', '') and saved == [1] and ch == [('isida_1.txt', 'Разоблаченная Изида', 'N2000')])
check('книга с неверным именем в строке не попала в настройки', 'other.txt' not in cd)
open(p, 'w', encoding='utf-8').write('mconfig="isida_1.txt = Новое имя, N300"\nТекст'); time.sleep(0.05); os.utime(p, None)
check('при обычном обновлении списка настройки книги не затираются', fm.apply_book_configs([p]) == [] and cd['isida_1.txt'][0] == 'Разоблаченная Изида')
fm.apply_book_configs([p], override=True)
check('при подключении (копирование в DB) строка в книге главнее', cd['isida_1.txt'] == ('Новое имя', 'N300', ''))
cd['isida_1.txt'] = ('Новое имя', 'N300', 'искл'); open(p, 'w', encoding='utf-8').write('mconfig="isida_1.txt = Ещё, N400"\nТекст'); fm.apply_book_configs([p], override=True)
check('подстрока-исключение (Excel) сохраняется', cd['isida_1.txt'] == ('Ещё', 'N400', 'искл'))

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(1 if False in results else 0)
