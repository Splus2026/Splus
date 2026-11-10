"""Анализ векторных представлений слов: понижение размерности (PCA, t-SNE), попарная
   близость, иерархическая кластеризация, поиск самой «насыщенной» области, радиальная
   раскладка. numpy/scikit-learn/scipy подключаются внутри функций — модуль
   импортируется быстро и без них.

   Чистые функции — ни одного обращения к интерфейсу. Раньше жили в
   ui/vector_visualization.py; рисует их ui/visualization_manager.py. Старый путь
   импорта (ui.vector_visualization) сохранён для обратной совместимости.

   Понижение размерности по умолчанию — PCA: просто, быстро, детерминированно (t-SNE/UMAP
   дали бы разную картинку для одних и тех же слов при разных запусках)."""



def reduce_to_dims(vectors_dict: dict, n_components: int):
    """vectors_dict — {слово: вектор}. Возвращает (words, coords) в том же
       порядке, что и во входном словаре — coords — список кортежей длины
       n_components (может быть меньше запрошенной, если слов или
       измерений исходных векторов недостаточно)."""
    import numpy as np
    from sklearn.decomposition import PCA

    words = list(vectors_dict.keys())
    if not words:
        return [], []
    matrix = np.array([vectors_dict[w] for w in words], dtype='float64')
    actual_dims = min(n_components, matrix.shape[0] - 1, matrix.shape[1])
    if actual_dims < 1:
        # Слишком мало слов (1-2) — показываем их вдоль одной оси, чем
        # совсем ничего не показывать.
        return words, [(float(i), 0.0, 0.0)[:max(n_components, 1)] for i in range(len(words))]
    pca = PCA(n_components=actual_dims, random_state=0)
    coords = pca.fit_transform(matrix)
    # Дополняем нулями до запрошенного числа измерений, если PCA вернул
    # меньше (например, попросили 3D для всего 2 слов — больше 1 оси
    # содержательно не построить).
    padded = []
    for row in coords:
        row = list(row)
        while len(row) < n_components:
            row.append(0.0)
        padded.append(tuple(row))
    return words, padded


def reduce_to_dims_tsne(vectors_dict: dict, n_components: int):
    """То же самое, что reduce_to_dims(), но через t-SNE вместо PCA — он
       специально настроен на то, чтобы РЯДОМ стоящие в исходном
       многомерном пространстве слова оставались рядом и после сжатия (PCA
       только сохраняет общую дисперсию, не гарантирует сохранение именно
       соседства). Результат может немного отличаться от запуска к
       запуску — в отличие от PCA, тут есть случайность."""
    import numpy as np
    from sklearn.manifold import TSNE

    words = list(vectors_dict.keys())
    if not words:
        return [], []
    matrix = np.array([vectors_dict[w] for w in words], dtype='float64')
    n = matrix.shape[0]
    if n < 4:
        # t-SNE плохо определён на очень малом числе точек (perplexity
        # должен быть меньше числа точек) — честно откатываемся на PCA,
        # чем ломаться или выдавать бессмысленный результат.
        return reduce_to_dims(vectors_dict, n_components)
    perplexity = max(2, min(30, (n - 1) // 3))
    tsne = TSNE(n_components=n_components, random_state=0, perplexity=perplexity,
               init='pca', learning_rate='auto')
    coords = tsne.fit_transform(matrix)
    return words, [tuple(row) for row in coords]


def compute_pairwise_similarity(vectors_dict: dict):
    """Возвращает (words, matrix) — матрицу косинусной близости "слово x
       слово" (симметричная, единицы по диагонали). Ничего не проецируется
       и не огрубляется — точные числа, в отличие от 2D/3D-картинки."""
    import numpy as np

    words = list(vectors_dict.keys())
    if not words:
        return [], None
    matrix = np.array([vectors_dict[w] for w in words], dtype='float64')
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1e-12
    normalized = matrix / norms
    sim = normalized @ normalized.T
    return words, sim


def compute_linkage(vectors_dict: dict):
    """Возвращает (words, Z) — Z — матрица связей для дендрограммы (см.
       scipy.cluster.hierarchy.linkage), построенная по косинусному
       расстоянию между векторами слов, методом Уорда (даёт более
       сбалансированные, легче читаемые деревья, чем "ближний/дальний
       соседи"). None, если слов меньше двух — дендрограмму строить
       не из чего."""
    import numpy as np
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import pdist

    words = list(vectors_dict.keys())
    if len(words) < 2:
        return words, None
    matrix = np.array([vectors_dict[w] for w in words], dtype='float64')
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1e-12
    normalized = matrix / norms
    distances = pdist(normalized, metric='euclidean')
    Z = linkage(distances, method='ward')
    return words, Z


def find_densest_cluster(vectors_dict: dict, k: int = 15, topn: int = 15):
    """Ищет "центр" самой насыщенной понятиями области всего пространства
       (не соседей одного конкретного слова, а анализ всего образца
       словаря целиком, см. VectorModelManager.get_vocabulary_vectors).

       Плотность слова = средняя близость к его k ближайшим соседям (не
       просто "есть ли близкие слова", а насколько тесно они все сбиты в
       кучу вокруг него) — слово с самой высокой плотностью и берётся за
       "центр" найденной области. Дальше оно используется ровно как
       обычное слово запроса — с ним и его topn ближайшими соседями можно
       построить любую из уже существующих визуализаций (2D/3D, столбцы,
       тепловая карта, дендрограмма, граф, сектора) без единого изменения
       в них самих.

       Возвращает (center_word, neighbors) — neighbors: [(слово, близость),
       ...] топ-topn соседей центра, отсортированы по убыванию близости
       (тот же формат, что и обычный список соседей слова запроса). Пустая
       строка и пустой список, если данных недостаточно."""
    import numpy as np

    words, sim = compute_pairwise_similarity(vectors_dict)
    n = len(words)
    if n < k + 1:
        return "", []

    k_eff = min(k, n - 1)
    density = np.zeros(n)
    for i in range(n):
        row = sim[i].copy()
        row[i] = -2.0  # исключаем сравнение слова с самим собой (иначе оно всегда "своя" лучшая пара)
        top_k = np.partition(row, -k_eff)[-k_eff:]
        density[i] = top_k.mean()

    center_idx = int(np.argmax(density))
    center_word = words[center_idx]

    sims_to_center = sim[center_idx].copy()
    sims_to_center[center_idx] = -2.0
    topn_eff = min(topn, n - 1)
    top_idx = np.argpartition(-sims_to_center, topn_eff - 1)[:topn_eff]
    top_idx = top_idx[np.argsort(-sims_to_center[top_idx])]
    neighbors = [(words[i], float(sims_to_center[i])) for i in top_idx]

    return center_word, neighbors


def compute_radial_layout(vectors_dict: dict, query_word: str, n_sectors: int = None):
    """Радиальная раскладка: слово запроса — в центре, остальные слова —
       на расстоянии от центра, обратном их близости к запросу (чем ближе
       по смыслу — тем ближе к центру), а угол определяется тем, в какую
       ГРУППУ (кластер) слово попало среди самих соседей — то есть слова,
       похожие МЕЖДУ СОБОЙ (не только на запрос), собираются в одном
       секторе круга. Возвращает (words, positions) — words[0] всегда
       query_word (в центре), positions — список (x, y) в диапазоне
       примерно [-1, 1]."""
    import numpy as np
    from sklearn.cluster import KMeans

    words = list(vectors_dict.keys())
    if query_word not in vectors_dict or len(words) < 2:
        return words, [(0.0, 0.0) for _ in words]

    others = [w for w in words if w != query_word]
    query_vec = vectors_dict[query_word]

    def cos_sim(a, b):
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-12 or nb < 1e-12:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    similarities = {w: cos_sim(vectors_dict[w], query_vec) for w in others}

    if n_sectors is None:
        n_sectors = max(2, min(6, len(others) // 2)) if len(others) >= 4 else 1

    if len(others) >= n_sectors and n_sectors > 1:
        matrix = np.array([vectors_dict[w] for w in others], dtype='float64')
        n_clusters = min(n_sectors, len(others))
        labels = KMeans(n_clusters=n_clusters, random_state=0, n_init=10).fit_predict(matrix)
    else:
        labels = [0] * len(others)
        n_clusters = 1

    # Кластеры упорядочиваем по средней близости к запросу (по убыванию) —
    # просто для того, чтобы самый релевантный сектор оказался сверху
    # (угол 90°), а не в случайном месте круга.
    cluster_avg_sim = {}
    for w, lbl in zip(others, labels):
        cluster_avg_sim.setdefault(lbl, []).append(similarities[w])
    cluster_order = sorted(cluster_avg_sim.keys(),
                           key=lambda c: -sum(cluster_avg_sim[c]) / len(cluster_avg_sim[c]))
    sector_of_cluster = {c: i for i, c in enumerate(cluster_order)}

    sector_words = {i: [] for i in range(n_clusters)}
    for w, lbl in zip(others, labels):
        sector_words[sector_of_cluster[lbl]].append(w)

    sector_angle = 2 * np.pi / n_clusters
    positions = {query_word: (0.0, 0.0)}
    for sector_idx, sector_ws in sector_words.items():
        # Слова внутри сектора сортируем по близости к запросу — чтобы
        # более похожие оказались ближе к "оси" сектора, менее похожие —
        # к его краю (чисто для порядка, не несёт отдельного смысла).
        sector_ws_sorted = sorted(sector_ws, key=lambda w: -similarities[w])
        count = len(sector_ws_sorted)
        start_angle = sector_idx * sector_angle + sector_angle * 0.15
        end_angle = sector_idx * sector_angle + sector_angle * 0.85
        for k, w in enumerate(sector_ws_sorted):
            angle = start_angle if count == 1 else start_angle + (end_angle - start_angle) * k / (count - 1)
            radius = 1.0 - max(0.0, min(1.0, similarities[w]))
            radius = 0.12 + radius * 0.88  # не даём словам садиться точно в центр, там уже запрос
            positions[w] = (radius * np.cos(angle), radius * np.sin(angle))

    return words, [positions[w] for w in words]
