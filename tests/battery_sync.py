import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import tempfile, time
from services.marks import MarksStore, mark_uid
from services import sync_folder as S

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

t = tempfile.mkdtemp(prefix='sync_')
drive = os.path.join(t, 'drive'); os.makedirs(drive)
A, B = MarksStore(os.path.join(t, 'a.db')), MarksStore(os.path.join(t, 'b.db'))
ka, kb = os.path.join(t, 'a_k.txt'), os.path.join(t, 'b_k.txt')
A.add_mark('DB\\Bibl.txt', 'слово', 'до ', ' после'); A.add_mark('x.txt', 'два', '', '')
open(ka, 'w', encoding='utf-8').write('.......цитата\n(bibl)\n')
S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba'))
r = S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb'))
check('отметки и конспект пришли на второе устройство', r['marks_added'] == 2 and len(B.all_marks()) == 2 and open(kb, encoding='utf-8').read() == '.......цитата\n(bibl)\n')
check('идентификатор отметки = sha1(файл, фрагмент, до, после)[:20], как в Синева Mobile', mark_uid('bibl.txt', 'слово', 'до ', ' после') == '15fb24d397127e333da8')
B.delete_marks([m.id for m in B.all_marks() if m.fragment == 'слово'])
S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb'))
r = S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba'))
check('снятие подчёркивания доходит до другого устройства', r['marks_removed'] == 1 and [m.fragment for m in A.all_marks()] == ['два'])
time.sleep(1.1)
A.add_mark('bibl.txt', 'слово', 'до ', ' после')
S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba')); S.sync_with_folder(drive, B, kb, os.path.join(t, 'bb'))
check('повторное подчёркивание после снятия снова живёт', sorted(m.fragment for m in B.all_marks()) == ['два', 'слово'])
try:
    S.sync_with_folder(os.path.join(t, 'нет'), A, ka, os.path.join(t, 'ba')); check('нет папки -> ошибка', False)
except FileNotFoundError:
    check('нет папки -> ошибка, данные целы', len(A.all_marks()) == 2)
# переустановка: пустые дневник и подчёркивания принимают накопленное из папки и ничего в ней не обнуляют
N = MarksStore(os.path.join(t, 'n.db')); nd, nk = os.path.join(t, 'n_d.txt'), os.path.join(t, 'n_k.txt')
open(os.path.join(t, 'a_d.txt'), 'wb').write('запись 1\n'.encode())
S.sync_with_folder(drive, A, ka, os.path.join(t, 'ba'), os.path.join(t, 'a_d.txt'))
open(nd, 'wb').close()
S.sync_with_folder(drive, N, nk, os.path.join(t, 'bn'), nd)
check('переустановка: пустой дневник и подчёркивания приняли данные папки',
      open(nd, 'rb').read() == 'запись 1\n'.encode() and len(N.all_marks()) == 2 and open(nk, 'rb').read() == open(ka, 'rb').read())
check('переустановка: в папке ничего не обнулено', open(os.path.join(drive, 'dnev.txt'), 'rb').read() == 'запись 1\n'.encode()
      and len(__import__('json').loads(open(os.path.join(drive, 'sineva_marks.json'), 'rb').read())['marks']) == 2)
N.close(); A.close(); B.close()
print(f"Проверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
