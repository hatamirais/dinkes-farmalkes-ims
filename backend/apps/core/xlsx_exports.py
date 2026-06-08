FORMULA_PREFIXES = ("=", "+", "-", "@")


def escape_xlsx_formula(value):
    if not isinstance(value, str):
        return value
    if value.startswith("'"):
        return value
    if value.lstrip().startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value
