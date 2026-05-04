import re

from django.utils import timezone


DEFAULT_DOCUMENT_NUMBER_TEMPLATES = {
    "LPLPO": "440/{seq}/SBBK.RF/{year}",
    "SPECIAL_REQUEST": "440/{seq}/KD.F/{year}",
}


def get_distribution_document_number_template(distribution_type):
    if distribution_type not in DEFAULT_DOCUMENT_NUMBER_TEMPLATES:
        return None

    from apps.core.models import SystemSettings

    settings = SystemSettings.get_settings()
    field_name = {
        "LPLPO": "lplpo_distribution_number_template",
        "SPECIAL_REQUEST": "special_request_distribution_number_template",
    }[distribution_type]
    return getattr(settings, field_name, None) or DEFAULT_DOCUMENT_NUMBER_TEMPLATES[distribution_type]


def _build_template_pattern(template):
    escaped_template = re.escape(template)
    escaped_template = escaped_template.replace(re.escape("{seq}"), r"(?P<sequence>\d+)")
    escaped_template = escaped_template.replace(re.escape("{year}"), r"(?P<year>\d{4})")
    return re.compile(rf"^{escaped_template}$")


def _render_document_number(template, sequence, year):
    return template.format(seq=sequence, year=year)


def render_distribution_document_number_preview(
    distribution_type,
    *,
    sequence="12",
    year=None,
):
    template = get_distribution_document_number_template(distribution_type)
    if template is None:
        return None
    year = str(year or timezone.now().year)
    return _render_document_number(template, sequence, year)


def generate_distribution_document_number(model_class, distribution_type, year=None):
    template = get_distribution_document_number_template(distribution_type)
    if template is None:
        year_month = timezone.now().strftime("%Y%m")
        prefix = f"DIST-{year_month}"
        last = (
            model_class.objects.filter(document_number__startswith=f"{prefix}-")
            .order_by("-document_number")
            .first()
        )
        if last:
            try:
                sequence = int(last.document_number.split("-")[-1]) + 1
            except (TypeError, ValueError, IndexError):
                sequence = 1
        else:
            sequence = 1
        return f"{prefix}-{str(sequence).zfill(5)}"

    year = str(year or timezone.now().year)
    pattern = _build_template_pattern(template)
    matching_numbers = model_class.objects.filter(
        distribution_type=distribution_type,
    ).values_list("document_number", flat=True)

    current_max = 0
    for document_number in matching_numbers:
        match = pattern.fullmatch(document_number or "")
        if not match:
            continue
        if match.group("year") != year:
            continue
        current_max = max(current_max, int(match.group("sequence")))

    next_sequence = current_max + 1
    return _render_document_number(template, next_sequence, year)