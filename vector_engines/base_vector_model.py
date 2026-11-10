"""Абстрактный интерфейс векторной (word-embedding) модели — по образцу
   engines/base_engine.py. Позволяет позже попробовать другую модель (не
   FastText), просто добавив новый класс-реализацию в vector_engines/ и
   зарегистрировав её в create_vector_model() — остальной код (обучение,
   поиск, хранение) трогать не придётся.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple


class TrainingCancelled(Exception):
    """Поднимается реализациями train()/continue_train(), когда обучение
       было прервано пользователем — см. параметр cancel_check ниже и
       VectorModelManager (проверка нажатия Esc)."""
    pass


class BaseVectorModel(ABC):
    model_type = "base"  # переопределяется в каждой реализации

    @abstractmethod
    def train(self, sentences, cancel_check=None, **params):
        """Обучает модель с нуля на подготовленных данных. Форма данных
           зависит от типа модели (готовит VectorModelManager):
           - FastText — список списков слов-токенов (окна вокруг
             предложений, см. _build_training_sentences);
           - MiniLM — список готовых топиков (index_name, rowid, text) из
             уже существующих индексов Manticore, см.
             _build_minilm_sections — эта модель кодирует целые куски
             текста, а не учится на пословных окнах контекста.

           cancel_check — необязательный вызываемый без аргументов,
           возвращающий True, если пользователь запросил прерывание
           (нажал Esc) — реализация должна проверять его периодически (не
           реже раза в минуту) и поднимать TrainingCancelled, если он
           вернул True, а не игнорировать прерывание."""
        raise NotImplementedError

    @abstractmethod
    def continue_train(self, sentences, cancel_check=None, **params):
        """Дообучает уже обученную/загруженную модель на новых данных той
           же формы, что и train() — расширяя её, а не начиная с нуля."""
        raise NotImplementedError

    @abstractmethod
    def save(self, path: str):
        raise NotImplementedError

    @abstractmethod
    def load(self, path: str):
        raise NotImplementedError

    @abstractmethod
    def most_similar(self, word: str, topn: int = 15) -> List[Tuple[str, float]]:
        """Возвращает до topn ближайших по вектору слов и их близость
           (0..1, чем больше — тем ближе), отсортированные по убыванию.
           Осмысленно только для word-embedding моделей (FastText) — для
           моделей уровня предложений (MiniLM) нет "словаря близких слов",
           реализация должна поднимать NotImplementedError с понятным
           объяснением (см. search_passages — правильная замена для них)."""
        raise NotImplementedError

    @abstractmethod
    def search_passages(self, query_text: str, topn: int = 15) -> List[Tuple[str, int, float]]:
        """Прямой семантический поиск: кодирует query_text и сравнивает с
           векторами уже закодированных при обучении топиков, возвращая до
           topn самых близких как (index_name, rowid, близость 0..1),
           отсортированных по убыванию близости. Это замена most_similar()
           для моделей уровня целых предложений (MiniLM), у которых нет
           смысла в "близких словах" — они сравнивают вектор запроса
           напрямую с вектором готового куска текста. Для word-embedding
           моделей (FastText) не применимо — реализация должна поднимать
           NotImplementedError с понятным объяснением."""
        raise NotImplementedError

    @abstractmethod
    def has_word(self, word: str) -> bool:
        """Есть ли слово (хотя бы приблизительно, через n-граммы) в модели."""
        raise NotImplementedError

    @abstractmethod
    def get_params(self) -> dict:
        """Возвращает реально использованные при обучении параметры модели
           (не то, что мы ЗАПРОСИЛИ, а то, что модель у себя сохранила) —
           нужно для подробного лога обучения (история модели)."""
        raise NotImplementedError

    def get_vector(self, word: str):
        """Возвращает координаты вектора слова (не близость к чему-то, а
           сами координаты) — нужно для визуализации (кнопка "3D/2D" у окна
           "Совпадения"). НЕ абстрактный: осмыслен только для
           word-embedding моделей (FastText) — у моделей уровня целых
           предложений (MiniLM/LSA) нет отдельных векторов слов, поэтому
           реализация по умолчанию поднимает NotImplementedError."""
        raise NotImplementedError(
            "У этой модели нет отдельных векторов слов — она работает с "
            "векторами целых кусков текста."
        )
