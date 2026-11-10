"""Работа с Excel-файлами (.xlsx) для индексации и поиска — отдельный модуль,
   чтобы не усложнять основной пайплайн чтения текстовых файлов и .docx в
   utils/text_processing.py: у Excel принципиально другая модель:

   - индексация и поиск ведутся только по ПЕРВОМУ листу файла;
   - каждая строка листа — это один топик (разделитель 'ExcelRow1');
   - строки, содержащие заданную подстроку-маркер (задаётся в конфигурации
     третьим полем после алиаса и разделителя), исключаются из
     индекса/поиска/результатов;
   - у топиков нет "шапки" и, соответственно, нет перехода по гиперссылке на
     файл-источник (в отличие от .txt/.docx) — это учитывается в
     services/search_controller.py и ui/results_renderer.py по расширению
     файла, а не здесь."""

import openpyxl

CELL_SEPARATOR = " | "


def _row_to_text(row_cells) -> str:
    """Склеивает непустые ячейки строки в одну строку текста."""
    parts = []
    for cell in row_cells:
        if cell is None:
            continue
        # Внутри ячейки бывают переводы строк (Alt+Enter). Строка листа — ОДИН топик, поэтому в тексте она
        # должна остаться одной строкой: иначе разбиение по строкам (ExcelRow1) разрезало бы её на несколько
        # топиков, и вторая часть (без названия товара, цены) жила бы отдельным результатом.
        text = ' '.join(part.strip() for part in str(cell).splitlines() if part.strip())
        if text:
            parts.append(text)
    return CELL_SEPARATOR.join(parts)


def read_excel_rows(file_path: str, exclude_substring: str = '') -> list:
    """Возвращает список строк текста — по одной на каждую непустую строку
       ПЕРВОГО листа файла, кроме тех, что содержат exclude_substring (если
       задан). Полностью пустые строки (после склейки ячеек) пропускаются."""
    exclude_substring = (exclude_substring or '').strip()
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        sheet = wb.worksheets[0]
        # Некоторые программы пишут в файл неверную «размерность» листа (например, A1 вместо A1:B7); в режиме
        # read_only openpyxl тогда читает только её, и остальные строки молча пропадают из индекса. Сбрасываем
        # размерность — читаются все строки (для исправных файлов ничего не меняется).
        reset_dimensions = getattr(sheet, 'reset_dimensions', None)
        if reset_dimensions:
            reset_dimensions()
        rows_text = []
        for row in sheet.iter_rows(values_only=True):
            text = _row_to_text(row)
            if not text:
                continue
            if exclude_substring and exclude_substring in text:
                continue
            rows_text.append(text)
        return rows_text
    finally:
        wb.close()


def read_excel_as_text(file_path: str, exclude_substring: str = '') -> str:
    """Возвращает все строки первого листа (после фильтрации по
       exclude_substring), склеенные по одной строке текста на каждую —
       готово для передачи в engine.index_text(text, separator='ExcelRow1'),
       где разделитель 'ExcelRow1' означает «один топик — одна строка»."""
    rows = read_excel_rows(file_path, exclude_substring)
    return "\n".join(rows)
