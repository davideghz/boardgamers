import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from webapp.services.bgg import normalize_bgg_id


def _read_columns(text):
    for delimiter in (',', ';'):
        rows = csv.reader(StringIO(text, newline=''), delimiter=delimiter, strict=True)
        try:
            header = next((row for row in rows if any(cell.strip() for cell in row)), [])
        except csv.Error:
            continue
        columns = [cell.strip().casefold() for cell in header]
        id_columns = [i for i, name in enumerate(columns) if name in {'bgg id', 'id bgg', 'bgg_id'}]
        if len(id_columns) == 1:
            title_column = next((i for i, name in enumerate(columns) if name in {'game', 'gioco'}), None)
            return rows, id_columns[0], title_column, None
        if len(header) == 1 and (first_id := normalize_bgg_id(header[0])):
            return rows, 0, None, first_id
    raise ValidationError(_("The CSV must contain a column named BGG ID or ID BGG."))


def read_game_library_csv(text):
    """Return unique BGG entries and the starting line numbers of invalid records."""
    rows, id_column, title_column, first_id = _read_columns(text)
    items = {first_id: {'bgg_id': first_id, 'name': ''}} if first_id else {}
    missing, invalid = [], []
    try:
        while True:
            line = rows.line_num + 1
            row = next(rows, None)
            if row is None:
                break
            if not row:
                continue
            code = row[id_column].strip() if id_column < len(row) else ''
            if not code:
                missing.append(line)
                continue
            bgg_id = normalize_bgg_id(code)
            if bgg_id is None:
                invalid.append(line)
                continue
            title = row[title_column].strip()[:255] if title_column is not None and title_column < len(row) else ''
            items.setdefault(bgg_id, {'bgg_id': bgg_id, 'name': title})
    except csv.Error as error:
        raise ValidationError(_("The CSV could not be read. Check the format near line %(line)s."),
                              params={'line': rows.line_num}) from error
    return list(items.values()), missing, invalid
