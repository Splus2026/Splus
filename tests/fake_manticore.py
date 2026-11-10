"""Подставной «SQL-сервер Manticore» для тестов движка: хранит таблицы в памяти и понимает ровно те запросы, что отправляет
   engines/manticore_engine.py (SHOW/CREATE/DROP TABLE, INSERT пачками с экранированием, SELECT по id, постраничное чтение,
   MAX(id), MATCH-поиск). Видно, что реально записано в таблицы, а не только какие запросы ушли. Отказы задаются через
   Server.fail_when(sql) -> bool. Экранирование соединения повторяет драйвер pymysql (escape_string)."""
import re

ESC = {'\0': '\\0', '\n': '\\n', '\r': '\\r', '\x1a': '\\Z', '"': '\\"', "'": "\\'", '\\': '\\\\'}
UNESC = {'0': '\0', 'n': '\n', 'r': '\r', 'Z': '\x1a', '"': '"', "'": "'", '\\': '\\'}
MAX_MATCHES = 1000     # предел сервера на выдачу за один запрос: больший LIMIT он молча обрезает

class Server:
    def __init__(self, tables=None):
        self.tables = {n: dict(rows) for n, rows in (tables or {}).items()}; self.sql = []; self.fail_when = None; self.autocommit_log = []; self.commits = 0
    def run(self, sql):
        self.sql.append(sql)
        if self.fail_when and self.fail_when(sql): raise RuntimeError('сервер отказал')
        s = ' '.join(sql.split())
        if s == 'SHOW TABLES': return [(n, 'rt') for n in self.tables]
        m = re.match(r'DROP TABLE (`(?:[^`]|``)*`)$', s)
        if m:
            n = self._ident(m.group(1))
            if n not in self.tables: raise RuntimeError(f'unknown table {n}')
            del self.tables[n]; return []
        m = re.match(r'CREATE TABLE (`(?:[^`]|``)*`) \( id bigint, section_id int, section_text text, file_name text, position text \) type=\'rt\' charset_table=\'non_cjk\' min_infix_len=\'2\'$', s)
        if m:
            n = self._ident(m.group(1))
            if n in self.tables: raise RuntimeError(f'table {n} already exists')
            self.tables[n] = {}; return []
        m = re.match(r'INSERT INTO (`(?:[^`]|``)*`) \(id, section_id, section_text, file_name, position\) VALUES (.*)$', sql.strip(), re.S)
        if m: return self._insert(self._ident(m.group(1)), m.group(2))
        m = re.match(r'SELECT section_text FROM (`(?:[^`]|``)*`) WHERE id = (\d+)$', s)
        if m: return [(self._table(m.group(1))[int(m.group(2))][0],)] if int(m.group(2)) in self._table(m.group(1)) else []
        m = re.match(r'SELECT section_text, file_name, position FROM (`(?:[^`]|``)*`) WHERE id = (\d+)$', s)
        if m: return [self._table(m.group(1))[int(m.group(2))]] if int(m.group(2)) in self._table(m.group(1)) else []
        m = re.match(r'SELECT MAX\(id\) FROM (`(?:[^`]|``)*`)$', s)
        if m: t = self._table(m.group(1)); return [(max(t) if t else None,)]
        m = re.match(r'SELECT id, section_text, file_name FROM (`(?:[^`]|``)*`) WHERE id > (\d+) ORDER BY id ASC LIMIT (\d+)$', s)
        if m:
            t = self._table(m.group(1)); ids = sorted(i for i in t if i > int(m.group(2)))[:min(int(m.group(3)), MAX_MATCHES)]
            return [(i, t[i][0], t[i][1]) for i in ids]
        m = re.match(r'SELECT id, section_text, file_name, position, WEIGHT\(\) as weight FROM (.+?) WHERE MATCH\(\'@\(section_text\) (.+?)\'\) LIMIT (\d+) OPTION ranker=bm25, field_weights=\(section_text=10\)$', s)
        if m: return self._match(m.group(1), m.group(2), int(m.group(3)))
        raise AssertionError('сервер не знает запрос: ' + s[:120])
    @staticmethod
    def _ident(q): return q[1:-1].replace('``', '`')
    def _table(self, q):
        n = self._ident(q)
        if n not in self.tables: raise RuntimeError(f'unknown table {n}')
        return self.tables[n]
    def _insert(self, name, values):
        if name not in self.tables: raise RuntimeError(f'unknown table {name}')
        rows, i, n = [], 0, len(values)
        while i < n:
            assert values[i] == '(', values[i - 5:i + 5]; i += 1; fields = []
            while True:
                if values[i] == "'":
                    i += 1; buf = []
                    while values[i] != "'":
                        if values[i] == '\\': buf.append(UNESC[values[i + 1]]); i += 2
                        else: buf.append(values[i]); i += 1
                    i += 1; fields.append(''.join(buf))
                else:
                    j = i
                    while values[j] not in ',)': j += 1
                    fields.append(int(values[i:j])); i = j
                if values[i] == ',': i += 2; continue
                break
            assert values[i] == ')'; i += 1; rows.append(fields)
            if i < n: assert values[i:i + 2] == ', '; i += 2
        for f in rows:
            if f[0] in self.tables[name]: raise RuntimeError(f'duplicate id {f[0]}')
        for f in rows: self.tables[name][f[0]] = (f[2], f[3], f[4])
        return []
    def _match(self, from_clause, expr, limit):
        names = [self._ident(x.strip()) for x in re.findall(r'`(?:[^`]|``)*`', from_clause)]
        terms = expr.split(' | '); found = []
        for n in names:
            if n not in self.tables: raise RuntimeError(f'unknown table {n}')
            for rid, (text, fname, pos) in self.tables[n].items():
                low = text.lower(); w = 0
                for term in terms:
                    t = term.strip('*').lower()
                    if term.startswith('*'): w += low.count(t)
                    else: w += re.findall(r'\w+', low).count(t)
                if w: found.append((w, rid, text, fname, pos))
        found.sort(key=lambda x: -x[0])
        return [(rid, text, fname, pos, w) for w, rid, text, fname, pos in found[:limit]]

class Cursor:
    def __init__(self, server): self.server = server; self.rows = []; self.pos = 0
    def execute(self, sql): self.rows = self.server.run(sql); self.pos = 0
    def fetchall(self): return list(self.rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def close(self): pass
class Conn:
    def __init__(self, server): self.server = server; self.escape_fails_on = None
    def cursor(self): return Cursor(self.server)
    def escape_string(self, s):
        if self.escape_fails_on is not None and self.escape_fails_on in s: raise RuntimeError('не удалось экранировать')
        return ''.join(ESC.get(c, c) for c in s)
    def autocommit(self, v): self.server.autocommit_log.append(v)
    def commit(self): self.server.commits += 1
    def close(self): pass
