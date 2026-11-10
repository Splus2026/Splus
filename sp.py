import exe_layout  # noqa: F401  (раскладка файлов рядом с exe; должен быть первым)
import tkinter as tk
from ui.custom_dialogs import messagebox
from config import load_config, create_engine, resource_path
from utils.password import check_password
from utils.project_files import project_sources
from ui.main_window import MainWindow
import os
import shutil
from datetime import datetime
import sys
import time
import stats_logger

# ------------------ Настройки ------------------
APP_VERSION = "1.0.0"
BACKUP_ENABLED = True
STATS_ENABLED = True
SOUND_VOLUME_PERCENT = 30
# ----------------------------------------------

def backup_source_files():
    if getattr(sys, 'frozen', False):
        print("Запуск из сборки, пропускаем резервное копирование.")
        return

    tmp_dir = os.path.join(os.path.dirname(__file__), '.tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    now = datetime.now()
    folder_name = now.strftime("%H-%M-%Y-%m-%d")
    backup_folder = os.path.join(tmp_dir, folder_name)
    os.makedirs(backup_folder, exist_ok=True)

    # Файлы НЕ на Python, которые тоже нужно сохранять. ИСХОДНИКИ (.py) сюда вносить не нужно —
    # они копируются автоматически, см. ниже (utils/project_files.py).
    files_to_copy = [
        ('mconfig.ini', 'mconfig.ini'),
    ]

    for src_rel, dst_rel in files_to_copy:
        src_abs = os.path.join(os.path.dirname(__file__), src_rel)
        if os.path.exists(src_abs):
            dst_abs = os.path.join(backup_folder, dst_rel)
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            shutil.copy2(src_abs, dst_abs)
        else:
            print(f"Предупреждение: файл {src_rel} не найден, пропускаем.")

    # ИСХОДНИКИ проекта копируются АВТОМАТИЧЕСКИ: все .py в корне и во всех пакетах верхнего
    # уровня (папки с __init__.py) — новый модуль (как ui/file_viewer.py) вносить в список выше не
    # нужно, забыть его нельзя. Виртуальное окружение, DB и т. п. под правило не попадают (см.
    # utils/project_files.py). Сбой здесь не должен мешать запуску программы.
    base_dir = os.path.dirname(__file__)
    try:
        for rel in project_sources(base_dir):
            src_abs = os.path.join(base_dir, rel)
            dst_abs = os.path.join(backup_folder, rel)
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            shutil.copy2(src_abs, dst_abs)
    except Exception as e:
        print(f"Предупреждение: не удалось скопировать исходники: {e}")

    # Автотесты (папка tests/) копируем ЦЕЛИКОМ — вместе с подставным tkinter и данными
    # проверок, — поэтому новые файлы проверок не нужно вносить в список выше вручную.
    tests_src = os.path.join(base_dir, 'tests')
    if os.path.isdir(tests_src):
        for dir_path, dir_names, file_names in os.walk(tests_src):
            dir_names[:] = [name for name in dir_names if name != '__pycache__']
            for file_name in file_names:
                if file_name.endswith('.pyc'):
                    continue
                src_abs = os.path.join(dir_path, file_name)
                dst_abs = os.path.join(backup_folder, os.path.relpath(src_abs, base_dir))
                os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                shutil.copy2(src_abs, dst_abs)

def show_authorization_dialog(parent):
    """
    Создаёт собственное окно авторизации с увеличенным шрифтом.
    Возвращает True, если пароль верный, иначе False.
    """
    today = datetime.now()
    # Пароль входа: прежний (день и месяц, ДДММ) работает всегда; кроме него, может
    # быть сменный пароль (хеш и соль в mconfig.ini, "Настройки → Сменить пароль") —
    # подходит любой из двух (см. utils/password.py).
    try:
        _config = load_config()
        stored_hash, salt = _config.get('password_hash', ''), _config.get('password_salt', '')
    except Exception:
        # Конфигурация не читается — остаётся прежний пароль, а не блокировка входа.
        stored_hash, salt = '', ''

    dialog = tk.Toplevel(parent)
    dialog.title("Авторизация")
    dialog.geometry("500x200")
    dialog.resizable(False, False)

    parent.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 200) // 2
    dialog.geometry(f"+{x}+{y}")

    label = tk.Label(dialog, text="Введите пароль:", font=('Arial', 14))
    label.pack(pady=20)

    entry_var = tk.StringVar()
    entry = tk.Entry(dialog, textvariable=entry_var, show='*', font=('Arial', 14), width=20)
    entry.pack(pady=10)
    entry.focus_set()

    result = [False]

    def on_ok():
        if check_password(entry_var.get(), stored_hash, salt, now=today):
            result[0] = True
            dialog.destroy()
        else:
            messagebox.showerror("Ошибка", "Неверный пароль. Доступ запрещён.", parent=dialog)
            sys.exit(1)

    def on_cancel():
        dialog.destroy()
        sys.exit(1)

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=10)

    ok_btn = tk.Button(btn_frame, text="OK", command=on_ok, font=('Arial', 13), width=10)
    ok_btn.pack(side='left', padx=10)
    cancel_btn = tk.Button(btn_frame, text="Отмена", command=on_cancel, font=('Arial', 13), width=10)
    cancel_btn.pack(side='left', padx=10)

    dialog.bind('<Return>', lambda e: on_ok())
    dialog.bind('<Escape>', lambda e: on_cancel())

    parent.wait_window(dialog)
    return result[0]

def ensure_db_folder():
    """
    Проверяет наличие папки DB в корне рядом с исполняемым файлом.
    Если её нет, копирует из _internal (или исходной папки) в корень.
    """
    if getattr(sys, 'frozen', False):
        # Запуск из сборки
        dest_dir = os.path.join(os.path.dirname(sys.executable), 'DB')
        src_dir = resource_path('DB')  # внутри _internal
    else:
        # Запуск из исходников
        dest_dir = os.path.join(os.path.dirname(__file__), 'DB')
        src_dir = dest_dir  # уже есть

    # Если в корне уже есть папка DB, ничего не делаем
    if os.path.exists(dest_dir):
        return

    # Если исходная папка существует, копируем её в корень
    if os.path.exists(src_dir) and os.path.isdir(src_dir):
        try:
            shutil.copytree(src_dir, dest_dir)
            print(f"✅ Папка DB скопирована в {dest_dir}")
        except Exception as e:
            print(f"⚠️ Не удалось скопировать DB: {e}")
    else:
        # Если даже в _internal нет DB, создаём пустую папку
        os.makedirs(dest_dir, exist_ok=True)
        print(f"ℹ️ Создана пустая папка DB в {dest_dir}")

def main():
    # Создаём главное окно, но скрываем его до авторизации
    root = tk.Tk()
    root.withdraw()
    root.geometry("1400x750")

    # Показываем диалог авторизации
    if not show_authorization_dialog(root):
        return  # если отмена или ошибка, программа завершится внутри

    # После успешной авторизации показываем главное окно
    root.deiconify()

    if STATS_ENABLED:
        stats_logger.enable_stats()

    if BACKUP_ENABLED:
        backup_source_files()

    # ---- Копируем папку DB в корень, если её нет ----
    ensure_db_folder()

    start_time = time.time()

    config = load_config()

    def show_startup_failure(title, text):
        # Движок окон не создаёт — он сообщает о неудачном запуске, а показываем мы (у нас есть окно)
        messagebox.showerror(title, text, parent=root)

    engine = create_engine(config['engine_type'], config['engine_params'], on_startup_failure=show_startup_failure)
    if config.get('last_db'):
        engine.connect(config['last_db'])

    root.title(f"Синева+ {APP_VERSION} — {datetime.now().strftime('%d.%m.%Y')}")

    app = MainWindow(root, engine, config)

    ready_time = time.time()
    startup_duration = (ready_time - start_time) * 1000

    if STATS_ENABLED:
        stats_logger.log_startup(startup_duration, engine=engine, version=APP_VERSION)

    root.mainloop()

if __name__ == "__main__":
    main()