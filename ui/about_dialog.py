"""Окно «О программе»: версия, дата сборки, размер книг и индексов."""
from services import about_info
from ui.custom_dialogs import messagebox

APP_VERSION = ''   # sp.py подставляет свою APP_VERSION до создания окна


def show_about(parent, file_manager, engine):
    try:
        books = about_info.books_size(file_manager._scan_text_files())
    except Exception:
        books = (0, 0)
    try:
        indexes = about_info.index_sizes(engine)
    except Exception:
        indexes = []
    text = about_info.about_text(APP_VERSION, books, indexes, about_info.build_date())
    messagebox.showinfo("О программе", text, parent=parent)
