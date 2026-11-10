import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import random

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from utils.query_parser import parse_query_words, get_fragments_with_levels, compute_matches, compute_matches_unique

# ===================== A. parse_query_words =====================
check('обычные слова: (слово, None, False)', parse_query_words('слово другое') == [('слово', None, False), ('другое', None, False)])
check('слова короче трёх букв (и одиночные) отбрасываются', parse_query_words('а бв abc 12') == [('abc', None, False)])
check('min_word_length=2 пропускает двухсимвольные (режим двух Excel-файлов: «12» в «Болт М 12»)',
      parse_query_words('а бв abc 12', min_word_length=2) == [('бв', None, False), ('abc', None, False), ('12', None, False)])
check('знаки препинания разделяют слова', [w for w, _m, _s in parse_query_words('кот,пес;слон! (рыба)')] == ['кот', 'пес', 'слон', 'рыба'])
check('регистр запроса сохраняется (сопоставление потом регистронезависимое)', parse_query_words('СЛОВО Слово') == [('СЛОВО', None, False), ('Слово', None, False)])
check('цифры и латиница — тоже слова', [w for w, _m, _s in parse_query_words('ГОСТ 12345 abc')] == ['ГОСТ', '12345', 'abc'])
check('пустой запрос и одни знаки — пустой результат', parse_query_words('') == [] and parse_query_words('!!! ???') == [] and parse_query_words('   ') == [])

# точки — «управление сокращением слова»
check('точка в начале: слово должно НАЧИНАТЬСЯ так (.сло -> must_start)', parse_query_words('.сло') == [('сло', None, True)])
check('одна точка в середине: сокращать слово можно до длины части перед точкой (сло.во -> 3)', parse_query_words('сло.во') == [('слово', 3, False)])
check('точка после первой буквы: сокращать можно до одной буквы', parse_query_words('с.лово') == [('слово', 1, False)])
check('две точки: сокращать до части перед ПОСЛЕДНЕЙ точкой без точек (сл.ов.о -> 4)', parse_query_words('сл.ов.о') == [('слово', 4, False)])
check('.слово. — «без сокращения»: длина = длине слова, слово с начала', parse_query_words('.слово.') == [('слово', 5, True)])
check('точечный фильтр короткого числа: .12. (при min_word_length=2) -> exact', parse_query_words('.12.', min_word_length=2) == [('12', 2, True)])
check('слово из одних точек и слишком короткое с точкой отбрасываются', parse_query_words('... . .а т.е.') == [])
check('точки не попадают в само слово', all('.' not in w for w, _m, _s in parse_query_words('.сло с.лово .сло. а.б.в.г')))

check('буква «ё» входит в слово: «ещё» ищется', parse_query_words('ещё') == [('ещё', None, False)], f"parse_query_words('ещё') -> {parse_query_words('ещё')}")
check('буква «ё» входит в слово: «жёлтый» не обрезается до «лтый»', parse_query_words('жёлтый') == [('жёлтый', None, False)], f"parse_query_words('жёлтый') -> {parse_query_words('жёлтый')}")
check('«всё», «её», «ёж» с буквой «ё» не пропадают из запроса', [w for w, _m, _s in parse_query_words('всё её', min_word_length=2)] == ['всё', 'её'], f"-> {parse_query_words('всё её', min_word_length=2)}")

# ===================== B. get_fragments_with_levels =====================
check('пустое слово — нет фрагментов', get_fragments_with_levels('') == [])
check('слова до 3 букв не дробятся (их единственный фрагмент — уровень 10)', all(get_fragments_with_levels(w) == [(w, 10)] for w in ('а', 'ку', 'кот', '12')))
check('«слово» (5): слово/слов/сло — уровни 10/8/6', get_fragments_with_levels('слово') == [('слово', 10), ('слов', 8), ('сло', 6)])
check('«равновесие» (10): от полной длины до половины — уровни 10,9,8,7,6,5', [lvl for _f, lvl in get_fragments_with_levels('равновесие')] == [10, 9, 8, 7, 6, 5]
      and get_fragments_with_levels('равновесие')[0] == ('равновесие', 10) and get_fragments_with_levels('равновесие')[-1] == ('равно', 5))
word20 = 'а' * 20
expected_levels = {20: 10, 19: 10, 18: 9, 17: 9, 16: 8, 15: 8, 14: 7, 13: 7, 12: 6, 11: 6, 10: 5}
check('границы уровней по доле длины (для слова из 20 букв: ≥95% -> 10, ≥85 -> 9, ≥75 -> 8, ≥65 -> 7, ≥55 -> 6, иначе 5)',
      {len(f): lvl for f, lvl in get_fragments_with_levels(word20)} == expected_levels, str({len(f): lvl for f, lvl in get_fragments_with_levels(word20)}))
check('min_len_override ограничивает сокращение: «равновесие», 4 -> фрагменты до 4 букв, последний уровень 5',
      [len(f) for f, _l in get_fragments_with_levels('равновесие', 4)] == [10, 9, 8, 7, 6, 5, 4] and get_fragments_with_levels('равновесие', 4)[-1][1] == 5)
check('min_len_override больше длины слова — только слово целиком; 0 — до одной буквы',
      get_fragments_with_levels('слово', 99) == [('слово', 10)] and [len(f) for f, _l in get_fragments_with_levels('слово', 0)] == [5, 4, 3, 2, 1])
check('у слов до 3 букв override игнорируется', get_fragments_with_levels('кот', 1) == [('кот', 10)])
rnd = random.Random(7); ok_prefix = ok_mono = True
for _ in range(300):
    w = ''.join(rnd.choice('абвгдежзик') for _ in range(rnd.randint(4, 25))); frags = get_fragments_with_levels(w, rnd.choice([None, 1, 3, 6]))
    ok_prefix &= all(w.startswith(f) for f, _l in frags) and frags[0] == (w, 10)
    ok_mono &= all(frags[i][1] >= frags[i + 1][1] for i in range(len(frags) - 1)) and all(5 <= l <= 10 for _f, l in frags)
check('свойство (300 случайных слов): фрагменты — начала слова, первый — слово целиком, уровни не растут с сокращением и лежат в 5..10', ok_prefix and ok_mono)

# ===================== C. compute_matches =====================
def cm(text, query, **kw): return compute_matches(text, parse_query_words(query, **kw))
check('нет совпадений — None', cm('Бог создал небо', 'машина') is None)
r = cm('Бог создал небо', 'бог')
check('простое совпадение: слово, уровень 10, одно вхождение, в нижнем регистре', r == {'matched_words': ['бог'], 'counts': {5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 1}, 'max_level': 10, 'count_at_max': 1}, str(r))
check('регистр не важен ни в запросе, ни в тексте', cm('БОГ', 'бог') is not None and cm('бог', 'БОГ') is not None and cm('Бог', 'бОг')['matched_words'] == ['бог'])
check('совпадение по подстроке: «лово» находится внутри «слово»', cm('слово', 'лово') is not None)
r = cm('слово слов сло', 'слово')
check('слово запроса ищется и сокращённым: «слово»/«слов»/«сло» — уровни 10/8/6, по одному', (r['counts'][10], r['counts'][8], r['counts'][6]) == (1, 1, 1) and r['max_level'] == 10 and r['count_at_max'] == 1, str(r))
r = cm('словом', 'слово')
check('токен с несколькими подходящими фрагментами считается ОДИН раз — по лучшему уровню', sum(r['counts'].values()) == 1 and r['counts'][10] == 1)
r = cm('слово слово слово', 'слово')
check('повторы в тексте считаются каждый (3 вхождения -> 3)', r['counts'][10] == 3 and r['count_at_max'] == 3)
r = cm('равновесие души и равновесия мира', 'равновесие')
check('словоформы находятся сокращёнными фрагментами: равновесия -> уровень 9', r['counts'][10] == 1 and r['counts'][9] == 1 and set(r['matched_words']) == {'равновесие', 'равновесия'}, str(r))
check('результат всегда содержит все уровни 5..10, max_level — старший непустой, count_at_max согласован',
      all(set(x['counts']) == set(range(5, 11)) and x['counts'][x['max_level']] == x['count_at_max'] > 0 and all(x['counts'][l] == 0 for l in range(x['max_level'] + 1, 11))
          for x in (cm('слово слов сло', 'слово'), cm('равновесия', 'равновесие'), cm('а б слово', 'слово'))))
check('цифры и латиница — полноценные токены', cm('ГОСТ 12345-80 и abc', 'ГОСТ 12345')['matched_words'] and set(cm('ГОСТ 12345-80 и abc', 'ГОСТ 12345')['matched_words']) == {'гост', '12345'})
# «.сло» — только слова, НАЧИНАЮЩИЕСЯ так
r = cm('слово послов сложный', '.сло')
check('.сло: совпадают слова, начинающиеся на «сло» (слово, сложный), но не «послов»', set(r['matched_words']) == {'слово', 'сложный'}, str(r))
# «.12.» — ровно «12»: раньше совпадало и с 120, 12005 (исправлено, см. комментарий в compute_matches)
r = cm('12 120 12005 a12 12', '.12.', min_word_length=2)
check('.12. совпадает ТОЛЬКО с «12» (не с 120, 12005, a12) — два вхождения', set(r['matched_words']) == {'12'} and r['counts'][10] == 2, str(r))
r = cm('12 120 12005 a12', '.12', min_word_length=2)
check('.12 (без закрывающей точки): слова, НАЧИНАЮЩИЕСЯ на 12 — 12, 120, 12005, но не a12', set(r['matched_words']) == {'12', '120', '12005'}, str(r))
r = cm('12 120 12005 a12', '12', min_word_length=2)
check('12 (без точек): по подстроке — находит и a12', set(r['matched_words']) == {'12', '120', '12005', 'a12'}, str(r))
check('пустой список слов запроса — None', compute_matches('любой текст', []) is None and compute_matches('', parse_query_words('слово')) is None)
check('слово с «ё» из текста находится как есть («жёлтый» в «Цветок жёлтый»)', (compute_matches('Цветок жёлтый', [('жёлтый', None, False)]) or {}).get('matched_words') == ['жёлтый'],
            f"compute_matches('Цветок жёлтый', [('жёлтый',…)]) -> {compute_matches('Цветок жёлтый', [('жёлтый', None, False)])}")

# ===================== D. compute_matches_unique =====================
def cu(text, query, **kw): return compute_matches_unique(text, parse_query_words(query, **kw))
check('нет совпадений — None', cu('Бог создал небо', 'машина') is None)
r = cu('слово слово слово', 'слово')
check('главное отличие: три вхождения одного слова запроса дают ОДНО очко (в compute_matches — три)', r['counts'][10] == 1 and r['count_at_max'] == 1, str(r))
r = cu('слово равновесия', 'слово равновесие')
check('каждое слово запроса — одно очко по лучшему уровню: слово -> 10, равновесие -> 9', r['counts'][10] == 1 and r['counts'][9] == 1 and r['max_level'] == 10 and r['count_at_max'] == 1, str(r))
r = cu('слово', 'бог слово')
check('слово запроса, которого в тексте нет, очков не даёт', sum(r['counts'].values()) == 1 and r['counts'][10] == 1)
r = cu('бог', 'бог бог')
check('повтор слова в запросе схлопывается (рейтинг считается по уникальным словам)', sum(r['counts'].values()) == 1)
r = cu('12 120', '.12.', min_word_length=2)
check('быстрый путь для точных слов (.12.): совпадает только «12»', set(r['matched_words']) == {'12'} and r['counts'][10] == 1 and cu('120 12005', '.12.', min_word_length=2) is None, str(r))
check('быстрый путь работает при смеси точных и обычных слов', set(cu('12 120 слово', '.12. слово', min_word_length=2)['matched_words']) == {'12', 'слово'})
check('слово с «ё» из текста находится как есть и в compute_matches_unique', (compute_matches_unique('Цветок жёлтый', [('жёлтый', None, False)]) or {}).get('matched_words') == ['жёлтый'],
            f"-> {compute_matches_unique('Цветок жёлтый', [('жёлтый', None, False)])}")

# ===================== E. согласованность двух функций (свойства на случайных данных) =====================
rnd = random.Random(11); ALPHA = 'абвгде'
def rand_word(lo, hi): return ''.join(rnd.choice(ALPHA) for _ in range(rnd.randint(lo, hi)))
def rand_query():
    parts = []
    for _ in range(rnd.randint(1, 3)):
        w = rand_word(3, 8); r_ = rnd.random()
        if r_ < 0.15: w = '.' + w
        elif r_ < 0.30: w = w + '.'
        elif r_ < 0.40: p = rnd.randint(1, len(w) - 1); w = w[:p] + '.' + w[p:]
        elif r_ < 0.50: w = '.' + w + '.'
        parts.append(w)
    return ' '.join(parts)
none_same = words_same = level_same = structure_ok = unique_bound = True; matched_cases = 0
for _ in range(500):
    info = parse_query_words(rand_query()); pieces = [rand_word(1, 9) for _ in range(rnd.randint(1, 12))]
    for w, _m, _s in info:  # подмешиваем начала слов запроса (с «шумом» по краям), чтобы совпадений было достаточно
        if rnd.random() < 0.6: pieces.append(rnd.choice(['', rand_word(0, 2)]) + w[:rnd.randint(2, len(w))] + rnd.choice(['', rand_word(0, 2)]))
    rnd.shuffle(pieces); text = ' '.join(pieces)
    a, b = compute_matches(text, info), compute_matches_unique(text, info)
    none_same &= (a is None) == (b is None)
    if a is not None and b is not None:
        matched_cases += 1
        words_same &= set(a['matched_words']) == set(b['matched_words'])
        level_same &= a['max_level'] == b['max_level']
        for x in (a, b):
            structure_ok &= set(x['counts']) == set(range(5, 11)) and x['counts'][x['max_level']] == x['count_at_max'] > 0 and len(set(x['matched_words'])) == len(x['matched_words'])
        unique_bound &= sum(b['counts'].values()) <= len({w for w, _m, _s in info})
check(f'свойство ({matched_cases} совпавших из 500 случайных пар): обе функции одновременно находят или не находят совпадение', none_same)
check('свойство: обе функции подсвечивают одни и те же слова (matched_words) — рейтинг unique на подсветку не влияет', words_same)
check('свойство: максимальный уровень у обеих одинаков', level_same)
check('свойство: структура результата верна у обеих (уровни 5..10, count_at_max согласован, слова без повторов)', structure_ok)
check('свойство: очков в compute_matches_unique не больше, чем уникальных слов запроса', unique_bound)
check('случайных проверок со совпадением достаточно (набор не вырожден)', matched_cases >= 200, str(matched_cases))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
