import csv
import io
import re
import unicodedata
from pathlib import PurePath

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[a-zA-Z]:[\\/]")
IMAGE_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}


def sanitize_uploaded_filename(filename):
    normalized = unicodedata.normalize("NFC", str(filename or "")).strip()
    if not normalized:
        raise ValidationError("Nama file wajib diisi.")
    if "\x00" in normalized:
        raise ValidationError("Nama file mengandung karakter null byte yang tidak diizinkan.")
    if normalized.startswith(("/", "\\")) or WINDOWS_ABSOLUTE_PATH_RE.match(normalized):
        raise ValidationError("Nama file tidak aman.")

    path = PurePath(normalized.replace("\\", "/"))
    if len(path.parts) != 1 or path.name in {".", ".."}:
        raise ValidationError("Nama file tidak aman.")

    return path.name


def validate_uploaded_file_basics(uploaded_file, *, allowed_extensions, max_size_bytes, field_label):
    if uploaded_file is None:
        raise ValidationError(f"{field_label} wajib diisi.")

    safe_name = sanitize_uploaded_filename(getattr(uploaded_file, "name", ""))
    suffix = PurePath(safe_name).suffix.lower().lstrip(".")
    normalized_extensions = {extension.lower().lstrip(".") for extension in allowed_extensions}
    if suffix not in normalized_extensions:
        allowed_list = ", ".join(sorted(f".{ext}" for ext in normalized_extensions))
        raise ValidationError(
            f"{field_label} harus memakai ekstensi yang diizinkan: {allowed_list}."
        )

    file_size = getattr(uploaded_file, "size", None)
    if file_size is None:
        raise ValidationError(f"Ukuran {field_label.lower()} tidak dapat dibaca.")
    if file_size > max_size_bytes:
        max_size_mb = max_size_bytes / (1024 * 1024)
        raise ValidationError(
            f"{field_label} melebihi batas ukuran {max_size_mb:.0f} MB."
        )

    uploaded_file.name = safe_name
    return safe_name


def validate_csv_upload(uploaded_file, *, max_size_bytes):
    validate_uploaded_file_basics(
        uploaded_file,
        allowed_extensions={"csv"},
        max_size_bytes=max_size_bytes,
        field_label="File CSV",
    )

    try:
        sample = uploaded_file.read(min(uploaded_file.size, 4096))
    finally:
        uploaded_file.seek(0)

    try:
        decoded = sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("File CSV harus menggunakan encoding UTF-8.") from exc

    if not decoded.strip():
        raise ValidationError("File CSV tidak boleh kosong.")
    if "\x00" in decoded:
        raise ValidationError("File CSV mengandung null byte yang tidak diizinkan.")

    try:
        rows = list(csv.reader(io.StringIO(decoded)))
    except csv.Error as exc:
        raise ValidationError("File CSV tidak valid.") from exc

    if not rows or not rows[0] or len(rows[0]) < 2:
        raise ValidationError("Konten file CSV tidak valid.")

    return uploaded_file


def validate_image_upload(
    uploaded_file,
    *,
    max_size_bytes,
    field_label,
    allowed_extensions,
    allowed_formats,
):
    validate_uploaded_file_basics(
        uploaded_file,
        allowed_extensions=allowed_extensions,
        max_size_bytes=max_size_bytes,
        field_label=field_label,
    )

    try:
        with Image.open(uploaded_file) as image:
            image.verify()

        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(f"{field_label} harus berupa file gambar yang valid.") from exc
    finally:
        uploaded_file.seek(0)

    if image_format not in allowed_formats:
        allowed_list = ", ".join(sorted(allowed_formats))
        raise ValidationError(
            f"{field_label} harus memakai format gambar yang diizinkan: {allowed_list}."
        )

    return IMAGE_FORMAT_TO_MIME[image_format]


def validate_receiving_document_upload(uploaded_file, *, max_size_bytes):
    validate_uploaded_file_basics(
        uploaded_file,
        allowed_extensions={"pdf", "png", "jpg", "jpeg"},
        max_size_bytes=max_size_bytes,
        field_label="Dokumen lampiran",
    )

    suffix = PurePath(uploaded_file.name).suffix.lower()
    if suffix == ".pdf":
        try:
            signature = uploaded_file.read(5)
        finally:
            uploaded_file.seek(0)

        if signature != b"%PDF-":
            raise ValidationError("Dokumen lampiran PDF tidak valid.")
        return "application/pdf"

    return validate_image_upload(
        uploaded_file,
        max_size_bytes=max_size_bytes,
        field_label="Dokumen lampiran",
        allowed_extensions={"png", "jpg", "jpeg"},
        allowed_formats={"PNG", "JPEG"},
    )