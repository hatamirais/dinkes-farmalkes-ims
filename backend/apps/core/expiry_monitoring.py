"""Shared display/filter rules only; never authorize or change stock."""
from django.db.models import Q


def expiry_display(expiry_date, today):
    days = (expiry_date - today).days
    status = "expired" if days < 0 else "near-critical" if days <= 30 else "near"
    return {"days_to_expiry": days, "expiry_status": status}


def expiry_levels(window_days):
    return [("all", "Semua level"), ("expired", "Sudah kedaluwarsa"),
            ("near", f"Mendekati kedaluwarsa (≤ {window_days} hari)"),
            ("critical", "Kritis (0–30 hari, termasuk hari ED)")]


def expiry_level_filter(field, level, today):
    # The caller supplies its own window, stock source and authorization scope.
    from datetime import timedelta
    if level == "expired":
        return Q(**{f"{field}__lt": today})
    if level == "near":
        return Q(**{f"{field}__gte": today})
    if level == "critical":
        return Q(**{f"{field}__gte": today, f"{field}__lte": today + timedelta(days=30)})
    return Q()
