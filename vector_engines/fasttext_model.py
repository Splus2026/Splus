"""Реализация BaseVectorModel через gensim.models.FastText (gensim 4.x).

   FastText выбран (а не Word2Vec) специально для обучения "с нуля" на
   небольшом корпусе (одна-несколько книг): в отличие от Word2Vec, который
   учит вектор только для целого слова как атомарной единицы, FastText
   дополнительно учитывает вектор слова как сумму векторов его буквенных
   n-грамм. Для языка с богатой морфологией (русский) это даёт заметно более
   устойчивые векторы при малом объёме данных — разные словоформы одного
   корня оказываются близко друг к другу просто за счёт совпадающих
   n-грамм, даже если каждая форма встретилась в тексте всего пару раз.

   gensim — необязательная зависимость: устанавливается через
   `pip install gensim`. Импортируется здесь лениво (внутри методов), а не
   на уровне модуля, чтобы само наличие этого файла не требовало gensim,
   пока пользователь реально не запустит обучение/поиск по векторам."""

from typing import List, Tuple
from .base_vector_model import BaseVectorModel, TrainingCancelled


class FastTextModel(BaseVectorModel):
    model_type = "fasttext"

    def __init__(self):
        self.model = None

    def train(self, sentences: List[List[str]], cancel_check=None, **params):
        try:
            from gensim.models import FastText
        except ImportError as e:
            raise ImportError(
                "Для векторного поиска нужен пакет gensim. Установите его: "
                "pip install gensim\n\nПричина: %s" % e
            )
        # Параметры по умолчанию подобраны для обучения "с нуля" на малом
        # корпусе (одна-несколько книг), а не на типичном для gensim корпусе
        # из миллионов слов:
        # - vector_size=100 (не 300) — на малом корпусе большая размерность
        #   не успеет обучиться содержательно;
        # - epochs=20 (не 5) — компенсируем малый объём текста повторными
        #   проходами; корпус маленький, так что это всё равно быстро;
        # - min_count=1 (не 5) — иначе редкие, но важные для книги термины
        #   просто выкинутся из словаря;
        # - sg=1 (skip-gram, не CBOW) — на малых корпусах и для редких слов
        #   обычно даёт качественнее векторы.
        vector_size = params.get('vector_size', 100)
        window = params.get('window', 5)
        min_count = params.get('min_count', 1)
        epochs = params.get('epochs', 20)
        sg = params.get('sg', 1)
        workers = params.get('workers', 4)

        # Строим модель и словарь без обучения, а сами эпохи прогоняем по
        # одной — чтобы между ними можно было проверить прерывание (Esc,
        # см. VectorModelManager). Скорость обучения (alpha) при этом
        # уменьшаем вручную линейно по всем эпохам сразу — как это делает
        # сам gensim при epochs=N одним вызовом — иначе, разбив эпохи по
        # отдельности "наивно", каждая заново начинала бы и заканчивала
        # свой отдельный, слишком короткий цикл затухания alpha.
        model = FastText(vector_size=vector_size, window=window, min_count=min_count,
                         sg=sg, workers=workers)
        model.build_vocab(sentences)
        start_alpha = model.alpha
        min_alpha = model.min_alpha
        for i in range(epochs):
            if cancel_check and cancel_check():
                raise TrainingCancelled("Обучение прервано пользователем.")
            cur_alpha = start_alpha - (start_alpha - min_alpha) * (i / epochs)
            next_alpha = start_alpha - (start_alpha - min_alpha) * ((i + 1) / epochs)
            model.train(sentences, total_examples=model.corpus_count, epochs=1,
                       start_alpha=cur_alpha, end_alpha=next_alpha)
        self.model = model

    def continue_train(self, sentences: List[List[str]], cancel_check=None, **params):
        if self.model is None:
            raise RuntimeError("Модель не обучена и не загружена — дообучать нечего")
        # Стандартный для gensim способ дообучения: расширяем словарь новыми
        # словами (update=True — не начинаем словарь заново), затем дообучаем
        # на новых данных тем же числом эпох, что использовалось при
        # изначальном обучении — по одной эпохе за раз, как и в train()
        # выше, чтобы можно было проверить прерывание между ними.
        self.model.build_vocab(sentences, update=True)
        epochs = self.model.epochs
        start_alpha = self.model.alpha
        min_alpha = self.model.min_alpha
        for i in range(epochs):
            if cancel_check and cancel_check():
                raise TrainingCancelled("Дообучение прервано пользователем.")
            cur_alpha = start_alpha - (start_alpha - min_alpha) * (i / epochs)
            next_alpha = start_alpha - (start_alpha - min_alpha) * ((i + 1) / epochs)
            self.model.train(sentences, total_examples=len(sentences), epochs=1,
                             start_alpha=cur_alpha, end_alpha=next_alpha)

    def save(self, path: str):
        if self.model is None:
            raise RuntimeError("Модель не обучена и не загружена")
        self.model.save(path)

    def load(self, path: str):
        try:
            from gensim.models import FastText
        except ImportError as e:
            raise ImportError(
                "Для векторного поиска нужен пакет gensim. Установите его: "
                "pip install gensim\n\nПричина: %s" % e
            )
        self.model = FastText.load(path)

    def most_similar(self, word: str, topn: int = 15) -> List[Tuple[str, float]]:
        if self.model is None:
            raise RuntimeError("Модель не обучена и не загружена")
        try:
            return list(self.model.wv.most_similar(word.lower(), topn=topn))
        except KeyError as e:
            print(f"⚠️ FastText most_similar('{word}'): KeyError — {e} "
                 f"(слово не нашлось в словаре модели даже через n-граммы)")
            return []

    def search_passages(self, query_text: str, topn: int = 15):
        raise NotImplementedError(
            "Прямой семантический поиск по кускам текста не применим к FastText — "
            "это модель отдельных слов, а не целых предложений. Используйте "
            "most_similar() (поиск близких слов) вместо этого."
        )

    def has_word(self, word: str) -> bool:
        if self.model is None:
            return False
        try:
            _ = self.model.wv[word.lower()]
            return True
        except KeyError:
            return False

    def get_vector(self, word: str):
        """Возвращает сам вектор слова (не близость к чему-то, а его
           координаты) — нужно для визуализации (кнопка "3D/2D" у окна
           "Совпадения"): чтобы показать взаимное расположение слов в
           пространстве, нужны именно координаты, а не заранее посчитанная
           близость к ОДНОМУ конкретному слову запроса."""
        if self.model is None:
            raise RuntimeError("Модель не обучена и не загружена")
        return self.model.wv[word.lower()]

    def get_vocabulary_words(self):
        """Возвращает список ВСЕХ слов словаря модели (не соседей одного
           запроса, а вообще всё, чему модель обучалась) — нужен для
           анализа всего векторного пространства целиком: поиска самых
           "насыщенных понятиями" (густо скопившихся) областей (кнопка
           "3D/2D" -> "Сгущения понятий", см. ui/app_window.py)."""
        if self.model is None:
            return []
        return list(self.model.wv.index_to_key)

    def get_word_frequency(self, word: str) -> int:
        """Частота слова в обучающем корпусе — используется при поиске
           "насыщенных" областей, чтобы отличать содержательные скопления
           слов от скоплений чисто служебных, частотных слов (предлоги,
           союзы и т.п.), которые иначе легко "забивают" собой самые
           густые области просто в силу частоты употребления, а не
           смысловой значимости."""
        if self.model is None:
            return 0
        try:
            return int(self.model.wv.get_vecattr(word, 'count'))
        except (KeyError, AttributeError):
            return 0

    def get_params(self) -> dict:
        if self.model is None:
            return {}
        # Значения берём с самого объекта gensim (а не из тех параметров,
        # что мы ему передавали) — это то, что модель реально использовала.
        return {
            'vector_size': self.model.vector_size,
            'window': self.model.window,
            'min_count': self.model.min_count,
            'epochs': self.model.epochs,
            'sg': self.model.sg,
            'workers': self.model.workers,
        }
