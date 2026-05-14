from django.utils import timezone

from apps.core.numbering import (
    get_template_from_settings,
    render_document_number_preview,
    generate_document_number,
)


DEFAULT_DOCUMENT_NUMBER_TEMPLATES = {
    "LPLPO": "440/{seq}/SBBK.RF/{year}",
    "SPECIAL_REQUEST": "440/{seq}/KD.F/{year}",
}


def get_distribution_document_number_template(distribution_type):
    if distribution_type not in DEFAULT_DOCUMENT_NUMBER_TEMPLATES:
        return None

    field_name = {
        "LPLPO": "lplpo_distribution_number_template",
        "SPECIAL_REQUEST": "special_request_distribution_number_template",
    }[distribution_type]
    return get_template_from_settings(field_name, DEFAULT_DOCUMENT_NUMBER_TEMPLATES[distribution_type])


def render_distribution_document_number_preview(distribution_type, *, sequence="12", year=None):
    template = get_distribution_document_number_template(distribution_type)
    return render_document_number_preview(
        template=template,
        sequence=sequence,
        year=year,
    )


def generate_distribution_document_number(model_class, distribution_type, year=None):
    template = get_distribution_document_number_template(distribution_type)
    if template is None:
        # Use same fallback prefix used previously: DIST-YYYYMM
        year_month = timezone.now().strftime("%Y%m")
        fallback_prefix = f"DIST-{year_month}"
        return generate_document_number(model_class, template=None, template_field_name=None, template_default=None, filter_kwargs=None, year=year, fallback_prefix=fallback_prefix)

    # When using template-based numbering, scan all existing document numbers.
    # The sequence still remains effectively per-template because numbers that
    # don't match the current template/year are ignored, and this avoids unique
    # collisions if a record's distribution_type is changed after creation.
    return generate_document_number(
        model_class,
        template=template,
        year=year,
    )
