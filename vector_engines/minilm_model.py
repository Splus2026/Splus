"""Реализация BaseVectorModel через пред-обученную модель предложений
   sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2).

   Архитектура подсмотрена в отдельном (не Tkinter, веб-) проекте
   пользователя, где та же модель уже реально используется для
   семантического поиска — см. обсуждение: там куски текста режутся с
   перекрытием, кодируются моделью, векторы нормируются по длине и
   складываются в единый numpy-массив; поиск — это кодирование запроса тем
   же способом и обычное матричное умножение (скалярное произведение
   нормированных векторов = косинусная близость) со всеми топиками сразу.

   Принципиально другая природа по сравнению с FastText:
   - FastText учится "с нуля" на тексте выбранных книг — веса модели
     подстраиваются под конкретный текст, и результат поиска — список
     БЛИЗКИХ СЛОВ, которыми затем ищут через обычный текстовый поиск.
   - MiniLM — уже готовая, скачанная (один раз, из интернета) модель; веса
     не меняются. "Обучение" здесь — это кодирование уже существующих
     топиков выбранных индексов (не текста заново нарезанного, а именно
     того, что уже лежит в Manticore — см.
     services/vector_model_manager.py, _build_minilm_sections) в векторы,
     которые запоминаются вместе со ссылкой (индекс, rowid) на топик.
     Результат поиска — не список слов, а сразу САМИ похожие по смыслу
     топики (most_similar() для этой модели не применим — см. ниже,
     вместо него search_passages())."""

import pickle
from typing import List, Tuple
from .base_vector_model import BaseVectorModel, TrainingCancelled

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class MiniLMModel(BaseVectorModel):
    model_type = "minilm"

    def __init__(self):
        self.encoder = None       # сама pretrained-модель (sentence_transformers.SentenceTransformer)
        self.refs = []            # список (index_name, rowid) — параллельно строкам embeddings
        self.embeddings = None    # numpy-массив (N, dim), L2-нормированный (см. _normalize)

    def _load_encoder(self):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            # Except Exception, не только ImportError — если PyTorch физически
            # отсутствует (например, программу установили без компонента
            # MiniLM, см. установщик), отсутствующая .dll может дать не
            # ImportError, а OSError или что-то ещё; в любом случае нужно
            # понятное сообщение, а не сырая ошибка загрузки библиотеки.
            raise ImportError(
                "Для модели paraphrase-multilingual-MiniLM-L12-v2 нужен пакет "
                "sentence-transformers (и PyTorch). Если вы ставили программу через "
                "установщик — переустановите с отмеченным компонентом MiniLM; если "
                "запускаете из Python — установите: pip install sentence-transformers "
                "(при первом использовании модель также скачивается из интернета, один раз)."
                f"\n\n(техническая причина: {type(e).__name__}: {e})"
            ) from e
        if self.encoder is None:
            self.encoder = SentenceTransformer(MODEL_NAME)
        return self.encoder

    @staticmethod
    def _normalize(vectors):
        """L2-нормирует векторы по строкам — после этого скалярное
           произведение двух векторов равно косинусной близости, и не
           нужна отдельная формула на каждое сравнение при поиске."""
        import numpy as np
        vectors = np.asarray(vectors, dtype='float32')
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1e-12
        return vectors / norms

    def train(self, sections, cancel_check=None, **params):
        """sections — список (index_name, rowid, text) уже существующих
           топиков (готовит VectorModelManager._build_minilm_sections) —
           не список слов-токенов, как у FastText: эта модель кодирует
           целые куски текста, а не учится на пословных окнах контекста.

           cancel_check — см. BaseVectorModel.train; кодирование разбито
           на чекпоинты по 500 блоков — между ними проверяется
           прерывание, а не только один раз перед всем encode()."""
        encoder = self._load_encoder()
        batch_size = params.get('batch_size', 32)
        sections = [s for s in sections if s[2] and s[2].strip()]
        if not sections:
            self.refs = []
            self.embeddings = None
            return
        texts = [text for _idx, _rowid, text in sections]
        raw = self._encode_with_checkpoints(encoder, texts, batch_size, cancel_check)
        self.embeddings = self._normalize(raw)
        self.refs = [(idx, rowid) for idx, rowid, _text in sections]

    def continue_train(self, sections, cancel_check=None, **params):
        encoder = self._load_encoder()
        batch_size = params.get('batch_size', 32)
        sections = [s for s in sections if s[2] and s[2].strip()]
        if not sections:
            return
        texts = [text for _idx, _rowid, text in sections]
        raw = self._encode_with_checkpoints(encoder, texts, batch_size, cancel_check)
        new_embeddings = self._normalize(raw)
        new_refs = [(idx, rowid) for idx, rowid, _text in sections]
        if self.embeddings is None:
            self.embeddings = new_embeddings
            self.refs = new_refs
        else:
            import numpy as np
            self.embeddings = np.vstack([self.embeddings, new_embeddings])
            self.refs = self.refs + new_refs

    @staticmethod
    def _encode_with_checkpoints(encoder, texts, batch_size, cancel_check, checkpoint_size=100):
        """Кодирует тексты порциями по checkpoint_size, а не одним вызовом
           encode() на весь корпус — между порциями проверяется
           прерывание (Esc, см. VectorModelManager). batch_size — это
           внутренний, более мелкий шаг самого sentence-transformers
           (для эффективности CPU/GPU), не связан с checkpoint_size.
           checkpoint_size уменьшен с прежних 500: если весь корпус
           укладывался в один чекпоинт целиком, проверка происходила
           только один раз в самом начале, и Esc физически не успевал
           сработать до завершения всего кодирования."""
        import numpy as np
        n_checkpoints = (len(texts) + checkpoint_size - 1) // checkpoint_size
        print(f"⏳ Кодирование {len(texts)} блоков за {n_checkpoints} чекпоинт(ов) "
             f"по {checkpoint_size} блоков — прерывание проверяется между ними")
        chunks = []
        for i in range(0, len(texts), checkpoint_size):
            if cancel_check and cancel_check():
                raise TrainingCancelled("Обучение прервано пользователем.")
            piece = texts[i:i + checkpoint_size]
            chunks.append(encoder.encode(piece, batch_size=batch_size, show_progress_bar=False))
        return np.vstack(chunks) if len(chunks) > 1 else chunks[0]

    def save(self, path: str):
        # Саму pretrained-модель не сохраняем (она не менялась — при
        # загрузке просто скачивается/берётся из локального кеша заново по
        # имени) — сохраняем только векторы топиков и ссылки на них.
        with open(path, 'wb') as f:
            pickle.dump({'refs': self.refs, 'embeddings': self.embeddings}, f)

    def load(self, path: str):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.refs = data.get('refs', [])
        self.embeddings = data.get('embeddings')
        # Саму тяжёлую модель (загрузка весов, ~20 с) грузим здесь же, а не
        # откладываем до первого search_passages() — иначе фоновая
        # предзагрузка (VectorModelManager.preload_model_async, которая как
        # раз вызывает load()) успевает загрузить только лёгкие данные
        # (векторы топиков — это pickle, быстро), а самая долгая часть всё
        # равно происходит на первом реальном поиске, сводя предзагрузку на
        # нет. Модель нужна и для поиска, и для дообучения — не грузить её
        # тут смысла нет в любом случае.
        self._load_encoder()

    def most_similar(self, word: str, topn: int = 15) -> List[Tuple[str, float]]:
        raise NotImplementedError(
            "Поиск по близким словам не применим к этой модели: "
            "paraphrase-multilingual-MiniLM-L12-v2 работает с векторами целых "
            "кусков текста, а не отдельных слов, как FastText. Используйте "
            "search_passages() — прямой поиск похожих по смыслу топиков."
        )

    def search_passages(self, query_text: str, topn: int = 15) -> List[Tuple[str, int, float]]:
        if self.embeddings is None or not self.refs:
            return []
        query_text = (query_text or "").strip()
        if not query_text:
            return []
        import numpy as np
        encoder = self._load_encoder()
        query_vec = self._normalize(encoder.encode([query_text])[0])[0]
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
            'model_name': MODEL_NAME,
            'corpus_size': len(self.refs),
        }
