"""Presentation-only rendering for bound Django fields on Tailwind pages."""

from django import template

register = template.Library()


@register.inclusion_tag("components/forms/field.html")
def tailwind_field(field, quick_create_label="", quick_create_target=""):
    is_checkbox = getattr(field.field.widget, "input_type", None) == "checkbox"
    is_switch = is_checkbox and field.name in {
        "is_program_item", "requires_expiry_date", "is_active"
    }
    attrs = {"class": "ims-switch" if is_switch else "ims-choice" if is_checkbox else "ims-control"}
    descriptions = []
    if field.help_text:
        descriptions.append(f"{field.auto_id}_helptext")
    if field.errors:
        attrs["aria-invalid"] = "true"
        descriptions.append(f"{field.auto_id}_errors")
        if not is_checkbox:
            attrs["class"] += " ims-control--invalid"
    if descriptions:
        attrs["aria-describedby"] = " ".join(descriptions)
    return {
        "field": field,
        "widget": field.as_widget(attrs=attrs),
        "is_checkbox": is_checkbox,
        "quick_create_label": quick_create_label,
        "quick_create_target": quick_create_target,
    }
