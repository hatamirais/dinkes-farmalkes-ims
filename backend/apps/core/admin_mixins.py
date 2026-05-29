"""Mixin for ImportExportModelAdmin that adds CSV column reference guide."""

from apps.core.csv_exports import SanitizedCSV


class ImportGuideMixin:
    """Adds a CSV column reference table to the import page.

    Usage: Set `import_guide` on the admin class as a dict with:
        - title: str
        - description: str (optional)
        - columns: list of dicts with 'name', 'required', 'description'
    """

    import_guide = None
    import_template_name = 'admin/import_with_guide.html'

    def get_export_formats(self):
        formats = super().get_export_formats()
        sanitized_formats = []
        for file_format in formats:
            if file_format is SanitizedCSV:
                sanitized_formats.append(file_format)
                continue
            try:
                if file_format().get_extension() == "csv":
                    sanitized_formats.append(SanitizedCSV)
                    continue
            except Exception:
                pass
            sanitized_formats.append(file_format)
        return sanitized_formats

    def get_import_context_data(self, **kwargs):
        context = super().get_import_context_data(**kwargs)
        if self.import_guide:
            context['column_guide_title'] = self.import_guide.get('title', '')
            context['column_guide_description'] = self.import_guide.get('description', '')
            context['column_guide'] = self.import_guide.get('columns', [])
        return context
