import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import tkinter as tk
tk._GENERIC_FALLBACK = True

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import ui.app_window as aw
from tests import ui_trace

# Структура главного окна: что в какой зоне, в каком порядке упаковано, какие команды и привязки у кнопок, меню, текстовых окон.
# Окно строится по-настоящему под подставным tkinter, все обращения к виджетам записываются (tests/ui_trace.py) — проверяется то,
# что пользователь увидит и нажмёт, а не внутреннее устройство метода построения.
U = ui_trace.build(aw); win = U.win
def opts(widget): return U.new(U.id(widget))[2]
def lay(widget): return U.layout(U.id(widget))
def calls(widget, method=None): return U.calls(U.id(widget), method)
def btn(text):
    ids = U.find('Button', text=text)
    if len(ids) > 1: ids = [i for i in ids if U.layout(i) != ('pack', {'padx': (4, 0), 'side': 'right'})]   # кнопка режима показа «Все» второй строки — не «Все» индексов
    return ids[0] if len(ids) == 1 else ids
def bopts(text): return U.new(btn(text))[2]
def blay(text): return U.layout(btn(text))
def fn(name): return ('fn', name)
def bound(widget): return [a[0] for m, a, k in calls(widget, 'bind')]

# ===================== A. зоны окна и порядок упаковки =====================
top, status_row, main_paned = U.children(0)
check('под корнем три зоны: верхняя строка поиска, строка статуса, основная панель', len(U.children(0)) == 3 and U.new(main_paned)[0] == 'PanedWindow')
check('верхняя строка: растягивается по ширине', U.layout(top) == ('pack', {'fill': 'x'}), str(U.layout(top)))
check('порядок упаковки: строка статуса (внизу) упаковывается РАНЬШЕ основной панели — иначе панель заняла бы всё место, и для статуса его не осталось бы', U.position(top) < U.position(status_row) < U.position(main_paned), str((U.position(top), U.position(status_row), U.position(main_paned))))
check('строка статуса: внизу окна, по ширине, отступы 10 по бокам и 8 снизу', U.layout(status_row) == ('pack', {'fill': 'x', 'padx': 10, 'pady': (0, 8), 'side': 'bottom'}), str(U.layout(status_row)))
check('основная панель: горизонтальная, занимает всё оставшееся место', U.new(main_paned)[2] == {'orient': 'horizontal'} and U.layout(main_paned) == ('pack', {'fill': 'both', 'expand': True, 'padx': 5, 'pady': 5}), str(U.layout(main_paned)))
left, center, right = U.children(main_paned)
adds = [(a[0], k) for m, a, k in U.calls(main_paned, 'add')]
check('в основную панель добавлены три части слева направо: левая (слова) и правая (индексы, файлы) фиксированной ширины, центральная (результаты) забирает остальное (вес 4)', adds == [(('w', left), {'weight': 0}), (('w', center), {'weight': 4}), (('w', right), {'weight': 0})], str(adds))
# ===================== B. строка поиска =====================
search_row = win.bottom_row_frame
check('строка поиска: голубая полоса внутри верхней зоны', opts(search_row) == {'bg': '#d4e8f7'} and U.new(U.id(search_row))[1] == ('w', top) and lay(search_row) == ('pack', {'fill': 'x', 'pady': 3}))
lbl = U.find('Label', text='Поисковый запрос:')[0]
check('надпись «Поисковый запрос:» слева', U.layout(lbl) == ('pack', {'padx': (0, 5), 'side': 'left'}) and U.new(lbl)[2]['font'] == ('Arial', 12, 'bold'))
check('поле запроса: ширина 30, шрифт Consolas размера из настроек, растягивается, слева от кнопок', opts(win.query_entry)['width'] == 30 and opts(win.query_entry)['font'] == ('Consolas', win.font_size) and lay(win.query_entry) == ('pack', {'expand': True, 'fill': 'x', 'padx': 5, 'side': 'left'}), str(lay(win.query_entry)))
check('Enter в поле запроса запускает поиск (привязка); фокус стоит в поле запроса', '<Return>' in bound(win.query_entry) and calls(win.query_entry, 'focus_set'))
o = opts(win.btn_settings)
check('«Настройки»: кнопка-меню фиолетовая, слева; в неё вставлено меню настроек', o['text'] == 'Настройки' and o['bg'] == '#6a4a8a' and lay(win.btn_settings) == ('pack', {'padx': 3, 'side': 'left'}) and any(c == {'menu': ('w', U.id(win.settings_menu))} for c in U.configs(U.id(win.btn_settings))))
entries = [(k['label'], k.get('command'), k.get('menu')) for m, a, k in calls(win.settings_menu) if m in ('add_command', 'add_cascade')]
check('меню настроек: «Конфигурация», «Экспорт подчеркнутых», синхронизация (2 пункта), «Сменить пароль» и подменю «Выбор движка» (его пункты заполняет главное окно)', entries == [('Конфигурация', fn('AppWindow.open_config'), None), ('Экспорт подчеркнутых', fn('AppWindow.export_underlined'), None), ('Папка синхронизации…', fn('AppWindow.choose_sync_folder'), None), ('Синхронизировать с телефоном', fn('AppWindow.sync_with_phone'), None), ('Сменить пароль', fn('AppWindow.change_password_dialog'), None), ('Выбор движка', None, ('w', U.id(win.engine_submenu)))], str(entries))
check('подменю движка — дочернее меню настроек, без «отрывной» полоски', U.new(U.id(win.engine_submenu))[1] == ('w', U.id(win.settings_menu)) and opts(win.engine_submenu)['tearoff'] == 0 and opts(win.settings_menu)['tearoff'] == 0)
check('«Выход»: красная кнопка справа, закрывает программу (on_close)', bopts('Выход')['command'] == fn('AppWindow.on_close') and bopts('Выход')['bg'] == '#b84a4a' and blay('Выход') == ('pack', {'padx': 3, 'side': 'right'}))
# ===================== C. строка статуса =====================
check('строка статуса: колонка 0 растягивается, колонка 1 нет', [(a, k) for m, a, k in calls(win.status_row_frame, 'columnconfigure')] == [((0,), {'weight': 1}), ((1,), {'weight': 0})])
sl, sr = win.scroll_left_btn, win.scroll_right_btn
check('кнопки прокрутки статуса «◄» и «►»: команды _scroll_left/_scroll_right, колонки 0 и 2, плоский вид', opts(sl)['text'] == '◄' and opts(sl)['command'] == fn('AppWindow._scroll_left') and lay(sl) == ('grid', {'column': 0, 'row': 0, 'sticky': 'ns'}) and opts(sr)['text'] == '►' and opts(sr)['command'] == fn('AppWindow._scroll_right') and lay(sr) == ('grid', {'column': 2, 'row': 0, 'sticky': 'ns'}) and opts(sl)['relief'] == 'flat')
check('поле статуса: только для чтения, плоское, в колонке 1 между кнопками прокрутки', opts(win.status_entry)['state'] == 'readonly' and lay(win.status_entry) == ('grid', {'column': 1, 'padx': 2, 'row': 0, 'sticky': 'we'}))
check('полоса прогресса: горизонтальная, длина 200, определённый режим; поставлена в строку статуса и сразу СКРЫТА (показывается только на время работы)', opts(win.progress_bar) == {'orient': 'horizontal', 'length': 200, 'mode': 'determinate'} and [m for m, a, k in calls(win.progress_bar)] == ['grid', 'grid_remove'] and lay(win.progress_bar) == ('grid', {'column': 1, 'padx': 5, 'row': 0, 'sticky': 'we'}))
# ===================== D. левая панель («Совпадения») =====================
check('левая панель: ширина 225 (и в конструкторе, и после)', U.new(left)[2].get('width') == 225 and {'width': 225} in U.configs(left))
check('верхняя панель «Совпадения» занимает левую часть целиком; нижняя (для режима разделения) создана, но НЕ показана', lay(win.word_panel_top_frame) == ('pack', {'expand': True, 'fill': 'both'}) and lay(win.word_panel_bottom_frame) is None and U.new(U.id(win.word_panel_top_frame))[1] == ('w', left) and U.new(U.id(win.word_panel_bottom_frame))[1] == ('w', left))
check('обе панели «Совпадения» (верхняя и нижняя) созданы и знают окно', type(win.word_panel).__name__ == 'WordPanel' and type(win.word_panel_2).__name__ == 'WordPanel' and win.word_panel.main_app is win and win.word_panel_2.main_app is win)
# ===================== E. центр: навигация =====================
nav_frame = [i for i in U.children(center) if U.new(i)[2].get('bg') == '#d4e8f7'][0]
check('центр: сверху полоса навигации, под ней результаты (порядок упаковки)', U.layout(nav_frame) == ('pack', {'fill': 'x', 'padx': 5, 'pady': (5, 5), 'side': 'top'}) and U.position(nav_frame) < U.position(U.id(win.results_paned)))
expected_nav = [(win.btn_first, '<< В начало', 'AppWindow.go_to_first_page', {'padx': 3, 'side': 'left'}), (win.btn_back, '◀ Назад', 'AppWindow.page_back', {'padx': (80, 3), 'side': 'left'}),
                (win.btn_forward, 'Вперед ▶', 'AppWindow.page_forward', {'padx': (3, 80), 'side': 'left'}), (win.btn_last, 'В конец >>', 'AppWindow.go_to_last_page', {'padx': 3, 'side': 'left'})]
for w_, text, command, layout in expected_nav:
    o = opts(w_); check(f'кнопка «{text}»: класс NavButton, команда {command}, стартует выключенной, в полосе навигации слева', U.new(U.id(w_))[0] == 'NavButton' and o['text'] == text and o['command'] == fn(command) and o['state'] == 'disabled' and lay(w_) == ('pack', layout) and U.new(U.id(w_))[1] == ('w', nav_frame), str((o, lay(w_))))
check('порядок кнопок навигации слева направо: «В начало», «Назад», «Вперед», «В конец»', [U.position(U.id(w_)) for w_, *_ in expected_nav] == sorted(U.position(U.id(w_)) for w_, *_ in expected_nav))
check('«КП» (ключевые понятия): команда, цвет, в первой строке слева', bopts('КП')['command'] == fn('AppWindow._add_key_concept') and bopts('КП')['bg'] == '#2a6fbf' and blay('КП') == ('pack', {'padx': (80, 0), 'side': 'left'}))
check('«Ч» (подчеркнуть) — первая кнопка второй строки, подчёркнутый шрифт', bopts('Ч')['command'] == fn('AppWindow._toggle_underline') and bopts('Ч')['font'] == ('Arial', 12, 'bold underline') and blay('Ч') == ('pack', {'padx': (0, 4), 'side': 'left'}))
check('вторая строка слева: «Ч», «A+», «Цвет», «Мысль» — по порядку', [U.position(btn(t)) for t in ('Ч', 'A+', 'Цвет', 'Мысль')] == sorted(U.position(btn(t)) for t in ('Ч', 'A+', 'Цвет', 'Мысль')))
all_ids = U.find('Button', text='Все'); mode_all = [i for i in all_ids if U.layout(i) == ('pack', {'padx': (4, 0), 'side': 'right'})]
check('справа: «Все», «Кратко», «Отметки» — кнопки режимов показа, пакуются справа налево (видны слева направо)', len(mode_all) == 1 and all(blay(t) == ('pack', {'padx': (4, 0), 'side': 'right'}) for t in ('Кратко', 'Отметки')) and U.position(btn('Отметки')) < U.position(btn('Кратко')) < U.position(mode_all[0]))
check('подсказки («Ч», «КП», «Кратко») подключены') if False else check('подсказки («Ч», «КП», «Кратко») подключены (события наведения привязаны)', all('<Enter>' in [a[0] for m, a, k in U.calls(btn(t), 'bind')] for t in ('Ч', 'КП', 'Кратко')))
check('«−В»: кнопка создана, но НЕ упакована (показывает и прячет её окно «Совпадения» вместе с кнопкой 3D/2D)', U.new(btn('−В'))[2]['command'] == fn('AppWindow.toggle_word_variations') and U.layout(btn('−В')) is None and '<Enter>' in [a[0] for m, a, k in U.calls(btn('−В'), 'bind')])
# ===================== F. центр: окна результатов =====================
rp = win.results_paned
check('область результатов: вертикальная панель, занимает остаток центра', opts(rp) == {'orient': 'vertical'} and lay(rp) == ('pack', {'expand': True, 'fill': 'both', 'padx': 5, 'pady': (0, 5), 'side': 'top'}))
radds = [(a[0], k) for m, a, k in calls(rp, 'add')]
check('в вертикальную панель добавлено только ВЕРХНЕЕ окно результатов (вес 1); нижнее добавляется только в режиме разделения', radds == [(('w', U.id(win.results_top_frame)), {'weight': 1})] and U.position(U.id(win.results_bottom_frame)) is None, str(radds))
check('верхняя и нижняя подписи файла (для режима разделения) созданы, но НЕ упакованы', U.layout(U.id(win.results_top_label)) is None and U.layout(U.id(win.results_bottom_label)) is None and opts(win.results_top_label)['anchor'] == 'w')
rt = win.result_text
check('верхнее окно результатов: ScrolledText, перенос по словам, Consolas размера из настроек, на всю область', U.new(U.id(rt))[0] == 'ScrolledText' and opts(rt)['wrap'] == 'word' and opts(rt)['font'] == ('Consolas', win.font_size) and lay(rt) == ('pack', {'expand': True, 'fill': 'both', 'side': 'top'}) and U.new(U.id(rt))[1] == ('w', U.id(win.results_top_frame)))
tags = {a[0]: k for m, a, k in calls(rt, 'tag_configure')}
check('теги верхнего окна: подсветка слова (жёлтый), частичного совпадения (светло-жёлтый) и гиперссылка (синий, подчёркнутый)', tags == {'highlight': {'background': '#FFFF00', 'selectforeground': 'black'}, 'partial': {'background': '#FFFF99', 'selectforeground': 'black'}, 'hyperlink': {'foreground': 'blue', 'underline': True}}, str(tags))
tb = [(a[0], a[1], ) for m, a, k in calls(rt, 'tag_bind')]
check('гиперссылка: рука при наведении и обычный курсор при уходе (лямбды), клик открывает файл топика (on_hyperlink_click)', tb == [('hyperlink', '<Enter>'), ('hyperlink', '<Leave>'), ('hyperlink', '<Button-1>')] and [a[2] for m, a, k in calls(rt, 'tag_bind')] == [fn('<lambda>'), fn('<lambda>'), fn('AppWindow.on_hyperlink_click')], str(calls(rt, 'tag_bind')))
check('правая кнопка мыши в верхнем окне добавляет выделенное в конспект', [(a[0], a[1]) for m, a, k in calls(rt, 'bind')] == [('<Button-3>', fn('AppWindow.append_selection_to_conspect'))])
rt2 = win.result_text_2
tags2 = {a[0] for m, a, k in calls(rt2, 'tag_configure')}
check('нижнее окно результатов (режим разделения): те же подсветки, но БЕЗ гиперссылки (в этом режиме шапок нет); правая кнопка — в конспект', tags2 == {'highlight', 'partial'} and U.new(U.id(rt2))[1] == ('w', U.id(win.results_bottom_frame)) and [(a[0], a[1]) for m, a, k in calls(rt2, 'bind')] == [('<Button-3>', fn('AppWindow.append_selection_to_conspect'))])
check('холст 2D-визуализации создан в верхней области (белый, без рамки), но НЕ упакован — показывается вместо текста по требованию', U.new(U.id(win.vector_viz_canvas))[0] == 'Canvas' and opts(win.vector_viz_canvas) == {'bg': 'white', 'highlightthickness': 0} and U.layout(U.id(win.vector_viz_canvas)) is None and U.new(U.id(win.vector_viz_canvas))[1] == ('w', U.id(win.results_top_frame)))
# ===================== G. правая панель =====================
check('правая панель: ширина 355 (и в конструкторе, и после), НЕ раздувается содержимым (pack_propagate(False))', U.new(right)[2].get('width') == 355 and {'width': 355} in U.configs(right) and U.calls(right, 'pack_propagate')[0][1] == (False,))
top_right, bottom_right, prepare_frame = U.children(right)
check('правая панель: сверху индексы, ниже файлы, внизу кнопки «Редактировать»/«Собрать базу» — все три делят место', U.layout(top_right) == ('pack', {'expand': True, 'fill': 'both', 'padx': 5, 'pady': 5}) and U.layout(bottom_right) == ('pack', {'expand': True, 'fill': 'both', 'padx': 5, 'pady': 5}) and U.layout(prepare_frame) == ('pack', {'fill': 'x', 'padx': 5, 'pady': 5}))
check('заголовок индексов: «Индексы:» и счётчик «(0)»', bool(U.find('Label', text='Индексы:')) and opts(win.selected_count_label)['text'] == '(0)' and lay(win.selected_count_label) == ('pack', {'padx': (4, 8), 'side': 'left'}))
expected_idx = [('Все', 'AppWindow._toggle_select_all', '#4a7a8a', {'padx': 5, 'side': 'left'}), ('Удалить', '<lambda>', '#b84a4a', {'padx': 2, 'side': 'left'}),
                ('Т', 'VisualizationController.show_word_cloud_for_selected', '#6a4a8a', {'padx': 2, 'side': 'left'}), ('Ц', 'VisualizationController.show_textrank_for_selected', '#6a4a8a', {'padx': 2, 'side': 'left'})]
for text, command, color, layout in expected_idx:
    check(f'кнопка индексов «{text}»: команда {command}, цвет {color}', bopts(text)['command'] == fn(command) and bopts(text)['bg'] == color and blay(text) == ('pack', layout), str((bopts(text), blay(text))))
check('«Т» и «Ц» привязаны к методам КОНТРОЛЛЕРА визуализаций и снабжены подсказками', bopts('Т')['command'] == ('fn', 'VisualizationController.show_word_cloud_for_selected') and all('<Enter>' in [a[0] for m, a, k in U.calls(btn(t), 'bind')] for t in ('Т', 'Ц')))
cl = win.index_check_list
check('список индексов: настоящий IndexCheckList под заголовком, без обратного вызова (его подключает менеджер индексов), на всё место; для движка Manticore — множественный выбор', type(cl).__name__ == 'IndexCheckList' and cl.single_select is False and lay(cl) == ('pack', {'expand': True, 'fill': 'both'}) and U.new(U.id(cl))[1] == ('w', top_right))
check('заголовок файлов: «Файлы:», кнопки «▲ В индекс» (_add_to_index) и «▲ Векторы» (prepare_vectors) слева', bool(U.find('Label', text='Файлы:')) and bopts('▲ В индекс')['command'] == fn('AppWindow._add_to_index') and bopts('▲ Векторы')['command'] == fn('AppWindow.prepare_vectors') and blay('▲ В индекс') == ('pack', {'padx': 3, 'side': 'left'}) and blay('▲ Векторы') == ('pack', {'padx': 3, 'side': 'left'}))
lb = win.text_listbox
check('список файлов: Listbox с выбором нескольких (Ctrl/Shift), Consolas, белый фон, на всё место; выбор и правый клик привязаны', U.new(U.id(lb))[0] == 'Listbox' and opts(lb) == {'font': ('Consolas', win.font_size), 'bg': 'white', 'fg': '#1a2a3a', 'selectmode': 'extended'} and lay(lb) == ('pack', {'expand': True, 'fill': 'both'}) and [(a[0], a[1]) for m, a, k in calls(lb, 'bind')] == [('<<ListboxSelect>>', fn('AppWindow._on_text_select')), ('<Button-3>', fn('AppWindow._on_text_right_click'))], str(calls(lb, 'bind')))
check('кнопки «Редактировать» и «Собрать базу» внизу правой панели слева направо', bopts('Редактировать')['command'] == fn('AppWindow._open_selected_file') and bopts('Собрать базу')['command'] == fn('AppWindow.open_file_merger') and blay('Редактировать') == ('pack', {'side': 'left'}) and blay('Собрать базу') == ('pack', {'padx': (5, 0), 'side': 'left'}) and U.position(btn('Редактировать')) < U.position(btn('Собрать базу')))
# ===================== H. итог =====================
ran = 0
for func, args in list(tk.AFTER_QUEUE):
    if getattr(func, '__name__', '') == '_do_update': func(*args); ran += 1
check('в конце построения в строку статуса записано «Готов к работе»', win.status_entry._text == 'Готов к работе' and ran >= 1, str(win.status_entry._text))
U2 = ui_trace.build(aw, 'fts5')
check('для движка FTS5 список индексов — с выбором одного индекса (single_select)', U2.win.index_check_list.single_select is True)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
