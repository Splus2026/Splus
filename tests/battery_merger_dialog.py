import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, os, time, shutil, tempfile
import tkinter as tk
assert 'fake_tk' in tk.__file__, "должна использоваться заглушка"

from ui import file_merger_dialog as fmd
from utils import file_merger as fm

# Данные проверки копируются во временную папку: батарея пишет рядом с ними (битые файлы, результаты склейки).
WORK = os.path.normpath(env.tmpdir('merge_'))
SRC = os.path.join(WORK, 'src'); shutil.copytree(os.path.join(env.DATA, 'merger_src'), SRC)
import importlib.util
# PDF читается через pypdf (или PyPDF2) — это необязательная зависимость проекта: без неё файл f.pdf просто не берётся в проверку.
HAVE_PDF = bool(importlib.util.find_spec('pypdf') or importlib.util.find_spec('PyPDF2'))
MIX = ['a.txt', 'b.txt', 'e.docx'] + (['f.pdf'] if HAVE_PDF else []) + ['c.txt']
results = []
def check(name, cond, detail=''):
    results.append(cond)
    print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

# ---------- заглушки messagebox / filedialog ----------
class FakeMB:
    def __init__(self): self.calls = []; self.answers = {}; self.timeline = None
    def _rec(self, kind, title, message, **kw):
        self.calls.append((kind, title, message))
        if self.timeline is not None: self.timeline.append(('msg', kind))
        return self.answers.get(kind, True)
    def showinfo(self, t, m, **k): return self._rec('showinfo', t, m)
    def showwarning(self, t, m, **k): return self._rec('showwarning', t, m)
    def showerror(self, t, m, **k): return self._rec('showerror', t, m)
    def askyesno(self, t, m, **k): return self._rec('askyesno', t, m)
    def kinds(self): return [c[0] for c in self.calls]

class FakeFD:
    def __init__(self): self.opts = []; self.files = (); self.folder = ''; self.save = ''
    def askopenfilenames(self, **kw): self.opts.append(('files', kw)); return self.files
    def askdirectory(self, **kw): self.opts.append(('dir', kw)); return self.folder
    def asksaveasfilename(self, **kw): self.opts.append(('save', kw)); return self.save

def pump(dlg, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        batch = list(tk.AFTER_QUEUE); tk.AFTER_QUEUE.clear()
        for f, a in batch: f(*a)
        if not dlg._is_processing: 
            batch = list(tk.AFTER_QUEUE); tk.AFTER_QUEUE.clear()
            for f, a in batch: f(*a)
            return True
        time.sleep(0.01)
    return False

def make(source='', output='DB', out_tmp=None):
    mb, fd = FakeMB(), FakeFD()
    fmd.messagebox, fmd.filedialog = mb, fd
    tk.AFTER_QUEUE.clear()
    rec = {'dirs': [], 'merged': []}
    dlg = fmd.FileMergerDialog(
        parent=tk.Toplevel(),
        initial_source_dir=source, initial_output_dir=output,
        on_dirs_changed=lambda **kw: rec['dirs'].append(kw),
        on_merged=lambda p: rec['merged'].append(p))
    return dlg, mb, fd, rec

def fresh_out():
    d = tempfile.mkdtemp(prefix='out_', dir=WORK); return d

# ======================= 1. начальное состояние =======================
dlg, mb, fd, rec = make(source=SRC, output='DB')
check('галочка «Открыть объединённый файл» стоит по умолчанию', dlg.open_after_merge.get() is True)
check('в поле разделителя по умолчанию пунктирная линия', dlg.separator_var.get() == '-' * 70 and len(dlg.separator_var.get()) > 0)
check('выходной файл по умолчанию — в подкаталоге DB', dlg.output_file.get() == os.path.join('DB', 'out.txt'), dlg.output_file.get())
check('формат по умолчанию TXT', dlg.output_format.get() == 'txt')
check('окно модальное (grab_set вызван)', dlg.root.grab_calls >= 1)

# ======================= 2. добавление файлов + запоминание папки =======================
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'), os.path.join(SRC, 'note.rtf'))
dlg.add_files()
check('askopenfilenames открылся в запомненной папке', fd.opts[-1][1].get('initialdir') == SRC, str(fd.opts[-1][1]))
check('добавлены 2 поддерживаемых, .rtf отвергнут', [os.path.basename(p) for p in dlg.files] == ['a.txt', 'b.txt'], str(dlg.files))
check('папка выбора запомнена через колбэк', rec['dirs'] and rec['dirs'][-1] == {'source_dir': SRC, 'output_dir': None}, str(rec['dirs']))
check('в списке имя + папка', all('—' in s for s in dlg.file_listbox.items) and 'a.txt' in dlg.file_listbox.items[0])
n_before = len(dlg.files)
dlg.add_files()  # те же файлы ещё раз
check('повторное добавление не плодит дубликаты', len(dlg.files) == n_before and dlg.file_listbox.size() == n_before)
fd.files = ''.join([os.path.join(SRC, 'c.txt'), '|', os.path.join(SRC, 'd.txt')])   # Tk иногда отдаёт строку
dlg.add_files()
check('строка вместо кортежа (особенность некоторых Tk) обработана', [os.path.basename(p) for p in dlg.files][-2:] == ['c.txt', 'd.txt'], str(dlg.files))
check('счётчики обновились', dlg.file_count_label.cget('text') == f'Файлов: {len(dlg.files)}')

# запомненной папки больше нет -> ближайшая существующая; если вообще нет -> без initialdir
dlg2, mb2, fd2, rec2 = make(source=os.path.join(SRC, 'удалённая', 'глубже'))
fd2.files = ()
dlg2.add_files()
check('исчезнувшая папка: подсказка = ближайший существующий родитель', fd2.opts[-1][1].get('initialdir') == SRC, str(fd2.opts[-1][1]))
dlg3, mb3, fd3, rec3 = make(source='')
dlg3.add_files()
check('нет запомненной папки: initialdir не передаётся', 'initialdir' not in fd3.opts[-1][1], str(fd3.opts[-1][1]))

# ======================= 3. добавление папки =======================
dlg4, mb4, fd4, rec4 = make(source=WORK)
fd4.folder = SRC
dlg4.add_folder()
names = [os.path.basename(p) for p in dlg4.files]
check('из папки взяты только поддерживаемые файлы', 'note.rtf' not in names and 'old.doc' not in names and '~$e.docx' not in names, str(names))
check('папка отсортирована естественно: глава1, глава2, глава10',
      [n for n in names if n.startswith('глава')] == ['глава1.txt', 'глава2.txt', 'глава10.txt'], str(names))
check('папка запомнена (сама папка)', rec4['dirs'][-1]['source_dir'] == SRC, str(rec4['dirs']))
check('askdirectory открылся в запомненной папке', fd4.opts[-1][1].get('initialdir') == WORK)
# выбор отмены
fd4.folder = ''
cnt = len(dlg4.files); dlg4.add_folder()
check('отмена выбора папки ничего не меняет', len(dlg4.files) == cnt)

# ======================= 4. удаление / очистка =======================
dlg4.file_listbox.selection_set(0); dlg4.file_listbox.selection_set(1)
total = len(dlg4.files)
dlg4.remove_selected()
check('удалены выбранные', len(dlg4.files) == total - 2 and dlg4.file_listbox.size() == total - 2)
check('ключи дубликатов синхронны (удалённый файл можно добавить снова)', len(dlg4._file_keys) == len(dlg4.files))
dlg4.clear_all()
check('очистка списка', dlg4.files == [] and dlg4.file_listbox.size() == 0 and not dlg4._file_keys)

# ======================= 5. полная склейка: пунктир =======================
out = fresh_out()
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = tuple(os.path.join(SRC, n) for n in MIX)
dlg.add_files()
timeline = []; mb.timeline = timeline
dlg._open_file = lambda p: timeline.append(('open', p))
check('путь по умолчанию в выбранной папке', dlg.output_file.get() == os.path.join(out, 'out.txt'))
dlg.process_files()
check('рабочий поток завершился', pump(dlg))
outp = os.path.join(out, 'out.txt')
check('файл создан', os.path.exists(outp))
got = open(outp, encoding='utf-8').read().replace('\r\n', '\n')
texts = [fm.read_source_text(os.path.join(SRC, n)) for n in MIX]
expected = fm.merge_texts(texts, '-' * 70)
check('содержимое = ровно тексты файлов + пунктирные строки между ними', got == expected, repr(got[:200]))
check(f'между {len(MIX)} файлами ровно {len(MIX) - 1} разделителя', got.count('\n' + '-' * 70 + '\n') == len(MIX) - 1, str(got.count('-' * 70)))
check('в результате нет ни шапки, ни имён/путей, ни пометок страниц',
      not any(w in got for w in ('ОБЪЕДИНЕН', 'ФАЙЛ:', 'ПУТЬ', 'КОНЕЦ', 'Создан', 'Страница 1 из', 'a.txt', SRC)), repr(got[:300]))
check('BOM из b.txt не попал в середину результата', '\ufeff' not in got)
check('сообщение «Готово» показано', mb.kinds() == ['showinfo'], str(mb.calls))
check('файл открыт ПОСЛЕ сообщения, а не до него', timeline == [('msg', 'showinfo'), ('open', outp)], str(timeline))
check('папка результата запомнена', rec['dirs'][-1] == {'source_dir': None, 'output_dir': out}, str(rec['dirs'][-1]))
check('on_merged вызван с путём результата', rec['merged'] == [outp], str(rec['merged']))
check('кнопки снова доступны', dlg.process_btn.cget('state') == 'normal' and all(b.cget('state') == 'normal' for b in dlg._file_buttons))
check('прогресс 100%', dlg.progress_var.get() == 100)
check('нет временного файла .part', not os.path.exists(outp + '.part'))

# ======================= 6. пустой разделитель, галочка снята =======================
out = fresh_out()
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'))
dlg.add_files()
opened = []; dlg._open_file = lambda p: opened.append(p)
dlg.separator_var.set('')
dlg.open_after_merge.set(False)
dlg.process_files(); pump(dlg)
got = open(os.path.join(out, 'out.txt'), encoding='utf-8').read().replace('\r\n', '\n')
check('пустое поле разделителя: файлы разделены ровно одной пустой строкой',
      got == "Первая книга\nстрока 2\n\nВторая книга без перевода строки\n", repr(got))
check('галочка снята — файл не открывается', opened == [])

# ======================= 7. DOCX-результат, смена формата меняет расширение =======================
out = fresh_out()
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'))
dlg.add_files()
dlg.output_format.set('docx'); dlg._on_format_changed()
check('смена формата меняет расширение в поле', dlg.output_file.get().endswith('out.docx'), dlg.output_file.get())
dlg._open_file = lambda p: None
dlg.process_files(); pump(dlg)
from utils.text_processing import read_text_file
d = read_text_file(os.path.join(out, 'out.docx'), keep_empty_docx_paragraphs=True)
check('docx-результат читается и содержит разделитель между файлами', '-' * 70 in d and 'Первая книга' in d and 'Вторая книга' in d, repr(d))

# ======================= 8. выходной файл = один из исходных =======================
out = fresh_out()
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'))
dlg.add_files()
before = open(os.path.join(SRC, 'a.txt'), 'rb').read()
dlg.output_file.set(os.path.join(SRC, 'a.txt'))
dlg.process_files()
check('совпадение с исходным: показана ошибка, склейка не запущена', mb.kinds() == ['showerror'] and not dlg._is_processing, str(mb.calls))
check('исходный файл не тронут', open(os.path.join(SRC, 'a.txt'), 'rb').read() == before)

# ======================= 9. перезапись существующего =======================
out = fresh_out()
existing = os.path.join(out, 'out.txt')
open(existing, 'w', encoding='utf-8').write('СТАРОЕ')
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'))
dlg.add_files(); dlg._open_file = lambda p: None
mb.answers['askyesno'] = False
dlg.process_files()
check('отказ от перезаписи: склейка не запущена, файл цел', mb.kinds() == ['askyesno'] and open(existing, encoding='utf-8').read() == 'СТАРОЕ' and not dlg._is_processing)
mb.calls.clear(); mb.answers['askyesno'] = True
dlg.process_files(); pump(dlg)
check('согласие на перезапись: файл перезаписан', 'Первая книга' in open(existing, encoding='utf-8').read())

# ======================= 10. нечитаемый файл среди прочих =======================
out = fresh_out()
bad_docx = os.path.join(SRC, 'битый.docx')
open(bad_docx, 'wb').write('это не docx'.encode('utf-8'))
empty_txt = os.path.join(SRC, 'пустой.txt')
open(empty_txt, 'w').write('   \n\n')
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), bad_docx, empty_txt, os.path.join(SRC, 'b.txt'))
dlg.add_files(); dlg._open_file = lambda p: None
dlg.process_files(); pump(dlg)
got = open(os.path.join(out, 'out.txt'), encoding='utf-8').read().replace('\r\n', '\n')
check('нечитаемый и пустой файлы пропущены, остальные склеены',
      got == fm.merge_texts(["Первая книга\nстрока 2\n", "Вторая книга без перевода строки"], '-' * 70), repr(got))
check('ошибка чтения НЕ вписана в результат', 'Ошибка' not in got and 'битый' not in got and 'пустой' not in got and '⚠' not in got and '❌' not in got)
check('итог — предупреждение о пропущенных, с числом', mb.kinds() == ['showwarning'] and 'из 4' in mb.calls[0][2] and 'ПРОПУЩЕНО файлов: 2' in mb.calls[0][2], str(mb.calls))
check('в журнале есть красная запись об ошибке', any(tag == 'error' for _, tag in dlg.log_text.tagged))
os.remove(bad_docx); os.remove(empty_txt)

# ======================= 11. ни один файл не прочитан =======================
out = fresh_out()
open(bad_docx, 'wb').write(b'x')
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (bad_docx,)
dlg.add_files(); dlg._open_file = lambda p: None
dlg.process_files(); pump(dlg)
check('всё нечитаемо: ошибка, файл не создан, кнопки разблокированы',
      mb.kinds() == ['showerror'] and not os.path.exists(os.path.join(out, 'out.txt')) and dlg.process_btn.cget('state') == 'normal')
check('при ошибке on_merged и запоминание output не вызываются', rec['merged'] == [] and not any(d.get('output_dir') for d in rec['dirs']))
os.remove(bad_docx)

# ======================= 12. выходная папка не существует — создаётся =======================
out = fresh_out()
newdir = os.path.join(out, 'новая', 'вложенная')
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'),); dlg.add_files(); dlg._open_file = lambda p: None
dlg.output_file.set(os.path.join(newdir, 'база'))      # без расширения!
dlg.process_files(); pump(dlg)
check('несуществующая папка создана, расширение дописано', os.path.exists(os.path.join(newdir, 'база.txt')))

# ======================= 13. только имя без папки + подкаталог DB =======================
work = tempfile.mkdtemp(prefix='cwd_', dir=WORK); os.makedirs(os.path.join(work, 'DB'))
old_cwd = os.getcwd(); os.chdir(work)
try:
    dlg, mb, fd, rec = make(source=SRC, output='DB')
    fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt')); dlg.add_files(); dlg._open_file = lambda p: None
    dlg.process_files(); pump(dlg)
    check('по умолчанию результат лёг в подкаталог DB', os.path.exists(os.path.join(work, 'DB', 'out.txt')))
    check("папка DB запоминается как относительная 'DB' (не абсолютным путём)", rec['dirs'][-1]['output_dir'] == 'DB', str(rec['dirs'][-1]))
    # только имя файла
    dlg.output_file.set('моя_база'); mb.calls.clear()
    dlg.process_files(); pump(dlg)
    check('задано только имя — кладётся в текущую папку результата (DB)', os.path.exists(os.path.join(work, 'DB', 'моя_база.txt')))
    # другая папка -> становится папкой по умолчанию
    other = os.path.join(work, 'другая'); os.makedirs(other)
    dlg.output_file.set(os.path.join(other, 'x.txt'))
    dlg.process_files(); pump(dlg)
    check('результат в другую папку — она запомнена как новая по умолчанию', rec['dirs'][-1]['output_dir'] == os.path.abspath(other), str(rec['dirs'][-1]))
    check('on_merged получил путь во второй папке', rec['merged'][-1] == os.path.join(os.path.abspath(other), 'x.txt'))
    dlg5, *_ = make(source=SRC, output=os.path.abspath(other))
    check('следующее открытие окна: поле по умолчанию указывает на запомненную папку', dlg5.output_file.get() == os.path.join(os.path.abspath(other), 'out.txt'), dlg5.output_file.get())
finally:
    os.chdir(old_cwd)

# ======================= 14. кнопка «Выбрать» выходной файл =======================
dlg, mb, fd, rec = make(source=SRC, output=WORK)
fd.save = os.path.join(WORK, 'выбранный', 'итог.txt')
dlg.select_output_file()
check('«Выбрать»: путь попал в поле', dlg.output_file.get() == os.path.normpath(os.path.join(WORK, 'выбранный', 'итог.txt')), dlg.output_file.get())
check('«Выбрать»: диалог открылся с подсказкой имени и расширением по формату',
      fd.opts[-1][1]['initialfile'] == 'out.txt' and fd.opts[-1][1]['defaultextension'] == '.txt', str(fd.opts[-1][1]))
check('«Выбрать» само по себе папку НЕ запоминает (только успешная склейка)', not any(d.get('output_dir') for d in rec['dirs']))
fd.save = ''
before = dlg.output_file.get(); dlg.select_output_file()
check('отмена «Выбрать» ничего не меняет', dlg.output_file.get() == before)

# ======================= 15. нет файлов / нет имени =======================
dlg, mb, fd, rec = make(source=SRC, output=WORK)
dlg.process_files()
check('пустой список: предупреждение, поток не запущен', mb.kinds() == ['showwarning'] and not dlg._is_processing)
fd.files = (os.path.join(SRC, 'a.txt'),); dlg.add_files(); mb.calls.clear()
dlg.output_file.set('   ')
dlg.process_files()
check('пустое имя файла: предупреждение', mb.kinds() == ['showwarning'] and not dlg._is_processing)

# ======================= 15б. «Копировать в папку DB» =======================
work = tempfile.mkdtemp(prefix='mv_', dir=WORK); os.makedirs(os.path.join(work, 'DB')); srcm = os.path.join(work, 'ист'); os.makedirs(srcm)
for n in ('p.txt', 'q.txt'): open(os.path.join(srcm, n), 'w', encoding='utf-8').write(n)
open(os.path.join(work, 'DB', 'q.txt'), 'w', encoding='utf-8').write('старый')
old_cwd = os.getcwd(); os.chdir(work)
try:
    moved_rec = []
    dlg, mb, fd, rec = make(source=srcm, output='DB'); dlg.on_files_moved = lambda ps: moved_rec.append(ps)
    dlg.move_to_db()
    check('копирование: пустой список — предупреждение', mb.kinds() == ['showwarning'])
    mb.calls.clear(); mb.answers['askyesno'] = False
    fd.files = (os.path.join(srcm, 'p.txt'), os.path.join(srcm, 'q.txt')); dlg.add_files(); mb.calls.clear()
    dlg.move_to_db()
    check('копирование: отказ в подтверждении — в DB ничего нового', not os.path.exists(os.path.join(work, 'DB', 'p.txt')) and mb.kinds() == ['askyesno'])
    mb.calls.clear(); mb.answers['askyesno'] = True
    dlg.move_to_db()
    check('копирование: файлы скопированы в DB, исходные ОСТАЛИСЬ на месте, совпавшее имя заменено',
          os.path.exists(os.path.join(srcm, 'p.txt')) and os.path.exists(os.path.join(srcm, 'q.txt'))
          and open(os.path.join(work, 'DB', 'p.txt'), encoding='utf-8').read() == 'p.txt'
          and open(os.path.join(work, 'DB', 'q.txt'), encoding='utf-8').read() == 'q.txt')
    check('копирование: список окна не изменился (пути исходные), главное окно уведомлено', all(os.path.dirname(p) == os.path.abspath(srcm) for p in dlg.files) and len(moved_rec) == 1 and len(moved_rec[0]) == 2)
finally:
    os.chdir(old_cwd)

# ======================= 16. закрытие окна =======================
dlg, mb, fd, rec = make(source=SRC, output=WORK)
dlg._on_close()
check('закрытие в покое — окно уничтожено', dlg.root.destroyed)

# ======================= 17. прерывание посреди обработки =======================
out = fresh_out()
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = tuple(os.path.join(SRC, n) for n in ['a.txt', 'b.txt', 'c.txt', 'd.txt'])
dlg.add_files(); dlg._open_file = lambda p: None
orig_read = fm.read_source_text
fm.read_source_text = lambda p: (time.sleep(0.25), orig_read(p))[1]
try:
    dlg.process_files()
    time.sleep(0.3); 
    batch = list(tk.AFTER_QUEUE); tk.AFTER_QUEUE.clear()
    for f, a in batch: f(*a)
    mb.answers['askyesno'] = True
    dlg._on_close()   # пользователь жмёт крестик посреди работы и подтверждает
    check('закрытие посреди работы не закрывает окно мгновенно (поток ещё пишет в очередь)', not dlg.root.destroyed and dlg._close_after_finish)
    pump(dlg)
finally:
    fm.read_source_text = orig_read
check('после прерывания окно закрыто, файл не создан',
      dlg.root.destroyed and not os.path.exists(os.path.join(out, 'out.txt')))
# отказ от прерывания
dlg, mb, fd, rec = make(source=SRC, output=out)
fd.files = (os.path.join(SRC, 'a.txt'), os.path.join(SRC, 'b.txt'), os.path.join(SRC, 'c.txt')); dlg.add_files(); dlg._open_file = lambda p: None
fm.read_source_text = lambda p: (time.sleep(0.15), orig_read(p))[1]
try:
    dlg.process_files(); time.sleep(0.1)
    mb.answers['askyesno'] = False
    dlg._on_close()
    check('отказ от прерывания: работа продолжается', dlg._is_processing and not dlg._close_after_finish and not dlg._cancel_event.is_set() and not dlg.root.destroyed)
    pump(dlg)
finally:
    fm.read_source_text = orig_read
check('и успешно завершается', os.path.exists(os.path.join(out, 'out.txt')) and not dlg.root.destroyed)

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
