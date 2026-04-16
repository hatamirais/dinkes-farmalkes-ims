from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with created_at and updated_at timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SystemSettings(TimeStampedModel):
    """
    Singleton model to hold dynamic system settings (facility name, logo, etc.).
    """
    platform_label = models.CharField(
        max_length=255,
        default="Healthcare Inventory Platform",
        help_text="Label singkat untuk branding aplikasi, misalnya badge di halaman login.",
    )
    facility_name = models.CharField(max_length=255, default="Healthcare Inventory Management System")
    facility_address = models.TextField(blank=True)
    facility_phone = models.CharField(max_length=50, blank=True)
    header_title = models.CharField(max_length=255, default="KEMENTERIAN KESEHATAN REPUBLIK INDONESIA")
    logo = models.ImageField(upload_to="settings/", blank=True, null=True, help_text="Biarkan kosong jika tidak ada logo khusus. Gunakan gambar transparan (PNG) untuk hasil terbaik.")

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    def save(self, *args, **kwargs):
        self.id = 1  # Force id to 1 for singleton
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Settings for {self.facility_name}"
