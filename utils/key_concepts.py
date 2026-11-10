"""Словарь ключевых понятий: кнопка "КП" над средним окном добавляет в него
   выделенное слово, а параметр key_concepts_only в mconfig.ini ограничивает
   облако тегов ("Т"), центральные понятия ("Ц") и пункты "Сгущение понятий" и
   "Всё пространство" меню "3D/2D" только словами из этого словаря и их
   вариациями.

   Словарь — обычный текстовый файл key_concepts.txt рядом с mconfig.ini: по
   одному слову на строке, строчными буквами. Его можно править вручную (убрать
   лишнее, добавить своё): пустые строки и строки, начинающиеся с "#", при чтении
   пропускаются и при дописывании кнопкой не затрагиваются.

   ВАРИАЦИЯ слова понимается ровно так же, как кнопкой "−В/+В" (слова, которые
   она убирает из окна "Совпадения", — те же, что фильтр включает): грубая проверка
   по общему началу. Определение живёт здесь, а services/vector_model_manager.py
   импортирует его обратно — чтобы два места не разошлись."""

import os
import re

# Те же "слова", что у облака тегов и TextRank (ui/vector_visualization.py): только
# буквы. Слово с дефисом ("кто-то") — два слова.
WORD_RE = re.compile(r'[а-яА-ЯёЁa-zA-Z]+')


def extract_words(text):
    """Слова из текста (строчными): из выделенного фрагмента берутся только
       буквенные слова, знаки препинания и цифры отбрасываются."""
    return [w.lower() for w in WORD_RE.findall(text or '')]


def words_are_variations(w1: str, w2: str, min_shared_ratio: float = 0.75, min_shared_chars: int = 3) -> bool:
    """Грубая проверка "одно ли это слово в разных формах" — по общему
       началу (префиксу): считаем словоформами одного слова, если общий
       префикс покрывает большую часть КОРОТКОГО из двух слов (например,
       "равновесие"/"равновесием"/"равновесию" — общее начало "равновеси"
       покрывает 90% десятибуквенного "равновесие"). Не идеально (не
       различает чередования в самом корне, может изредка ложно объединить
       разные слова со случайно совпадающим началом — у совсем коротких слов
       это заметнее: "бог" совпадёт и с "богатый"), но простой, без
       словаря/морфологии способ — той же природы, что и уже используемая в
       проекте грубая "стемминг"-логика для русского языка (см.
       vector_engines/lsa_model.py, там для другой цели — векторизации, здесь —
       для группировки при показе и для фильтра ключевых понятий)."""
    if w1 == w2:
        return True
    shorter = w1 if len(w1) <= len(w2) else w2
    if len(shorter) < min_shared_chars:
        return False
    common_len = 0
    for a, b in zip(w1, w2):
        if a == b:
            common_len += 1
        else:
            break
    return common_len >= max(min_shared_chars, int(len(shorter) * min_shared_ratio))


def expand_dictionary(key_words, vocabulary):
    """Множество слов из vocabulary, которые совпадают с ключевым словом или
       являются его вариацией (см. words_are_variations). Возвращаются слова
       в том виде, как они записаны в vocabulary.

       Ключевые слова группируются по первым трём буквам: вариацией может быть
       только слово с тем же началом (короче трёх букв слово совпадает лишь с
       самим собой), поэтому каждое слово словаря сравнивается не со всеми
       ключевыми словами, а с парой-тройкой из своей группы."""
    keys = {w.lower() for w in key_words if w}
    by_prefix = {}
    for key in keys:
        if len(key) >= 3:
            by_prefix.setdefault(key[:3], []).append(key)
    result = set()
    for word in vocabulary:
        lowered = word.lower()
        if lowered in keys:
            result.add(word)
            continue
        if len(lowered) >= 3:
            for key in by_prefix.get(lowered[:3], ()):
                if words_are_variations(lowered, key):
                    result.add(word)
                    break
    return result


def _read_text(path):
    """Содержимое файла словаря; UTF-8 (в том числе с меткой BOM), а если файл
       сохранён старым Блокнотом в cp1251 — как cp1251. Возвращает (текст,
       была_ли_cp1251)."""
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        return raw.decode('utf-8-sig'), False
    except UnicodeDecodeError:
        return raw.decode('cp1251', errors='replace'), True


def load_key_concepts(path):
    """Слова словаря по порядку добавления, без повторов, строчными. Нет файла —
       пустой список (словарь ещё не заведён)."""
    if not os.path.exists(path):
        return []
    text, _legacy = _read_text(path)
    seen, words = set(), []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        word = line.lower()
        if word not in seen:
            seen.add(word)
            words.append(word)
    return words


def add_key_concept(path, word):
    """Дописывает слово в словарь. True — добавлено, False — такое уже есть
       (регистр не важен). Строки, которые пользователь мог дописать вручную
       (комментарии, пустые), сохраняются как были: файл не переписывается, слово
       дописывается в конец."""
    word = (word or '').strip().lower()
    if not word:
        raise ValueError("Пустое слово")
    if word in load_key_concepts(path):
        return False
    if os.path.exists(path):
        text, legacy = _read_text(path)
        if legacy:
            # Файл в cp1251: дописывать UTF-8 байты в такой файл значит
            # испортить его — переводим весь файл в UTF-8 заодно с новым словом.
            if text and not text.endswith('\n'):
                text += '\n'
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(text + word + '\n')
            return True
        with open(path, 'rb') as f:
            data = f.read()
        prefix = '' if (not data or data.endswith(b'\n')) else '\n'  # файл без перевода строки в конце
    else:
        prefix = ''
    with open(path, 'a', encoding='utf-8', newline='') as f:
        f.write(prefix + word + '\n')
    return True
