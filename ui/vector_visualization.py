"""Показ векторной близости слов в браузере: интерактивная 3D-сцена (HTML-страница,
   вращается мышью). Кнопка "3D/2D" у окна "Совпадения" (ui/word_panel.py) доступна только
   когда там показаны слова, близкие по вектору к запросу (FastText); у моделей уровня
   целых предложений (MiniLM/LSA) отдельных векторов слов нет, и кнопка не появляется.

   Алгоритмы вынесены: анализ текста — utils/text_analytics.py, анализ векторов —
   utils/vector_analytics.py. Ниже они реэкспортируются под прежними именами — для
   обратной совместимости (новый код импортирует из utils/ напрямую)."""

import os
import json
import webbrowser

from utils.text_analytics import (  # noqa: F401  (обратная совместимость)
    RUSSIAN_STOPWORDS, build_cooccurrence_graph, compute_textrank, compute_word_frequencies,
    compute_key_word_frequencies, layout_word_cloud,
)
from utils.vector_analytics import (  # noqa: F401  (обратная совместимость)
    reduce_to_dims, reduce_to_dims_tsne, compute_pairwise_similarity, compute_linkage,
    find_densest_cluster, compute_radial_layout,
)


def build_html_3d(words, coords, query_word: str, title: str = "Векторная близость слов") -> str:
    """Строит самодостаточную HTML-страницу с интерактивным 3D-графиком
       (Plotly, подключается с CDN — интернет нужен только чтобы её
       показать, не для остальной программы) — вращается и масштабируется
       мышью прямо в браузере."""
    # float() — явно приводим к обычному Python-числу: PCA отдаёт float64
    # (тот случайно сериализуется в JSON, будучи подклассом обычного float),
    # а t-SNE — float32, который json.dumps НЕ умеет сериализовать вообще
    # (это не подкласс float, в отличие от float64) — отсюда и была ошибка.
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    zs = [float(c[2]) if len(c) > 2 else 0.0 for c in coords]
    colors = ['#c0392b' if w == query_word else '#2a6fbf' for w in words]
    sizes = [10 if w == query_word else 6 for w in words]

    data = {'x': xs, 'y': ys, 'z': zs, 'text': words, 'colors': colors, 'sizes': sizes}
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  body {{ font-family: Arial, sans-serif; margin: 0; background: #fafafa; }}
  h3 {{ text-align: center; margin: 10px; color: #1a4a7a; }}
  #plot {{ width: 100vw; height: 92vh; }}
</style>
</head>
<body>
<h3>{title} — «{query_word}»</h3>
<div id="plot"></div>
<script>
const data = {data_json};
Plotly.newPlot('plot', [{{
    x: data.x, y: data.y, z: data.z,
    mode: 'markers+text',
    type: 'scatter3d',
    text: data.text,
    textposition: 'top center',
    marker: {{ size: data.sizes, color: data.colors }}
}}], {{
    margin: {{l: 0, r: 0, b: 0, t: 0}}
}});
</script>
</body>
</html>"""


def open_3d_visualization(words, coords, query_word: str, output_dir: str) -> str:
    """Пишет HTML-страницу в output_dir и открывает её в браузере по
       умолчанию. Возвращает путь к файлу."""
    html = build_html_3d(words, coords, query_word)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, 'vector_visualization_3d.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open('file://' + os.path.abspath(path))
    return path
