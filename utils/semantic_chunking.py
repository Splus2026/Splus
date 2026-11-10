"""Нарезка текста на смысловые блоки — «окна смысла» для MiniLM (режимы 2-4 в диалоге параметров
   модели, см. ui/vector_params_dialog.py и VectorModelManager._build_minilm_semantic_chunks).

   Модуль подключался менеджером моделей, но самого файла в проекте не было: при выборе любого
   режима, кроме «Готовый индекс», обучение MiniLM заканчивалось ошибкой «No module named
   'utils.semantic_chunking'». Функции сделаны по описанию режимов в диалоге:

   - chunk_by_sentence_window — «Скользящее окно по предложениям»: на каждое предложение — блок из
     него самого, до N предложений ДО и до M предложений ПОСЛЕ (тот же смысл, что у «кругов связи» в
     настройках программы, откуда берутся значения по умолчанию); окно не выходит за границы абзаца;
   - chunk_by_overlap — «Перекрытие по символам»: блоки не длиннее target символов, каждый следующий
     начинается так, что с предыдущим перекрывается примерно на overlap символов; границы сдвигаются к
     пробелам, чтобы не резать слова;
   - chunk_by_paragraphs — «Автоматическая разбивка по абзацам»: один блок — один абзац (абзацы
     разделены пустой строкой).

   Все функции возвращают список непустых строк."""

import re

from utils.text_processing import split_sentences

_PARAGRAPH_SPLIT_RE = re.compile(r'\n\s*\n')


def _paragraphs(text):
    return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]


def _second_word_start(text, start, end):
    """Позиция начала второго слова в text[start:end] (минимальный шаг вперёд); если слово одно — конец блока."""
    i = start
    while i < end and not text[i].isspace():
        i += 1
    while i < end and text[i].isspace():
        i += 1
    return i


def chunk_by_paragraphs(text: str) -> list:
    """Один блок — один абзац (абзацы разделены пустой строкой); пустые абзацы пропускаются."""
    return _paragraphs(text)


def chunk_by_sentence_window(text: str, sentences_before: int = 7, sentences_after: int = 10) -> list:
    """Блок на каждое предложение: оно само, до sentences_before предложений до него и до
       sentences_after после него — в пределах одного абзаца. Предложения в блоке соединены пробелом.
       Отрицательные значения считаются нулём."""
    before = max(0, int(sentences_before))
    after = max(0, int(sentences_after))
    blocks = []
    for paragraph in _paragraphs(text):
        sentences = split_sentences(paragraph)
        count = len(sentences)
        for i in range(count):
            low = max(0, i - before)
            high = min(count, i + after + 1)
            blocks.append(' '.join(sentences[low:high]))
    return blocks


def chunk_by_overlap(text: str, target: int = 900, overlap: int = 150) -> list:
    """Блоки не длиннее target символов; следующий блок начинается так, чтобы перекрыться с предыдущим
       примерно на overlap символов. Конец блока сдвигается назад к ближайшему пробелу (если он в
       пределах второй половины блока), а начало следующего — вперёд к началу слова: слова не режутся
       (из-за этого перекрытие может оказаться короче на длину одного слова). Перекрытие, не меньшее
       размера блока, ограничивается (иначе блоки не продвигались бы вперёд)."""
    target = max(1, int(target))
    overlap = max(0, min(int(overlap), target - 1))
    length = len(text)
    chunks = []
    start = 0
    while start < length:
        while start < length and text[start].isspace():   # блок начинается со слова, а не с пробела, на котором
            start += 1                                      # оборвался предыдущий (иначе «следующий» блок мог
        if start >= length:                                 # совпасть с предыдущим: его начало считалось с пробела)
            break
        end = min(start + target, length)
        if end < length:
            cut = max(text.rfind(' ', start, end), text.rfind('\n', start, end), text.rfind('\t', start, end))
            if cut > start + target // 2:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        # Следующий блок начинается минимум со второго слова этого блока (иначе он не продвинулся бы вперёд и
        # повторил бы его), а при большом перекрытии — как можно раньше, но не ближе, чем overlap символов до конца.
        floor = _second_word_start(text, start, end)
        next_start = end - overlap
        if next_start <= floor:
            next_start = floor
        else:                            # не начинаем посреди слова: сдвигаем к началу следующего слова
            while next_start < end and not text[next_start - 1].isspace() and not text[next_start].isspace():
                next_start += 1
            while next_start < length and text[next_start].isspace():
                next_start += 1
        start = next_start
    return chunks
