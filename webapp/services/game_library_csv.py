import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from webapp.services.bgg import BGG_ID_PATTERN, normalize_bgg_id

MAX_CSV_RECORDS = 5000  # keeps the preview page and its queries within the Heroku timeout


def _format_error(line):
    return ValidationError(_("The CSV could not be read. Check the format near line %(line)s."),
                           params={'line': line})


def _read_columns(text):
    """Return the reader positioned after the header, the ID and title columns, and,
    for a headerless single-column file, its first row and line to read as data."""
    errors = []
    for delimiter in (',', ';'):
        rows = csv.reader(StringIO(text, newline=''), delimiter=delimiter, strict=True)
        try:
            header = next((row for row in rows if any(cell.strip() for cell in row)), [])
        except csv.Error:
            errors.append(rows.line_num)
            continue
        columns = [cell.strip().casefold() for cell in header]
        id_columns = [i for i, name in enumerate(columns) if name in {'bgg id', 'id bgg', 'bgg_id'}]
        if len(id_columns) == 1:
            title_column = next((i for i, name in enumerate(columns) if name in {'game', 'gioco'}), None)
            return rows, id_columns[0], title_column, None, None
        if len(header) == 1 and BGG_ID_PATTERN.fullmatch(header[0].strip()):
            return rows, 0, None, header, rows.line_num
    if len(errors) == 2:
        raise _format_error(errors[0])
    raise ValidationError(_("The CSV must contain a column named BGG ID or ID BGG."))


def read_game_library_csv(text):
    """Return unique BGG entries and the starting line numbers of invalid records."""
    rows, id_column, title_column, first_row, first_line = _read_columns(text)
    items = {}
    missing, invalid = [], []

    def records():
        if first_row is not None:
            yield first_line, first_row
        while True:
            line = rows.line_num + 1
            row = next(rows, None)
            if row is None:
                return
            if row:
                yield line, row

    try:
        for count, (line, row) in enumerate(records(), start=1):
            if count > MAX_CSV_RECORDS:
                raise ValidationError(
                    _("The CSV has more than %(max)s rows. Split it into smaller files."),
                    params={'max': MAX_CSV_RECORDS})
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
        raise _format_error(rows.line_num) from error
    return list(items.values()), missing, invalid
