from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.core.versioning import DEFAULT_VERSION, SemanticVersion, read_version, write_version


class SemanticVersionTests(SimpleTestCase):
    def test_parse_valid_semver(self):
        parsed = SemanticVersion.parse("2.4.9")
        self.assertEqual(parsed.major, 2)
        self.assertEqual(parsed.minor, 4)
        self.assertEqual(parsed.patch, 9)

    def test_parse_rejects_invalid_semver(self):
        with self.assertRaisesMessage(ValueError, "Invalid semantic version"):
            SemanticVersion.parse("1.0")

    def test_bump_rules(self):
        initial = SemanticVersion.parse("3.7.8")
        self.assertEqual(str(initial.bump_major()), "4.0.0")
        self.assertEqual(str(initial.bump_minor()), "3.8.0")
        self.assertEqual(str(initial.bump_patch()), "3.7.9")

    def test_read_missing_file_uses_default(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            self.assertEqual(str(read_version(version_file)), DEFAULT_VERSION)

    def test_write_and_read_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir) / "VERSION"
            expected = SemanticVersion.parse("1.2.3")

            write_version(version_file, expected)

            self.assertEqual(str(read_version(version_file)), "1.2.3")
