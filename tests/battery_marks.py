import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, os, re, time, types, random, tempfile, importlib.util
import tkinter as tk
from services import marks as M
from services.marks import MarksStore, Mark

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))
def tmpdb(): return os.path.join(tempfile.mkdtemp(prefix='marks_'), 'marks.db')

# ===================== A. нормализация, файл, поля =====================
rnd = random.Random(1); ok = True
for _ in range(300):
    s = ''.join(rnd.choice(['а', 'б', ' ', '\n', '\t', '  ', '\n\n', 'в']) for _ in range(rnd.randint(0, 40)))
    norm, idx = M.normalize_with_map(s)
    ok &= norm == M.collapse_ws(s) and len(idx) == len(norm) and all(
        (s[idx[i]].isspace() if norm[i] == ' ' else s[idx[i]] == norm[i]) for i in range(len(norm)))
check('normalize_with_map: 300 случайных строк — текст как у collapse_ws, карта индексов верна', ok)
check('file_key: путь, регистр и разделители не важны', M.file_key('DB\\Bibl.TXT') == M.file_key('/x/y/bibl.txt') == M.file_key('bibl.txt') == 'bibl.txt')
check('span_fields: пробелы по краям срезаются, окружение схлопнуто',
      M.span_fields('aaa  bbb ccc\n\nddd', 3, 12) == ('bbb ccc', 'aaa ', ' ddd') or M.span_fields('aaa  bbb ccc\n\nddd', 3, 12) == ('bbb ccc', 'aaa ', ' ddd'),
      str(M.span_fields('aaa  bbb ccc\n\nddd', 3, 12)))
check('span_fields: одни пробелы -> None', M.span_fields('a   b', 1, 4) is None)

def mk(i, frag, before='', after='', key='bibl.txt'): return Mark(i, key, key, frag, before, after, '')
def spans(content, marks): return sorted((s, e) for _m, s, e in M.find_mark_spans(content, marks))
def mark_from(content, frag, nth=0):
    pos = -1
    for _ in range(nth + 1): pos = content.index(frag, pos + 1)
    f, b, a = M.span_fields(content, pos, pos + len(frag)); return mk(1, f, b, a)

c = "кот сидит. кот спит."
m2 = mark_from(c, 'кот', 1)
check('одинаковые слова различаются окружением: подчёркнут только второй «кот»', spans(c, [m2]) == [(c.rindex('кот'), c.rindex('кот') + 3)], str(spans(c, [m2])))
mA = mark_from("Он сказал: Бог есть любовь. Все слышали.", 'Бог')
check('то же слово в начале ДРУГОГО блока не подчёркивается (окружение не сходится)', spans("Бог создал небо и землю.", [mA]) == [])
check('в своём блоке находится', len(spans("Он сказал: Бог есть любовь. Все слышали.", [mA])) == 1)
mLong = mark_from("Он сказал слово конец света, и все ушли.", 'слово')
check('блок из одного такого же слова (окружение проверить НЕ ЧЕМ) не подчёркивается — работает порог проверенного окружения',
      spans("слово", [mLong]) == [] and spans("слово.", [mLong]) == [])
check('а блок, где то же окружение есть, подчёркивается', len(spans("Он сказал слово конец света, и все ушли.", [mLong])) == 1)
# разные пробелы: индексация .docx пропускает пустые абзацы, просмотр файла их сохраняет
topic = "Первый абзац про равновесие.\nВторой абзац о гармонии."
fileview = "Первый абзац про равновесие.\n\n\nВторой абзац о гармонии.\n\n"
mT = mark_from(topic, 'равновесие.\nВторой')
sp = spans(fileview, [mT])
check('пустые строки в файле не мешают: отметка из топика найдена в просмотре файла', len(sp) == 1 and fileview[sp[0][0]:sp[0][1]] == 'равновесие.\n\n\nВторой', str(sp))
mF = mark_from(fileview, 'гармонии')
check('и наоборот: отметка из просмотра файла найдена в топике', spans(topic, [mF]) == [(topic.index('гармонии'), topic.index('гармонии') + 8)])
# окружение обрезано границей блока (топик — кусок файла)
filetext = "Предыдущее предложение тут. Начало блока: важное слово здесь. Конец блока. Следующее предложение там."
block = "Начало блока: важное слово здесь. Конец блока."
mFile = mark_from(filetext, 'Начало блока')
check('отметка из файла у границы блока найдена в блоке (окружение короче — допустимо)', len(spans(block, [mFile])) == 1)
mBlock = mark_from(block, 'Конец блока')
check('отметка из блока найдена в файле', len(spans(filetext, [mBlock])) == 1)
mWhole = mk(1, M.collapse_ws(block), '', '')
check('отметка на весь блок (пустое окружение) находится', len(spans(block, [mWhole])) == 1)
check('фрагмента нет в тексте — отметка просто не показывается', spans("совсем другой текст", [mA]) == [])
dup = "Повтор тут. Повтор тут. Повтор тут."
check('одинаковый фрагмент с одинаковым окружением — подчёркиваются все вхождения', len(spans(dup, [mk(1, 'Повтор тут.', '', '')])) == 3)

# карта кусков
segs = [(0, 10, 5), (8, 30, 4)]
check('экран -> текст по куску', M.display_span_to_content(segs, 1, 4) == [(11, 14)])
check('экран -> текст через «…»: два куска, разделитель пропущен', M.display_span_to_content(segs, 3, 10) == [(13, 15), (30, 32)], str(M.display_span_to_content(segs, 3, 10)))
check('текст -> экран', M.content_span_to_display(segs, 31, 33) == [(9, 11)] and M.content_span_to_display(segs, 0, 5) == [])

# планы "Ч"
doc = "alpha beta gamma delta"
def located_for(*words):
    out = []
    for i, w in enumerate(words, 1):
        p = doc.index(w); f, b, a = M.span_fields(doc, p, p + len(w)); out.append((mk(i, f, b, a), p, p + len(w)))
    return out
loc = located_for('alpha beta gamma')
cs, ce, ov, full = M.analyze_span(doc, loc, doc.index('beta'), doc.index('beta') + 4)
check('analyze: выделение внутри подчёркнутого — «целиком подчёркнуто»', full is True and len(ov) == 1)
ids, keep = M.plan_remove(doc, cs, ce, ov)
check('снятие с середины: остаются хвосты «alpha» и «gamma»', ids == [1] and [doc[a:b].strip() for a, b in keep] == ['alpha', 'gamma'], str(keep))
cs, ce, ov, full = M.analyze_span(doc, loc, doc.index('beta'), len(doc))
check('выделение шире подчёркнутого — не «целиком»', full is False)
ids, new = M.plan_add(cs, ce, ov)
check('добавление сливается с пересекающейся отметкой в одну', ids == [1] and [doc[a:b] for a, b in new] == ['alpha beta gamma delta'], str(new))
loc2 = located_for('alpha', 'beta')
res = M.analyze_span(doc, loc2, 0, doc.index('beta') + 4)
check('два соседних подчёркнутых слова + пробел между ними = «целиком» (пробелы не в счёт)', res[3] is True)
check('одни пробелы -> analyze даёт None', M.analyze_span("a   b", [], 1, 4) is None)
check('без отметок «целиком» = False', M.analyze_span(doc, [], 0, 5)[3] is False)

# ===================== B. хранилище =====================
db = tmpdb(); st = MarksStore(db)
check('создание хранилища не открывает файл (недоступная папка не мешает запуску)', MarksStore('/nonexistent_dir_xyz/marks.db')._conn is None)
try: MarksStore('/nonexistent_dir_xyz/marks.db').all_marks(); raised = False
except Exception: raised = True
check('обращение к недоступному файлу — исключение (его покажет окно, а не тихий сбой)', raised)
i1 = st.add_mark('DB\\Bibl.txt', 'фрагмент', 'до ', ' после'); i2 = st.add_mark('bibl.txt', 'второй', '', ''); i3 = st.add_mark('other.txt', 'чужой', '', '')
check('marks_for_file: по ключу файла (путь/регистр неважны)', [m.fragment for m in st.marks_for_file('bibl.txt')] == ['фрагмент', 'второй'])
check('метка файла для экспорта сохраняет исходное написание', st.marks_for_file('bibl.txt')[0].file_label == 'Bibl.txt')
st.add_mark('bibl.txt', 'третий', '', ''); n = len(st.marks_for_file('bibl.txt'))
check('кэш сбрасывается после записи', n == 3)
st.delete_marks([i1, i3])
check('delete_marks убирает и сбрасывает кэш обоих файлов', [m.fragment for m in st.marks_for_file('bibl.txt')] == ['второй', 'третий'] and st.marks_for_file('other.txt') == [])
st.close(); st2 = MarksStore(db)
check('отметки переживают закрытие и повторное открытие', [m.fragment for m in st2.all_marks()] == ['второй', 'третий'])
st2.delete_marks([]); check('пустое удаление безопасно', len(st2.all_marks()) == 2)

# ===================== C. экспорт в Word =====================
from docx import Document
st3 = MarksStore(tmpdb())
st3.add_mark('b.txt', 'подчёркнутое слово', 'до него ', ' после него'); st3.add_mark('a.txt', 'первый файл', '', ''); st3.add_mark('b.txt', 'плохой\x00символ', '', '')
out = os.path.join(tempfile.mkdtemp(), 'экспорт.docx'); M.export_marks_docx(st3.all_marks(), out)
d = Document(out); paras = [(p.style.name, p.text) for p in d.paragraphs]
check('экспорт: заголовок и счётчик', paras[0] == ('Heading 1', 'Подчёркнутые фрагменты') and 'Фрагментов: 3' in paras[1][1], str(paras[:2]))
heads = [t for s, t in paras if s == 'Heading 2']
check('экспорт: по разделу на файл, в алфавитном порядке', heads == ['a.txt', 'b.txt'], str(heads))
p = [p for p in d.paragraphs if 'подчёркнутое слово' in p.text][0]
under = [r.text for r in p.runs if r.font.underline]; grey = [r.text for r in p.runs if r.font.color is not None and r.font.color.rgb is not None]
check('экспорт: подчёркнут именно фрагмент, окружение серым', under == ['подчёркнутое слово'] and any('до него' in g for g in grey) and any('после него' in g for g in grey), (under, grey))
check('экспорт: недопустимые для XML символы не роняют запись', any('плохойсимвол' in p.text for p in d.paragraphs))
check('экспорт: нет временного файла', not os.path.exists(out + '.part'))

# ===================== D. краткий режим: карта кусков =====================
from utils import highlighting as H
sents = ["Первое предложение про слово.", "Второе предложение ни о чём.", "Третье про слово тоже.", "Четвёртое пустое.", "Пятое про слово снова."]
def brief_digest(fn):
    import hashlib
    gen = random.Random(3); h = hashlib.md5()
    for _ in range(200):
        content = ' '.join(gen.choice(sents) for _ in range(gen.randint(1, 6)))
        for words in (['слово'], ['нету'], []):
            h.update(repr(fn(content, words, [])).encode('utf-8'))
    return h.hexdigest()
rnd = random.Random(3); mapped_ok = True
for _ in range(200):
    content = ' '.join(rnd.choice(sents) for _ in range(rnd.randint(1, 6)))
    for words in (['слово'], ['нету'], []):
        text, ints, segs = H.build_brief_view_mapped(content, words, [])
        rebuilt = ' … '.join(content[c0:c0 + L] for _d, c0, L in segs)
        mapped_ok &= (rebuilt == text) and all(text[d:d + L] == content[c0:c0 + L] for d, c0, L in segs)
# «Золотое» значение посчитано по ПРЕЖНЕЙ build_brief_view (до появления карты кусков) на тех же 200 текстах × 3 запроса.
check('build_brief_view даёт прежний результат (200 случайных текстов × 3 запроса) — золотой хеш прежней версии',
      brief_digest(H.build_brief_view) == 'f416926f01a696972a0ca2675edcb5ba')
check('карта кусков восстанавливает короткий текст из исходного, куски на своих местах', mapped_ok)

# ===================== E. рендерер =====================
class FakeText:
    def __init__(self): self.text = ''; self.tags = {}; self.cursor = None
    def config(self, **k): pass
    configure = config
    def update_idletasks(self): pass
    def tag_config(self, *a, **k): pass
    def tag_bind(self, *a, **k): pass
    def yview(self, *a): pass
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
    def clear_sel(self): self.tags.pop('sel', None)

from ui.results_renderer import ResultsRenderer
def make_renderer(store=True):
    w = FakeText(); r = ResultsRenderer(w); r.marks_store = MarksStore(tmpdb()) if store else None; return w, r
def topics(*contents, file='bibl.txt'):
    return [{'global_idx': i, 'rowid': 100 + i, 'header': f'Файл: {file} | (уровень 1, совп. 1)', 'content': c, 'file_name': file} for i, c in enumerate(contents)]
def page(r, tps, brief=False, words=()):
    r.render_results_page(tps, 0, len(tps), list(words), [], brief)

T = ["Alpha beta gamma delta.\nSecond line here.", "Epsilon zeta eta theta.", "Iota kappa lambda mu."]
w, r = make_renderer(); page(r, topics(*T))
check('страница: по блоку на каждый топик, шапки вне блоков', len(r.regions) == 3 and all(w.get(g['start'], g['end']) == g['display'] for g in r.regions))
w.select_text('beta'); res = r.toggle_underline()
check('«Ч» по выделенному слову: added, подчёркнуто ровно оно', res == ('added', 1) and w.tagged('user_mark') == ['beta'], str((res, w.tagged('user_mark'))))
page(r, topics(*T))
check('подчёркивание не теряется при перерисовке страницы', w.tagged('user_mark') == ['beta'])
w.select_text('beta'); res = r.toggle_underline()
check('повторное «Ч» по тому же — removed, подчёркивания нет, в базе пусто', res == ('removed', 1) and w.tagged('user_mark') == [] and r.marks_store.all_marks() == [])

w, r = make_renderer(); page(r, topics(*T)); w.select_text('beta gamma'); r.toggle_underline()
w.select_text('gamma'); res = r.toggle_underline()
check('снятие с части: остаются хвосты («beta» остаётся подчёркнутым)', res[0] == 'removed' and w.tagged('user_mark') == ['beta'], str(w.tagged('user_mark')))
w.select_text('beta gamma delta'); res = r.toggle_underline()
check('выделение шире подчёркнутого — подчёркивается всё, отметки сливаются в одну', res[0] == 'added' and w.tagged('user_mark') == ['beta gamma delta'] and len(r.marks_store.all_marks()) == 1, str(w.tagged('user_mark')))

w, r = make_renderer(); page(r, topics(*T)); pos = w.text.index('line here'); end = w.text.index('Epsilon') + 7
w.select(pos, end); res = r.toggle_underline()
check('выделение через два блока: подчёркнуты обе части, шапка между ними — нет', res == ('added', 2) and w.tagged('user_mark') == ['Epsilon', 'line here.'] and not any('Файл' in t for t in w.tagged('user_mark')), str(w.tagged('user_mark')))

w, r = make_renderer(); page(r, topics(*T))
w.clear_sel(); check('нет выделения', r.toggle_underline() == ('no_selection', 0))
w.select_text('Файл: bibl.txt'); check('выделена только шапка блока -> outside', r.toggle_underline() == ('outside', 0))
w.select(w.text.index('beta') - 1, w.text.index('beta')); check('выделен один пробел -> empty', r.toggle_underline() == ('empty', 0))
check('ничего не записано при отказах', r.marks_store.all_marks() == [] and w.tagged('user_mark') == [])

# краткий режим
BRIEF = "Первое предложение про слово. Второе предложение ни о чём. Третье предложение про слово тоже."
w, r = make_renderer(); page(r, topics(BRIEF), brief=True, words=['слово'])
check('краткий режим: показаны первое и третье предложения через « … »', w.get(r.regions[0]['start'], r.regions[0]['end']) == "Первое предложение про слово. …  Третье предложение про слово тоже.", w.text)
a = w.text.index('слово.'); b = w.text.index('Третье') + 6
w.select(a, b); res = r.toggle_underline()
check('выделение через « … »: две отметки, сам разделитель не подчёркнут', res == ('added', 2) and w.tagged('user_mark') == ['Третье', 'слово.'], str(w.tagged('user_mark')))
page(r, topics(BRIEF), brief=False)
check('те же отметки в РАЗВЁРНУТОМ режиме на своих местах (и нет подчёркивания в пропущенном предложении)', w.tagged('user_mark') == ['Третье', 'слово.'] and 'ни о чём' not in ''.join(w.tagged('user_mark')))
w.select_text('Второе предложение'); r.toggle_underline()
page(r, topics(BRIEF), brief=True, words=['слово'])
check('отметка из пропущенного предложения в кратком режиме не видна, но в базе есть', 'Второе предложение' not in w.tagged('user_mark') and any(m.fragment == 'Второе предложение' for m in r.marks_store.all_marks()), str(w.tagged('user_mark')))
page(r, topics(BRIEF), brief=False)
check('в развёрнутом — видна', 'Второе предложение' in w.tagged('user_mark'))

# просмотр файла целиком
FT = "Первый абзац про равновесие.\n\n\nВторой абзац о гармонии.\n\nТретий абзац без отметок."
w, r = make_renderer(); page(r, topics("Первый абзац про равновесие.\nВторой абзац о гармонии."))
w.select_text('равновесие.\nВторой'); r.toggle_underline()
off = r.render_file_content(FT, lambda e: None, file_name='DB\\Bibl.TXT')
check('просмотр файла: отметка, сделанная в топике, видна (в файле между абзацами пустые строки)', w.tagged('user_mark') == ['равновесие.\n\n\nВторой'], str(w.tagged('user_mark')))
check('шапка «Назад к результатам» не подчёркнута, блок файла начинается с 3-й строки', off == len("◀ Назад к результатам\n\n") and r.regions[0]['start'] == '3.0')
w.select_text('Третий абзац'); r.toggle_underline()
page(r, topics("Третий абзац без отметок."))
check('отметка, сделанная при просмотре файла, видна в топике', w.tagged('user_mark') == ['Третий абзац'], str(w.tagged('user_mark')))

# изоляция и ложные срабатывания
w, r = make_renderer(); page(r, topics("Он сказал: Бог есть любовь. Все слышали.", "Бог создал небо и землю.")); w.select_text('Бог', 0); r.toggle_underline()
check('то же слово в начале другого топика того же файла не подчёркнуто', w.tagged('user_mark') == ['Бог'] and w.text.count('Бог') == 2 and len(w.tags['user_mark']) == 1)
r.render_results_page(topics("Он сказал: Бог есть любовь. Все слышали.", file='other.txt'), 0, 1, [], [], False)
check('отметка другого файла не показывается (одинаковый текст)', w.tagged('user_mark') == [])

# режимы без подчёркивания
w, r = make_renderer(); page(r, topics(*T)); w.select_text('beta')
r.render_results_page_compact([{'content': 'beta gamma'}], [], [], False); w.select_text('beta')
check('режим разделения (compact): блоков нет — «unsupported»', r.regions == [] and r.toggle_underline() == ('unsupported', 0))
page(r, topics(*T)); r.render_error("ошибка"); w.select_text('ошибка')
check('после ошибки/справки блоков нет', r.regions == [] and r.toggle_underline() == ('unsupported', 0))
w2, r2 = make_renderer(store=False); page(r2, topics(*T)); w2.select_text('beta')
check('вторая панель без хранилища: «unavailable», показ результатов работает', r2.toggle_underline() == ('unavailable', 0) and len(r2.regions) == 3)

# сбой хранилища
class BrokenStore:
    def marks_for_file(self, k): raise OSError("диск недоступен")
    def delete_marks(self, ids): raise OSError("диск недоступен")
    def add_mark(self, *a): raise OSError("диск недоступен")
w, r = make_renderer(); r.marks_store = BrokenStore()
try: page(r, topics(*T)); shown = True
except Exception as e: shown = False
check('сбой хранилища не ломает показ результатов', shown and len(r.regions) == 3 and w.tagged('user_mark') == [])
w.select_text('beta')
try: r.toggle_underline(); raised = False
except OSError: raised = True
check('сбой хранилища при «Ч» пробрасывается — окно покажет ошибку', raised)

# скорость
w, r = make_renderer(); rr = random.Random(7)
words = [''.join(rr.choice('абвгдежзиклмн') for _ in range(rr.randint(4, 9))) for _ in range(400)]
bodies = [' '.join(rr.choice(words) for _ in range(300)) for _ in range(30)]
for b in bodies[:20]:
    pos = rr.randint(0, len(b) - 30); f, bf, af = M.span_fields(b, pos, pos + 12); r.marks_store.add_mark('bibl.txt', f, bf, af)
for _ in range(180):
    b = rr.choice(bodies); pos = rr.randint(0, len(b) - 30); f, bf, af = M.span_fields(b, pos, pos + 10); r.marks_store.add_mark('bibl.txt', f, bf, af)
t0 = time.time(); page(r, topics(*bodies)); first = time.time() - t0
M._NORM_CACHE.clear(); t0 = time.time(); r.apply_marks(); cold = time.time() - t0
t0 = time.time(); r.apply_marks(); warm = time.time() - t0
print(f"     скорость: 200 отметок, 30 блоков по ~{len(bodies[0])} симв.: показ страницы {first*1000:.0f} мс, apply (холодно) {cold*1000:.0f} мс, apply (кэш) {warm*1000:.0f} мс")
check('показ страницы с 200 отметками укладывается в секунду', first < 1.0 and cold < 1.0, f"{first:.2f}/{cold:.2f}")
check('подчёркнуто не меньше, чем отметок с различимым окружением', len(w.tags.get('user_mark', [])) >= 150, str(len(w.tags.get('user_mark', []))))

# ===================== F. главное окно =====================
import ui.app_window as aw
class Win(aw.AppWindow):
    pass
def make_win():
    win = Win.__new__(Win)
    win.toasts = []; win.logs = []; win.updated = 0
    win._show_temporary_notification = lambda m, duration_ms=700: win.toasts.append(m)
    win._update_log_field = win.logs.append
    win.update_text_list = lambda: setattr(win, 'updated', win.updated + 1)
    win.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: False)
    win.search_controller = types.SimpleNamespace(split_mode_active=False)
    rw, rr_ = make_renderer(); win.results_renderer = rr_; win.marks_store = rr_.marks_store; win.rw = rw
    return win
shown = []
aw.messagebox = types.SimpleNamespace(showerror=lambda t, m, **k: shown.append(('err', m)), showinfo=lambda t, m, **k: shown.append(('info', m)), askyesno=lambda t, m, **k: shown.append(('ask', m)) or ANSWER['v'])
ANSWER = {'v': False}
win = make_win(); page(win.results_renderer, topics(*T))
win._toggle_underline(); check('«Ч» без выделения: подсказка «Сначала выделите текст»', win.toasts == ["Сначала выделите текст"])
win.rw.select_text('beta'); win._toggle_underline()
check('«Ч» ставит подчёркивание и пишет в строку состояния', win.rw.tagged('user_mark') == ['beta'] and win.logs[-1].endswith('Подчёркнуто'))
win._toggle_underline(); check('повторное «Ч» снимает', win.rw.tagged('user_mark') == [] and 'снято' in win.logs[-1])
win.search_controller.split_mode_active = True; n = len(win.toasts); win._toggle_underline()
check('режим разделения: сообщение, ничего не делается', len(win.toasts) == n + 1 and 'разделени' in win.toasts[-1])
win.search_controller.split_mode_active = False; win.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: True); win._toggle_underline()
check('показана визуализация: «Откройте окно результатов»', 'результатов' in win.toasts[-1])
win.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: False); win.results_renderer.marks_store = BrokenStore(); win.rw.select_text('beta'); shown.clear(); win._toggle_underline()
check('сбой базы при «Ч»: окно с ошибкой, программа не падает', shown and shown[0][0] == 'err' and 'диск недоступен' in shown[0][1], str(shown))

# экспорт
cwd = os.getcwd(); work = tempfile.mkdtemp(); os.chdir(work)
try:
    win = make_win(); shown.clear(); win.export_underlined()
    check('экспорт без отметок: сообщение, файла нет', shown and shown[0][0] == 'info' and 'пока нет' in shown[0][1] and not os.path.exists('DB'))
    win.marks_store.add_mark('bibl.txt', 'слово', 'до ', ' после'); win.marks_store.add_mark('gita.txt', 'другое', '', '')
    opened = []; aw.os.startfile = lambda p: opened.append(p); aw.sys = types.SimpleNamespace(platform='win32')
    shown.clear(); ANSWER['v'] = False; win.export_underlined()
    files = os.listdir('DB')
    check('экспорт: один .docx в папке DB с понятным именем', len(files) == 1 and files[0].startswith('Подчёркнутое ') and files[0].endswith('.docx'), str(files))
    check('экспорт: список файлов в окне обновлён, «Открыть?» задан, при «Нет» файл не открывается', win.updated == 1 and shown[0][0] == 'ask' and 'Фрагментов: 2' in shown[0][1] and opened == [])
    d = Document(os.path.join('DB', files[0])); check('экспорт: в документе обе отметки', 'слово' in '\n'.join(p.text for p in d.paragraphs) and 'другое' in '\n'.join(p.text for p in d.paragraphs))
    ANSWER['v'] = True; time.sleep(1.1); win.export_underlined()
    check('«Да»: файл открыт; повторный экспорт не затирает прежний (имя с секундами)', len(opened) == 1 and len(os.listdir('DB')) == 2, str((opened, os.listdir('DB'))))
    aw.export_marks_docx = lambda marks, path: (_ for _ in ()).throw(ImportError("Для экспорта в Word установите python-docx"))
    shown.clear(); win.export_underlined()
    check('нет python-docx: понятное сообщение', shown and shown[0][0] == 'err' and 'python-docx' in shown[0][1])
    win.marks_store = BrokenStore(); BrokenStore.all_marks = lambda self: (_ for _ in ()).throw(OSError("нет доступа к marks.db")); shown.clear(); win.export_underlined()
    check('нет доступа к базе: сообщение вместо падения', shown and shown[0][0] == 'err' and 'marks.db' in shown[0][1])
finally:
    os.chdir(cwd)

src = open(os.path.join(env.ROOT, 'ui/app_window.py'), encoding='utf-8').read()
check('кнопка «Ч»: подчёркнутый шрифт, слева (между «В конец» и «Кратко/Всё»), подсказка «Подчеркнуть»', "text=\"Ч\"" in src and "'bold underline'" in src and "self.btn_underline.pack(side='left'" in src and 'ToolTip(self.btn_underline, "Подчеркнуть")' in src)
check('пункт «Экспорт подчеркнутых» в меню «Настройки»', 'self.settings_menu.add_command(label="Экспорт подчеркнутых", command=self.export_underlined)' in src)
check('база закрывается при выходе', "getattr(self, 'marks_store', None)" in src and 'marks_store.close()' in src)
sc = open(os.path.join(env.ROOT, 'services/search_controller.py'), encoding='utf-8').read()
check('контроллер передаёт имя файла и в результаты, и в просмотр файла', "'file_name': file_name,  # для подчёркивания" in sc and 'file_name=file_name)' in sc)
import config
check('MARKS_DB_FILE лежит рядом с mconfig.ini', os.path.dirname(config.MARKS_DB_FILE) == os.path.dirname(config.CONFIG_FILE) and config.MARKS_DB_FILE.endswith('marks.db'))

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
