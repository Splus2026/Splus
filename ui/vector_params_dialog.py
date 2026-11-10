"""Диалог кнопки "Векторы" для СОЗДАНИЯ НОВОЙ модели: выбор типа (FastText,
   paraphrase-multilingual-MiniLM-L12-v2 — см. vector_engines.
   AVAILABLE_MODEL_TYPES/MODEL_PARAM_SCHEMAS) и настройка её параметров.

   Список типов — всегда ровно столько пунктов, сколько зарегистрировано в
   AVAILABLE_MODEL_TYPES (сейчас два), независимо от того, сколько моделей
   уже обучено на основе файлов — уже обученные модели сюда не подмешиваются.

   Дообучение уже существующей модели — ОТДЕЛЬНЫЙ путь, не через этот
   диалог: оно запускается отметкой её галочки в списке индексов (вместе с
   файлом(-ами) внизу) — см. ui/app_window.py, prepare_vectors().

   Форма параметров перестраивается под выбранный ТИП модели — у каждого
   типа свой набор полей (см. MODEL_PARAM_SCHEMAS)."""

import tkinter as tk
from tkinter import ttk
from vector_engines import AVAILABLE_MODEL_TYPES, MODEL_PARAM_SCHEMAS, CHUNK_BASED_MODEL_TYPES

FONT_LABEL = ('Arial', 13)
FONT_LABEL_BOLD = ('Arial', 13, 'bold')
FONT_ENTRY = ('Arial', 13)
FONT_SMALL = ('Arial', 11)
FONT_BUTTON = ('Arial', 12, 'bold')


def ask_vector_params(parent, suggest_params_fn, total_mb, sentence_window_config=(7, 10)):
    """suggest_params_fn(model_type, planned_total_mb: float | None) -> dict
       — пересчитывает рекомендации под выбранный тип модели (и, для
       FastText, по ожидаемому суммарному размеру при будущем дообучении).
       sentence_window_config — (vector_sentences_before, vector_sentences_
       after) из общих настроек — только для отображения в режиме 2 "окна
       смысла" (см. ниже), сами числа не редактируются в этом диалоге.

       Возвращает {'model_type': '<ключ>', 'params': {...}} — для FastText;
       для MiniLM дополнительно {'semantic_window': {'mode': ..., 'params':
       {...}}} — способ получения смысловых блоков (см.
       VectorModelManager.build_minilm_training_data). None, если
       пользователь отменил."""
    result = {'value': None}

    type_key_by_label = {label: key for key, label in AVAILABLE_MODEL_TYPES.items()}
    type_labels = list(AVAILABLE_MODEL_TYPES.values())

    dialog = tk.Toplevel(parent)
    dialog.title("Векторы — новая модель")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    tk.Label(dialog, text=f"Суммарный размер выбранных файлов: {total_mb:.1f} МБ",
             font=FONT_LABEL_BOLD).pack(padx=18, pady=(18, 8), anchor='w')

    # --- Выбор типа модели ---
    model_frame = tk.Frame(dialog)
    model_frame.pack(padx=18, pady=(0, 10), fill='x')
    tk.Label(model_frame, text="Тип модели:", font=FONT_LABEL).grid(row=0, column=0, sticky='w')
    model_var = tk.StringVar(value=type_labels[0] if type_labels else "")
    model_combo = ttk.Combobox(model_frame, textvariable=model_var, values=type_labels,
                               state='readonly', font=FONT_ENTRY, width=32)
    model_combo.grid(row=0, column=1, sticky='e', padx=(15, 0))
    model_frame.columnconfigure(1, weight=1)

    params_container = tk.Frame(dialog)
    params_container.pack(padx=18, pady=(0, 5), fill='x')

    # "Планируется дообучение" — актуально только для FastText: у него
    # параметры (в первую очередь vector_size) фиксируются на весь срок
    # жизни модели, поэтому имеет смысл сразу закладываться на будущий
    # объём. Для MiniLM (готовая модель, здесь настраивается по сути
    # только скорость/память кодирования) это не имеет смысла — блок для
    # неё просто не показывается.
    plan_row = tk.Frame(params_container)
    plan_var = tk.BooleanVar(value=False)
    plan_check = tk.Checkbutton(plan_row, text="Планируется дообучение модели",
                                variable=plan_var, font=FONT_LABEL)
    plan_check.pack(side='left')

    plan_size_frame = tk.Frame(params_container)
    tk.Label(plan_size_frame, text="Ожидаемый суммарный размер файлов (с учётом дообучения), МБ:",
             font=FONT_LABEL, anchor='w', wraplength=380, justify='left').pack(side='left')
    plan_size_var = tk.StringVar(value=f"{total_mb:.0f}")
    plan_size_entry = tk.Entry(plan_size_frame, textvariable=plan_size_var, width=8,
                               font=FONT_ENTRY, justify='right')
    plan_size_entry.pack(side='left', padx=(10, 0))

    plan_note = tk.Label(
        params_container,
        text="(параметры ниже нельзя изменить позже, при дообучении — поэтому если оно\n"
             "планируется, лучше сразу ориентироваться на ожидаемый итоговый объём)",
        font=FONT_SMALL, fg='#555555', justify='left'
    )

    form = tk.Frame(params_container)
    form.pack(fill='x')

    field_widgets = {}   # ключ параметра -> (StringVar, тип поля: 'int'/'choice')

    # --- "Окно смысла" — только для MiniLM: каким способом получить
    # смысловые блоки текста для кодирования (см. обсуждение с
    # пользователем и VectorModelManager.build_minilm_training_data).
    # N700 и подобные обычные разделители режут текст на равные куски
    # символов, оберегая только отдельные слова — для семантического
    # поиска это не даёт содержательных блоков, отсюда и эта настройка.
    sw_frame = tk.Frame(params_container)
    sw_mode_var = tk.StringVar(value='existing_index')
    before_cfg, after_cfg = sentence_window_config

    tk.Label(sw_frame, text="Окно смысла:", font=FONT_LABEL_BOLD, anchor='w').pack(anchor='w', pady=(10, 4))

    tk.Radiobutton(
        sw_frame, text="Готовый индекс — вектор = его блокам (как сейчас)",
        variable=sw_mode_var, value='existing_index', font=FONT_LABEL
    ).pack(anchor='w')
    tk.Label(sw_frame, text="   (файлы должны быть уже проиндексированы кнопкой «В индекс»)",
            font=FONT_SMALL, fg='#555555', justify='left').pack(anchor='w', padx=(20, 0))

    radio_sentence_window = tk.Radiobutton(
        sw_frame, text="Скользящее окно по предложениям:",
        variable=sw_mode_var, value='sentence_window', font=FONT_LABEL
    )
    radio_sentence_window.pack(anchor='w', pady=(6, 0))

    # Отдельная группа-обёртка — строка с полями и подсказка под ней
    # показываются/скрываются вместе, одним pack()/pack_forget().
    sentence_window_group = tk.Frame(sw_frame)
    sentence_window_row = tk.Frame(sentence_window_group)
    sentence_window_row.pack(anchor='w')
    tk.Label(sentence_window_row, text="   ", font=FONT_LABEL).pack(side='left')
    sw_before_var = tk.StringVar(value=str(before_cfg))
    tk.Entry(sentence_window_row, textvariable=sw_before_var, width=4, font=FONT_ENTRY,
            justify='right').pack(side='left')
    tk.Label(sentence_window_row, text="предложений до, текущее предложение,",
            font=FONT_LABEL).pack(side='left', padx=(5, 5))
    sw_after_var = tk.StringVar(value=str(after_cfg))
    tk.Entry(sentence_window_row, textvariable=sw_after_var, width=4, font=FONT_ENTRY,
            justify='right').pack(side='left')
    tk.Label(sentence_window_row, text="предложений после",
            font=FONT_LABEL).pack(side='left', padx=(5, 0))
    tk.Label(sentence_window_group,
            text="   (изначально взято из общих настроек — можно поправить только для этой модели)",
            font=FONT_SMALL, fg='#555555', justify='left').pack(anchor='w', padx=(20, 0))

    radio_char_overlap = tk.Radiobutton(
        sw_frame, text="Перекрытие по символам (как в образце corpus.py)",
        variable=sw_mode_var, value='char_overlap', font=FONT_LABEL
    )
    radio_char_overlap.pack(anchor='w', pady=(6, 0))

    overlap_row = tk.Frame(sw_frame)
    tk.Label(overlap_row, text="   Размер блока (символов):", font=FONT_LABEL).pack(side='left')
    target_chars_var = tk.StringVar(value='900')
    tk.Entry(overlap_row, textvariable=target_chars_var, width=6, font=FONT_ENTRY,
            justify='right').pack(side='left', padx=(5, 15))
    tk.Label(overlap_row, text="Перекрытие (символов):", font=FONT_LABEL).pack(side='left')
    overlap_chars_var = tk.StringVar(value='150')
    tk.Entry(overlap_row, textvariable=overlap_chars_var, width=6, font=FONT_ENTRY,
            justify='right').pack(side='left', padx=(5, 0))

    radio_paragraphs = tk.Radiobutton(
        sw_frame, text="Автоматическая разбивка по абзацам",
        variable=sw_mode_var, value='paragraphs', font=FONT_LABEL
    )
    radio_paragraphs.pack(anchor='w', pady=(6, 0))

    def on_sw_mode_change(*_args):
        if sw_mode_var.get() == 'sentence_window':
            sentence_window_group.pack(anchor='w', pady=(4, 0), before=radio_char_overlap)
        else:
            sentence_window_group.pack_forget()
        if sw_mode_var.get() == 'char_overlap':
            overlap_row.pack(anchor='w', pady=(4, 0), before=radio_paragraphs)
        else:
            overlap_row.pack_forget()

    sw_mode_var.trace_add('write', on_sw_mode_change)

    error_label = tk.Label(dialog, text='', fg='#b84a4a', font=FONT_SMALL)

    def current_planned_mb():
        if not plan_var.get():
            return None
        try:
            return float(plan_size_var.get())
        except ValueError:
            return None

    # Флаг: параметры формы могли устареть относительно введённого
    # "ожидаемого размера" — пока он взведён, "ОК" для FastText заблокирован.
    stale = {'value': False}

    def apply_suggested(*_args):
        stale['value'] = False
        error_label.config(text='')
        model_type = type_key_by_label.get(model_var.get())
        if not model_type:
            return
        suggested = suggest_params_fn(model_type, current_planned_mb())
        for key, (var, kind) in field_widgets.items():
            value = suggested.get(key, '')
            if kind == 'choice' and key == 'sg':
                var.set('skip-gram' if value == 1 else 'CBOW')
            else:
                var.set(str(value))

    def mark_stale(*_args):
        if plan_var.get():
            stale['value'] = True

    def on_plan_toggle():
        if plan_var.get():
            plan_size_frame.pack(anchor='w', fill='x', pady=(0, 4), after=plan_row)
        else:
            plan_size_frame.pack_forget()
        apply_suggested()

    plan_check.config(command=on_plan_toggle)
    plan_size_entry.bind('<KeyRelease>', mark_stale)
    plan_size_entry.bind('<FocusOut>', apply_suggested)
    plan_size_entry.bind('<Return>', lambda e: (apply_suggested(), "break")[1])

    def _rebuild_form(model_type):
        """Перестраивает форму параметров под схему выбранного типа модели
           (см. vector_engines.MODEL_PARAM_SCHEMAS)."""
        for child in form.winfo_children():
            child.destroy()
        field_widgets.clear()

        schema = MODEL_PARAM_SCHEMAS.get(model_type, [])
        for row, (key, label, kind) in enumerate(schema):
            tk.Label(form, text=label, font=FONT_LABEL, anchor='w').grid(row=row, column=0, sticky='w', pady=4)
            if kind.startswith('choice:'):
                options = kind.split(':', 1)[1].split(',')
                var = tk.StringVar()
                combo = ttk.Combobox(form, textvariable=var, values=options,
                                     width=9, state='readonly', font=FONT_ENTRY, justify='right')
                combo.grid(row=row, column=1, sticky='e', padx=(15, 0))
                field_widgets[key] = (var, 'choice')
            else:
                var = tk.StringVar()
                tk.Entry(form, textvariable=var, width=8, font=FONT_ENTRY, justify='right').grid(
                    row=row, column=1, sticky='e', padx=(15, 0))
                field_widgets[key] = (var, 'int')

        if model_type == 'fasttext':
            plan_row.pack(anchor='w', fill='x', pady=(0, 4), before=form)
            plan_note.pack(anchor='w', pady=(2, 10), before=form)
        else:
            plan_row.pack_forget()
            plan_size_frame.pack_forget()
            plan_note.pack_forget()
            plan_var.set(False)

        if model_type in CHUNK_BASED_MODEL_TYPES:
            sw_frame.pack(anchor='w', fill='x', pady=(0, 5))
            on_sw_mode_change()
        else:
            sw_frame.pack_forget()

        apply_suggested()

    def on_model_change(*_args):
        model_type = type_key_by_label.get(model_var.get())
        if model_type:
            _rebuild_form(model_type)
        dialog.update_idletasks()

    model_combo.bind('<<ComboboxSelected>>', on_model_change)
    on_model_change()
    error_label.pack(padx=18, pady=(0, 5))

    def on_ok():
        model_type = type_key_by_label.get(model_var.get())
        if not model_type:
            dialog.destroy()
            return
        if model_type == 'fasttext' and stale['value']:
            error_label.config(text="Сначала обновите рекомендуемые параметры — нажмите Enter "
                                    "в поле ожидаемого размера или переведите фокус на другое поле.")
            return
        values = {}
        try:
            for key, (var, kind) in field_widgets.items():
                if kind == 'choice':
                    values[key] = 1 if var.get() == 'skip-gram' else 0
                else:
                    values[key] = int(var.get())
        except ValueError:
            error_label.config(text="Все числовые поля должны содержать целые числа.")
            return
        for key, (var, kind) in field_widgets.items():
            if kind == 'int' and values[key] <= 0 and key != 'min_count':
                error_label.config(text="Значения должны быть положительными числами.")
                return
        if 'min_count' in values and values['min_count'] < 0:
            error_label.config(text="Мин. число вхождений не может быть отрицательным.")
            return

        result_value = {'model_type': model_type, 'params': values}

        if model_type in CHUNK_BASED_MODEL_TYPES:
            sw_mode = sw_mode_var.get()
            sw_params = {}
            if sw_mode == 'sentence_window':
                try:
                    sw_before = int(sw_before_var.get())
                    sw_after = int(sw_after_var.get())
                except ValueError:
                    error_label.config(text="Число предложений до/после должно быть целым числом.")
                    return
                if sw_before < 0 or sw_after < 0:
                    error_label.config(text="Число предложений до/после не может быть отрицательным.")
                    return
                sw_params = {'sentences_before': sw_before, 'sentences_after': sw_after}
            elif sw_mode == 'char_overlap':
                try:
                    target_chars = int(target_chars_var.get())
                    overlap_chars = int(overlap_chars_var.get())
                except ValueError:
                    error_label.config(text="Размер блока и перекрытие должны быть целыми числами.")
                    return
                if target_chars <= 0:
                    error_label.config(text="Размер блока должен быть положительным числом.")
                    return
                if overlap_chars < 0:
                    error_label.config(text="Перекрытие не может быть отрицательным.")
                    return
                if overlap_chars >= target_chars:
                    error_label.config(text="Перекрытие должно быть меньше размера блока.")
                    return
                sw_params = {'target_chars': target_chars, 'overlap_chars': overlap_chars}
            result_value['semantic_window'] = {'mode': sw_mode, 'params': sw_params}

        result['value'] = result_value
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=18)
    tk.Button(btn_frame, text="OK", command=on_ok, width=10, font=FONT_BUTTON,
             bg='#4a7a8a', fg='white').pack(side='left', padx=5)
    tk.Button(btn_frame, text="Отмена", command=on_cancel, width=10, font=FONT_BUTTON).pack(side='left', padx=5)

    dialog.bind('<Return>', lambda e: on_ok())
    dialog.bind('<Escape>', lambda e: on_cancel())

    dialog.update_idletasks()
    try:
        x = parent.winfo_x() + (parent.winfo_width() - dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass

    dialog.focus_set()
    dialog.wait_window()
    return result['value']
