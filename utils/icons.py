"""Пиктограммы кнопок, нарисованные кодом (без файлов-картинок и Pillow)."""
import math


def refresh_icon_rows(size=26, bg='#6a4a8a', fg='#ffffff', supersample=4):
    """Пиктограмма «обновить» — как в Синеве Mobile (RefreshIcon): дуга почти в полный круг (от 25° до 320°
       по часовой стрелке от «севера») со стрелкой на конце. Возвращает строки пикселей '#rrggbb', уже
       смешанных с фоном кнопки (прозрачность Tk не сглаживает края)."""
    def rgb(color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    bg_c, fg_c = rgb(bg), rgb(fg)
    cx = cy = size / 2.0
    r = size * 0.36
    half = r * 0.17                          # половина толщины линии
    a0, a1 = 25.0, 320.0
    t = math.radians(a1)
    ex, ey = cx + r * math.sin(t), cy + r * math.cos(t)       # конец дуги (y вверх)
    dx, dy = math.cos(t), -math.sin(t)                          # направление движения
    nx, ny = -dy, dx
    h, w = r * 0.75, r * 0.6
    tri = [(ex + dx * h, ey + dy * h), (ex + nx * w, ey + ny * w), (ex - nx * w, ey - ny * w)]

    def in_tri(px, py):
        (x1, y1), (x2, y2), (x3, y3) = tri
        d1 = (px - x2) * (y1 - y2) - (x1 - x2) * (py - y2)
        d2 = (px - x3) * (y2 - y3) - (x2 - x3) * (py - y3)
        d3 = (px - x1) * (y3 - y1) - (x3 - x1) * (py - y1)
        neg = d1 < 0 or d2 < 0 or d3 < 0
        pos = d1 > 0 or d2 > 0 or d3 > 0
        return not (neg and pos)

    def covered(px, py):
        ddx, ddy = px - cx, py - cy
        dist = math.hypot(ddx, ddy)
        if abs(dist - r) <= half:
            angle = math.degrees(math.atan2(ddx, ddy)) % 360.0   # от севера по часовой
            if a0 <= angle <= a1:
                return True
        return in_tri(px, py)

    rows, n = [], supersample
    for iy in range(size):
        row = []
        for ix in range(size):
            hits = 0
            for sy in range(n):
                for sx in range(n):
                    px = ix + (sx + 0.5) / n
                    py = size - (iy + (sy + 0.5) / n)          # y вверх
                    hits += covered(px, py)
            a = hits / float(n * n)
            c = tuple(round(bg_c[k] + (fg_c[k] - bg_c[k]) * a) for k in range(3))
            row.append('#%02x%02x%02x' % c)
        rows.append(row)
    return rows


def make_photo(master, rows):
    """tk.PhotoImage из строк пикселей refresh_icon_rows()."""
    import tkinter as tk
    size = len(rows)
    img = tk.PhotoImage(master=master, width=size, height=len(rows[0]))
    img.put(' '.join('{' + ' '.join(row) + '}' for row in rows))
    return img
