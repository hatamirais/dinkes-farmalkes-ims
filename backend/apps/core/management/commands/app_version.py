from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.versioning import (
    SemanticVersion,
    get_version_file,
    read_version,
    write_version,
)


class Command(BaseCommand):
    help = "Show or bump project semantic version (MAJOR.MINOR.PATCH)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--major",
            action="store_true",
            help="Bump MAJOR and reset MINOR/PATCH to 0.",
        )
        parser.add_argument(
            "--minor",
            action="store_true",
            help="Bump MINOR and reset PATCH to 0.",
        )
        parser.add_argument(
            "--patch",
            action="store_true",
            help="Bump PATCH.",
        )
        parser.add_argument(
            "--set",
            dest="set_version",
            metavar="VERSION",
            help="Set a specific version value like 2.5.1.",
        )

    def handle(self, *args, **options):
        version_file = get_version_file(Path(settings.BASE_DIR).parent)
        current = read_version(version_file)

        bump_flags = [options["major"], options["minor"], options["patch"]]
        selected_actions = sum(1 for flag in bump_flags if flag) + bool(
            options["set_version"]
        )

        if selected_actions > 1:
            raise CommandError("Use only one action: --major, --minor, --patch, or --set")

        if options["set_version"]:
            try:
                next_version = SemanticVersion.parse(options["set_version"])
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            write_version(version_file, next_version)
            self.stdout.write(str(next_version))
            return

        if options["major"]:
            next_version = current.bump_major()
            write_version(version_file, next_version)
            self.stdout.write(str(next_version))
            return

        if options["minor"]:
            next_version = current.bump_minor()
            write_version(version_file, next_version)
            self.stdout.write(str(next_version))
            return

        if options["patch"]:
            next_version = current.bump_patch()
            write_version(version_file, next_version)
            self.stdout.write(str(next_version))
            return

        self.stdout.write(str(current))
