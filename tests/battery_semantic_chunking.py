import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import random, re

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import utils.semantic_chunking as sc

# Нарезка текста на смысловые блоки для MiniLM («окна смысла»). Разбиение на предложения подменено детерминированным (не зависит от nltk).
sc.split_sentences = lambda text: [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

# ===================== абзацы =====================
cp = sc.chunk_by_paragraphs
check('абзацы: делятся по пустой строке, пробелы по краям срезаются', cp('Раз один.\nещё строка.\n\nДва.\n\nТри.') == ['Раз один.\nещё строка.', 'Два.', 'Три.'])
check('абзацы: несколько пустых строк, строки из пробелов и пустые края не дают пустых блоков', cp('\n\n  Раз.  \n \t \n\n\n\nДва.\n\n  \n') == ['Раз.', 'Два.'])
check('абзацы: пустой и «пустой» текст — пустой список; один абзац — один блок', cp('') == [] and cp('  \n\n \n') == [] and cp('Только один.') == ['Только один.'])
# ===================== окно по предложениям =====================
sw = sc.chunk_by_sentence_window
check('окно 1/1: на каждое предложение — оно, одно до и одно после (в пределах абзаца), через пробел', sw('а1. а2. а3. а4.', 1, 1) == ['а1. а2.', 'а1. а2. а3.', 'а2. а3. а4.', 'а3. а4.'], str(sw('а1. а2. а3. а4.', 1, 1)))
check('окно 0/0: блок — одно предложение; число блоков равно числу предложений при любом размере окна', sw('а1. а2. а3.', 0, 0) == ['а1.', 'а2.', 'а3.'] and len(sw('а1. а2. а3.', 5, 5)) == 3)
check('окно не выходит за границы абзаца', sw('а1. а2.\n\nб1. б2.', 3, 3) == ['а1. а2.', 'а1. а2.', 'б1. б2.', 'б1. б2.'])
check('окно: несимметричное (2 до, 0 после) и отрицательные значения (считаются нулём)', sw('а1. а2. а3. а4.', 2, 0) == ['а1.', 'а1. а2.', 'а1. а2. а3.', 'а2. а3. а4.'] and sw('а1. а2.', -5, -1) == ['а1.', 'а2.'])
check('окно: пустой текст — пустой список; значения по умолчанию — 7 до и 10 после (всё предложение абзаца в одном блоке)', sw('') == [] and sw('  \n\n ') == [] and sw('а1. а2. а3.')[0] == 'а1. а2. а3.')
check('окно: числа можно передать строками (как из диалога)', sw('а1. а2.', '1', '0') == ['а1.', 'а1. а2.'])
# ===================== перекрытие по символам =====================
co = sc.chunk_by_overlap
check('перекрытие: пустой текст — пустой список; короткий текст — один блок', co('') == [] and co('Короткий текст.', 900, 150) == ['Короткий текст.'] and co('  пробелы  ', 900, 150) == ['пробелы'])
words = [f'сл{i:03d}' for i in range(120)]; text = ' '.join(words)
chunks = co(text, 100, 30)
def as_ranges(chunks, words):
    ranges = []
    for c in chunks:
        toks = c.split(); first, last = words.index(toks[0]), words.index(toks[-1]); ranges.append((first, last)); assert toks == words[first:last + 1], c
    return ranges
rngs = as_ranges(chunks, words)
check('перекрытие: каждый блок — непрерывный кусок текста из целых слов; первый начинается с первого слова, последний заканчивается последним', rngs[0][0] == 0 and rngs[-1][1] == len(words) - 1, str(rngs[:3]))
check('перекрытие: блоки идут вперёд, соседние перекрываются или смыкаются (слова не теряются)', all(rngs[i + 1][0] > rngs[i][0] and rngs[i + 1][0] <= rngs[i][1] + 1 for i in range(len(rngs) - 1)), str(rngs[:4]))
check('перекрытие: ни один блок не длиннее заданного размера', all(len(c) <= 100 for c in chunks), str(max(len(c) for c in chunks)))
def shared(a, b):
    for k in range(min(len(a), len(b)), 0, -1):
        if a.endswith(b[:k]): return k
    return 0
check('перекрытие: соседние блоки действительно разделяют текст — не меньше заданного перекрытия минус длина слова', all(shared(chunks[i], chunks[i + 1]) >= 30 - len(words[0]) - 1 for i in range(len(chunks) - 1)), str([shared(chunks[i], chunks[i + 1]) for i in range(5)]))
chunks0 = co(text, 100, 0); rng0 = as_ranges(chunks0, words)
check('перекрытие 0: блоки смыкаются без повторов, все слова на месте по порядку', [w for c in chunks0 for w in c.split()] == words and all(rng0[i + 1][0] == rng0[i][1] + 1 for i in range(len(rng0) - 1)))
check('перекрытие не меньше размера блока ограничивается (иначе блоки не двигались бы вперёд): цикл заканчивается, слова не теряются', set(w for c in co(text, 50, 500) for w in c.split()) == set(words) and set(w for c in co(text, 50, 50) for w in c.split()) == set(words))
long_word = 'я' * 250; cl = co(long_word, 100, 20)
check('слово длиннее блока режется по размеру (пробела негде найти), всё содержимое сохраняется', all(len(c) <= 100 for c in cl) and ''.join(cl).count('я') >= 250 and len(cl) >= 3, str([len(c) for c in cl]))
check('перенос строки и табуляция тоже границы слов', set(w for c in co('\n'.join(words), 60, 10) for w in c.split()) == set(words) and set(w for c in co('\t'.join(words), 60, 10) for w in c.split()) == set(words))
check('размер блока 1, нулевой и отрицательный — не зависает и даёт результат', len(co('аб вг', 1, 0)) >= 2 and co('аб вг', 0, 0) != [] and co('аб вг', -5, -5) != [])
rnd = random.Random(88); bad_struct = bad_len = bad_cover = 0
for _ in range(600):
    n = rnd.randint(0, 120); ws = [f'w{i}x' + 'y' * rnd.randint(0, 6) for i in range(n)]; tg = rnd.randint(60, 200); ov = rnd.randint(0, tg - 1)
    t = ' '.join(ws); ch = co(t, tg, ov)
    if not ws: bad_struct += bool(ch); continue
    bad_len += any(len(c) > tg for c in ch)
    try: rg = as_ranges(ch, ws)
    except Exception: bad_struct += 1; continue
    bad_struct += not (rg[0][0] == 0 and rg[-1][1] == len(ws) - 1 and all(rg[i + 1][0] > rg[i][0] and rg[i + 1][0] <= rg[i][1] + 1 for i in range(len(rg) - 1)))
    bad_cover += set(w for c in ch for w in c.split()) != set(ws)
check('свойства на 600 случайных текстах (блок не короче 60 символов — пробел в блоке всегда найдётся): структура (целые слова, вперёд, без дыр и без повторов), размер не больше заданного, покрытие всех слов', bad_struct == 0 and bad_len == 0 and bad_cover == 0, f'структура {bad_struct}, длина {bad_len}, покрытие {bad_cover}')
dups = 0; lost = 0; slow = 0
for _ in range(600):
    n = rnd.randint(1, 60); ws = [f'{i}' + ''.join(rnd.choice('абвгдежз') for _ in range(rnd.randint(0, 8))) for i in range(n)]; tg = rnd.randint(3, 40); ov = rnd.randint(0, 60); t = ' '.join(ws); ch = co(t, tg, ov)
    dups += any(ch[i] == ch[i + 1] for i in range(len(ch) - 1)); lost += set(re.sub(r'\s', '', t)) != set(re.sub(r'\s', '', ''.join(ch))); slow += len(ch) > len(t) + 1
check('крошечные блоки (3-40 символов, слово может не поместиться): без подряд идущих одинаковых блоков, символы не теряются, число блоков не растёт бесконечно', dups == 0 and lost == 0 and slow == 0, f'повторов {dups}, потерь {lost}, лишних блоков {slow}')
tail_ws = co(' '.join(f'сл{i:02d}' for i in range(60)), 30, 29); check('перекрытие почти равно размеру блока (29 из 30): блоки не повторяются и идут вперёд', all(tail_ws[i] != tail_ws[i + 1] for i in range(len(tail_ws) - 1)) and len(tail_ws) > 20, str(len(tail_ws)))
check('перекрытие по умолчанию — 900 символов с перекрытием 150', len(co(' '.join(f'слово{i}' for i in range(800)))) >= 6 and all(len(c) <= 900 for c in co(' '.join(f'слово{i}' for i in range(800)))))
# ===================== с настоящим разбиением на предложения =====================
import importlib; real = importlib.reload(sc)
check('с настоящим разбиением на предложения: окно 1/1 на простом тексте даёт то же самое', real.chunk_by_sentence_window('Раз один. Два два. Три три.', 1, 1) == ['Раз один. Два два.', 'Раз один. Два два. Три три.', 'Два два. Три три.'], str(real.chunk_by_sentence_window('Раз один. Два два. Три три.', 1, 1)))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
