from tkinter import Widget, Entry  # ttk.Entry — то же поле ввода с настоящим текстом
class Progressbar(Widget): pass
class Label(Widget): pass
class Frame(Widget): pass
class Button(Widget): pass


# Универсальный режим — как в tkinter/__init__.py (включается флагом tkinter._GENERIC_FALLBACK).
import tkinter as _tk
_generic_classes = {}

def __getattr__(name):
    if name.startswith('__') or not getattr(_tk, '_GENERIC_FALLBACK', False):
        raise AttributeError(f"module 'tkinter.ttk' has no attribute {name!r}")
    if name[:1].isupper():
        return _generic_classes.setdefault(name, type(name, (Widget,), {}))
    raise AttributeError(f"module 'tkinter.ttk' has no attribute {name!r}")
