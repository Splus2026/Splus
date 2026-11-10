"""Нумератор разбивки — вставка нумерованных строк-разделителей горячими
   клавишами в документ, открытый во внешней программе (Word, Блокнот).

   Перенесён из прежнего проекта (там — Вход 2: кнопка "Дополнить базы"). Как
   работает здесь:

   1. В mconfig.ini включён флаг enable_numerator_on_update = 1.
   2. Кнопка "Редактировать" открывает файл во внешней программе (как и
      раньше) и включает клавишу F7 — на полсекунды показывается подсказка.
   3. F7 в любой момент, даже поверх Word, открывает диалог нумератора
      (ui/numerator_dialog.py): формат, номер, текстовая часть.
   4. После OK работают F9 (вставить следующий номер) и F8 (откат: счётчик
      на единицу назад и предыдущий номер вставляется заново — на случай,
      если предыдущий вставили не туда). ВАЖНО, как и в прежней версии:
      после F8 счётчик стоит на только что вставленном номере, поэтому
      СЛЕДУЮЩИЙ F9 вставит тот же номер ещё раз (F9 вставляет значение
      счётчика, а затем увеличивает его). Поведение перенесено без
      изменений; если нужен иной смысл F8 — менять только
      NumeratorState.rollback().
   Переиндексация по завершении правки НЕ предлагается (в прежнем проекте
   предлагалась).

   --- Про F7/F8/F9 в самом Word ---
   У Word эти клавиши заняты (F7 — проверка орфографии, F8 — режим
   выделения, F9 — обновление полей). Все три регистрируются с suppress=True:
   нажатие перехватывается и до Word не доходит. В присланном архиве прежнего
   проекта этого не было (там add_hotkey без suppress) — найденное при
   отладке решение для F7 там не сохранилось, поэтому глушение сделано здесь
   заново.
   Оборотная сторона: пока клавиши зарегистрированы, они "мёртвые" во ВСЕХ
   программах (в Total Commander F7 — новая папка, F8 — удаление). Поэтому
   F8/F9 включаются только после настройки нумератора, а в диалоге есть
   кнопка "Выключить", освобождающая все три клавиши.

   --- Потоки ---
   Обработчики клавиш вызывает поток библиотеки keyboard, а Tkinter не
   потокобезопасен (в проекте уже сталкивались с ненадёжностью root.after
   из фоновых потоков, см. AppWindow._update_log_field). Поэтому обработчик
   ничего не делает сам — только кладёт задание в очередь:
   - вставка/откат (буфер обмена + Ctrl+V) выполняет собственный рабочий
     поток, чтобы не задерживать поток перехвата клавиш;
   - открытие диалога и сообщения в строку состояния выполняет ГЛАВНЫЙ
     поток, опрашивая очередь через root.after (_poll)."""

import atexit
import queue
import re
import threading
import time
from datetime import datetime

FORMAT_NUMBER_TEXT = 'number_text'   # 001.2026
FORMAT_TEXT_NUMBER = 'text_number'   # .2026001

HOTKEY_DIALOG = 'f7'
HOTKEY_INSERT = 'f9'
HOTKEY_ROLLBACK = 'f8'

_POLL_INTERVAL_MS = 100
# Автоповтор удерживаемой клавиши приходит потоком событий с шагом ~30-40 мс;
# событие, пришедшее раньше чем через это время после предыдущего, считаем
# повтором (см. NumeratorController._accept_key). Заведомо меньше времени
# между двумя осознанными нажатиями.
_REPEAT_GUARD_S = 0.12
_ASCII_DIGITS_RE = re.compile(r'[0-9]+')


def default_text_part() -> str:
    """Текстовая часть по умолчанию — ".<текущий год>". В прежнем проекте было
       жёстко ".2026"; в 2026 году результат тот же, но в следующем не придётся
       каждый раз переправлять."""
    return '.' + str(datetime.now().year)


def compose(fmt: str, number_str: str, text: str) -> str:
    return number_str + text if fmt == FORMAT_NUMBER_TEXT else text + number_str


class NumeratorUnavailable(Exception):
    """Нет библиотек keyboard/pyperclip (или они не работают на этой системе)."""


class NumeratorState:
    """Формат и счётчик. Потокобезопасно: счётчик меняет и рабочий поток
       (F9/F8), и главный (диалог по F7)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.format = FORMAT_NUMBER_TEXT
        self.text = default_text_part()
        self.width = 3
        self.counter = 1
        self.configured = False

    def configure(self, fmt: str, number_str: str, text: str):
        """Задаёт формат, стартовый номер и текстовую часть. Бросает
           ValueError с текстом для пользователя. Ширина номера — число
           введённых цифр ("001" -> 3, затем 001, 002, ...)."""
        number_str = (number_str or '').strip()
        text = (text or '').strip()
        if fmt not in (FORMAT_NUMBER_TEXT, FORMAT_TEXT_NUMBER):
            raise ValueError("Неизвестный формат разделителя.")
        if not number_str or not text:
            raise ValueError("Заполните оба поля.")
        # Только обычные цифры: int() принял бы и "+5", и цифры других
        # алфавитов, а ширина считается по длине строки.
        if not _ASCII_DIGITS_RE.fullmatch(number_str) or int(number_str) < 1:
            raise ValueError("Номер должен быть целым числом ≥ 1.")
        with self._lock:
            self.format = fmt
            self.text = text
            self.width = len(number_str)
            self.counter = int(number_str)
            self.configured = True

    def _format_locked(self, n: int) -> str:
        return compose(self.format, str(n).zfill(self.width), self.text)

    def take_next(self) -> str:
        """Текущий номер для вставки; счётчик увеличивается (как в прежней
           версии — независимо от того, удалась ли сама вставка)."""
        with self._lock:
            value = self._format_locked(self.counter)
            self.counter += 1
            return value

    def rollback(self):
        """Откат: счётчик на единицу назад, возвращается строка этого (уже
           вставлявшегося) номера — чтобы вставить её заново. None, если
           откатывать нечего (счётчик на 1)."""
        with self._lock:
            if self.counter <= 1:
                return None
            self.counter -= 1
            return self._format_locked(self.counter)

    def dialog_prefill(self):
        """(формат, номер, текст) для полей диалога. Номер — СЛЕДУЮЩИЙ, который
           вставит F9, а не стартовый: иначе открытие диалога по F7 "просто
           поменять текст" и нажатие OK молча сбрасывало бы счётчик на
           стартовое значение (в прежней версии именно так и было) и
           нумерация пошла бы заново с дублями."""
        with self._lock:
            return self.format, str(self.counter).zfill(self.width), self.text


class KeyboardBackend:
    """Тонкая обёртка над keyboard и pyperclip (импортируются здесь, а не при
       запуске программы — без этих пакетов остальное приложение работает,
       просто нумератор сообщит, что ему нужно)."""

    def __init__(self):
        try:
            import keyboard
            import pyperclip
        except ImportError as e:
            raise NumeratorUnavailable(
                "Для нумератора нужны пакеты keyboard и pyperclip: pip install keyboard pyperclip"
            ) from e
        self._keyboard = keyboard
        self._pyperclip = pyperclip

    def add_hotkey(self, key: str, callback):
        # suppress=True — нажатие не доходит до активной программы (см. начало
        # файла: F7/F8/F9 заняты в самом Word).
        return self._keyboard.add_hotkey(key, callback, suppress=True)

    def remove_hotkey(self, handle):
        self._keyboard.remove_hotkey(handle)

    def paste_text(self, text: str):
        self._pyperclip.copy(text)
        time.sleep(0.05)  # дать буферу обмена обновиться до Ctrl+V
        self._keyboard.send('ctrl+v')

    def release_all(self):
        """Снять вообще все перехваты — на случай, если remove_hotkey у
           подавляющих клавиш оставит что-то зарегистрированным."""
        try:
            self._keyboard.unhook_all()
        except Exception:
            pass


class NumeratorController:
    def __init__(self, root, status_callback, notify_callback, open_dialog_callback,
                 backend_factory=KeyboardBackend):
        """root — главное окно (для опроса очереди через after).
           status_callback(text) — строка состояния; notify_callback(text,
           duration_ms) — короткое всплывающее окно; open_dialog_callback(
           controller) — показать диалог нумератора. ВСЕ три вызываются
           только из главного потока."""
        self._root = root
        self._status = status_callback
        self._notify = notify_callback
        self._open_dialog = open_dialog_callback
        self._backend_factory = backend_factory

        self.state = NumeratorState()
        self.dialog_window = None  # ссылка на открытое окно диалога (его ведёт ui/numerator_dialog.py)
        # Причина последней неудачи activate() — готовый текст для пользователя.
        # В строке состояния (куда причина уходит тоже) её легко не заметить, а
        # самая вероятная — не установлен пакет keyboard — требует действия;
        # главное окно показывает по ней отдельное сообщение.
        self.last_error = ''
        self._last_seen = {}  # клавиша -> время последнего события (только поток перехвата)

        self._backend = None
        self._handles = {}                 # клавиша -> то, что вернул add_hotkey
        self._jobs = queue.Queue()         # поток перехвата клавиш -> рабочий поток
        self._ui_events = queue.Queue()    # рабочий/перехвата -> главный поток
        self._worker = None
        self._active = False
        self._polling = False
        self._atexit_registered = False

    # ---------- включение / выключение (главный поток) ----------

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self) -> bool:
        """Включает F7. Повторный вызов безопасен. False — если нумератор
           включить не удалось (причина показана в строке состояния)."""
        if self._active:
            return True
        self.last_error = ''
        try:
            if self._backend is None:
                self._backend = self._backend_factory()
        except NumeratorUnavailable as e:
            return self._fail(str(e), f"⚠️ {e}")
        except Exception as e:
            return self._fail(f"Нумератор недоступен: {e}", f"❌ Нумератор недоступен: {e}")
        try:
            self._register(HOTKEY_DIALOG, self._on_f7)
        except Exception as e:
            return self._fail(
                f"Не удалось включить клавишу F7: {e}\n"
                "(на Linux библиотеке keyboard нужны права root)",
                f"❌ Не удалось включить F7: {e}")
        self._active = True
        self._start_worker()
        self._start_polling()
        if not self._atexit_registered:
            atexit.register(self.shutdown)
            self._atexit_registered = True
        self._status("🔄 Нумератор: F7 — настройка разделителя")
        return True

    def _fail(self, user_message: str, status_text: str) -> bool:
        self.last_error = user_message
        self._status(status_text)
        return False

    def apply_settings(self, fmt: str, number_str: str, text: str):
        """Из диалога по OK. Включает F9/F8. ValueError — неверные данные ИЛИ
           не удалось включить клавиши (диалог покажет текст в самом окне и
           не закроется). Клавиши включаются парой: если одна из двух не
           зарегистрировалась, обе снимаются — не остаётся включённой одна
           F9 без F8."""
        self.state.configure(fmt, number_str, text)
        try:
            self._register(HOTKEY_INSERT, self._on_f9)
            self._register(HOTKEY_ROLLBACK, self._on_f8)
        except Exception as e:
            for key in (HOTKEY_INSERT, HOTKEY_ROLLBACK):
                handle = self._handles.pop(key, None)
                if handle is not None:
                    try:
                        self._backend.remove_hotkey(handle)
                    except Exception:
                        pass
            self._status(f"❌ Ошибка регистрации горячих клавиш: {e}")
            raise ValueError(f"Не удалось включить F9/F8: {e}") from e
        self._status("🔄 Нумератор активирован (F9 — вставить, F8 — откат)")
        self._notify("Нумератор настроен\nF9 — вставить номер, F8 — откат", 1500)

    def deactivate(self):
        """Кнопка "Выключить": освобождает F7/F8/F9 во всех программах."""
        self._teardown()
        self._status("⏹ Нумератор выключен — F7/F8/F9 снова работают как обычно")

    def shutdown(self):
        """Тихое выключение при выходе из программы (не трогает Tk)."""
        self._teardown()

    def _teardown(self):
        self._active = False
        for key, handle in list(self._handles.items()):
            try:
                self._backend.remove_hotkey(handle)
            except Exception:
                pass
        self._handles.clear()
        if self._backend is not None:
            self._backend.release_all()
        # Накопившиеся события уже не нужны (иначе после повторного включения
        # всплыло бы "старое" окно диалога, а отложенные вставки выполнились бы
        # уже после выключения).
        self._drain(self._ui_events)
        if self._worker is not None:
            # Сначала очищаем очередь ЭТОГО рабочего потока, и только потом
            # кладём сигнал остановки — в обратном порядке очистка стёрла бы
            # сам сигнал, и поток завис бы навсегда.
            self._drain(self._jobs)
            self._jobs.put(None)
            self._worker = None

    @staticmethod
    def _drain(q):
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _register(self, key, callback):
        if key in self._handles:
            return
        self._handles[key] = self._backend.add_hotkey(key, callback)

    # ---------- обработчики клавиш: вызываются потоком перехвата ----------
    # Только очередь — никаких виджетов и никакой работы с буфером обмена.

    def _accept_key(self, key, *, while_dialog_open):
        """Пропускать ли это нажатие (вызывается в потоке перехвата).

           - Пока открыт диалог нумератора, F9/F8 игнорируются: активно окно
             диалога, и Ctrl+V вставил бы номер в одно из его полей (F7 при
             этом пропускается — он просто выведет диалог на передний план).
           - Автоповтор удерживаемой клавиши отбрасывается: под suppress=True
             он идёт обычным потоком нажатий, и без этого удержание F9 дало бы
             десятки вставок в секунду. Сравниваем с последним ВИДЕННЫМ
             событием (а не принятым) — поток повторов сам продлевает окно
             отбрасывания. Одно удержание всё равно может дать две вставки
             (само нажатие и первый повтор после паузы автоповтора), но не
             десятки."""
        if not while_dialog_open and self.dialog_window is not None:
            return False
        now = time.monotonic()
        previous = self._last_seen.get(key)
        self._last_seen[key] = now
        return previous is None or now - previous >= _REPEAT_GUARD_S

    def _on_f7(self):
        if self._accept_key(HOTKEY_DIALOG, while_dialog_open=True):
            self._ui_events.put(('dialog',))

    def _on_f9(self):
        if self._accept_key(HOTKEY_INSERT, while_dialog_open=False):
            self._jobs.put('insert')

    def _on_f8(self):
        if self._accept_key(HOTKEY_ROLLBACK, while_dialog_open=False):
            self._jobs.put('rollback')

    # ---------- рабочий поток: вставка ----------

    def _start_worker(self):
        if self._worker is not None and self._worker.is_alive():
            return
        # У каждого рабочего потока СВОЯ очередь заданий: если выключить и тут
        # же включить нумератор заново, сигнал остановки старого потока не
        # может достаться новому (общая очередь давала бы такую гонку).
        jobs = queue.Queue()
        self._jobs = jobs
        self._worker = threading.Thread(target=self._worker_loop, args=(jobs,), daemon=True,
                                        name='numerator-worker')
        self._worker.start()

    def _worker_loop(self, jobs):
        while True:
            job = jobs.get()
            if job is None:
                return
            try:
                if job == 'insert':
                    text = self.state.take_next()
                elif job == 'rollback':
                    text = self.state.rollback()
                    if text is None:
                        continue
                else:
                    continue
                self._backend.paste_text(text)
                self._ui_events.put(('status', f"📋 Вставлено: {text}"))
            except Exception as e:
                self._ui_events.put(('status', f"❌ Ошибка вставки: {e}"))

    # ---------- главный поток: опрос очереди ----------

    def _start_polling(self):
        if self._polling:
            return
        self._polling = True
        self._schedule_poll()

    def _schedule_poll(self):
        try:
            self._root.after(_POLL_INTERVAL_MS, self._poll)
        except Exception:
            self._polling = False  # окно уже закрыто

    def _poll(self):
        try:
            while True:
                event = self._ui_events.get_nowait()
                try:
                    if event[0] == 'dialog':
                        self._open_dialog(self)
                    elif event[0] == 'status':
                        self._status(event[1])
                except Exception as e:
                    print(f"⚠️ Нумератор: ошибка обработки события {event[0]}: {e}")
        except queue.Empty:
            pass
        if self._active:
            self._schedule_poll()
        else:
            self._polling = False
