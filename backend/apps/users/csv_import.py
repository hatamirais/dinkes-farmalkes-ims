"""Create-only user CSV imports with an actor-owned, single-use preview."""

import csv
import io
import unicodedata
from datetime import timedelta

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.core.upload_validation import validate_csv_upload
from apps.items.models import Facility

from .access import has_module_permission, lock_authority_user_state
from .creation import serialized_user_creation
from .forms import FACILITY_LINKABLE_ROLES, UserCreateForm
from .models import ModuleAccess, UserImportBatch

HEADERS = ("username", "full_name", "nip", "email", "role", "facility_code", "is_active", "password")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 25
PREVIEW_LIFETIME = timedelta(minutes=15)


class UserCSVUploadForm(forms.Form):
    file = forms.FileField(label="File CSV", help_text="UTF-8, maksimal 1 MiB dan 25 pengguna.")

    def clean_file(self):
        return validate_csv_upload(self.cleaned_data["file"], max_size_bytes=MAX_BYTES)


def require_import_access(actor):
    if not actor or not actor.is_active or not (
        actor.is_superuser or actor.has_perm("users.add_user")
        or has_module_permission(actor, "users.add_user")
    ):
        raise PermissionDenied("Anda tidak memiliki izin untuk mengimpor pengguna.")


@sensitive_variables()
def _profile_form(row, *, password=None):
    data = {key: row[key] for key in HEADERS if key not in {"password", "facility_code"}}
    code = row["facility_code"]
    facility = None
    if code:
        if row["role"] not in FACILITY_LINKABLE_ROLES:
            raise ValidationError("facility_code: Jabatan ini tidak boleh memiliki fasilitas.")
        facility = Facility.objects.filter(
            code=code, is_active=True, facility_type=Facility.FacilityType.PUSKESMAS,
        ).first()
        if facility is None:
            raise ValidationError("facility_code: Kode Puskesmas aktif tidak ditemukan.")
    data["facility"] = facility.pk if facility else ""
    data["is_active"] = row["is_active"]
    if password is not None:
        data.update(password1=password, password2=password)
    form = UserCreateForm(data, can_manage_module_scopes=False)
    if password is None:
        # Confirmation revalidates the profile; plaintext no longer exists.
        del form.fields["password1"]
        del form.fields["password2"]
    if not form.is_valid():
        errors = []
        for field, messages in form.errors.items():
            if field.startswith("password"):
                errors.append("password: Password tidak memenuhi kebijakan keamanan.")
            else:
                errors.extend(f"{field}: {message}" for message in messages)
        raise ValidationError(errors)
    return form


@sensitive_variables()
def parse_user_csv(upload):
    validate_csv_upload(upload, max_size_bytes=MAX_BYTES)
    try:
        content = upload.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValidationError("File CSV melebihi 1 MiB.")
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("File CSV harus menggunakan encoding UTF-8.") from exc
    if "\x00" in text:
        raise ValidationError("File CSV tidak boleh mengandung null byte.")
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    rows, errors = [], []
    seen_usernames, seen_emails = set(), set()
    try:
        headers = [unicodedata.normalize("NFC", cell.strip()) for cell in next(reader)]
        if len(headers) != len(HEADERS) or set(headers) != set(HEADERS):
            raise ValidationError("Header CSV harus tepat: " + ",".join(HEADERS))
        data_rows = [(reader.line_num, cells) for cells in reader if cells]
        if len(data_rows) > MAX_ROWS:
            raise ValidationError("Maksimal 25 pengguna per file.")
        for line, cells in data_rows:
            if len(cells) != len(headers):
                errors.append(f"Baris {line}: Jumlah kolom tidak sesuai header.")
                continue
            row = dict(zip(headers, cells))
            password = row.pop("password")
            row = {key: unicodedata.normalize("NFC", value.strip()) for key, value in row.items()}
            try:
                if row["is_active"] not in {"true", "false"}:
                    raise ValidationError("is_active: Gunakan true atau false.")
                row["is_active"] = row["is_active"] == "true"
                if not password or len(password) > 1024:
                    raise ValidationError("password: Wajib diisi, maksimal 1024 karakter.")
                if len(row["facility_code"]) > Facility._meta.get_field("code").max_length:
                    raise ValidationError("facility_code: Kode terlalu panjang.")
                form = _profile_form(row, password=password)
                user = form.save(commit=False)
                row["username"], row["email"] = user.username, user.email
                username_key, email_key = user.username.casefold(), user.email.casefold()
                if username_key in seen_usernames or (email_key and email_key in seen_emails):
                    raise ValidationError("Username atau email duplikat dalam CSV.")
                seen_usernames.add(username_key)
                if email_key:
                    seen_emails.add(email_key)
                row["password_hash"] = user.password
                row["line"] = line
                rows.append(row)
            except ValidationError as exc:
                errors.extend(f"Baris {line}: {message}" for message in exc.messages)
    except (csv.Error, StopIteration) as exc:
        raise ValidationError("Struktur CSV tidak valid.") from exc
    if errors:
        raise ValidationError(errors)
    if not rows:
        raise ValidationError("CSV harus memiliki minimal satu pengguna.")
    return rows


@sensitive_variables()
def stage_import(actor, upload):
    require_import_access(actor)
    rows = parse_user_csv(upload)
    cleanup_expired_imports()
    return UserImportBatch.objects.create(
        actor=actor, rows=rows, expires_at=timezone.now() + PREVIEW_LIFETIME,
    )


def cleanup_expired_imports():
    return UserImportBatch.objects.filter(expires_at__lte=timezone.now()).delete()[0]


@sensitive_variables()
def finish_import(actor, batch_id, *, cancel=False):
    # Shared creation lock precedes actor, batch and facility locks.
    with serialized_user_creation():
        actor = lock_authority_user_state(actor, ModuleAccess.Module.USERS)
        require_import_access(actor)
        try:
            batch = UserImportBatch.objects.select_for_update().get(pk=batch_id, actor=actor)
        except (UserImportBatch.DoesNotExist, ValueError, ValidationError) as exc:
            raise ValidationError("Pratinjau tidak tersedia atau sudah digunakan.") from exc
        if cancel:
            batch.delete()
            return 0
        if batch.expires_at <= timezone.now():
            raise ValidationError("Pratinjau kedaluwarsa. Unggah kembali CSV.")
        codes = {row["facility_code"] for row in batch.rows if row["facility_code"]}
        list(Facility.objects.select_for_update().filter(code__in=codes).order_by("pk"))
        for row in batch.rows:
            try:
                form = _profile_form(row)
            except ValidationError as exc:
                raise ValidationError([f"Baris {row['line']}: {message}" for message in exc.messages]) from exc
            user = form.instance
            user.password = row["password_hash"]
            user.save()  # Signals provision groups/default scopes and audit history.
        count = len(batch.rows)
        batch.delete()  # Single-use marker and credential cleanup commit atomically.
        return count
