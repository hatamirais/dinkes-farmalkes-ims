import csv
from io import StringIO

from import_export.formats import base_formats


FORMULA_PREFIXES = ("=", "+", "-", "@")
CSV_DELIMITER = ","


def escape_csv_formula(value):
    if not isinstance(value, str):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def sanitize_csv_row(row):
    return [escape_csv_formula(value) for value in row]


class SanitizedCSV(base_formats.CSV):
    def export_data(self, dataset, **kwargs):
        stream = StringIO()
        kwargs.setdefault("delimiter", CSV_DELIMITER)

        writer = csv.writer(stream, **kwargs)
        for row in dataset._package(dicts=False):
            writer.writerow(sanitize_csv_row(row))

        return stream.getvalue()