from .base_engine import SearchEngine
from typing import List, Dict, Any, Optional, Callable
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from utils.text_processing import split_into_sections_by_separator
from utils.query_parser import parse_query_words, compute_matches
import os


class ElasticEngine(SearchEngine):
    def __init__(self, config: dict):
        self.host = config.get('host', 'localhost')
        self.port = int(config.get('port', 9200))
        self.index = config.get('index', 'documents')
        self.client = None
        self.default_separator = config.get('default_separator', 'N1000')
        self._current_index = None
        self.prefix = "ms_"
        self.engine_type = "elasticsearch"
        self._current_file_name = None

    def is_available(self, timeout=2) -> bool:
        try:
            temp_client = Elasticsearch(
                [{'host': self.host, 'port': self.port, 'scheme': 'http'}],
                request_timeout=timeout,
                max_retries=0,
                retry_on_timeout=False
            )
            return temp_client.ping()
        except Exception:
            return False

    def _ensure_connected(self):
        if self.client is None:
            self.connect()
        if self.client is None:
            raise Exception("Не удалось подключиться к Elasticsearch")

    def connect(self, source: str = None, timeout=5) -> bool:
        try:
            if self.client is None:
                self.client = Elasticsearch(
                    [{'host': self.host, 'port': self.port, 'scheme': 'http'}],
                    request_timeout=timeout,
                    max_retries=0,
                    retry_on_timeout=False
                )
            if not self.client.ping():
                self.client = None
                return False
            if source:
                self.index = source
            self._current_index = self.index
            if not self.client.indices.exists(index=self.index):
                self._create_index_with_analyzer(self.index)
            return True
        except Exception as e:
            print(f"Ошибка подключения к Elasticsearch: {e}")
            self.client = None
            self._current_index = None
            return False

    def _create_index_with_analyzer(self, index_name):
        settings = {
            "settings": {
                "number_of_shards": 4,
                "number_of_replicas": 0,
                "index.refresh_interval": "30s",
                "index.max_ngram_diff": 10,
                "analysis": {
                    "filter": {
                        "ru_stop": {"type": "stop", "stopwords": "_russian_"},
                        "ru_stemmer": {"type": "stemmer", "language": "russian"},
                        "edge_ngram_filter": {"type": "edge_ngram", "min_gram": 2, "max_gram": 20},
                        "ngram_filter": {"type": "ngram", "min_gram": 2, "max_gram": 10}
                    },
                    "analyzer": {
                        "russian_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "ru_stop", "ru_stemmer"]
                        },
                        "autocomplete_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "edge_ngram_filter"]
                        },
                        "ngram_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "ngram_filter"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "file_name": {"type": "keyword"},
                    "position": {"type": "text"},
                    "section_text": {
                        "type": "text",
                        "analyzer": "russian_analyzer",
                        "fields": {
                            "autocomplete": {"type": "text", "analyzer": "autocomplete_analyzer",
                                             "search_analyzer": "standard"},
                            "ngram": {"type": "text", "analyzer": "ngram_analyzer", "search_analyzer": "standard"}
                        }
                    }
                }
            }
        }
        self.client.indices.create(index=index_name, body=settings)
        print(f"✅ Индекс {index_name} создан с анализаторами (ngram, edge_ngram)")

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
            self._current_index = None

    def get_section_text(self, rowid: int) -> str:
        self._ensure_connected()
        try:
            doc = self.client.get(index=self.index, id=rowid, _source=["section_text"])
            return doc['_source'].get('section_text', '')
        except NotFoundError:
            return None

    def get_section_info(self, rowid: int) -> Dict[str, Any]:
        self._ensure_connected()
        try:
            doc = self.client.get(index=self.index, id=rowid)
            source = doc['_source']
            return {
                'text': source.get('section_text', ''),
                'file_name': source.get('file_name', ''),
                'position': source.get('position', '0')
            }
        except NotFoundError:
            return None

    def index_file(self, file_path: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self._current_file_name = os.path.basename(file_path)
        encodings = ['utf-8', 'cp1251', 'latin-1', 'koi8-r']
        text = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise Exception("Не удалось прочитать файл")
        result = self.index_text(text, separator, progress_callback)
        self._current_file_name = None
        return result

    def index_text(self, text: str, separator: str = None,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        self._ensure_connected()
        if separator is None:
            separator = self.default_separator

        lines = text.splitlines(keepends=False)
        sections = split_into_sections_by_separator(lines, separator)

        if not sections:
            return 0

        total = len(sections)
        if not self._current_file_name:
            self._current_file_name = 'indexed_file'

        file_name = self._current_file_name

        bulk_body = []
        for i, section in enumerate(sections, 1):
            doc_content = '\n'.join(section['lines'])
            position = str(section.get('start_line', 0))

            bulk_body.append({
                'index': {'_index': self.index, '_id': i}
            })
            bulk_body.append({
                'section_text': doc_content,
                'file_name': file_name,
                'position': position
            })

            if progress_callback and i % 100 == 0:
                progress_callback(i, total)

        if bulk_body:
            success, failed = bulk(self.client, bulk_body, refresh=True, raise_on_error=False)
            if failed > 0:
                print(f"⚠️ {failed} документов не были проиндексированы")
            if progress_callback:
                progress_callback(total, total)
            return success
        return 0

    def list_indices(self) -> List[str]:
        self._ensure_connected()
        try:
            indices = self.client.cat.indices(format='json')
            our_indices = [idx['index'] for idx in indices
                           if idx['index'].startswith(self.prefix) and not idx['index'].startswith('.')]
            return our_indices
        except Exception:
            return []

    def select_index(self, name: str) -> bool:
        self._ensure_connected()
        self.index = name
        self._current_index = name
        if not self.client.indices.exists(index=name):
            try:
                self._create_index_with_analyzer(name)
            except Exception:
                return False
        return True

    def create_index(self, name: str):
        self._ensure_connected()
        index_name = f"{self.prefix}{name.lower()}"
        if self.client.indices.exists(index=index_name):
            self.client.indices.delete(index=index_name)
        self._create_index_with_analyzer(index_name)
        self.index = index_name
        self._current_index = index_name
        return index_name

    def delete_index(self, name: str) -> bool:
        self._ensure_connected()
        try:
            self.client.indices.delete(index=name)
            if self._current_index == name:
                self._current_index = None
                self.index = None
            return True
        except Exception as e:
            print(f"Ошибка удаления индекса {name}: {e}")
            return False

    def search(self, query: str, indices: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        self._ensure_connected()
        query_words_info = parse_query_words(query)
        if not query_words_info:
            return []

        if indices is None:
            indices = [self.index]

        should_clauses = [
            {"match": {"section_text.autocomplete": {"query": query, "boost": 5, "operator": "and"}}},
            {"match": {"section_text": {"query": query, "fuzziness": "AUTO", "boost": 3, "operator": "or"}}},
            {"match_phrase": {"section_text": {"query": query, "slop": 2, "boost": 2}}},
            {"match": {"section_text.ngram": {"query": query, "operator": "and", "boost": 4}}}
        ]
        body = {
            "query": {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
                }
            },
            "size": 1000,
            "_source": ["section_text", "file_name", "position"],
            "sort": [{"_score": {"order": "desc"}}]
        }

        try:
            response = self.client.search(
                index=indices,
                body=body,
                search_type='dfs_query_then_fetch'
            )
            hits = response['hits']['hits']
        except Exception as e:
            print(f"Ошибка поиска в ES: {e}")
            return []

        results = []
        for hit in hits:
            rowid = int(hit['_id'])
            source = hit['_source']
            content = source.get('section_text', '')
            if not content:
                continue
            file_name = source.get('file_name', '')
            position = source.get('position', '0')
            meta = compute_matches(content, query_words_info)
            if meta is None:
                continue
            results.append({
                'rowid': rowid,
                'content': content,
                'meta': meta,
                'file_name': file_name,
                'position': position
            })

        return results