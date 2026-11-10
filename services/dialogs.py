"""Диалоги для сервисов — без зависимости от окон.

   Сервисам (FileManager, IndexManager, SearchController) нужно показать пользователю сообщение или
   задать вопрос, но им незачем знать, КАК это показывается: Tk-окнами, в консоли или заглушкой в
   автоматических проверках. Раньше они импортировали ui.custom_dialogs напрямую — слой сервисов
   зависел от слоя интерфейса, и без интерфейса их нельзя было ни запустить, ни проверить.

   Теперь сервисы берут messagebox отсюда (`from services.dialogs import messagebox`), а окно при
   создании регистрирует настоящую реализацию — set_backend(ui.custom_dialogs.messagebox). Имя
   messagebox в модулях сервисов осталось прежним, поэтому проверки по-прежнему могут подменять его
   у модуля.

   Пока реализация не зарегистрирована, работает запасная: сообщения печатаются в stderr (ни одно не
   пропадает молча), на вопросы она отвечает «нет»."""

import sys


class ConsoleDialogs:
    """Запасная реализация: сообщения — в stderr, на вопросы («Да/Нет», «ОК/Отмена») — «нет»."""

    @staticmethod
    def _say(kind, title, message):
        print(f"[{kind}] {title}: {message}", file=sys.stderr)

    def showinfo(self, title="", message="", *args, **kwargs):
        self._say('info', title, message)

    def showwarning(self, title="", message="", *args, **kwargs):
        self._say('warning', title, message)

    def showerror(self, title="", message="", *args, **kwargs):
        self._say('error', title, message)

    def askyesno(self, title="", message="", *args, **kwargs):
        self._say('question', title, message)
        return False

    def askokcancel(self, title="", message="", *args, **kwargs):
        self._say('question', title, message)
        return False

    def ask_choice(self, title="", message="", *args, **kwargs):
        self._say('question', title, message)
        return None


_backend = ConsoleDialogs()


def set_backend(backend):
    """Регистрирует реализацию диалогов (объект с методами showinfo/showwarning/showerror/askyesno/
       askokcancel/ask_choice — например, ui.custom_dialogs.messagebox)."""
    global _backend
    _backend = backend


def get_backend():
    return _backend


class _MessageBoxProxy:
    """Передаёт вызов ТЕКУЩЕЙ зарегистрированной реализации (её можно сменить после импорта)."""

    def __getattr__(self, name):
        return getattr(_backend, name)


messagebox = _MessageBoxProxy()
