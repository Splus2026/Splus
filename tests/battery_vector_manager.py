import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import re, types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import services.vector_model_manager as V
from docx import Document

# Менеджер векторных моделей: ключи и реестр, подготовка обучающих данных, обучение и дообучение, удаление, получение соседей.
# Сами модели (gensim, sentence-transformers) НЕ используются: вместо них подставная модель, которая записывает обращения. Движок
# Manticore для MiniLM — подставной. Разбиение на предложения подменено детерминированным (не зависит от наличия nltk).
WORK = env.tmpdir('vecmgr_'); os.chdir(WORK)
LOG = []
ns = types.SimpleNamespace
def rec(name, ret=None): return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]
def calls(name): return [c for c in LOG if c[0] == name]
V.split_sentences = lambda text: [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
V.save_config = rec('save_config')
PREFIX = V.MODEL_TYPE_PREFIXES
FT, ML = 'fasttext', 'minilm'

class Vec:
    def __init__(self, values): self.values = values
    def tolist(self): return list(self.values)
class FakeModel:
    script = {}
    def __init__(self, mtype):
        self.mtype = mtype; self.data = None; self.embeddings = None; self.neighbors = {}; self.freq = {}
        self.model = ns(wv=ns(key_to_index={'слово': 0}), )
    def get_params(self): return {'window': 5, 'vector_size': 100}
    def train(self, sentences, cancel_check=None, **params):
        LOG.append(('model.train', len(sentences), tuple(sorted(params.items()))))
        if FakeModel.script.get('cancel'): raise V.TrainingCancelled()
        if FakeModel.script.get('import_error'): raise ImportError('нужен gensim')
        if FakeModel.script.get('train_error'): raise RuntimeError('сбой обучения')
        self.data = repr(sentences[0]) if sentences else ''
        self.embeddings = [Vec([0.5, 0.25])] * len(sentences)
    def continue_train(self, sentences, cancel_check=None):
        LOG.append(('model.continue_train', len(sentences)))
        if FakeModel.script.get('cancel'): raise V.TrainingCancelled()
        if FakeModel.script.get('train_error'): raise RuntimeError('сбой дообучения')
        self.embeddings = list(self.embeddings or []) + [Vec([0.5, 0.25])] * len(sentences)
    def save(self, path):
        LOG.append(('model.save', path))
        if FakeModel.script.get('save_error'): raise OSError('диск полон')
        open(path, 'w', encoding='utf-8').write(self.data or '')
    def load(self, path):
        LOG.append(('model.load', path))
        if FakeModel.script.get('load_error'): raise OSError('файл повреждён')
        self.data = open(path, encoding='utf-8').read()
    def most_similar(self, word, topn=10):
        LOG.append(('most_similar', word, topn))
        if FakeModel.script.get('similar_error'): raise RuntimeError('нет слова')
        return list(self.neighbors.get(word, []))[:topn]
    def search_passages(self, query, topn=15):
        LOG.append(('search_passages', query, topn))
        if FakeModel.script.get('passages_error'): raise FakeModel.script['passages_error']
        return [('idx', 1, 0.9)]
    def get_vector(self, word):
        if word == 'нет': raise KeyError(word)
        return [1.0, float(len(word))]
    def get_vocabulary_words(self): return list(self.freq)
    def get_word_frequency(self, word): return self.freq[word]
V.create_vector_model = lambda t: FakeModel(t)

class Engine:
    engine_type = 'manticore'
    def __init__(self, indices=None, sections=None, fail=None):
        self.indices = set(indices or []); self.sections = {k: list(v) for k, v in (sections or {}).items()}; self.fail = fail or {}; self.next_rowid = 1000
    def _maybe(self, op):
        if op in self.fail: raise RuntimeError(self.fail[op])
    def list_indices(self): self._maybe('list_indices'); return list(self.indices)
    def get_all_sections(self, name): self._maybe('get_all_sections'); return list(self.sections.get(name, []))
    def ensure_chunk_index(self, name, drop_if_exists=False):
        LOG.append(('ensure_chunk_index', name, drop_if_exists)); self._maybe('ensure_chunk_index')
        if drop_if_exists or name not in self.indices: self.sections[name] = []
        self.indices.add(name)
    def insert_chunks(self, name, chunks, file_name):
        self._maybe('insert_chunks'); added = 0
        for c in chunks: self.next_rowid += 1; self.sections.setdefault(name, []).append((self.next_rowid, c, file_name)); added += 1
        return added
    def delete_index(self, name):
        LOG.append(('delete_index', name)); self._maybe('delete_index'); self.indices.discard(name); self.sections.pop(name, None); return True

def make(config=None, engine=None):
    LOG.clear(); FakeModel.script = {}
    cfg = {'vector_models_dir': 'models'}; cfg.update(config or {})
    return V.VectorModelManager(engine or Engine(), cfg, rec('status')), cfg
def write(name, text='Альфа слово. Бета слово.'): open(name, 'w', encoding='utf-8').write(text); return name
def write_docx(name, paragraphs):
    d = Document(); [d.add_paragraph(t) for t in paragraphs]; d.save(name); return name

# ===================== A. чистые функции =====================
dd = V.dedupe_word_variations
kept, removed = dd([('равновесие', 0.9), ('равновесием', 0.8), ('покой', 0.7), ('равновесию', 0.6), ('душа', 0.5)])
check('dedupe_word_variations: по одному, самому рейтинговому, представителю группы словоформ; считает отсеянные', [w for w, _s in kept] == ['равновесие', 'покой', 'душа'] and removed == 2, str((kept, removed)))
check('dedupe_word_variations: пустой список, список без словоформ — без изменений', dd([]) == ([], 0) and dd([('абв', 1), ('где', 2)]) == ([('абв', 1), ('где', 2)], 0))
check('dedupe_word_variations: порядок и близость сохраняются', [s for _w, s in dd([('равновесие', 0.9), ('равновесием', 0.8), ('покой', 0.7)])[0]] == [0.9, 0.7])
sp = V.suggest_vector_params; MB = 1024 * 1024
check('suggest_vector_params (FastText): ступени по размеру 10/50/150 МБ — 100/150/200/300 измерений', [sp(FT, int(m * MB))['vector_size'] for m in (1, 9.99, 10, 49, 50, 149, 150, 800)] == [100, 100, 150, 150, 200, 200, 300, 300])
check('suggest_vector_params: на больших объёмах меньше эпох и выше порог редких слов; sg=0 на самой большой ступени', sp(FT, 200 * MB) == {'vector_size': 300, 'window': 5, 'min_count': 5, 'epochs': 5, 'sg': 0, 'workers': 4} and sp(FT, 1 * MB)['sg'] == 1 and sp(FT, 1 * MB)['epochs'] == 20)
check('suggest_vector_params: «планируемый объём» поднимает ступень, если больше текущего, и игнорируется, если меньше', sp(FT, 1 * MB, planned_total_mb=60)['vector_size'] == 200 and sp(FT, 60 * MB, planned_total_mb=1)['vector_size'] == 200 and sp(FT, 0)['vector_size'] == 100)
check('suggest_vector_params: MiniLM — только размер пакета', sp(ML, 999 * MB) == {'batch_size': 32})
check('suggest_vector_params: LSA — ступени размерности и min_df, планируемый объём учитывается', [sp('lsa', int(m * MB)) for m in (1, 20, 100, 500)] == [{'dim': 100, 'min_df': 2}, {'dim': 200, 'min_df': 3}, {'dim': 320, 'min_df': 4}, {'dim': 400, 'min_df': 5}] and sp('lsa', MB, planned_total_mb=60)['dim'] == 320)
check('suggest_vector_params: неизвестный тип — как FastText', sp('чужой', 20 * MB) == sp(FT, 20 * MB))
got = sp(FT, MB); got['vector_size'] = 1
check('suggest_vector_params возвращает копию: правка результата не портит таблицу ступеней', sp(FT, MB)['vector_size'] == 100)
check('VectorModelManager.suggest_params делегирует', make()[0].suggest_params(FT, 20 * MB) == sp(FT, 20 * MB))

# ===================== B. ключи и реестр =====================
vm, cfg = make({'vector_models': {'FT Книга': ('', FT, os.path.join('models', 'ft_kniga.model')), 'PM Книга': ('', ML, os.path.join('models', 'pm_kniga.model'))},
                'vector_semantic_window': {'PM Книга': {'mode': 'sentence_window', 'indices': ['model_pm_kniga']}, 'PM Другая': {'mode': 'existing_index', 'indices': ['real_a', 'real_b']}}})
check('_normalize_key снимает суффикс « [модель]» (только на конце)', vm._normalize_key('FT Книга [модель]') == 'FT Книга' and vm._normalize_key('FT Книга') == 'FT Книга' and vm._normalize_key('FT [модель] Книга') == 'FT [модель] Книга')
check('list_display_keys: каждая модель из конфигурации с суффиксом « [модель]»', vm.list_display_keys() == ['FT Книга [модель]', 'PM Книга [модель]'])
check('is_vector_key: и «сырой» ключ, и строка из списка индексов; чужая строка — нет', vm.is_vector_key('FT Книга') and vm.is_vector_key('FT Книга [модель]') and not vm.is_vector_key('книга') and not vm.is_vector_key('FT Нет'))
check('get_model_type: по ключу (с суффиксом тоже); нет модели — None', vm.get_model_type('PM Книга [модель]') == ML and vm.get_model_type('FT Книга') == FT and vm.get_model_type('FT Нет') is None)
check('get_associated_indices: сохранённые при обучении; для FastText и неизвестной модели — пустой список; результат — копия', vm.get_associated_indices('PM Книга') == ['model_pm_kniga'] and vm.get_associated_indices('PM Другая') == ['real_a', 'real_b'] and vm.get_associated_indices('FT Книга') == [] and vm.get_associated_indices('нет') == [])
vm.get_associated_indices('PM Книга').append('х'); check('…правка результата не меняет конфигурацию', vm.get_associated_indices('PM Книга') == ['model_pm_kniga'])
check('get_auxiliary_indices: только вспомогательные индексы «окон смысла» (режим не existing_index) по ВСЕМ моделям', vm.get_auxiliary_indices() == {'model_pm_kniga'})
check('is_loaded / is_preloading: по умолчанию нет, ключ с суффиксом нормализуется', vm.is_loaded('FT Книга') is False and vm.is_preloading('FT Книга [модель]') is False and (vm._loaded_models.update({'FT Книга': 1}), vm.is_loaded('FT Книга [модель]'))[1] is True)
names_ = {'a.txt': 'Альфа', 'b.txt': 'Бэ'}
ck = vm.compute_display_key
check('compute_display_key: префикс типа, названия файлов через « + »', ck(FT, ['a.txt', 'b.txt'], names_) == f"{PREFIX[FT]} Альфа + Бэ" and ck(ML, ['a.txt'], names_) == f"{PREFIX[ML]} Альфа")
check('compute_display_key: уточнение имени — в скобках; файла нет в словаре — имя файла как есть; неизвестный тип — префикс FastText',
      ck(FT, ['a.txt'], names_, name_suffix='вариант 2') == f"{PREFIX[FT]} Альфа (вариант 2)" and ck(FT, [os.path.join('DB', 'x.txt')], {}) == f"{PREFIX[FT]} x.txt" and ck('чужой', ['a.txt'], names_) == f"{PREFIX['fasttext'] if 'fasttext' in PREFIX else 'FT'} Альфа" or ck('чужой', ['a.txt'], names_) == 'FT Альфа')

# ===================== C. обучающие данные FastText («круги связи») =====================
TEXT = 'а1 б1. а2 б2. а3 б3. а4 б4.'
vm, cfg = make({'vector_sentences_before': 1, 'vector_sentences_after': 1}); write('круги.txt', TEXT)
wins, err = vm._build_training_sentences(['круги.txt'])
check('круги связи 1/1: окно — предложение плюс по одному соседнему с каждой стороны, слова в нижнем регистре, без знаков',
      err is None and wins == [['а1', 'б1', 'а2', 'б2'], ['а1', 'б1', 'а2', 'б2', 'а3', 'б3'], ['а2', 'б2', 'а3', 'б3', 'а4', 'б4'], ['а3', 'б3', 'а4', 'б4']], str(wins))
vm, cfg = make({'vector_sentences_before': 0, 'vector_sentences_after': 0}); check('круги связи 0/0: окно — одно предложение', vm._build_training_sentences(['круги.txt'])[0] == [['а1', 'б1'], ['а2', 'б2'], ['а3', 'б3'], ['а4', 'б4']])
vm, cfg = make(); check('круги связи по умолчанию — 7 до и 10 после (всё предложение в окне)', len(vm._build_training_sentences(['круги.txt'])[0][0]) == 8)
write('абзацы.txt', 'а1 б1. а2 б2.\n\nв1 г1. в2 г2.\n\n\n\nд1.')
vm, cfg = make({'vector_sentences_before': 5, 'vector_sentences_after': 5}); wins, err = vm._build_training_sentences(['абзацы.txt'])
check('.txt: окно не выходит за границы абзаца (пустая строка между абзацами), пустые абзацы пропускаются', [len(w) for w in wins] == [4, 4, 4, 4, 1], str(wins))
write('регистр.txt', 'Слово, ЁЖ и «Слово»! 12 abc.'); vm, cfg = make(); check('токены: буквы (включая «ё»), цифры, латиница; пунктуация отбрасывается; нижний регистр', vm._build_training_sentences(['регистр.txt'])[0][0] == ['слово', 'ёж', 'и', 'слово', '12', 'abc'])
write('два1.txt', 'а1.'); write('два2.txt', 'б1.'); vm, cfg = make({'vector_sentences_before': 3, 'vector_sentences_after': 3}); check('несколько файлов: окна каждого файла отдельно, не склеиваются', vm._build_training_sentences(['два1.txt', 'два2.txt'])[0] == [['а1'], ['б1']])
write('пусто.txt', '  \n\n  '); vm, cfg = make(); wins, err = vm._build_training_sentences(['пусто.txt'])
check('пустой файл: ни одного окна, понятное сообщение', wins is None and err == 'Не удалось выделить предложения для обучения — файл(ы) пусты?')
wins, err = vm._build_training_sentences(['круги.txt', 'нет_такого.txt'])
check('файл не читается: ошибка с путём, обучение не начинается', wins is None and err.startswith('Ошибка чтения файла нет_такого.txt:'), str(err))
write_docx('доки.docx', ['а1 б1. а2 б2.', 'в1 г1. в2 г2.', 'д1.'])
vm, cfg = make({'vector_sentences_before': 5, 'vector_sentences_after': 5}); wins, err = vm._build_training_sentences(['доки.docx'])
check('.docx: окно тоже не выходит за границы абзаца (абзац документа — отдельная строка)', [len(w) for w in wins] == [4, 4, 4, 4, 1], f'длины окон {[len(w) for w in wins]}: окна переходят через абзацы')

# ===================== D. MiniLM: готовые топики и «окна смысла» =====================
SECTIONS = {'kniga': [(1, 'текст раз', 'kniga.txt'), (2, 'текст два', 'kniga.txt')], 'tabl': [(7, 'строка', 'tabl.txt')]}
vm, cfg = make(engine=Engine(['kniga', 'tabl'], SECTIONS))
secs, err = vm._build_minilm_sections(['kniga.txt', os.path.join('DB', 'tabl.txt')])
check('MiniLM, готовые топики: (индекс, rowid, текст) по файлам в порядке выбора; индексы определяются по безопасному имени файла', err is None and secs == [('kniga', 1, 'текст раз'), ('kniga', 2, 'текст два'), ('tabl', 7, 'строка')], str(secs))
secs, err = vm._build_minilm_sections(['kniga.txt', 'не_готов.txt', 'ещё.txt'])
check('MiniLM: непроиндексированные файлы названы в ошибке с подсказкой про «В индекс» (тихого пропуска нет)', secs is None and 'не_готов.txt, ещё.txt' in err and 'В индекс' in err, str(err))
vm, cfg = make(engine=Engine(['kniga'], {'kniga': []})); secs, err = vm._build_minilm_sections(['kniga.txt']); check('MiniLM: в индексе нет топиков — понятное сообщение', secs is None and err == 'В выбранных индексах не нашлось ни одного топика.')
vm, cfg = make(engine=Engine(fail={'list_indices': 'нет связи'})); check('MiniLM: движок не отвечает — «Не удалось получить список индексов: …»', vm._build_minilm_sections(['a.txt']) == (None, 'Не удалось получить список индексов: нет связи'))
fts = Engine(); fts.engine_type = 'fts5'; vm, cfg = make(engine=fts); check('MiniLM: только для Manticore', vm._build_minilm_sections(['a.txt'])[1] == 'Обучение MiniLM поддерживается только для движка Manticore.' and vm._build_minilm_semantic_chunks(['a.txt'], 'paragraphs', {}, 'model_x')[1] == 'Обучение MiniLM поддерживается только для движка Manticore.')
write('смысл.txt', 'Первый абзац один. Первый абзац два.\n\nВторой абзац.\n\nТретий абзац.')
vm, cfg = make(engine=Engine()); secs, err = vm._build_minilm_semantic_chunks(['смысл.txt'], 'paragraphs', {}, 'model_x')
check('«окна смысла», абзацы: вспомогательный индекс создаётся заново (drop_if_exists), блоки вставляются, возвращаются (индекс, rowid, текст)', err is None and calls('ensure_chunk_index') == [('ensure_chunk_index', 'model_x', True)] and [s[0] for s in secs] == ['model_x'] * len(secs) and len(secs) >= 2, str(secs))
vm, cfg = make(engine=Engine()); secs, err = vm._build_minilm_semantic_chunks(['смысл.txt'], 'sentence_window', {'sentences_before': 0, 'sentences_after': 0}, 'model_x')
check('режим «окно предложений»: параметры блока берутся из ответа диалога', err is None and len(secs) == 4, str(len(secs) if secs else err))
vm, cfg = make({'vector_sentences_before': 0, 'vector_sentences_after': 0}, engine=Engine()); secs0, _ = vm._build_minilm_semantic_chunks(['смысл.txt'], 'sentence_window', {}, 'model_x')
vm, cfg = make({'vector_sentences_before': 7, 'vector_sentences_after': 10}, engine=Engine()); secs7, _ = vm._build_minilm_semantic_chunks(['смысл.txt'], 'sentence_window', {}, 'model_x')
check('режим «окно предложений»: параметров нет — берутся «круги связи» из настроек программы (при 0/0 блок — одно предложение, при 7/10 — длиннее)', len(secs0) == len(secs7) and max(len(s[2]) for s in secs0) < max(len(s[2]) for s in secs7), f'{max(len(s[2]) for s in secs0)} против {max(len(s[2]) for s in secs7)}')
vm, cfg = make(engine=Engine()); secs, err = vm._build_minilm_semantic_chunks(['смысл.txt'], 'char_overlap', {'target_chars': 30, 'overlap_chars': 5}, 'model_x'); check('режим «нарезка с перекрытием»: размер и перекрытие из параметров', err is None and len(secs) >= 2 and all(len(s[2]) <= 40 for s in secs), str([len(s[2]) for s in secs] if secs else err))
vm, cfg = make(engine=Engine()); check('неизвестный режим — «Неизвестный режим "окна смысла"»', vm._build_minilm_semantic_chunks(['смысл.txt'], 'нет', {}, 'model_x')[1] == 'Неизвестный режим "окна смысла": нет')
eng = Engine(); vm, cfg = make(engine=eng); vm._build_minilm_semantic_chunks(['смысл.txt'], 'paragraphs', {}, 'model_x'); first_count = len(eng.sections['model_x']); LOG.clear()
write('новый.txt', 'Совсем новый абзац.'); secs, err = vm._build_minilm_semantic_chunks(['новый.txt'], 'paragraphs', {}, 'model_x', append=True)
check('дообучение: индекс НЕ пересоздаётся (drop_if_exists=False), возвращаются только НОВЫЕ блоки, старые остаются в индексе', calls('ensure_chunk_index') == [('ensure_chunk_index', 'model_x', False)] and len(secs) == 1 and secs[0][2] == 'Совсем новый абзац.' and len(eng.sections['model_x']) == first_count + 1, str(secs))
write('пустой_смысл.txt', ''); vm, cfg = make(engine=Engine()); check('ни одного блока — «Не удалось выделить ни одного смыслового блока»', vm._build_minilm_semantic_chunks(['пустой_смысл.txt'], 'paragraphs', {}, 'model_x')[1] == 'Не удалось выделить ни одного смыслового блока из выбранных файлов.')
for op, text in (('ensure_chunk_index', 'Не удалось создать вспомогательный индекс «model_x»: сбой'), ('insert_chunks', 'Не удалось вставить блоки в «model_x»: сбой'), ('get_all_sections', 'Не удалось прочитать вспомогательный индекс «model_x»: сбой')):
    vm, cfg = make(engine=Engine(fail={op: 'сбой'})); check(f'сбой движка ({op}): сообщение «{text[:42]}…», обучение не начинается', vm._build_minilm_semantic_chunks(['смысл.txt'], 'paragraphs', {}, 'model_x') == (None, text))
vm, cfg = make(engine=Engine()); check('файл не читается — «Не удалось прочитать файл имя: …»', vm._build_minilm_semantic_chunks(['нет.txt'], 'paragraphs', {}, 'model_x')[1].startswith('Не удалось прочитать файл нет.txt:'))
eng = Engine(['kniga'], SECTIONS); vm, cfg = make(engine=eng)
sec, assoc, err = vm.build_minilm_training_data(['kniga.txt'], {'mode': 'existing_index'}, 'PM Книга')
check('build_minilm_training_data, готовый индекс: топики и отсортированный список индексов без повторов', err is None and assoc == ['kniga'] and len(sec) == 2)
sec, assoc, err = vm.build_minilm_training_data(['смысл.txt'], {'mode': 'paragraphs', 'params': {}}, 'PM Книга')
check('build_minilm_training_data, «окно смысла»: вспомогательный индекс называется model_<безопасное имя ключа>', err is None and assoc == ['model_pm_kniga'] and eng.indices >= {'model_pm_kniga'}, str(assoc))
check('build_minilm_training_data: ошибка сборки возвращается третьим значением', make(engine=Engine())[0].build_minilm_training_data(['смысл.txt'], {'mode': 'нет'}, 'PM К')[2] == 'Неизвестный режим "окна смысла": нет')
# ===================== E. обучение «с нуля» =====================
SAFE = lambda name: V.make_safe_index_name(name, 'manticore')[0]
class WV:
    key_to_index = {'слово': 0}
    def __getitem__(self, word): return Vec([0.1234567, 0.5])
write('альфа.txt', 'Альфа слово. Бета слово.'); write('бета.txt', 'Бета слово. Гамма слово.')
IDX_A = V.make_safe_index_name('альфа.txt', 'manticore')[1]   # индекс, который код ожидает для файла «альфа.txt» (имя транслитерируется)
def train(vm, files=('альфа.txt',), names=None, **kw):
    names = names or {f: os.path.splitext(f)[0].capitalize() for f in files}
    LOG.clear(); return vm.train(list(files), names, **kw)
vm, cfg = make(); r = vm.train([], {}); check('train: нет файлов — «Не выбрано ни одного файла.», модель не создаётся', r == (False, 'Не выбрано ни одного файла.') and not calls('model.train'))
r = vm.train(['a.txt', 'таблица.XLSX'], {}); check('train: Excel не годится для обучения (регистр расширения не важен)', r[0] is False and 'только для текстовых книг' in r[1] and not calls('model.train'))
vm, cfg = make(); prog = []; r = train(vm, model_type=FT, model_params={'vector_size': 50}, progress_callback=prog.append)
key = f"{PREFIX[FT]} Альфа"; path = os.path.join('models', f"{PREFIX[FT].lower()}_{SAFE('Альфа')}.model")
check('train FastText: успех, сообщение с числом обучающих окон', r == (True, f"Модель «{key}» обучена на 2 обучающих окнах."), str(r))
check('модель обучается на окнах и переданных параметрах; файл сохранён в папку моделей под безопасным именем (префикс типа в нижнем регистре); папка создана', calls('model.train') == [('model.train', 2, (('vector_size', 50),))] and calls('model.save') == [('model.save', path)] and os.path.exists(path), str(LOG))
check('реестр: vector_models[ключ] = («», тип, путь), vector_model_params — копия параметров; для FastText окна смысла нет; конфигурация сохранена один раз; модель в кеше',
      cfg['vector_models'][key] == ('', FT, path) and cfg['vector_model_params'][key] == {'vector_size': 50} and 'vector_semantic_window' not in cfg and len(calls('save_config')) == 1 and vm.is_loaded(key))
hist = open(os.path.join('models', f"{PREFIX[FT].lower()}_{SAFE('Альфа')}_history.txt"), encoding='utf-8').read()
check('история: строка «дата — обучение: названия файлов» и подробный лог с параметрами и окнами', re.search(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d — обучение: Альфа', hist) and 'Параметры модели:' in hist and 'Обучающих окон всего: 2' in hist and 'Первые 2 обучающих окон (из 2)' in hist, hist[:200])
check('прогресс: 0,1 -> 0,4 -> 0,9 -> 1,0', prog == [0.1, 0.4, 0.9, 1.0], str(prog))
vm, cfg = make({'vector_model_type': ML}, engine=Engine([IDX_A], {IDX_A: [(1, 'т', 'альфа.txt')]}))
r = train(vm, model_params={'batch_size': 8}); check('тип не задан — берётся настройка vector_model_type', f"Модель «{PREFIX[ML]} Альфа»" in r[1] and r[1].endswith('на 1 топиках.'), str(r))
vm, cfg = make(); train(vm, model_type=FT); check('параметры не заданы — рекомендованные по размеру файлов (маленькие файлы — первая ступень)', calls('model.train')[0][2] == tuple(sorted(V.suggest_vector_params(FT, os.path.getsize('альфа.txt')).items())))
vm, cfg = make(); r = train(vm, model_type=FT, model_params={}, name_suffix='вариант 2'); key2 = f"{PREFIX[FT]} Альфа (вариант 2)"
check('уточнение имени: другой ключ и другой файл модели — две модели на одном файле не затирают друг друга', key2 in cfg['vector_models'] and cfg['vector_models'][key2][2].endswith(f"{PREFIX[FT].lower()}_{SAFE('Альфа (вариант 2)')}.model") and os.path.exists(cfg['vector_models'][key2][2]), str(cfg['vector_models']))
write('пустой.txt', ''); vm, cfg = make(); r = train(vm, ['пустой.txt'], model_type=FT, model_params={})
check('нет обучающих окон: сообщение, модель не создаётся, ничего не регистрируется', r[0] is False and 'пусты' in r[1] and not calls('model.train') and not calls('save_config') and 'vector_models' not in cfg)
for script, expected in (({'cancel': True}, 'Обучение прервано пользователем.'), ({'import_error': True}, 'нужен gensim'), ({'train_error': True}, 'Ошибка обучения модели: сбой обучения'), ({'save_error': True}, 'Ошибка сохранения модели на диск: диск полон')):
    vm, cfg = make(); LOG.clear(); FakeModel.script = script; r = vm.train(['альфа.txt'], {'альфа.txt': 'Альфа'}, model_type=FT, model_params={})
    check(f'сбой обучения ({list(script)[0]}): сообщение «{expected[:34]}…»; в реестре и в сохранённой конфигурации ничего не появляется', r == (False, expected) and 'vector_models' not in cfg and not calls('save_config'), str(r))
# модель с таким ключом уже есть
write('старый.model', 'старые данные'); write('старый_history.txt', 'история'); 
vm, cfg = make({'vector_models': {key: ('', FT, 'старый.model')}}); vm._loaded_models[key] = 'старая в памяти'
train(vm, model_type=FT, model_params={})
check('повторное создание модели с тем же ключом: старые файл модели и история удалены, кеш обновлён, в реестре — новый путь', not os.path.exists('старый.model') and not os.path.exists('старый_history.txt') and cfg['vector_models'][key][2] == path and vm._loaded_models[key] != 'старая в памяти')
write('тот_же.model', 'старые данные'); vm, cfg = make({'vector_models': {key: ('', FT, path)}}); open(path, 'w').write('старое'); train(vm, model_type=FT, model_params={})
check('тот же путь файла: файл перезаписывается, а не удаляется', os.path.exists(path) and open(path, encoding='utf-8').read() != 'старое')
# MiniLM
eng = Engine([IDX_A], {IDX_A: [(1, 'блок раз', 'альфа.txt'), (2, 'блок два', 'альфа.txt')]}); vm, cfg = make(engine=eng); r = train(vm, model_type=ML, model_params={'batch_size': 32})
mkey = f"{PREFIX[ML]} Альфа"
check('MiniLM, готовый индекс (по умолчанию): обучение на топиках, окно смысла в реестре — режим и отсортированные индексы', r == (True, f"Модель «{mkey}» обучена на 2 топиках.") and cfg['vector_semantic_window'][mkey] == {'mode': 'existing_index', 'indices': [IDX_A]}, str(cfg.get('vector_semantic_window')))
check('MiniLM: в подробном журнале — блоки с индексом, rowid и текстом', 'Смысловых блоков всего: 2' in open(os.path.join('models', f"{PREFIX[ML].lower()}_{SAFE('Альфа')}_history.txt"), encoding='utf-8').read())
write('окна.txt', 'Раз два. Три четыре.\n\nПять шесть.'); eng = Engine(); vm, cfg = make(engine=eng)
r = train(vm, ['окна.txt'], {'окна.txt': 'Окна'}, model_type=ML, model_params={}, semantic_window={'mode': 'paragraphs', 'params': {}})
aux = f"model_{SAFE(f'{PREFIX[ML]} Окна')}"
check('MiniLM, «окно смысла»: вспомогательный индекс model_<имя> создан, модель знает его как свой единственный индекс; параметры режима записаны вместе с режимом', r[0] is True and cfg['vector_semantic_window'][f"{PREFIX[ML]} Окна"] == {'mode': 'paragraphs', 'indices': [aux]} and aux in eng.indices, str(cfg.get('vector_semantic_window')))
eng = Engine(); vm, cfg = make(engine=eng); train(vm, ['окна.txt'], {'окна.txt': 'Окна'}, model_type=ML, model_params={}, semantic_window={'mode': 'sentence_window', 'params': {'sentences_before': 1, 'sentences_after': 2}})
check('MiniLM: параметры режима попадают в запись окна смысла', cfg['vector_semantic_window'][f"{PREFIX[ML]} Окна"] == {'mode': 'sentence_window', 'indices': [aux], 'sentences_before': 1, 'sentences_after': 2})
eng = Engine(); vm, cfg = make(engine=eng); LOG.clear(); FakeModel.script = {'cancel': True}; r = vm.train(['окна.txt'], {'окна.txt': 'Окна'}, model_type=ML, model_params={}, semantic_window={'mode': 'paragraphs', 'params': {}})
check('прерывание (Esc) при «окне смысла»: созданный вспомогательный индекс удаляется (осиротевшим не остаётся), модель не регистрируется', r == (False, 'Обучение прервано пользователем.') and aux not in eng.indices and 'vector_models' not in cfg and ('delete_index', aux) in LOG)
eng = Engine([IDX_A], {IDX_A: [(1, 'т', 'альфа.txt')]}); vm, cfg = make(engine=eng); LOG.clear(); FakeModel.script = {'cancel': True}; vm.train(['альфа.txt'], {'альфа.txt': 'Альфа'}, model_type=ML, model_params={})
check('прерывание при готовом индексе: реальные файловые индексы не трогаются', IDX_A in eng.indices and not calls('delete_index'))
vm, cfg = make(engine=Engine()); LOG.clear(); vm._cleanup_aux_index_on_cancel(FT, ['model_x'], None); vm._cleanup_aux_index_on_cancel(ML, [], {'mode': 'paragraphs'})
check('очистка при прерывании: для FastText и без индексов ничего не делает', not calls('delete_index'))
bad = Engine(['model_x', 'model_y'], fail={'delete_index': 'занят'}); vm, cfg = make(engine=bad); vm._cleanup_aux_index_on_cancel(ML, ['model_x', 'model_y'], {'mode': 'paragraphs'})
check('очистка при прерывании: сбой удаления одного индекса не мешает остальным и не выходит наружу', len(calls('delete_index')) == 2)
# перезапись и прерывание: честная фиксация нынешнего ограничения
eng = Engine(); vm, cfg = make(engine=eng); train(vm, ['окна.txt'], {'окна.txt': 'Окна'}, model_type=ML, model_params={}, semantic_window={'mode': 'paragraphs', 'params': {}}); okey = f"{PREFIX[ML]} Окна"
FakeModel.script = {'cancel': True}; vm.train(['окна.txt'], {'окна.txt': 'Окна'}, model_type=ML, model_params={}, semantic_window={'mode': 'paragraphs', 'params': {}})
check('(ограничение) перезапись модели «окна смысла» с прерыванием: старая модель остаётся в реестре, но её вспомогательный индекс уже удалён (пересоздаётся ДО обучения) — старая модель теряет работоспособность', okey in cfg['vector_models'] and aux not in eng.indices, str(eng.indices))
# коллизии имён
write('к1.txt', 'Первая книга слово. Ещё.'); write('к2.txt', 'Вторая книга слово. Ещё.')
vm, cfg = make(); train(vm, ['к1.txt'], {'к1.txt': 'Книга 1'}, model_type=FT, model_params={}); train(vm, ['к2.txt'], {'к2.txt': 'Книга-1'}, model_type=FT, model_params={})
paths = [v[2] for v in cfg['vector_models'].values()]; contents = [open(p, encoding='utf-8').read() for p in paths]
check('две модели с названиями, дающими одно безопасное имя («Книга 1» и «Книга-1»), получают РАЗНЫЕ файлы: вторая не затирает первую', len(set(paths)) == 2 and len(set(contents)) == 2, f'пути {paths}, содержимое {contents}')
eng = Engine(); vm, cfg = make(engine=eng); sw = {'mode': 'paragraphs', 'params': {}}
train(vm, ['к1.txt'], {'к1.txt': 'Книга 1'}, model_type=ML, model_params={}, semantic_window=sw); first_aux = cfg['vector_semantic_window'][f"{PREFIX[ML]} Книга 1"]['indices'][0]; first_rows = len(eng.sections[first_aux])
train(vm, ['к2.txt'], {'к2.txt': 'Книга-1'}, model_type=ML, model_params={}, semantic_window=sw); second_aux = cfg['vector_semantic_window'][f"{PREFIX[ML]} Книга-1"]['indices'][0]
check('у моделей «окна смысла» с похожими названиями РАЗНЫЕ вспомогательные индексы: создание второй не стирает индекс первой', first_aux != second_aux and first_aux in eng.indices and len(eng.sections[first_aux]) == first_rows, f'индексы {first_aux!r} и {second_aux!r}; строк в первом: {len(eng.sections.get(first_aux, []))} (было {first_rows})')
# ===================== F. дообучение =====================
def trained(config=None, engine=None, model_type=FT, files=('альфа.txt',), names=None, semantic_window=None, params=None):
    vm, cfg = make(config, engine); names = names or {f: os.path.splitext(f)[0].capitalize() for f in files}
    vm.train(list(files), names, model_type=model_type, model_params=params if params is not None else ({'batch_size': 32} if model_type == ML else {}), semantic_window=semantic_window)
    LOG.clear(); return vm, cfg
vm, cfg = make(); r = vm.continue_train('FT Нет', ['альфа.txt'], {}); check('continue_train: модели нет в конфигурации — «не найдена в конфигурации»', r == (False, 'Модель «FT Нет» не найдена в конфигурации.'))
vm, cfg = trained(); key = f"{PREFIX[FT]} Альфа"
r = vm.continue_train(key, ['таблица.xlsx'], {}); check('continue_train: Excel не годится', r[0] is False and 'только для текстовых книг' in r[1])
vm._loaded_models.clear(); FakeModel.script = {'load_error': True}; r = vm.continue_train(key, ['бета.txt'], {}); check('continue_train: модель не загрузилась — «Не удалось загрузить модель … для дообучения»', r == (False, f'Не удалось загрузить модель «{key}» для дообучения.') and any('Не удалось загрузить векторную модель' in c[1] for c in calls('status')), str(r))
vm, cfg = trained(); prog = []; LOG.clear(); r = vm.continue_train(key + ' [модель]', ['альфа.txt', 'бета.txt'], {'альфа.txt': 'Альфа', 'бета.txt': 'Бэ'}, progress_callback=prog.append)
check('дообучение FastText: ключ из списка (с суффиксом «[модель]») принимается; итог перечисляет файлы; прогресс 0,1 -> 0,4 -> 0,9 -> 1,0', r == (True, f'Модель «{key}» дообучена на: Альфа, Бэ.') and prog == [0.1, 0.4, 0.9, 1.0], str(r))
check('дообучение: модель сохраняется ПО ПРЕЖНЕМУ пути, остаётся в кеше; для FastText конфигурация не перезаписывается', calls('model.save') == [('model.save', cfg['vector_models'][key][2])] and vm.is_loaded(key) and not calls('save_config'))
hist = open(vm._history_path(cfg['vector_models'][key][2]), encoding='utf-8').read(); check('история: дописана строка «дообучение: …»', '— обучение: Альфа' in hist and '— дообучение: Альфа, Бэ' in hist)
for script, expected in (({'cancel': True}, 'Дообучение прервано пользователем. Модель осталась в прежнем состоянии; чтобы всё же добавить эти файлы — запустите дообучение ещё раз.'), ({'train_error': True}, 'Ошибка дообучения модели: сбой дообучения'), ({'save_error': True}, 'Ошибка сохранения модели на диск: диск полон')):
    vm, cfg = trained(); FakeModel.script = script; r = vm.continue_train(key, ['бета.txt'], {}); check(f'дообучение, сбой ({list(script)[0]}): «{expected[:36]}…»', r == (False, expected), str(r))
vm, cfg = trained(); r = vm.continue_train(key, ['пустой.txt'], {}); check('дообучение: нет предложений — сообщение, модель не дообучается', r[0] is False and 'пусты' in r[1] and not calls('model.continue_train'))
eng = Engine([IDX_A, 'beta_idx'], {IDX_A: [(1, 'раз', 'альфа.txt')], 'beta_idx': [(5, 'два', 'бета.txt')]})
vm, cfg = trained(engine=eng, model_type=ML); mkey = f"{PREFIX[ML]} Альфа"; make_idx_b = V.make_safe_index_name('бета.txt', 'manticore')[1]; eng.indices.add(make_idx_b); eng.sections[make_idx_b] = [(5, 'два', 'бета.txt')]
r = vm.continue_train(mkey, ['бета.txt'], {'бета.txt': 'Бета'}); check('дообучение MiniLM (готовый индекс): список индексов модели ДОПОЛНЯЕТСЯ новыми, а не затирается; конфигурация сохраняется', r[0] is True and cfg['vector_semantic_window'][mkey] == {'mode': 'existing_index', 'indices': sorted({IDX_A, make_idx_b})} and calls('save_config'), str(cfg.get('vector_semantic_window')))
eng = Engine(); vm, cfg = trained(engine=eng, model_type=ML, files=('окна.txt',), names={'окна.txt': 'Окна'}, semantic_window={'mode': 'char_overlap', 'params': {'target_chars': 30, 'overlap_chars': 5}}); okey = f"{PREFIX[ML]} Окна"; aux = cfg['vector_semantic_window'][okey]['indices'][0]; before = len(eng.sections[aux])
write('добавка.txt', 'Новый текст для дообучения модели окон смысла и ещё немного слов.'); LOG.clear(); r = vm.continue_train(okey, ['добавка.txt'], {'добавка.txt': 'Добавка'})
check('дообучение MiniLM («окно смысла»): режим и параметры берутся из сохранённого, вспомогательный индекс НЕ пересоздаётся, добавляются только новые блоки', r[0] is True and ('ensure_chunk_index', aux, False) in LOG and len(eng.sections[aux]) > before and all(len(row[1]) <= 40 for row in eng.sections[aux][before:]), str(LOG[:4]))
eng = Engine(); vm, cfg = trained(engine=eng, model_type=ML, files=('окна.txt',), names={'окна.txt': 'Окна'}, semantic_window={'mode': 'paragraphs', 'params': {}}); okey = f"{PREFIX[ML]} Окна"
cfg['vector_semantic_window'][okey]['indices'] = ['model_старый_вариант']; eng.indices.add('model_старый_вариант'); eng.sections['model_старый_вариант'] = [(1, 'раньше', 'окна.txt')]; LOG.clear(); vm.continue_train(okey, ['добавка.txt'], {'добавка.txt': 'Добавка'})
check('дообучение «окна смысла» кладёт новые блоки в ТОТ вспомогательный индекс, который сохранён за моделью (а не в заново вычисленный по имени — у моделей, созданных старой версией, имена могли отличаться)',
            ('ensure_chunk_index', 'model_старый_вариант', False) in LOG and len(eng.sections['model_старый_вариант']) > 1, f'обращения к индексам: {[c for c in LOG if c[0] == "ensure_chunk_index"]}')

# ===================== G. удаление =====================
vm, cfg = make(); check('delete_model: нет такой модели — сообщение, конфигурация не сохраняется', vm.delete_model('FT Нет') == (False, 'Модель «FT Нет» не найдена в конфигурации.') and not calls('save_config'))
vm, cfg = trained(); key = f"{PREFIX[FT]} Альфа"; mpath = cfg['vector_models'][key][2]; hpath = vm._history_path(mpath)
check('до удаления файлы модели и истории на месте', os.path.exists(mpath) and os.path.exists(hpath))
r = vm.delete_model(key + ' [модель]')
check('delete_model: удалены файл модели и история, записи из vector_models/params/окон, кеш; конфигурация сохранена; сообщение «удалена.»', r == (True, f'Модель «{key}» удалена.') and not os.path.exists(mpath) and not os.path.exists(hpath) and key not in cfg['vector_models'] and key not in cfg['vector_model_params'] and not vm.is_loaded(key) and len(calls('save_config')) == 1, str(r))
eng = Engine(); vm, cfg = trained(engine=eng, model_type=ML, files=('окна.txt',), names={'окна.txt': 'Окна'}, semantic_window={'mode': 'paragraphs', 'params': {}}); okey = f"{PREFIX[ML]} Окна"; aux = cfg['vector_semantic_window'][okey]['indices'][0]
r = vm.delete_model(okey); check('«окно смысла»: вспомогательный индекс удаляется вместе с моделью', r[0] is True and aux not in eng.indices and okey not in cfg['vector_semantic_window'])
eng = Engine([IDX_A], {IDX_A: [(1, 'т', 'альфа.txt')]}); vm, cfg = trained(engine=eng, model_type=ML); mkey = f"{PREFIX[ML]} Альфа"; LOG.clear(); r = vm.delete_model(mkey)
check('готовый индекс (режим 1): реальные файловые индексы НЕ удаляются (ими пользуется и обычный поиск)', r[0] is True and IDX_A in eng.indices and not calls('delete_index'))
eng = Engine(fail={'delete_index': 'занят'}); vm, cfg = trained(engine=eng, model_type=ML, files=('окна.txt',), names={'окна.txt': 'Окна'}, semantic_window={'mode': 'paragraphs', 'params': {}}); LOG.clear(); r = vm.delete_model(okey)
check('ошибка удаления индекса не прерывает остальное: модель убрана из списка, сообщение «удалена из списка, но с ошибками: …»', r[0] is False and r[1].startswith(f'Модель «{okey}» удалена из списка, но с ошибками: вспомогательный индекс model_') and okey not in cfg['vector_models'], str(r))
vm, cfg = make({'vector_models': {'FT Старая': ('легаси_индекс', FT, '')}}); eng2 = vm.engine; r = vm.delete_model('FT Старая')
check('старая запись формата «индекс в третьем поле»: этот индекс удаляется; пустой путь файла не мешает', r[0] is True and calls('delete_index') == [('delete_index', 'легаси_индекс')] and 'FT Старая' not in cfg['vector_models'])

# ===================== H. загрузка модели и получение данных =====================
vm, cfg = trained(); key = f"{PREFIX[FT]} Альфа"; vm._loaded_models.clear(); LOG.clear()
m1 = vm._get_model(key + ' [модель]'); m2 = vm._get_model(key)
check('_get_model: загружает с диска ОДИН раз и дальше отдаёт из кеша (ключ с суффиксом «[модель]» — тот же)', m1 is m2 and len(calls('model.load')) == 1 and vm.is_loaded(key))
check('_get_model: модели нет в конфигурации — None, без исключения', make()[0]._get_model('FT Нет') is None)
vm, cfg = trained(); vm._loaded_models.clear(); FakeModel.script = {'load_error': True}; LOG.clear()
check('_get_model: файл не загрузился — None и сообщение в статусной строке', vm._get_model(key) is None and any('Не удалось загрузить векторную модель' in c[1] and 'файл повреждён' in c[1] for c in calls('status')))
class Sync:
    started = 0
    def __init__(self, target=None, daemon=None): self.target = target
    def start(self): Sync.started += 1; self.target()
vm, cfg = trained(); vm._loaded_models.clear(); V.threading = types.SimpleNamespace(Thread=Sync, Lock=__import__('threading').Lock); seen = []
orig_load = FakeModel.load; FakeModel.load = lambda self, path: (seen.append(vm.is_preloading(key)), orig_load(self, path))[1]
vm.preload_model_async(key + ' [модель]')
check('preload_model_async: загрузка в фоне, на время загрузки модель числится «грузящейся», потом отметка снимается и модель в кеше', seen == [True] and not vm.is_preloading(key) and vm.is_loaded(key) and Sync.started == 1, str(seen))
vm.preload_model_async(key); check('preload_model_async: уже загружена — поток не запускается', Sync.started == 1)
vm._loaded_models.clear(); vm._preloading.add(key); vm.preload_model_async(key); check('preload_model_async: уже грузится — второй поток не запускается', Sync.started == 1)
FakeModel.load = orig_load; import threading as _th; V.threading = _th
vm, cfg = trained(); key = f"{PREFIX[FT]} Альфа"; m = vm._get_model(key); m.neighbors = {'слово': [('слова', 0.9), ('словом', 0.8), ('текст', 0.7)]}
check('get_neighbors: слово приводится к нижнему регистру и обрезается; число соседей по умолчанию — настройка vector_model_topn (15)', vm.get_neighbors(key, '  СЛОВО ') == [('слова', 0.9), ('словом', 0.8), ('текст', 0.7)] and calls('most_similar')[-1] == ('most_similar', 'слово', 15), str(calls('most_similar')))
check('get_neighbors: явное число соседей', len(vm.get_neighbors(key, 'слово', topn=2)) == 2)
vm.config_dict['vector_model_topn'] = 1; check('get_neighbors: число соседей берётся из настройки vector_model_topn', len(vm.get_neighbors(key, 'слово')) == 1)
check('get_neighbors: пустое слово — пустой список, модель не опрашивается; нет модели — пустой список', (LOG.clear(), vm.get_neighbors(key, '   '))[1] == [] and not calls('most_similar') and make()[0].get_neighbors('FT Нет', 'слово') == [])
FakeModel.script = {'similar_error': True}; LOG.clear(); check('get_neighbors: ошибка модели — пустой список и «❌ Ошибка векторного поиска» в статусе', vm.get_neighbors(key, 'слово') == [] and any(c[1].startswith('❌ Ошибка векторного поиска') for c in calls('status')))
FakeModel.script = {}; check('get_neighbors: слова нет в модели (пусто) — пустой список без исключения', vm.get_neighbors(key, 'неизвестное') == [])
m.neighbors = {'слово': [('равновесие', 0.9), ('равновесием', 0.8), ('равновесию', 0.7), ('покой', 0.6), ('душа', 0.5), ('мир', 0.4)]}
LOG.clear(); got = vm.get_neighbors_deduplicated(key, 'слово', target_count=2)
check('get_neighbors_deduplicated: без словоформ, нужное число уникальных; число запрашиваемых соседей растёт вдвое (2 -> 4), пока не хватит', [w for w, _s in got] == ['равновесие', 'покой'] and [c[2] for c in calls('most_similar')] == [2, 4], f'{got}; запросы {[c[2] for c in calls("most_similar")]}')
m.neighbors = {'слово': [('равновесие', 0.9), ('равновесием', 0.8)]}; LOG.clear(); got = vm.get_neighbors_deduplicated(key, 'слово', target_count=5)
check('get_neighbors_deduplicated: у модели больше нет слов — останавливается, отдаёт сколько есть', [w for w, _s in got] == ['равновесие'] and [c[2] for c in calls('most_similar')] == [5], str([c[2] for c in calls('most_similar')]))
m.neighbors = {'слово': [(f'слово{chr(0x430 + i)}{chr(0x430 + i)}{chr(0x430 + i)}', 1 - i / 100) for i in range(40)]}
LOG.clear(); vm.get_neighbors_deduplicated(key, 'слово', target_count=30); check('get_neighbors_deduplicated: не больше 5 попыток', len(calls('most_similar')) <= 5)
vm.config_dict['vector_model_topn'] = 3; m.neighbors = {'слово': [('а', .9), ('б', .8), ('в', .7), ('г', .6)]}; check('get_neighbors_deduplicated: число по умолчанию — vector_model_topn', len(vm.get_neighbors_deduplicated(key, 'слово')) == 3)
vm, cfg = trained(engine=Engine([IDX_A], {IDX_A: [(1, 'т', 'альфа.txt')]}), model_type=ML); mkey = f"{PREFIX[ML]} Альфа"; LOG.clear()
check('search_semantic: результат модели; число по умолчанию — vector_model_topn (15), явное число передаётся', vm.search_semantic(mkey, 'смысл') == [('idx', 1, 0.9)] and calls('search_passages')[-1] == ('search_passages', 'смысл', 15) and (vm.search_semantic(mkey, 'смысл', 4), calls('search_passages')[-1][2])[1] == 4)
vm.config_dict['vector_model_topn'] = 7; LOG.clear(); vm.search_semantic(mkey, 'смысл'); check('search_semantic: число топиков берётся из настройки vector_model_topn', calls('search_passages')[-1] == ('search_passages', 'смысл', 7), str(calls('search_passages')[-1])); vm.config_dict.pop('vector_model_topn')
check('search_semantic: нет модели — пустой список', make()[0].search_semantic('PM Нет', 'смысл') == [])
FakeModel.script = {'passages_error': NotImplementedError('не поддерживается')}; LOG.clear(); check('search_semantic: «не поддерживается» — пустой список и сообщение в статусе', vm.search_semantic(mkey, 'смысл') == [] and any(c[1] == '❌ не поддерживается' for c in calls('status')))
FakeModel.script = {'passages_error': RuntimeError('сбой')}; LOG.clear(); check('search_semantic: ошибка — пустой список и «❌ Ошибка семантического поиска: …»', vm.search_semantic(mkey, 'смысл') == [] and any(c[1] == '❌ Ошибка семантического поиска: сбой' for c in calls('status')))
FakeModel.script = {}
vm, cfg = trained(); key = f"{PREFIX[FT]} Альфа"
check('get_word_vectors: слова, для которых вектор получить нельзя, пропускаются, остальные возвращаются; нет модели — пустой словарь', vm.get_word_vectors(key, ['слово', 'нет', 'текст']) == {'слово': [1.0, 5.0], 'текст': [1.0, 5.0]} and make()[0].get_word_vectors('FT Нет', ['слово']) == {})
m = vm._get_model(key); m.freq = {'слово': 50, 'и': 90, 'редкое': 1, 'текст': 30, 'нет': 40}
check('get_vocabulary_vectors: короткие слова и слишком редкие отсеиваются, остальные — по убыванию частоты; слово без вектора пропускается', list(vm.get_vocabulary_vectors(key)) == ['слово', 'текст'], str(list(vm.get_vocabulary_vectors(key))))
check('get_vocabulary_vectors: max_words оставляет самые частые; пороги настраиваются', list(vm.get_vocabulary_vectors(key, max_words=1)) == ['слово'] and list(vm.get_vocabulary_vectors(key, min_word_length=1, min_frequency=1, max_words=10)) == ['и', 'слово', 'текст', 'редкое'])
m.freq = {'равновесие': 5, 'равновесием': 2, 'покой': 9, 'ко': 1}
check('get_vocabulary_vectors с ключевыми понятиями: только слова словаря и их вариации, пороги длины и редкости не применяются', list(vm.get_vocabulary_vectors(key, key_words=['равновесие', 'ко'])) == ['равновесие', 'равновесием', 'ко'], str(list(vm.get_vocabulary_vectors(key, key_words=['равновесие', 'ко']))))
vm._loaded_models[key] = ns(get_vector=lambda w: [1.0])   # модель без метода словаря
check('get_vocabulary_vectors: модель без метода словаря или нет модели — пустой словарь', make()[0].get_vocabulary_vectors('FT Нет') == {} and vm.get_vocabulary_vectors(key) == {})

# ===================== I. история и подробные журналы =====================
vm, cfg = make(); check('_history_path: рядом с файлом модели, имя с «_history.txt» вместо расширения', vm._history_path(os.path.join('models', 'ft_x.model')) == os.path.join('models', 'ft_x_history.txt'))
hp = os.path.join(WORK, 'история.model'); vm._append_history(hp, 'обучение', ['a.txt', 'b.txt'], {'a.txt': 'Альфа'}, detailed_log=['строка 1', 'строка 2'])
txt = open(vm._history_path(hp), encoding='utf-8').read()
check('_append_history: «дата — действие: названия (из словаря или имя файла)», подробный лог и разделитель из «=»', re.search(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d — обучение: Альфа, b.txt\nстрока 1\nстрока 2\n\n=+\n\n$', txt), repr(txt))
vm._append_history(hp, 'дообучение', ['a.txt'], {}); check('_append_history: повторный вызов дописывает, а не затирает', txt in open(vm._history_path(hp), encoding='utf-8').read() and open(vm._history_path(hp), encoding='utf-8').read().count('—') >= 2)
vm._append_history(os.path.join(WORK, 'нет_папки', 'x.model'), 'обучение', ['a.txt'], {}); check('_append_history: нельзя записать — предупреждение в статусе, исключения нет', any(c[1].startswith('⚠️ Не удалось записать историю обучения модели') for c in calls('status')))
model = FakeModel(FT); model.model = ns(wv=WV())
sents = [['а', 'б', 'в'], ['г'], ['д', 'е']] + [['ж'] * 2 for _ in range(10)]
lg = vm._build_detailed_training_log(model, sents, {'model_type': FT, 'vector_sentences_before': 7}); joined = '\n'.join(lg)
check('журнал FastText: параметры (модели и добавленные), число окон, размер словаря, первые 7 окон и 7 окон из середины', 'window = 5' in joined and 'model_type = fasttext' in joined and 'Обучающих окон всего: 13' in joined and 'Слов в словаре после обучения: 1' in joined and 'Первые 7 обучающих окон (из 13)' in joined and '6 окон в районе середины обучения (окна 8-13 из 13)' in joined, joined[:300])
check('журнал FastText: окно, пары (слово, контекст) в пределах window и итоговый вектор слова', 'Окно №1: [\'а\', \'б\', \'в\']' in joined and '(а, б), (а, в), (б, а), (б, в), (в, а), (в, б)' in joined and 'а: [0.1235, 0.5000]' in joined and 'нет пар — окно из одного слова' in joined)
lg_small = vm._build_detailed_training_log(model, [['а']], {}); check('журнал FastText: мало окон — раздела «из середины» нет', not any('середины' in l for l in lg_small))
bad_model = FakeModel(FT); lg_bad = '\n'.join(vm._build_detailed_training_log(bad_model, [['а']], {})); check('журнал FastText: вектор слова недоступен — пометка, а не падение', '(вектор недоступен)' in lg_bad)
mm = FakeModel(ML); mm.embeddings = [Vec([float(i), 0.5]) for i in range(10)]; secs = [('idx', i, 'текст блока %d' % i) for i in range(10)]
lgm = '\n'.join(vm._build_minilm_detailed_log(mm, secs, {'model_type': ML}))
check('журнал MiniLM: число блоков, первые 7 и блоки из середины с индексом, rowid, текстом и итоговым вектором', 'Смысловых блоков всего: 10' in lgm and 'Первые 7 смысловых блоков (из 10)' in lgm and 'Блок №1 (индекс «idx», rowid 0)' in lgm and 'Итоговый вектор: [0.0000, 0.5000]' in lgm and '3 блоков в районе середины (блоки 8-10 из 10)' in lgm, lgm[:260])
lgo = '\n'.join(vm._build_minilm_detailed_log(mm, secs[:3], {}, embedding_offset=5)); check('журнал MiniLM: при дообучении вектор берётся со смещением (новые блоки — в конце массива)', 'Итоговый вектор: [5.0000, 0.5000]' in lgo)
long_secs = [('idx', 1, 'я' * 500)]; check('журнал MiniLM: длинный текст блока обрезается до 400 символов с «…»', ('я' * 400 + '…') in '\n'.join(vm._build_minilm_detailed_log(mm, long_secs, {})) and 'я' * 401 not in '\n'.join(vm._build_minilm_detailed_log(mm, long_secs, {})))
# ===================== J. имена при нескольких «близнецах» =====================
write('к3.txt', 'Третья книга слово. Ещё.')
vm, cfg = make(); train(vm, ['к1.txt'], {'к1.txt': 'Книга 1'}, model_type=FT, model_params={}); train(vm, ['к2.txt'], {'к2.txt': 'Книга-1'}, model_type=FT, model_params={}); train(vm, ['к3.txt'], {'к3.txt': 'Книга_1'}, model_type=FT, model_params={})
paths = sorted(v[2] for v in cfg['vector_models'].values()); base_path = os.path.join('models', f"{PREFIX[FT].lower()}_{SAFE('Книга 1')}.model"); stem, ext = os.path.splitext(base_path)
check('три «близнеца»: файлы — основное имя, затем _2 и _3, содержимое у каждого своё', paths == sorted([base_path, f'{stem}_2{ext}', f'{stem}_3{ext}']) and len({open(p, encoding='utf-8').read() for p in paths}) == 3, str(paths))
k1, k2 = f"{PREFIX[FT]} Книга 1", f"{PREFIX[FT]} Книга-1"; p1, p2 = cfg['vector_models'][k1][2], cfg['vector_models'][k2][2]
vm.delete_model(k2); check('удаление одного «близнеца» не трогает файл другого', os.path.exists(p1) and not os.path.exists(p2) and k1 in cfg['vector_models'])
train(vm, ['к2.txt'], {'к2.txt': 'Книга-1'}, model_type=FT, model_params={}); check('создание «близнеца» заново занимает освободившееся имя, а не копит номера', cfg['vector_models'][k2][2] in (f'{stem}_2{ext}', f'{stem}_3{ext}') and cfg['vector_models'][k2][2] != p1)
before = dict(cfg['vector_models']); train(vm, ['к1.txt'], {'к1.txt': 'Книга 1'}, model_type=FT, model_params={})
check('повторное обучение ТОЙ ЖЕ модели (тот же ключ) путь не меняет — файл перезаписывается', cfg['vector_models'][k1][2] == before[k1][2] == base_path)
vm2, cfg2 = make({'vector_models': {'FT А': ('', FT, os.path.join('models', 'ft_x.model')), 'FT Б': ('', FT, '')}})
check('_free_model_path: свободный путь — как есть; занятый другой моделью — с номером; записи с пустым путём путь не занимают', vm2._free_model_path(os.path.join('models', 'ft_y.model'), 'FT В') == os.path.join('models', 'ft_y.model') and vm2._free_model_path(os.path.join('models', 'ft_x.model'), 'FT В') == os.path.join('models', 'ft_x_2.model') and vm2._free_model_path(os.path.join('models', 'ft_x.model'), 'FT А') == os.path.join('models', 'ft_x.model') and vm2._free_model_path('', 'FT В') == '')
vm3, cfg3 = make({'vector_semantic_window': {'PM А': {'mode': 'paragraphs', 'indices': ['model_pm_x']}, 'PM Б': {'mode': 'paragraphs', 'indices': ['model_pm_x_2']}}})
check('_aux_index_name_for: имя свободно — model_<безопасное имя ключа>', vm3._aux_index_name_for('PM Новая', False) == 'model_pm_novaya', vm3._aux_index_name_for('PM Новая', False))
check('_aux_index_name_for: занято и основное имя, и _2 (другими моделями) — берётся _3', vm3._aux_index_name_for('PM X', False) == 'model_pm_x_3', vm3._aux_index_name_for('PM X', False))
vm3.config_dict['vector_semantic_window']['PM Новая'] = {'mode': 'paragraphs', 'indices': ['model_старое_имя']}
check('_aux_index_name_for: дообучение берёт сохранённое имя; новое создание не считает занятым индекс этой же модели', vm3._aux_index_name_for('PM Новая', True) == 'model_старое_имя' and vm3._aux_index_name_for('PM Новая', False) == 'model_pm_novaya' and vm3._aux_index_name_for('PM Без записи', True) == 'model_pm_bez_zapisi', str(vm3._aux_index_name_for('PM Без записи', True)))
cfg4 = {'vector_semantic_window': {'PM А': {'mode': 'paragraphs', 'indices': [f"model_{SAFE('PM Книга 1')}"]}}}; vm4, _ = make(cfg4)
check('_aux_index_name_for: «PM Книга-1» при занятом «PM Книга 1» получает имя с номером _2', vm4._aux_index_name_for('PM Книга-1', False) == f"model_{SAFE('PM Книга-1')}_2", vm4._aux_index_name_for('PM Книга-1', False))
check('_indices_of_other_models: индексы всех моделей, кроме указанной', vm3._indices_of_other_models('PM А') == {'model_pm_x_2', 'model_старое_имя'})
check('_unsupported_files_error: пустой список и Excel; для дообучения пустой список допустим', V.VectorModelManager._unsupported_files_error([]) == 'Не выбрано ни одного файла.' and V.VectorModelManager._unsupported_files_error([], require_files=False) is None and V.VectorModelManager._unsupported_files_error(['a.txt']) is None and 'Excel' in V.VectorModelManager._unsupported_files_error(['a.XLSX']))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
