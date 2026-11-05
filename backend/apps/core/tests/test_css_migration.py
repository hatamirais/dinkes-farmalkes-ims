"""Repository and bound-widget contracts after Bootstrap CSS removal."""

from pathlib import Path

from django import forms
from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase


class CssMigrationTests(SimpleTestCase):
    def test_runtime_templates_and_styles_do_not_reference_removed_dependencies(self):
        backend = Path(settings.BASE_DIR)
        for directory, suffix in (("templates", "*.html"), ("static_src/css", "*.css")):
            for path in (backend / directory).rglob(suffix):
                with self.subTest(path=path.relative_to(backend)):
                    source = path.read_text(encoding="utf-8")
                    for dependency in (
                        "vendor/bootstrap/css/", "css/style.css", "mobile/css/mobile.css",
                        "tom-select.bootstrap5", "crispy_forms_tags", "--bs-",
                    ):
                        self.assertNotIn(dependency, source)

    def test_removed_assets_and_form_packages_are_absent(self):
        backend = Path(settings.BASE_DIR)
        for name in (
            "static/vendor/bootstrap/css", "static/css/style.css",
            "static/mobile/css/mobile.css", "static/vendor/tom-select/tom-select.bootstrap5.min.css",
        ):
            self.assertFalse((backend / name).exists(), name)
        self.assertNotIn("crispy_forms", settings.INSTALLED_APPS)
        self.assertNotIn("crispy_bootstrap5", settings.INSTALLED_APPS)
        self.assertTrue((backend / "static/vendor/bootstrap/js/bootstrap.bundle.min.js").exists())
        self.assertTrue((backend / "static/vendor/bootstrap-icons/bootstrap-icons.min.css").exists())

    def render_field(self, field, data=None):
        form = forms.Form(data=data)
        form.fields["value"] = field
        return Template("{% load tailwind_forms %}{% tailwind_field field %}").render(
            Context({"field": form["value"]})
        )

    def test_error_help_and_existing_description_are_linked(self):
        html = self.render_field(
            forms.CharField(help_text="Help", widget=forms.TextInput(attrs={
                "aria-describedby": "external-description", "data-hook": "preserved",
            })),
            data={"value": ""},
        )
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('aria-describedby="external-description id_value_helptext id_value_errors"', html)
        self.assertIn('data-hook="preserved"', html)
        self.assertIn('id="div_id_value"', html)

    def test_hidden_widget_remains_hidden_without_visible_label(self):
        html = self.render_field(forms.CharField(widget=forms.HiddenInput(), initial="kept"))
        self.assertIn('type="hidden"', html)
        self.assertIn('value="kept"', html)
        self.assertNotIn("<label", html)

    def test_radio_and_checkbox_groups_keep_names_values_and_legend(self):
        for field in (
            forms.ChoiceField(choices=(("fixed", "Fixed"),), widget=forms.RadioSelect),
            forms.MultipleChoiceField(choices=(("fixed", "Fixed"),), widget=forms.CheckboxSelectMultiple),
        ):
            with self.subTest(widget=field.widget.__class__.__name__):
                data = ["fixed"] if isinstance(field, forms.MultipleChoiceField) else "fixed"
                html = self.render_field(field, {"value": data})
                self.assertIn("<fieldset", html)
                self.assertIn('<legend class="ims-label">', html)
                self.assertIn('name="value"', html)
                self.assertRegex(html, r'<input[^>]*value="fixed"[^>]* checked')
                self.assertIn('class="ims-choice-group"', html)
