from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.items.models import Item, Program


class Command(BaseCommand):
    help = "Assign a DEFAULT Program to items that are marked as program items but have no program set."

    def add_arguments(self, parser):
        parser.add_argument(
            "--program-id",
            type=int,
            help="ID of program to assign (overrides --program-code and default lookup)",
        )
        parser.add_argument(
            "--program-code",
            type=str,
            help="Program code to assign (case-insensitive)",
        )
        parser.add_argument(
            "--create-default",
            action="store_true",
            help="Create a Program with code/name 'DEFAULT' if not found",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making updates",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not prompt for confirmation; assume yes",
        )

    def handle(self, *args, **options):
        program = None

        if options.get("program_id"):
            program = Program.objects.filter(pk=options["program_id"]).first()
            if not program:
                raise CommandError(f"Program with id={options['program_id']} not found")

        if not program and options.get("program_code"):
            program = Program.objects.filter(
                code__iexact=options["program_code"]
            ).first()
            if not program:
                raise CommandError(
                    f"Program with code={options['program_code']} not found"
                )

        if not program:
            # try common DEFAULT fallbacks
            program = Program.objects.filter(code__iexact="DEFAULT").first()
            if not program:
                program = Program.objects.filter(name__iexact="DEFAULT").first()

        if not program and options.get("create_default"):
            program = Program.objects.create(
                code="DEFAULT", name="DEFAULT", is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS(f"Created DEFAULT program (id={program.pk})")
            )

        if not program:
            raise CommandError(
                "No DEFAULT program found. Provide --program-id or --program-code, or run with --create-default to create one."
            )

        qs = Item.objects.filter(is_program_item=True, program__isnull=True)
        total = qs.count()

        if total == 0:
            self.stdout.write(
                self.style.NOTICE("No items require assignment. Exiting.")
            )
            return

        self.stdout.write(
            f"Found {total} items to assign to Program: {program.code} — {program.name} (id={program.pk})"
        )

        if options.get("dry_run"):
            sample = qs[:20]
            self.stdout.write("Sample items that would be updated:")
            for it in sample:
                self.stdout.write(f" - {it.pk}: {it.kode_barang} — {it.nama_barang}")
            self.stdout.write("Dry-run complete. No changes made.")
            return

        if not options.get("no_input"):
            confirm = input("Proceed to assign? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted by user.")
                return

        with transaction.atomic():
            updated = qs.update(program=program)

        self.stdout.write(self.style.SUCCESS(f"Assigned program to {updated} items."))
