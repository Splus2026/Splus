import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import random, re

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from utils import highlighting as hl

# ===================== A. get_intervals =====================
gi = hl.get_intervals
check('нет слов и фрагментов или нет совпадений — пустой список', gi('текст', [], []) == [] and gi('', ['бог'], ['бо']) == [] and gi('текст', ['бог'], ['ябл']) == [])
check('точное слово: без учёта регистра, возвращает [начало, конец, 2]', gi('Бог создал БОГ', ['бог'], []) == [[0, 3, 2], [11, 14, 2]])
check('точное слово — по границам слова: «бог» не подсвечивается внутри «богатый»', gi('бог богатый Бог', ['бог'], []) == [[0, 3, 2], [12, 15, 2]])
check('точное слово с буквой «ё» подсвечивается (границы слова — Юникод)', gi('Это всё и ещё', ['всё', 'ещё'], []) == [[4, 7, 2], [10, 13, 2]])
check('частичный фрагмент — по подстроке (и внутри слова), без учёта регистра, уровень 1', gi('Богатый БОГ', [], ['бог']) == [[0, 3, 1], [8, 11, 1]])
check('спецсимволы регулярных выражений экранируются: «a.b» не находит «axb»', gi('a.b axb a+b', ['a.b', 'a+b'], []) == [[0, 3, 2], [8, 11, 2]])
check('перекрывающиеся интервалы сливаются в один', gi('слово', ['слово'], ['лов']) == [[0, 5, 2]] and gi('абвгд', [], ['абв', 'вгд']) == [[0, 5, 1]])
check('соприкасающиеся интервалы (конец одного = начало другого) тоже сливаются', gi('абвг', [], ['аб', 'вг']) == [[0, 4, 1]])
check('непересекающиеся остаются раздельными, результат отсортирован по позиции', gi('вг аб', [], ['аб', 'вг']) == [[0, 2, 1], [3, 5, 1]])
check('при слиянии побеждает точное совпадение (приоритет 2)', gi('слово', ['слово'], ['сл']) == [[0, 5, 2]] and gi('словом', ['слово'], ['сло']) == [[0, 3, 1]])
rnd = random.Random(41); ok_sorted = ok_cover = ok_prio = ok_bounds = True
for _ in range(300):
    text = ' '.join(''.join(rnd.choice('абв') for _ in range(rnd.randint(1, 5))) for _ in range(rnd.randint(1, 12)))
    exact = [''.join(rnd.choice('абв') for _ in range(rnd.randint(2, 4))) for _ in range(rnd.randint(0, 2))]
    partial = [''.join(rnd.choice('абв') for _ in range(rnd.randint(2, 3))) for _ in range(rnd.randint(0, 2))]
    merged = gi(text, exact, partial)
    raw = [(m.start(), m.end(), 2) for w in exact for m in re.finditer(r'\b' + re.escape(w) + r'\b', text, re.I)] + \
          [(m.start(), m.end(), 1) for f in partial for m in re.finditer(re.escape(f), text, re.I)]
    ok_sorted &= all(merged[i][0] > merged[i - 1][1] for i in range(1, len(merged)))
    ok_bounds &= all(0 <= s < e <= len(text) for s, e, _p in merged)
    ok_cover &= all(sum(1 for s, e, _p in merged if s <= a and b <= e) == 1 for a, b, _pr in raw) and bool(merged) == bool(raw)
    ok_prio &= all((p == 2) == any(pr == 2 and s <= a and b <= e for a, b, pr in raw) for s, e, p in merged)
check('свойство (300 случайных): интервалы упорядочены и не пересекаются, внутри текста', ok_sorted and ok_bounds)
check('свойство: каждое найденное вхождение лежит ровно в одном итоговом интервале, лишних интервалов нет', ok_cover)
check('свойство: приоритет интервала = 2 тогда и только тогда, когда в нём есть точное вхождение', ok_prio)

# ===================== B. краткий вид =====================
bvm, bv = hl.build_brief_view_mapped, hl.build_brief_view
C = "Первое слово тут. Второе предложение ни о чём. Третье слово снова. Четвёртое пустое. Пятое слово конец."
check('нет подсветки — текст целиком, без интервалов, карта из одного куска', bvm(C, ['нетут'], []) == (C, [], [(0, 0, len(C))]))
text, intervals, segs = bvm(C, ['слово'], [])
check('краткий вид оставляет только предложения с подсветкой (1-е, 3-е, 5-е), пропущенное заменено « … »',
      text.count(' … ') == 2 and 'Второе' not in text and 'Четвёртое' not in text and all(w in text for w in ('Первое', 'Третье', 'Пятое')), repr(text))
check('карта кусков: куски исходного текста, склеенные « … », дают показанный текст', ' … '.join(C[c0:c0 + n] for _d, c0, n in segs) == text and len(segs) == 3)
check('интервалы пересчитаны под короткий текст: на указанных местах стоят подсвеченные слова', [text[s:e] for s, e, _p in intervals] == ['слово'] * 3, str(intervals))
text, intervals, segs = bvm(C, ['предложение', 'снова'], [])
check('подсвеченные предложения подряд (2-е и 3-е) образуют один непрерывный кусок без « … »; текст до и после не показывается',
      ' … ' not in text and len(segs) == 1 and 'Первое' not in text and 'Четвёртое' not in text and 'Второе' in text and 'Третье' in text, repr(text))
text, _i, segs = bvm(C, ['конец'], [])
check('подсветка только в последнем предложении: начало текста не показывается', text.strip().startswith('Пятое') and 'Первое' not in text and len(segs) == 1)
check('текст без знаков конца предложения — одно предложение, показывается целиком', bvm('слово без точки', ['слово'], [])[0] == 'слово без точки')
text, intervals, _s = bvm('Вопрос слово? Другое! Третье слово.', ['слово'], [])
check('концы предложений: ? ! . — все считаются', text.count(' … ') == 1 and 'Другое' not in text, repr(text))
text, intervals, _s = bvm(C, [], ['слов'])
check('только частичные совпадения тоже определяют предложения (уровень 1)', len(intervals) == 3 and all(p == 1 for _s_, _e, p in intervals))
check('build_brief_view = первые два элемента build_brief_view_mapped', bv(C, ['слово'], []) == bvm(C, ['слово'], [])[:2])

# ===================== C. _find_topic_text =====================
ft = hl._find_topic_text; dp0 = hl.determine_position
check('точное вхождение: (позиция, длина)', ft('аа бб вв', 'бб') == (3, 2))
check('при повторах берётся ПЕРВОЕ вхождение', ft('аминь. аминь.', 'аминь.') == (0, 6))
check('различия в пробелах и переводах строк допускаются (так расходятся индексация и просмотр .docx): найдено начало и вся область',
      ft('абзац 1\n\n\nабзац 2', 'абзац 1\nабзац 2') == (0, 17) and ft('до\nодин  два\tтри', 'один два три') == (3, 13))
check('не найдено и запрос из одних пробелов — (-1, 0)', ft('abc', 'xyz') == (-1, 0) and ft('abc', '   ') == (-1, 0))
check('пустой текст топика определение позиции вообще не ищет (идёт по запасному варианту)', dp0('abc', '.txt', '', '0') == (1, 0, 0, 0, 3) and dp0('abc', '.txt', '   ', '0') == (1, 0, 0, 0, 3))
check('спецсимволы в словах не ломают поиск (a+b (c) ищется «терпимо»)', ft('x a+b\n\n(c) y', 'a+b (c)') == (2, 8))
long_topic = ' '.join(f'w{i}' for i in range(400)); content = 'х ' + long_topic.replace(' ', '\n', 1)
pos, length = ft(content, long_topic)
check('топик длиннее 300 слов: начало найдено верно, конец приблизительный (начало + длина текста)', pos == 2 and length == len(long_topic), f'{pos}, {length}')

# ===================== D. determine_position =====================
dp = hl.determine_position
T = "строка0\nстрока1\nстрока2\nстрока3"
check('топик найден: (строка с 1, столбец, позиция, начало, конец)', dp(T, '.txt', 'строка2', '0') == (3, 0, 16, 16, 23))
check('топик найден не с начала строки: столбец считается от начала строки', dp('аа\nбб вв гг', '.txt', 'вв', '0') == (2, 3, 6, 6, 8))
check('пробелы по краям текста топика не мешают поиску', dp(T, '.txt', '  строка1\n', '0')[2] == 8)
check('найден в самом начале файла: строка 1, позиция 0', dp(T, '.docx', 'строка0', '0')[:3] == (1, 0, 0))
check('найден «терпимым» поиском (.docx с пустыми абзацами)', dp('а\n\n\nб\nв', '.docx', 'б в', '0')[2:] == (4, 4, 7))
check('топик не найден, .txt, position = номер строки (с 0): строка и позиция берутся из него', dp(T, '.txt', 'нет такого', '2') == (3, 0, 16, 16, 26))
check('position за пределами файла: последняя строка, позиция в конце; без текста топика — окно ±2000 символов', dp(T, '.txt', '', '99') == (4, 0, 31, 0, 31))
big = ('x' * 99 + '\n') * 100
check('окно ±2000 символов вокруг строки (position 50 в файле из 10 000 символов): 3000..7000', dp(big, '.txt', '', '50')[2:] == (5000, 3000, 7000), str(dp(big, '.txt', '', '50')))
check('начало окна не уходит в минус, конец — за конец файла', dp(big, '.txt', '', '1')[3] == 0 and dp(big, '.txt', '', '99')[4] == len(big))
check('.docx, position «0», пустая, «abc», отрицательная, None — запасной вариант (1, 0, 0, 0, min(длина, 2000))',
      all(dp(T, e, '', p) == (1, 0, 0, 0, 31) for e, p in (('.docx', '2'), ('.txt', '0'), ('.txt', ''), ('.txt', 'abc'), ('.txt', '-3'), ('.txt', None))))
check('запасной вариант для большого файла ограничен 2000 символами', dp(big, '.docx', '', '5')[4] == 2000)
rnd = random.Random(51); ok_slice = ok_line = True
for _ in range(200):
    lines_ = [' '.join(''.join(rnd.choice('абвг') for _ in range(rnd.randint(2, 6))) for _ in range(rnd.randint(1, 6))) for _ in range(rnd.randint(2, 12))]
    content = '\n'.join(lines_); words = content.split(); a = rnd.randint(0, len(words) - 1); topic = ' '.join(words[a:a + rnd.randint(1, 4)])
    line_num, char_pos, target, start, end = dp(content, '.txt', topic, '0')
    ok_slice &= content[start:end].split() == topic.split() and target == start
    ok_line &= line_num == content[:target].count('\n') + 1 and content.split('\n')[line_num - 1][char_pos:].startswith(topic.split()[0])
check('свойство (200 случайных текстов): найденный топик = срез файла (с точностью до пробелов/переводов строк между словами), позиция совпадает с началом', ok_slice)
check('свойство: номер строки и столбец указывают на то же место', ok_line)
weird = "a\x0cb\nc\nd"
check('position = номер строки считается по переводам строки \\n (как в окне просмотра), а не по любым разрывам вроде form feed', dp(weird, '.txt', '', '2')[2] == weird.index('d'),
            f"строка «d» (третья по \\n) начинается с символа {weird.index('d')}, а определено {dp(weird, '.txt', '', '2')[2]}")

# ===================== E. compute_file_highlight_intervals =====================
cf = hl.compute_file_highlight_intervals
check('нет слов и фрагментов или пустой текст — ([], 0)', cf('текст', 0, 5, [], []) == ([], 0) and cf('', 0, 0, ['а'], ['а']) == ([], 0))
full = "Бог создал небо. Богатый человек. БОГ един. " * 3
r, total = cf(full, 0, len(full), ['бог'], [], 0)
check('context_size = 0: подсвечивается весь текст, без частичных, все интервалы «highlight»', total == len(r) == 9 and all(t == 'highlight' for _s, _e, t in r) and {full[s:e].lower() for s, e, _t in r} == {'бог'})
check('(особенность) точные слова в просмотре файла ищутся по ПОДСТРОКЕ без учёта границ слова: «бог» подсвечен и внутри «богатый» (в результатах поиска — по границам)',
      cf('богатый', 0, 7, ['бог'], [], 0)[0] == [[0, 3, 'highlight']])
check('слова и фрагменты короче 2 символов игнорируются', cf('а б ав', 0, 6, ['а', ''], ['б'], 10) == ([], 0))
r, total = cf("abc abcd xyz", 0, 12, ['abc'], ['abcd', 'xy'], 100)
check('частичные фрагменты добавляются, перекрытие с точным даёт «highlight»; total — число интервалов ДО слияния', r == [[0, 3, 'highlight'], [4, 8, 'highlight'], [9, 11, 'partial']] and total == 4, f'{r}, {total}')
check('фрагмент целиком внутри точного совпадения не добавляется', cf('abcdef', 0, 6, ['abcdef'], ['abc'], 50) == ([[0, 6, 'highlight']], 1))
text = 'слово ' * 10 + 'ЯЯ ' + 'слово ' * 10
mid = text.index('ЯЯ'); r, _t = cf(text, mid, mid + 2, ['слово'], [], 12)
check('окно context_size вокруг топика (по 12 символов СЛЕВА и СПРАВА): подсвечены ровно совпадения внутри окна, координаты — в тексте файла',
      r == [[48, 53, 'highlight'], [54, 59, 'highlight'], [63, 68, 'highlight'], [69, 74, 'highlight']], str(r))
check('у начала файла окно обрезается слева (0), справа — на context_size: вне окна ничего нет', cf(text, 0, 2, ['слово'], [], 3)[0] == [[0, 5, 'highlight']], str(cf(text, 0, 2, ['слово'], [], 3)[0]))
check('совпадение, начинающееся ДО границы окна, не подсвечивается (context 3 у конца файла: окно «лово », слова целиком в нём нет)',
      cf(text, len(text) - 2, len(text), ['слово'], [], 3)[0] == [], str(cf(text, len(text) - 2, len(text), ['слово'], [], 3)[0]))
many = ' '.join(['ааа'] * 60) + ' бб бб'
check('если точных совпадений уже 50 и больше, частичные фрагменты не ищутся (экономия времени)', cf(many, 0, len(many), ['ааа'], ['бб'], 10 ** 6)[0] and all(t == 'highlight' for _s, _e, t in cf(many, 0, len(many), ['ааа'], ['бб'], 10 ** 6)[0]))
few = ' '.join(['ааа'] * 10) + ' бб бб'
check('при менее чем 50 точных — частичные ищутся', any(t == 'partial' for _s, _e, t in cf(few, 0, len(few), ['ааа'], ['бб'], 10 ** 6)[0]))
big_text = ' '.join(['слово'] * 400)
r0, total0 = cf(big_text, 0, 20, ['слово'], [], 0); r1, total1 = cf(big_text, 0, len(big_text), ['слово'], [], 100)
check('предел числа подсвечиваемых мест: при context 0 — 500, иначе max_tags=200; total_intervals — всё найденное до обрезки', len(r0) == 400 and total0 == 400 and len(r1) == 200 and total1 == 400, f'{len(r0)} {len(r1)} {total1}')
check('обрезка оставляет ПЕРВЫЕ по позиции интервалы', r1 == sorted(r1) and r1[0][0] == 0)
check('max_tags можно задать', len(cf(big_text, 0, len(big_text), ['слово'], [], 100, max_tags=7)[0]) == 7)
rnd = random.Random(61); ok_sorted = ok_tags = ok_total = True
for _ in range(200):
    text = ' '.join(''.join(rnd.choice('абв') for _ in range(rnd.randint(1, 5))) for _ in range(rnd.randint(1, 30)))
    words = [''.join(rnd.choice('абв') for _ in range(rnd.randint(2, 3))) for _ in range(rnd.randint(0, 2))]; frags = [''.join(rnd.choice('абв') for _ in range(rnd.randint(2, 3))) for _ in range(rnd.randint(0, 2))]
    a = rnd.randint(0, len(text)); b = rnd.randint(a, len(text)); r, total = cf(text, a, b, words, frags, rnd.choice([0, 5, 20, 100]))
    ok_sorted &= all(r[i][0] > r[i - 1][1] for i in range(1, len(r))) and all(0 <= s < e <= len(text) for s, e, _t in r)
    ok_tags &= all(t in ('highlight', 'partial') for _s, _e, t in r); ok_total &= total >= len(r)
check('свойство (200 случайных): интервалы упорядочены, не пересекаются и лежат в тексте', ok_sorted)
check('свойство: тэги только «highlight»/«partial»; total_intervals не меньше числа итоговых интервалов', ok_tags and ok_total)
# ===================== F. окно просмотра файла =====================
cdw, loc = hl.compute_display_window, hl.locate_in_text
BIGC = ''.join(chr(0x430 + i % 26) for i in range(100000))
check('файл не больше предела — показывается целиком, границы топика без изменений', cdw('abc', 0, 0, 0, 50000) == ('abc', 0, 0) and cdw(BIGC, 5, 5, 9, len(BIGC)) == (BIGC, 5, 9))
check('предел 0 — «без ограничения»: большой файл целиком', cdw(BIGC, 50000, 50000, 50100, 0) == (BIGC, 50000, 50100))
check('большой файл: окно ровно в предел, центрировано на начале топика, границы топика пересчитаны в координаты окна', cdw(BIGC, 50000, 50000, 50100, 10000) == (BIGC[45000:55000], 5000, 5100))
check('топик у начала файла: окно прижато к началу', cdw(BIGC, 2000, 2000, 2100, 10000) == (BIGC[:10000], 2000, 2100))
check('топик у конца файла: окно прижато к концу (последние 10 000 символов)', cdw(BIGC, 99000, 99000, 99100, 10000) == (BIGC[90000:], 9000, 9100))
check('топик ровно в НАЧАЛЕ файла (позиция 0): показывается начало, а не середина', cdw(BIGC, 0, 0, 100, 10000) == (BIGC[:10000], 0, 100))
check('позиция неизвестна (область первых 2000 символов): показывается начало файла', cdw(BIGC, 0, 0, 2000, 10000) == (BIGC[:10000], 0, 2000))
check('топика нет вовсе (пустая область): берётся середина файла', cdw(BIGC, 0, 0, 0, 10000)[0] == BIGC[45000:55000])
check('топик больше окна: окно начинается у топика, конец топика обрезан краем окна', cdw(BIGC, 10000, 10000, 40000, 10000) == (BIGC[5000:15000], 5000, 10000))
rnd = random.Random(71); ok_len = ok_sub = ok_topic = True
for _ in range(400):
    content = BIGC[:rnd.randint(0, 5000)]; mx = rnd.randint(1, 3000); a = rnd.randint(0, max(0, len(content) - 1)); b = min(len(content), a + rnd.randint(0, 800))
    shown, ds, de = cdw(content, a, a, b, mx)
    ok_len &= len(shown) <= max(mx, len(content)) and (len(content) <= mx or len(shown) == mx)
    ok_sub &= shown in content
    if b > a and len(content) > mx and de - ds == b - a: ok_topic &= shown[ds:de] == content[a:b]
check('свойство (400 случайных): окно — кусок файла не длиннее предела (или файл целиком)', ok_len and ok_sub)
check('свойство: если топик целиком в окне, его граница указывает ровно на него', ok_topic)
check('locate_in_text: (строка с 1, столбец с 0)', loc('ab\ncd\nef', 4) == (2, 1) and loc('ab\ncd\nef', 0) == (1, 0) and loc('ab\ncd\nef', 3) == (2, 0) and loc('ab\ncd\nef', 7) == (3, 1))
check('locate_in_text: на самом переводе строки — конец той же строки; за концом текста — начало (1, 0)', loc('ab\ncd', 2) == (1, 2) and loc('ab\ncd', 5) == (1, 0) and loc('ab\ncd', 99) == (1, 0) and loc('', 0) == (1, 0))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
