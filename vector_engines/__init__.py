"""Фабрика векторных моделей — по образцу config.create_engine(). Чтобы
   попробовать ещё одну модель после FastText и MiniLM, достаточно:
   1. добавить новый класс-реализацию BaseVectorModel в vector_engines/;
   2. зарегистрировать её здесь: в create_vector_model, AVAILABLE_MODEL_TYPES
      (имя в диалоге выбора при кнопке "Векторы" — см.
      ui/vector_params_dialog.py), MODEL_TYPE_PREFIXES (префикс в списке
      индексов) и MODEL_PARAM_SCHEMAS (какие поля параметров показывать для
      этого типа в диалоге создания модели).
   Остальной код (обучение/поиск/хранение в services/vector_model_manager.py)
   работает с моделью только через интерфейс BaseVectorModel и менять его
   не придётся."""

from .base_vector_model import BaseVectorModel
from .fasttext_model import FastTextModel
from .minilm_model import MiniLMModel
from .lsa_model import LSAModel

# внутренний ключ -> отображаемое имя в диалоге создания модели (кнопка
# "Векторы"). Порядок словаря — порядок в выпадающем списке.
AVAILABLE_MODEL_TYPES = {
    'fasttext': 'FastText',
    'minilm': 'paraphrase-multilingual-MiniLM-L12-v2',
    'lsa': 'LSA (латентно-семантический анализ)',
}

# внутренний ключ -> префикс в списке индексов правого верхнего окна
# (без пробела — пробел добавляется при формировании отображаемого имени).
MODEL_TYPE_PREFIXES = {
    'fasttext': 'FT',
    'minilm': 'PM',
    'lsa': 'LSA',
}

# Модели уровня "целый блок текста", а не отдельных слов — поиск для них
# идёт напрямую по векторам топиков (search_passages), а не через список
# близких слов (most_similar), и обучение использует общую подготовку
# "окон смысла" (build_minilm_training_data — несмотря на название,
# годится для любой модели из этого множества, не только MiniLM). Чтобы
# добавить ещё одну такую модель — добавить её ключ сюда, остальной код
# (VectorModelManager, SearchController, диалог) уже написан по этому
# множеству, а не по жёсткой проверке на 'minilm'.
CHUNK_BASED_MODEL_TYPES = {'minilm', 'lsa'}

# внутренний ключ -> список полей параметров для диалога создания модели:
# (ключ_параметра, подпись, тип). тип 'int' — обычное числовое поле;
# 'choice:вариант1,вариант2' — выпадающий список (сейчас только у
# FastText — sg: skip-gram/CBOW). Список — только числовые/choice поля;
# порядок — порядок полей в форме.
MODEL_PARAM_SCHEMAS = {
    'fasttext': [
        ('vector_size', 'Размер вектора (vector_size)', 'int'),
        ('window', 'Окно контекста в словах (window)', 'int'),
        ('min_count', 'Мин. число вхождений слова (min_count)', 'int'),
        ('epochs', 'Число эпох обучения (epochs)', 'int'),
        ('workers', 'Потоков обучения (workers)', 'int'),
        ('sg', 'Алгоритм (sg)', 'choice:skip-gram,CBOW'),
    ],
    'minilm': [
        ('batch_size', 'Размер пакета при кодировании (batch_size)', 'int'),
    ],
    'lsa': [
        ('dim', 'Размерность пространства (dim)', 'int'),
        ('min_df', 'Мин. число блоков со словом (min_df)', 'int'),
    ],
}


def create_vector_model(model_type: str) -> BaseVectorModel:
    if model_type == 'fasttext':
        return FastTextModel()
    if model_type == 'minilm':
        return MiniLMModel()
    if model_type == 'lsa':
        return LSAModel()
    raise ValueError(f"Неизвестный тип векторной модели: {model_type}")
