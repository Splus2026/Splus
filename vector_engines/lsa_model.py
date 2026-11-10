"""Реализация BaseVectorModel через LSA (латентно-семантический анализ) —
   TF-IDF + сокращение размерности (TruncatedSVD). Портировано из
   отдельного (веб-) проекта пользователя, где эта же архитектура уже
   реально используется — см. обсуждение.

   Природа модели — гибрид между FastText и MiniLM:
   - как FastText — обучается "с нуля" НА САМОМ КОРПУСЕ (а не скачивается
     готовой), поэтому использует ту же инфраструктуру подготовки данных,
     что и MiniLM (build_minilm_training_data — несмотря на название,
     годится для любой модели уровня "целый блок текста", не только
     MiniLM, см. vector_engines.CHUNK_BASED_MODEL_TYPES);
   - как MiniLM — работает с целыми кусками текста (топиками/блоками), а
     не с отдельными словами, поэтому поиск — search_passages (сравнение
     векторов текста напрямую), а не most_similar (близкие слова).

   TfidfVectorizer использует грубый "стемминг" — отрезает окончание у
   длинных слов (analyzer ниже) — простой, не требующий словаря способ
   сблизить разные словоформы одного корня для русского языка (та же идея,
   что и в JS-подсветке веб-проекта, stemPrefix)."""

import re
import pickle
from typing import List, Tuple
from .base_vector_model import BaseVectorModel, TrainingCancelled

_WORD_RE = re.compile(r'[^\W\d_]+', re.UNICODE)


def _norm(s):
    return s.lower().replace('ё', 'е').replace('й', 'и')


def _stem(w):
    """Грубая основа слова: у длинных слов отрезает последние 2 буквы —
       чтобы разные окончания одного корня (важно для русской морфологии)
       попадали в один и тот же "термин" словаря TF-IDF."""
    return w if len(w) <= 5 else w[:len(w) - 2]


def _analyzer(text):
    """Токенизирует в основы слов — используется и при обучении
       (TfidfVectorizer.fit), и при кодировании запроса (тот же
       vectorizer.transform) — токенизация обязана совпадать в обоих
       случаях, иначе термины не совпадут со словарём."""
    return [_stem(w) for w in _WORD_RE.findall(_norm(text)) if len(w) >= 3]


class LSAModel(BaseVectorModel):
    model_type = "lsa"

    def __init__(self):
        self.vec = None          # sklearn.feature_extraction.text.TfidfVectorizer
        self.svd = None          # sklearn.decomposition.TruncatedSVD
        self.refs = []           # список (index_name, rowid) — параллельно embeddings
        self.embeddings = None   # numpy-массив (N, dim), L2-нормированный

    @staticmethod
    def _normalize(vectors):
        import numpy as np
        vectors = np.asarray(vectors, dtype='float32')
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1e-12
        return vectors / norms

    def train(self, sections, cancel_check=None, **params):
        """sections — список (index_name, rowid, text) готовых смысловых
           блоков (готовит VectorModelManager.build_minilm_training_data —
           та же подготовка данных, что и у MiniLM). dim — целевая
           размерность пространства после SVD (по умолчанию 320, как в
           образце); реально используемая размерность может быть меньше,
           если блоков или словаря мало (см. ниже)."""
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        dim = params.get('dim', 320)
        min_df = params.get('min_df', 3)
        max_df = params.get('max_df', 0.4)
        sections = [s for s in sections if s[2] and s[2].strip()]
        if not sections:
            self.refs = []
            self.embeddings = None
            return
        texts = [text for _idx, _rowid, text in sections]

        if cancel_check and cancel_check():
            raise TrainingCancelled("Обучение прервано пользователем.")
        # min_df=3 отсекает опечатки и случайные обрывки (термин должен
        # встретиться хотя бы в 3 блоках), max_df=0.4 — отсекает слишком
        # общие слова (встречаются в >40% блоков — мало что говорят о
        # конкретном блоке). На очень маленьком корпусе min_df=3 может
        # оказаться слишком строгим — тогда sklearn поднимет понятную
        # ошибку про пустой словарь, а не откуда-то из середины обучения.
        self.vec = TfidfVectorizer(analyzer=_analyzer, min_df=min_df, max_df=max_df,
                                   sublinear_tf=True)
        X = self.vec.fit_transform(texts)

        if cancel_check and cancel_check():
            raise TrainingCancelled("Обучение прервано пользователем.")
        actual_dim = min(dim, X.shape[1] - 1, X.shape[0] - 1)
        if actual_dim < 1:
            raise ValueError("Слишком мало текста для обучения LSA — увеличьте число "
                             "выбранных файлов или уменьшите min_df.")
        self.svd = TruncatedSVD(n_components=actual_dim, algorithm='randomized',
                                n_iter=5, random_state=0)
        V = self.svd.fit_transform(X).astype('float32')
        self.svd.components_ = self.svd.components_.astype('float32')

        self.embeddings = self._normalize(V)
        self.refs = [(idx, rowid) for idx, rowid, _text in sections]

    def continue_train(self, sections, cancel_check=None, **params):
        if self.vec is None or self.svd is None:
            raise RuntimeError("Модель не обучена и не загружена — дообучать нечего")
        sections = [s for s in sections if s[2] and s[2].strip()]
        if not sections:
            return
        if cancel_check and cancel_check():
            raise TrainingCancelled("Дообучение прервано пользователем.")
        # Словарь TF-IDF и разложение SVD НЕ переобучаются заново — иначе
        # прежние векторы стали бы несовместимы с новыми (другое
        # пространство). Новые блоки просто проецируются в уже
        # существующее пространство тем же способом, что и запрос при
        # поиске (см. search_passages) — слова, которых не было в
        # исходном словаре, при этом просто не учитываются: модель не
        # "узнаёт" новую лексику без полного переобучения с нуля.
        texts = [text for _idx, _rowid, text in sections]
        X_new = self.vec.transform(texts)
        V_new = self.svd.transform(X_new).astype('float32')
        new_embeddings = self._normalize(V_new)
        new_refs = [(idx, rowid) for idx, rowid, _text in sections]
        if self.embeddings is None:
            self.embeddings = new_embeddings
            self.refs = new_refs
        else:
            import numpy as np
            self.embeddings = np.vstack([self.embeddings, new_embeddings])
            self.refs = self.refs + new_refs

    def save(self, path: str):
        with open(path, 'wb') as f:
            pickle.dump({'vec': self.vec, 'svd': self.svd, 'refs': self.refs,
                        'embeddings': self.embeddings}, f)

    def load(self, path: str):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.vec = data.get('vec')
        self.svd = data.get('svd')
        self.refs = data.get('refs', [])
        self.embeddings = data.get('embeddings')

    def most_similar(self, word: str, topn: int = 15) -> List[Tuple[str, float]]:
        raise NotImplementedError(
            "Поиск по близким словам не применим к этой модели: LSA работает с "
            "векторами целых кусков текста, а не отдельных слов, как FastText. "
            "Используйте search_passages() — прямой поиск похожих по смыслу топиков."
        )

    def search_passages(self, query_text: str, topn: int = 15) -> List[Tuple[str, int, float]]:
        if self.embeddings is None or not self.refs or self.vec is None or self.svd is None:
            return []
        query_text = (query_text or "").strip()
        if not query_text:
            return []
        import numpy as np
        X_query = self.vec.transform([query_text])
        query_vec = self._normalize(self.svd.transform(X_query).astype('float32'))[0]
        sims = self.embeddings @ query_vec
        k = min(topn, sims.size)
        if k <= 0:
            return []
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        return [(self.refs[i][0], int(self.refs[i][1]), float(sims[i])) for i in top_idx]

    def has_word(self, word: str) -> bool:
        return False

    def get_params(self) -> dict:
        return {
            'dim': self.svd.n_components if self.svd is not None else None,
            'vocab_size': len(self.vec.vocabulary_) if self.vec is not None else 0,
            'corpus_size': len(self.refs),
        }
