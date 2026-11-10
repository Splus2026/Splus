from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable


class SearchEngine(ABC):
    """Абстрактный класс для всех поисковых движков."""

    @abstractmethod
    def connect(self, source: str) -> bool:
        pass

    @abstractmethod
    def search(self, query: str, indices: Optional[List[str]] = None,
               min_word_length: int = 3, unique_word_rating: bool = False) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def index_file(self, file_path: str, separator: str,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        pass

    @abstractmethod
    def index_text(self, text: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def list_indices(self) -> List[str]:
        pass

    @abstractmethod
    def select_index(self, name: str) -> bool:
        pass

    @abstractmethod
    def create_index(self, name: str):
        pass

    def get_section_text(self, rowid: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete_index(self, name: str) -> bool:
        pass

    def get_section_info(self, rowid: int) -> Dict[str, Any]:
        """
        Получает информацию о топике: имя файла, позицию, текст.
        Возвращает словарь с ключами: 'file_name', 'position', 'text'
        """
        raise NotImplementedError