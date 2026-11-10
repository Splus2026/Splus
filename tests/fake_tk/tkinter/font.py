"""Заглушка tkinter.font: размеры «как у моноширинного шрифта» — для логики раскладки хватает."""


class Font:
    def __init__(self, root=None, font=None, family=None, size=12, weight='normal', **kw):
        self.size = size if font is None else (font[1] if len(font) > 1 else 12)

    def measure(self, text, **kw): return 8 * len(str(text))
    def metrics(self, option=None): return 16 if option else {'ascent': 12, 'descent': 4, 'linespace': 16, 'fixed': 1}
    def actual(self, option=None): return {} if option is None else None
    def cget(self, option): return None
    def configure(self, **kw): pass


def nametofont(name, root=None): return Font()
