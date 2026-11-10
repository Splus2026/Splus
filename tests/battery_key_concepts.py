import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, os, re, ast, types, random, time, tempfile, importlib.machinery
from unittest.mock import MagicMock
import numpy as np
import tkinter as tk
results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))
from utils import key_concepts as KC
ROOT = env.ROOT

# ===== A. определение вариации — то же, что у «−В/+В» =====
rnd = random.Random(5); letters = 'абвгдежзиклмн'
def rw(a=1, b=9): return ''.join(rnd.choice(letters) for _ in range(rnd.randint(a, b)))
def variation_digest(fn):
    import hashlib
    gen = random.Random(5)
    def word(lo=1, hi=9): return ''.join(gen.choice(letters) for _ in range(gen.randint(lo, hi)))
    h = hashlib.md5()
    for _ in range(15000):
        a, b = word(), word(); h.update(b'1' if fn(a, b) else b'0')
        base = word(2, 8); x, y = base + word(0, 4), base + word(0, 4); h.update(b'1' if fn(x, y) else b'0')
    return h.hexdigest()
# «Золотое» значение посчитано по ПРЕЖНЕЙ реализации (_words_are_variations в vector_model_manager.py до
# выноса в utils/key_concepts.py) на тех же 30 000 парах: определение «вариации» не должно меняться молча —
# от него зависят и «−В/+В», и фильтр ключевых понятий.
check('определение вариации не изменилось (30 000 пар, в том числе с общим началом) — золотой хеш прежней реализации',
      variation_digest(KC.words_are_variations) == '7407ea581d9a1605c501457d98ae1a66')
import services.vector_model_manager as vmm
check('у «−В/+В» и фильтра ОДНО определение (импорт, а не копия)', vmm._words_are_variations is KC.words_are_variations)
kept, removed = vmm.dedupe_word_variations([('равновесие', .9), ('равновесия', .8), ('покой', .7)])
check('«−В/+В» работает как раньше (dedupe_word_variations)', [w for w, _ in kept] == ['равновесие', 'покой'] and removed == 1)

# ===== B. выделенное слово =====
check('слово со знаками препинания и регистром', KC.extract_words('«Бог,»') == ['бог'])
check('слово с дефисом — два слова (как у облака и TextRank)', KC.extract_words('кто-то') == ['кто', 'то'])
check('цифры и пустота — не слова', KC.extract_words('123 ... ') == [] and KC.extract_words(None) == [])
check('латиница тоже слово', KC.extract_words('God') == ['god'])

# ===== C. раскрытие словаря =====
vocab = ['бог', 'бога', 'богом', 'богов', 'Бога', 'равновесие', 'равновесия', 'равновесием', 'равновесиями', 'покой', 'гармония', 'ум', 'умный', 'богатый']
exp = KC.expand_dictionary(['бог', 'Равновесие', 'ум'], vocab)
check('слова и их вариации включены, регистр слова словаря не важен', {'бог', 'бога', 'богом', 'богов', 'равновесие', 'равновесия', 'равновесием', 'равновесиями'} <= exp)
check('слова в написании из vocabulary сохраняются («Бога»)', 'Бога' in exp)
check('чужие слова не попали', not ({'покой', 'гармония'} & exp))
check('слово короче трёх букв совпадает только с собой («ум» — но не «умный»)', 'ум' in exp and 'умный' not in exp)
check('известное ограничение грубой проверки: у «бог» попадает и «богатый» (так же, как у «−В»)', 'богатый' in exp)
check('пустой словарь -> пусто', KC.expand_dictionary([], vocab) == set())
big = [rw(4, 10) for _ in range(60000)]; keys = [rw(4, 8) for _ in range(300)]
t0 = time.time(); KC.expand_dictionary(keys, big); took = time.time() - t0
print(f"     скорость: 300 ключевых слов × 60 000 слов словаря — {took*1000:.0f} мс")
check('на больших словарях быстро (< 2 с)', took < 2.0, f"{took:.2f}")

# ===== D. файл словаря =====
d = tempfile.mkdtemp(); path = os.path.join(d, 'key_concepts.txt')
check('словаря нет — пустой список', KC.load_key_concepts(path) == [])
check('добавление создаёт файл, слово строчными', KC.add_key_concept(path, 'Бог') is True and open(path, encoding='utf-8').read() == 'бог\n')
check('повтор (другой регистр) не дописывается', KC.add_key_concept(path, 'БОГ') is False and KC.load_key_concepts(path) == ['бог'])
KC.add_key_concept(path, 'равновесие'); check('порядок добавления сохраняется', KC.load_key_concepts(path) == ['бог', 'равновесие'])
open(path, 'w', encoding='utf-8').write('# мои ключевые слова\n\nбог\n  Равновесие  \nбог\nпокой')   # руками: комментарий, пустая, повтор, без \n в конце
check('ручные правки: комментарии, пустые строки, повторы, пробелы', KC.load_key_concepts(path) == ['бог', 'равновесие', 'покой'])
KC.add_key_concept(path, 'гармония')
raw = open(path, encoding='utf-8').read()
check('файл без перевода строки в конце: слово дописано с новой строки, а не склеено', raw.endswith('покой\nгармония\n') and raw.startswith('# мои ключевые слова\n\nбог'), repr(raw))
open(path, 'wb').write(b'\xef\xbb\xbf' + 'бог\nпокой\n'.encode('utf-8'))
check('файл с BOM (Блокнот) читается', KC.load_key_concepts(path) == ['бог', 'покой'])
open(path, 'wb').write('бог\nпокой\n'.encode('cp1251'))
check('файл в cp1251 читается', KC.load_key_concepts(path) == ['бог', 'покой'])
KC.add_key_concept(path, 'любовь'); data = open(path, 'rb').read()
check('дописывание в cp1251-файл не портит его: файл переведён в UTF-8 целиком', data.decode('utf-8') == 'бог\nпокой\nлюбовь\n' and KC.load_key_concepts(path) == ['бог', 'покой', 'любовь'])
try: KC.add_key_concept(path, '   '); ok = False
except ValueError: ok = True
check('пустое слово отвергается', ok)
try: KC.add_key_concept('/nonexistent_dir_xyz/k.txt', 'слово'); ok = False
except OSError: ok = True
check('недоступная папка — OSError (окно покажет понятную ошибку)', ok)

# ===== E. облако: только словарь и его вариации =====
from ui import vector_visualization as VV
TEXTS = ["И сказал Бог: да будет свет. Бога слышали все. Богу молились и тогда, и теперь.",
         "Быть или не быть, вот в чём вопрос. Ум человека ищет равновесие; равновесия нет, равновесием дорожат.",
         "Покой и гармония. Богатый человек пришёл. Ум и ум."]
kw = ['бог', 'быть', 'ум', 'равновесие']
pairs = VV.compute_key_word_frequencies(TEXTS, kw)
words_in = [w for w, _ in pairs]; counts = dict(pairs)
check('только слова словаря и их вариации', set(words_in) <= {'бог', 'бога', 'богу', 'быть', 'ум', 'равновесие', 'равновесия', 'равновесием', 'богатый'} and 'покой' not in words_in and 'гармония' not in words_in and 'человек' not in words_in, str(words_in))
check('каждая форма считается отдельно (бог/бога/богу)', counts.get('бог') == 1 and counts.get('бога') == 1 and counts.get('богу') == 1)
check('стоп-слово «быть» и короткое «ум» НЕ отсеиваются — слово выбрал пользователь', counts.get('быть') == 2 and counts.get('ум') == 3, str(counts))
normal = dict(VV.compute_word_frequencies(TEXTS, top_n=500))
check('в обычном облаке «быть» и «ум» отсеиваются (контраст: режим словаря их возвращает)', 'быть' not in normal and 'ум' not in normal)
check('порядок: по убыванию частоты, при равенстве по алфавиту', pairs == sorted(pairs, key=lambda x: (-x[1], x[0])))
check('top_n ограничивает', len(VV.compute_key_word_frequencies(TEXTS, kw, top_n=3)) == 3)
check('нет совпадений — пусто', VV.compute_key_word_frequencies(TEXTS, ['слон']) == [])

# ===== F. граф TextRank =====
long_text = ' '.join(TEXTS * 6)
# Точный состав узлов зависит от окружения (установлен ли nltk — от него зависит объединение словоформ),
# поэтому проверяются свойства, а не конкретные числа.
w_plain, e_plain = VV.build_cooccurrence_graph([long_text])
check('без словаря: служебных слов в графе нет, рёбра идут между узлами графа, направленные, с положительным весом',
      w_plain and not (set(w_plain) & VV.RUSSIAN_STOPWORDS) and all(a in w_plain and b in w_plain and a != b and n > 0 for (a, b), n in e_plain.items()))
w_none, e_none = VV.build_cooccurrence_graph([long_text], key_words=None)
check('key_words=None — то же самое, что без параметра', set(w_none) == set(w_plain) and e_none == e_plain)
text2 = "алфавит " * 5 + "бета гамма дельта эпсилон " * 4 + "ковчег завета ковчег"
w0, _ = VV.build_cooccurrence_graph([text2], top_n_words=3)
wk, ek = VV.build_cooccurrence_graph([text2], top_n_words=3, key_words=['ковчег'])
check('редкое ключевое слово вне top-N в обычном графе отсутствует, а при словаре — входит', 'ковчег' not in w0 and 'ковчег' in wk)
ranked = VV.compute_textrank(wk, ek)
check('и получает оценку TextRank', any(w == 'ковчег' for w, _ in ranked))
w_s, _ = VV.build_cooccurrence_graph(["быть быть быть ум ум ум слово слово слово"], key_words=['быть', 'ум'])
check('служебное/короткое слово из словаря входит в граф (в обычном — нет)', 'быть' in w_s and 'ум' in w_s and 'быть' not in VV.build_cooccurrence_graph(["быть быть быть слово слово слово"])[0])

# ===== G. выборка словаря модели =====
class FakeModel:
    def __init__(self): self.freq = {'бог': 50, 'бога': 20, 'ум': 1, 'умный': 9, 'покой': 7, 'гармония': 5, 'и': 900, 'равновесие': 3, 'равновесия': 1}
    def get_vocabulary_words(self): return list(self.freq)
    def get_word_frequency(self, w): return self.freq[w]
    def get_vector(self, w): return np.ones(4)
mgr = vmm.VectorModelManager.__new__(vmm.VectorModelManager); mgr._get_model = lambda key: FakeModel()
plain = mgr.get_vocabulary_vectors('k')
check('без словаря выборка как раньше: короткие («и», «ум») и редкие (частота < 2) отсеяны', set(plain) == {'бог', 'бога', 'умный', 'покой', 'гармония', 'равновесие'}, str(sorted(plain)))
keyed = mgr.get_vocabulary_vectors('k', key_words=['ум', 'равновесие', 'бог'])
check('со словарём — только слова словаря и вариации, БЕЗ отсева по длине и редкости («ум», частота 1)', set(keyed) == {'ум', 'бог', 'бога', 'равновесие', 'равновесия'}, str(sorted(keyed)))
check('в выборку со словарём не попали посторонние', not ({'покой', 'гармония', 'и', 'умный'} & set(keyed)))
cap = mgr.get_vocabulary_vectors('k', max_words=2, key_words=['бог', 'ум', 'равновесие'])
check('предел max_words берёт самые частые слова словаря', set(cap) == {'бог', 'бога'}, str(sorted(cap)))
check('пустой словарь (не None) -> пустая выборка', mgr.get_vocabulary_vectors('k', key_words=[]) == {})

# ===== H. конфигурация =====
import config
config.CONFIG_FILE = tempfile.mktemp(suffix='.ini')
c = config.load_config(); check('по умолчанию фильтр выключен', c['key_concepts_only'] is False)
c['key_concepts_only'] = True; config.save_config(c); check('включённый параметр сохраняется и читается', config.load_config()['key_concepts_only'] is True)
config.save_config({**config.load_config(), 'engine_type': 'manticore'}); check('другое сохранение конфигурации параметр не стирает', config.load_config()['key_concepts_only'] is True)
raw = open(config.CONFIG_FILE, encoding='utf-8').read()
for val, exp_ in [('1', True), ('true', True), ('Yes', True), ('on', True), ('0', False), ('нет', False), ('', False)]:
    open(config.CONFIG_FILE, 'w', encoding='utf-8').write(raw.replace('key_concepts_only = 1', f'key_concepts_only = {val}'))
    check(f'значение {val!r} читается без падения -> {exp_}', config.load_config()['key_concepts_only'] is exp_)
open(config.CONFIG_FILE, 'w', encoding='utf-8').write('\n'.join(l for l in raw.splitlines() if 'key_concepts' not in l))
check('старый mconfig.ini без параметра читается (фильтр выключен)', config.load_config()['key_concepts_only'] is False)
import importlib; importlib.reload(config)
check('словарь лежит рядом с mconfig.ini', os.path.dirname(config.KEY_CONCEPTS_FILE) == os.path.dirname(config.CONFIG_FILE) and config.KEY_CONCEPTS_FILE.endswith('key_concepts.txt'))

# ===== I. главное окно =====
import ui.app_window as aw
from ui.visualization_controller import VisualizationController
class FakeSel:
    def __init__(self, content=None, mapped=True): self.content = content; self.mapped = mapped
    def tag_ranges(self, tag): return ('1.0', '1.5') if self.content is not None else ()
    def get(self, a, b): return self.content
    def winfo_ismapped(self): return self.mapped
KFILE = os.path.join(tempfile.mkdtemp(), 'key_concepts.txt'); aw.KEY_CONCEPTS_FILE = KFILE
shown = []
aw.messagebox = types.SimpleNamespace(showinfo=lambda t, m, **k: shown.append(('info', t, m)), showerror=lambda t, m, **k: shown.append(('err', t, m)))
import ui.visualization_controller as vc; vc.messagebox = aw.messagebox   # окна «ничего не найдено» для Т/Ц показывает контроллер визуализаций
def make_win(only=True):
    w = aw.AppWindow.__new__(aw.AppWindow); w.config = {'key_concepts_only': only}
    w.viz = VisualizationController(w)   # визуализации — отдельный объект, окно — владелец виджетов
    w.toasts = []; w.logs = []; shown.clear()
    w._show_temporary_notification = lambda m, duration_ms=700: w.toasts.append(m); w._update_log_field = w.logs.append
    w.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: False)
    w.result_text = FakeSel(); w.result_text_2 = FakeSel(mapped=False)
    return w
if os.path.exists(KFILE): os.remove(KFILE)
w = make_win(); w.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: True); w._add_key_concept()
check('КП при показанной визуализации: «Откройте окно результатов»', w.toasts == ['Откройте окно результатов'] and not os.path.exists(KFILE))
w = make_win(); w._add_key_concept(); check('КП без выделения: «Выделите слово»', w.toasts == ['Выделите слово'])
w.result_text.content = '123 …'; w._add_key_concept(); check('выделено не слово', w.toasts[-1] == 'Выделено не слово' and not os.path.exists(KFILE))
w.result_text.content = 'два слова'; w._add_key_concept(); check('выделено несколько слов: отказ, словарь не засоряется', w.toasts[-1] == 'Выделите одно слово' and not os.path.exists(KFILE))
w.result_text.content = 'Бог,'; w._add_key_concept()
check('слово добавлено в файл строчными, показана подсказка и запись в строке состояния', KC.load_key_concepts(KFILE) == ['бог'] and w.toasts[-1] == 'Добавлено: бог' and 'бог' in w.logs[-1])
w.result_text.content = 'БОГ'; w._add_key_concept(); check('повтор: «Уже в словаре», дубликата нет', w.toasts[-1] == 'Уже в словаре: бог' and KC.load_key_concepts(KFILE) == ['бог'])
long_word = 'абвгдежзиклмнопрстуфхцчшщ'; w.result_text.content = long_word; w._add_key_concept()
check('длинное слово: в подсказке сокращено «…», в словаре целиком', w.toasts[-1].endswith('…') and long_word in KC.load_key_concepts(KFILE))
w2 = make_win(); w2.result_text = FakeSel(); w2.result_text_2 = FakeSel('покой', mapped=True); w2._add_key_concept()
check('режим разделения: слово берётся и из второй панели', 'покой' in KC.load_key_concepts(KFILE))
w3 = make_win(); w3.result_text = FakeSel(); w3.result_text_2 = FakeSel('скрытое', mapped=False); w3._add_key_concept()
check('скрытая вторая панель со старым выделением игнорируется', w3.toasts == ['Выделите слово'] and 'скрытое' not in KC.load_key_concepts(KFILE))
aw.KEY_CONCEPTS_FILE = '/nonexistent_dir_xyz/key_concepts.txt'; w4 = make_win(); w4.result_text = FakeSel('слово'); w4._add_key_concept()
check('нельзя записать словарь: окно с путём и причиной, подсказки «Добавлено» нет', shown and shown[0][0] == 'err' and 'nonexistent_dir_xyz' in shown[0][2] and not w4.toasts)
aw.KEY_CONCEPTS_FILE = KFILE

# _key_concept_words
w = make_win(False); check('параметр выключен -> None (фильтра нет)', w._key_concept_words() is None)
w = make_win(True); check('параметр включён -> слова словаря', set(w._key_concept_words()) >= {'бог', 'покой'})
aw.KEY_CONCEPTS_FILE = os.path.join(tempfile.mkdtemp(), 'нет.txt'); check('включён, словаря нет -> пустой список', make_win(True)._key_concept_words() == [])
aw.KEY_CONCEPTS_FILE = KFILE
orig = KC.load_key_concepts; KC.load_key_concepts = lambda p: (_ for _ in ()).throw(PermissionError("нет доступа")); check('словарь не читается -> пустой список, не падение', make_win(True)._key_concept_words() == []); KC.load_key_concepts = orig

# Т
def setup_tc(win, texts):
    win.index_manager = types.SimpleNamespace(get_selected_indices_ordered=lambda: ['bibl'])
    win.search_controller = types.SimpleNamespace(gather_text_for_indices=lambda sel: texts)
    win.cloud_calls = []; win.viz.show_word_cloud = lambda pairs, title="Облако тегов": win.cloud_calls.append((pairs, title))
    win.bar_calls = []; win.viz.hide_vector_visualization = lambda: None
    win.viz.show_bar_chart = lambda ranked, central, title=None: win.bar_calls.append((ranked, central, title))
open(KFILE, 'w', encoding='utf-8').write('бог\nбыть\nум\nравновесие\n')
w = make_win(False); setup_tc(w, TEXTS); w.viz.show_word_cloud_for_selected()
check('Т, параметр выключен: обычное облако, заголовок прежний', w.cloud_calls and w.cloud_calls[0][1] == 'Облако тегов' and 'покой' in dict(w.cloud_calls[0][0]))
w = make_win(True); setup_tc(w, TEXTS); w.viz.show_word_cloud_for_selected()
pairs, ttl = w.cloud_calls[0]
check('Т, параметр включён: только слова словаря и вариации, заголовок «Облако ключевых понятий»', ttl == 'Облако ключевых понятий' and set(dict(pairs)) <= {'бог', 'бога', 'богу', 'быть', 'ум', 'равновесие', 'равновесия', 'равновесием', 'богатый'} and 'покой' not in dict(pairs), str(pairs))
open(KFILE, 'w', encoding='utf-8').write('')
w = make_win(True); setup_tc(w, TEXTS); w.viz.show_word_cloud_for_selected()
check('Т, словарь пуст: объяснение с именем параметра и путём к файлу, облако не строится', not w.cloud_calls and shown and 'key_concepts_only' in shown[0][2] and KFILE in shown[0][2])
open(KFILE, 'w', encoding='utf-8').write('слон\n')
w = make_win(True); setup_tc(w, TEXTS); w.viz.show_word_cloud_for_selected()
check('Т, слов словаря нет в книгах: сообщение, облако не строится', not w.cloud_calls and shown and 'нет в отмеченных книгах' in shown[0][2])

# Ц
open(KFILE, 'w', encoding='utf-8').write('бог\nравновесие\nковчег\n')
LONG = ' '.join(TEXTS * 8) + ' ковчег завета'
w = make_win(False); setup_tc(w, [LONG]); w.viz.show_textrank_for_selected()
ranked, central, ttl = w.bar_calls[0]
check('Ц, параметр выключен: как раньше — заголовок прежний, в рейтинге ВСЕ слова текста (не только словарные)',
      ttl.startswith('Центральные понятия текста (TextRank)') and any(not w.startswith(('бог', 'равновес', 'ковчег')) for w, _ in ranked), str([w for w, _ in ranked][:8]))
w = make_win(True); setup_tc(w, [LONG]); w.viz.show_textrank_for_selected()
ranked, central, ttl = w.bar_calls[0]
allowed = KC.expand_dictionary(['бог', 'равновесие', 'ковчег'], {x for x, _ in ranked})
check('Ц, параметр включён: показаны только слова словаря и вариации', ranked and all(x in allowed for x, _ in ranked), str([x for x, _ in ranked]))
check('Ц: заголовок «Центральные ключевые понятия», главное слово — из словаря', ttl.startswith('Центральные ключевые понятия (TextRank)') and central in allowed and central == ranked[0][0])
check('Ц: оценки по убыванию', [s for _, s in ranked] == sorted([s for _, s in ranked], reverse=True))
w = make_win(True); setup_tc(w, ["слово " * 30 + "другое " * 30]); w.viz.show_textrank_for_selected()
check('Ц: слов словаря нет в книгах — сообщение, диаграммы нет', not w.bar_calls and shown and 'нет в отмеченных книгах' in shown[0][2])
open(KFILE, 'w', encoding='utf-8').write('')
w = make_win(True); setup_tc(w, [LONG]); w.viz.show_textrank_for_selected()
check('Ц: словарь пуст — объяснение', not w.bar_calls and shown and 'key_concepts_only' in shown[0][2])

# Сгущение понятий
class FakeVMM:
    def __init__(self, n): self.n = n; self.kwargs = []
    def get_vocabulary_vectors(self, key, **kw):
        self.kwargs.append(kw); rs = np.random.RandomState(1)
        base = rs.randn(20); return {f'w{i}': base + rs.randn(20) * 0.1 for i in range(self.n)}
def dens_win(only, n):
    w = make_win(only); w.vector_model_manager = FakeVMM(n); return w
open(KFILE, 'w', encoding='utf-8').write('w1\nw2\nw3\n')
w = dens_win(False, 40); res = w.viz._get_density_cluster_data('ft')
check('Сгущение, параметр выключен: выборка запрашивается как раньше (key_words=None), результат есть', w.vector_model_manager.kwargs == [{}] or w.vector_model_manager.kwargs == [{'key_words': None}], str(w.vector_model_manager.kwargs))
check('Сгущение, выключен: 15 соседей, как раньше', res and len(res[1]) == 15)
w = dens_win(True, 8); res = w.viz._get_density_cluster_data('ft')
check('Сгущение, включён: в выборку передан словарь', w.vector_model_manager.kwargs[0]['key_words'] == ['w1', 'w2', 'w3'])
check('Сгущение, включён и слов мало (8): работает, число соседей подстроено (7)', res is not None and len(res[1]) == 7 and res[0] in res[2], str(res and len(res[1])))
w = dens_win(True, 5); res = w.viz._get_density_cluster_data('ft')
check('Сгущение: ровно 5 слов — минимум — работает', res is not None and len(res[1]) == 4)
w = dens_win(True, 4); res = w.viz._get_density_cluster_data('ft')
check('Сгущение: 4 слова — отказ с числом найденных и подсказкой про «КП»', res is None and shown and 'найдено слов: 4' in shown[0][2] and 'КП' in shown[0][2])
open(KFILE, 'w', encoding='utf-8').write('')
w = dens_win(True, 40); res = w.viz._get_density_cluster_data('ft')
check('Сгущение: словарь пуст — объяснение, выборка не запрашивается', res is None and w.vector_model_manager.kwargs == [] and shown and 'key_concepts_only' in shown[0][2])

# Всё пространство — через настоящее меню
class RecMenu:
    def __init__(self, master=None, **kw): self.items = []; self.master = master
    def add_command(self, **kw): self.items.append(kw)
    def add_cascade(self, **kw): self.items.append(kw)
    def add_separator(self): pass
    def tk_popup(self, *a): pass
    def grab_release(self): pass
tk.Menu = RecMenu
class FullVMM:
    def __init__(self): self.calls = []
    def get_word_vectors(self, key, words): return {w: np.ones(5) * i for i, w in enumerate(words)}
    def get_model_type(self, key): return 'fasttext'
    def get_vocabulary_vectors(self, key, **kw): self.calls.append(kw); return {f'w{i}': np.ones(5) * i for i in range(6)}
def full_space(only, dictionary):
    open(KFILE, 'w', encoding='utf-8').write(dictionary)
    w = make_win(only); w.root = MagicMock(); w.word_panel = MagicMock(); w.vector_model_manager = FullVMM()
    w.cloud_calls = []; w.viz.show_full_space_cloud = lambda vecs, key, **kw: w.cloud_calls.append((vecs, key, kw))
    captured = []
    orig_menu = tk.Menu
    class Capture(RecMenu):
        def add_command(self, **kw): super().add_command(**kw); captured.append(kw)
    tk.Menu = Capture
    try: w.viz.show_vector_viz_menu('слово', [('сосед', .9)], 'ft')
    finally: tk.Menu = orig_menu
    cmd = [c for c in captured if c.get('label', '').startswith('Всё пространство')][0]['command']
    cmd(); return w
w = full_space(False, 'w1\n')
check('Всё пространство, параметр выключен: как раньше (max_words=5000, без словаря), заголовок обычный',
      w.vector_model_manager.calls[0].get('key_words') is None and w.vector_model_manager.calls[0]['max_words'] == 5000 and w.cloud_calls[0][2].get('title') is None)
w = full_space(True, 'w1\nw2\n')
check('Всё пространство, включён: словарь передан в выборку, заголовок «Ключевые понятия — …»', w.vector_model_manager.calls[0]['key_words'] == ['w1', 'w2'] and w.cloud_calls[0][2]['title'].startswith('Ключевые понятия'))
w = full_space(True, '')
check('Всё пространство, словарь пуст: объяснение, облако не строится', not w.cloud_calls and shown and 'key_concepts_only' in shown[0][2] and w.vector_model_manager.calls == [])

# заголовок облака слов в самой отрисовке и «Назад»
src_app = open(f'{ROOT}/ui/app_window.py', encoding='utf-8').read()
src_viz = open(f'{ROOT}/ui/visualization_controller.py', encoding='utf-8').read()   # код визуализаций живёт в контроллере
check('заголовок облака тегов и «Всё пространство» берётся из параметра title (и сохраняется при «Назад»)',
      "text=f\"{title} — {len(placed)} слов — \"" in src_viz and "title=title)" in src_viz and "'Всё пространство модели'" in src_viz)

# ===== J. раскладка и кнопка =====
lay = aw.nav_toggle_layout(9, 41)
check('9 px, КП 41 px: отступы 30 | КП | 30, просвет 4', lay['underline_padx'] == (30, 0) and lay['kp_padx'] == (4, 0) and lay['brief_padx'] == (30, 3), str(lay))
prop = True
for cw in range(7, 15):
    for kp in range(30, 61):
        if 150 - 5 * cw - kp - 4 >= 0:
            L = aw.nav_toggle_layout(cw, kp)
            prop &= (L['underline_padx'][0] + L['kp_padx'][0] + kp + L['brief_padx'][0]) == 150 - 5 * cw
check('«Кратко/Всё» остаётся на месте: отступы + КП = прежний отступ (150 − 5 позиций) при любых размерах', prop)
check('«Ч» с «КП» посередине (отступы слева и справа различаются не больше чем на 1)', all(abs(aw.nav_toggle_layout(cw, 41)['underline_padx'][0] - aw.nav_toggle_layout(cw, 41)['brief_padx'][0]) <= 1 for cw in range(7, 12)))
check('без КП (kp_w=0) раскладка прежняя: 53 | 52', aw.nav_toggle_layout(9)['underline_padx'] == (53, 0) and aw.nav_toggle_layout(9)['brief_padx'] == (52, 3) and aw.nav_toggle_layout(9)['kp_padx'] == (0, 0))
big_l = aw.nav_toggle_layout(20, 90); check('при очень крупном шрифте отступы не уходят в минус', min(big_l['underline_padx'][0], big_l['brief_padx'][0]) >= 0)
section = src_app[src_app.index('nav_frame = tk.Frame(center_frame'):src_app.index('# Верхнее и нижнее окно результатов')]
check('порядок слева направо: … «В конец», «Ч», «КП», «Кратко/Всё»', re.findall(r'self\.(btn_\w+)\.pack\(', section) == ['btn_first', 'btn_back', 'btn_forward', 'btn_last', 'btn_underline', 'btn_key_concepts', 'btn_brief_toggle'])
check('КП синяя, с подсказкой «Ключевые понятия»', 'text="КП"' in section and "bg='#2a6fbf'" in section and 'ToolTip(self.btn_key_concepts, "Ключевые понятия")' in section)
check('ширина КП берётся реальная, с запасной прикидкой', 'self.btn_key_concepts.winfo_reqwidth()' in section and 'round(4.5 * char_w)' in section)

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
