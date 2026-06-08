import shutil
from pathlib import Path, PurePosixPath

import apps.receiving.storage
from django.conf import settings
from django.db import migrations, models


def _safe_relative_path(raw_name):
    normalized = str(raw_name or "").replace("\\", "/").strip()
    relative_path = PurePosixPath(normalized)
    if (
        not normalized
        or relative_path.is_absolute()
        or ".." in relative_path.parts
        or "." in relative_path.parts
    ):
        raise ValueError(f"Unsafe receiving document path: {raw_name!r}")
    return Path(*relative_path.parts)


def copy_receiving_documents_to_private_storage(apps, schema_editor):
    ReceivingDocument = apps.get_model("receiving", "ReceivingDocument")
    media_root = Path(settings.MEDIA_ROOT)
    private_media_root = Path(settings.PRIVATE_MEDIA_ROOT)

    for document in ReceivingDocument.objects.exclude(file="").iterator():
        relative_path = _safe_relative_path(document.file.name)
        source_path = media_root / relative_path
        destination_path = private_media_root / relative_path

        if destination_path.exists() or not source_path.exists():
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        source_path.unlink()


def copy_receiving_documents_back_to_media(apps, schema_editor):
    ReceivingDocument = apps.get_model("receiving", "ReceivingDocument")
    media_root = Path(settings.MEDIA_ROOT)
    private_media_root = Path(settings.PRIVATE_MEDIA_ROOT)

    for document in ReceivingDocument.objects.exclude(file="").iterator():
        relative_path = _safe_relative_path(document.file.name)
        source_path = private_media_root / relative_path
        destination_path = media_root / relative_path

        if destination_path.exists() or not source_path.exists():
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


class Migration(migrations.Migration):

    dependencies = [
        ("receiving", "0007_receiving_facility_and_more"),
    ]

    operations = [
        migrations.RunPython(
            copy_receiving_documents_to_private_storage,
            copy_receiving_documents_back_to_media,
        ),
        migrations.AlterField(
            model_name="receivingdocument",
            name="file",
            field=models.FileField(
                storage=apps.receiving.storage.ReceivingDocumentStorage(),
                upload_to="receiving/%Y/%m/",
            ),
        ),
    ]
