"""Анализ текста без векторной модели: частоты слов (облако тегов), граф совместной
   встречаемости и TextRank/PageRank (центральные понятия), раскладка облака тегов.

   Чистые функции — ни одного обращения к интерфейсу. Раньше жили в
   ui/vector_visualization.py только потому, что результат рисуется на Canvas; рисует
   их ui/visualization_manager.py, а считать им место здесь, чтобы сервисы и тесты
   могли ими пользоваться, не подтягивая за собой интерфейс. Старый путь импорта
   (ui.vector_visualization) сохранён для обратной совместимости."""

import math
import re as _re
from collections import Counter as _Counter
from utils.key_concepts import expand_dictionary as _expand_dictionary


_TAG_WORD_RE = _re.compile(r'[а-яА-ЯёЁa-zA-Z]+')


# Частые русские служебные слова (местоимения, предлоги, союзы, частицы) —
# без этого списка облако было бы забито словами вроде "и"/"в"/"это"
# вместо содержательных слов текста.
RUSSIAN_STOPWORDS = frozenset([
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они', 'его', 'её', 'ее', 'их',
    'ему', 'ей', 'им', 'ими', 'него', 'неё', 'нее', 'них', 'меня', 'тебя',
    'нас', 'вас', 'мне', 'тебе', 'нам', 'вам', 'себя', 'себе', 'собой',
    'мой', 'моя', 'моё', 'мое', 'мои', 'твой', 'твоя', 'твоё', 'твое', 'твои',
    'наш', 'наша', 'наше', 'наши', 'ваш', 'ваша', 'ваше', 'ваши',
    'свой', 'своя', 'своё', 'свое', 'свои', 'этот', 'эта', 'это', 'эти',
    'тот', 'та', 'то', 'те', 'такой', 'такая', 'такое', 'такие',
    'кто', 'что', 'какой', 'какая', 'какое', 'какие', 'каждый', 'каждая', 'каждое',
    'который', 'которая', 'которое', 'которые', 'весь', 'вся', 'всё', 'все',
    'в', 'во', 'на', 'за', 'из', 'изо', 'от', 'ото', 'до', 'по', 'под', 'подо',
    'над', 'надо', 'через', 'при', 'для', 'без', 'безо', 'про', 'между',
    'среди', 'вокруг', 'около', 'возле', 'перед', 'передо', 'после', 'сквозь',
    'вдоль', 'согласно', 'благодаря', 'вопреки', 'кроме', 'к', 'ко', 'у',
    'с', 'со', 'о', 'об', 'обо', 'и', 'а', 'но',
    'чтобы', 'если', 'когда', 'пока', 'хотя', 'будто', 'словно', 'как', 'так',
    'также', 'тоже', 'же', 'ли', 'бы', 'б', 'не', 'ни', 'да', 'или', 'либо',
    'только', 'уже', 'еще', 'ещё', 'вот', 'даже', 'разве', 'неужели', 'ведь',
    'именно', 'почти', 'очень', 'более', 'менее', 'самый', 'самая', 'самое', 'самые',
    'есть', 'быть', 'был', 'была', 'было', 'были', 'будет', 'будут', 'буду', 'будешь',
    'того', 'тому', 'тем', 'той', 'ту', 'там', 'тут', 'здесь', 'туда', 'сюда',
    'отсюда', 'оттуда', 'куда', 'откуда', 'всегда', 'никогда', 'иногда',
    'сейчас', 'потом', 'теперь', 'тогда', 'один', 'одна', 'одно', 'одни',
])


_snowball_stemmer = None


_snowball_tried = False


def _get_snowball_stemmer():
    """Пробует создать настоящий морфологический стеммер (nltk Snowball для
       русского, тот же пакет, что уже опционально используется в проекте
       для разбиения на предложения, см. utils/text_processing.
       split_sentences) — если недоступен, возвращает None, тогда
       используется грубая эвристика ниже. Результат кэшируется — пробуем
       завести стеммер не более одного раза за всё время работы программы."""
    global _snowball_stemmer, _snowball_tried
    if not _snowball_tried:
        _snowball_tried = True
        try:
            from nltk.stem.snowball import SnowballStemmer
            _snowball_stemmer = SnowballStemmer('russian')
        except Exception:
            _snowball_stemmer = None
    return _snowball_stemmer


def _stem_for_grouping(word: str) -> str:
    """Основа слова для объединения словоформ ("бог"/"бога"/"богу" и т.п.)
       — по возможности настоящий морфологический стеммер (точнее: верно
       учитывает окончания, а не просто длину слова — поэтому правильно
       объединяет и короткие, часто склоняемые слова вроде "бог", которые
       грубая эвристика ниже пропускает, трогая только слова длиннее 5
       букв). При недоступности nltk — откат на ту же грубую эвристику,
       что уже используется в LSA (vector_engines/lsa_model.py): отрезать
       последние 2 буквы у слов длиннее 5 символов."""
    stemmer = _get_snowball_stemmer()
    if stemmer is not None:
        try:
            return stemmer.stem(word)
        except Exception:
            pass
    return word if len(word) <= 5 else word[:len(word) - 2]


def _merge_word_forms(tokens):
    """Заменяет каждый токен на самую частую поверхностную форму среди
       всех токенов с той же грубой основой (см. _stem_for_grouping) —
       сохраняя исходный порядок (важно для окна совместной встречаемости
       ниже). Например, если "бог" встретился 5 раз, а "бога" — 8, то и
       "бог", и "бога" в результате станут "бога" — их общий вес уже не
       делится между формами."""
    from collections import Counter as _C
    stem_surface_counts = {}
    for tok in tokens:
        stem = _stem_for_grouping(tok)
        stem_surface_counts.setdefault(stem, _C())[tok] += 1
    stem_to_label = {stem: counts.most_common(1)[0][0] for stem, counts in stem_surface_counts.items()}
    return [stem_to_label[_stem_for_grouping(tok)] for tok in tokens]


def build_cooccurrence_graph(texts, window: int = 4, min_word_length: int = 3, top_n_words: int = 200,
                             key_words=None):
    """Строит НАПРАВЛЕННЫЙ граф совместной встречаемости слов — основа для
       TextRank: слово, встретившееся РАНЬШЕ в пределах окна из window слов,
       получает исходящее ребро к слову, встретившемуся ПОЗЖЕ (вес ребра =
       сколько раз так совпало по всем текстам). Это НЕ про векторную
       близость — про то, что слова реально стоят рядом в самом тексте и
       в каком порядке, тот же принцип, что лежит в основе PageRank
       (важен не сам факт связи, а то, с НАСКОЛЬКО ВАЖНЫМИ узлами слово
       связано).

       Граф именно НАПРАВЛЕННЫЙ, а не ненаправленный — важная деталь:
       PageRank на ненаправленном графе математически сходится к
       распределению, ПРОПОРЦИОНАЛЬНОМУ взвешенной степени узла (это
       доказуемая теорема, не особенность реализации) — а степень узла в
       графе совместной встречаемости сама сильно коррелирует с обычной
       частотой слова. На практике это означало, что результат почти не
       отличался от облака тегов (проверено: корреляция 0.998 на
       ненаправленном графе). На направленном графе этого математического
       совпадения уже нет (проверено: корреляция падает до ~0.1) —
       получаем действительно другую информацию: не "что часто
       встречается", а "через что идёт поток связей в тексте".

       Анализ ограничен top_n_words самыми частыми (после отсева стоп-слов
       и коротких) — иначе граф на весь словарь книги был бы неоправданно
       большим без заметного выигрыша в точности результата.

       key_words — слова словаря ключевых понятий (кнопка "КП", параметр
       key_concepts_only): слова словаря и их вариации не отсеиваются как
       короткие/служебные и входят в граф ВСЕГДА, даже если они не среди
       top_n_words самых частых — иначе редкое ключевое слово вообще не получило
       бы оценки. Остальное в графе остаётся как было, поэтому центральность
       ключевых слов считается в контексте ВСЕГО текста, а не только среди
       ключевых слов. Показывать только ключевые слова — забота вызывающего
       кода (ui/app_window.py).

       Возвращает (words, edges) — words: список узлов графа, edges:
       {(слово_раньше, слово_позже): вес} — направление в ключе важно,
       (а, б) и (б, а) — разные, отдельно учитываемые рёбра."""
    if key_words is None:
        all_tokens = []
        for text in texts:
            for word in _TAG_WORD_RE.findall((text or '').lower()):
                if len(word) < min_word_length or word in RUSSIAN_STOPWORDS:
                    continue
                all_tokens.append(word)
    else:
        raw_tokens = [w for text in texts for w in _TAG_WORD_RE.findall((text or '').lower())]
        allowed = _expand_dictionary(key_words, set(raw_tokens))
        all_tokens = [w for w in raw_tokens
                      if w in allowed or (len(w) >= min_word_length and w not in RUSSIAN_STOPWORDS)]

    if not all_tokens:
        return [], {}

    all_tokens = _merge_word_forms(all_tokens)
    freq = _Counter(all_tokens)
    top_words = {w for w, _c in freq.most_common(top_n_words)}
    if key_words is not None:
        top_words |= _expand_dictionary(key_words, freq.keys())

    edges = _Counter()
    n = len(all_tokens)
    for i, word in enumerate(all_tokens):
        if word not in top_words:
            continue
        for j in range(i + 1, min(i + window + 1, n)):
            other = all_tokens[j]
            if other == word or other not in top_words:
                continue
            edges[(word, other)] += 1  # направленное: word (раньше) -> other (позже)

    return list(top_words), dict(edges)


def _pagerank_single_pass(words, directed_edges, damping, max_iter, tol):
    """Один проход PageRank по направленному графу (см. compute_textrank —
       вызывается дважды, вперёд и назад, и результаты усредняются)."""
    import numpy as np

    n = len(words)
    word_idx = {w: i for i, w in enumerate(words)}
    adj = np.zeros((n, n))  # adj[i, j] — вес НАПРАВЛЕННОГО ребра i -> j
    for (src, dst), weight in directed_edges.items():
        adj[word_idx[src], word_idx[dst]] = weight

    out_weights = adj.sum(axis=1, keepdims=True)
    # "Тупиковые" узлы — без исходящих рёбер — стандартный приём PageRank:
    # их "вес" не теряется, а равномерно раздаётся всем узлам на
    # следующем шаге, иначе такие узлы становятся "утечкой" и итоговые
    # оценки не суммируются к осмысленному целому.
    dangling_mask = (out_weights.flatten() == 0)
    out_weights_safe = out_weights.copy()
    out_weights_safe[out_weights_safe == 0] = 1
    transition = adj / out_weights_safe

    scores = np.ones(n) / n
    for _ in range(max_iter):
        incoming = transition.T @ scores
        dangling_mass = scores[dangling_mask].sum() / n
        new_scores = (1 - damping) / n + damping * (incoming + dangling_mass)
        if np.abs(new_scores - scores).sum() < tol:
            scores = new_scores
            break
        scores = new_scores
    return scores


def compute_textrank(words, edges, damping: float = 0.85, max_iter: int = 100, tol: float = 1e-6):
    """TextRank — PageRank поверх графа совместной встречаемости слов (см.
       build_cooccurrence_graph). Слово "важно" не потому, что у него
       много связей вообще, а потому, что оно связано с другими ВАЖНЫМИ
       словами — то же рекурсивное определение важности, на котором
       Google изначально ранжировал веб-страницы.

       Считается ДВАЖДЫ — по направлению чтения (слово -> то, что идёт
       после в тексте) и против него (слово -> то, что было до) — и
       результаты усредняются. Так сделано намеренно, после проверки двух
       более простых вариантов:
       - граф без направления вообще — математически PageRank на нём
         сходится к распределению, пропорциональному степени узла, а она
         сама сильно коррелирует с обычной частотой слова — результат
         почти не отличался от облака тегов (проверено: корреляция 0.998);
       - только ОДНО направление (вперёд) — действительно давало другую
         картину, но вносило систематический перекос в пользу слов,
         упомянутых ближе к КОНЦУ текста (они накапливают "входящий" вес
         от всего, что было раньше, почти не "тратя" его обратно) — на
         проверке это выводило в топ второстепенную тему, упомянутую в
         конце, выше явно доминирующей темы всего текста.
       Усреднение прямого и обратного прохода лечит оба случая сразу:
       сохраняет отличие от простой частоты, но не даёт позиции в тексте
       перевешивать настоящую значимость.

       Возвращает список (слово, оценка), отсортированный по убыванию —
       первое слово и есть главный кандидат на "центральное понятие"
       текста."""
    n = len(words)
    if n == 0:
        return []

    reversed_edges = {(dst, src): weight for (src, dst), weight in edges.items()}
    forward_scores = _pagerank_single_pass(words, edges, damping, max_iter, tol)
    backward_scores = _pagerank_single_pass(words, reversed_edges, damping, max_iter, tol)
    combined = (forward_scores + backward_scores) / 2

    return sorted(zip(words, (float(s) for s in combined)), key=lambda x: -x[1])


def compute_word_frequencies(texts, min_word_length: int = 3, top_n: int = 80):
    """Считает частоты слов по списку текстов (один файл или несколько
       сразу — для облака по нескольким книгам одновременно) — с отсевом
       стоп-слов и слишком коротких слов. Возвращает список (слово,
       частота), по убыванию частоты, не длиннее top_n."""
    counter = _Counter()
    for text in texts:
        for word in _TAG_WORD_RE.findall((text or '').lower()):
            if len(word) < min_word_length:
                continue
            if word in RUSSIAN_STOPWORDS:
                continue
            counter[word] += 1
    return counter.most_common(top_n)


def compute_key_word_frequencies(texts, key_words, top_n: int = 80):
    """Частоты только тех слов текста, которые входят в словарь ключевых
       понятий или являются их вариациями (см. utils/key_concepts.py) — для
       облака тегов при key_concepts_only. Каждая форма слова считается
       отдельно (как и в обычном облаке: "бог" и "бога" — разные слова);
       стоп-слова и короткие слова НЕ отсеиваются — слово выбрал пользователь.
       Возвращает [(слово, частота)] по убыванию частоты (при равенстве — по
       алфавиту), не длиннее top_n."""
    counter = _Counter()
    for text in texts:
        counter.update(_TAG_WORD_RE.findall((text or '').lower()))
    allowed = _expand_dictionary(key_words, counter.keys())
    pairs = [(word, count) for word, count in counter.items() if word in allowed]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return pairs[:top_n]


def layout_word_cloud(word_freq_pairs, measure_fn, canvas_width, canvas_height,
                      min_font_size: int = 12, max_font_size: int = 64):
    """Раскладывает слова по расширяющейся спирали, без наложений —
       классический приём для облака тегов (как в Wordle): самое частое
       слово — у центра и крупнее всего, дальше по убыванию частоты ищем
       для каждого слова свободное место, начиная от центра и постепенно
       отдаляясь по спирали.

       measure_fn(word, font_size) -> (ширина, высота) в пикселях —
       передаётся снаружи (через настоящий шрифт Tkinter на вызывающей
       стороне), чтобы здесь не было зависимости от конкретной библиотеки
       отрисовки — координаты коллизий считаются по НАСТОЯЩИМ размерам
       текста, а не по приближению.

       Возвращает список (слово, x, y, размер_шрифта) — x/y это центр
       слова. Слово может быть пропущено (не попасть в результат), если
       за разумное число шагов по спирали не нашлось свободного места —
       лучше пропустить одно слово, чем уронить всю раскладку."""
    if not word_freq_pairs:
        return []

    max_freq = word_freq_pairs[0][1]
    min_freq = word_freq_pairs[-1][1]
    freq_span = max(max_freq - min_freq, 1)

    def font_size_for(freq):
        if max_freq == min_freq:
            return (min_font_size + max_font_size) // 2
        t = (freq - min_freq) / freq_span
        return int(min_font_size + t * (max_font_size - min_font_size))

    cx, cy = canvas_width / 2, canvas_height / 2
    placed_boxes = []

    def overlaps(box):
        x0, y0, x1, y1 = box
        for px0, py0, px1, py1 in placed_boxes:
            if x0 < px1 and x1 > px0 and y0 < py1 and y1 > py0:
                return True
        return False

    result = []
    for word, freq in word_freq_pairs:
        size = font_size_for(freq)
        w, h = measure_fn(word, size)
        half_w, half_h = w / 2, h / 2

        angle = 0.0
        radius = 0.0
        for _step in range(2000):
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            box = (x - half_w, y - half_h, x + half_w, y + half_h)
            if not overlaps(box):
                result.append((word, x, y, size))
                placed_boxes.append(box)
                break
            angle += 0.35
            radius += 2.0

    return result
