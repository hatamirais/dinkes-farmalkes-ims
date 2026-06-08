from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ReceivingDocumentStorage(FileSystemStorage):
    """Store receiving attachments outside the public MEDIA_ROOT tree."""

    def __init__(self, location=None):
        self._configured_location = location
        super().__init__(location=location, base_url=None)

    @property
    def base_location(self):
        configured = self._configured_location or settings.PRIVATE_MEDIA_ROOT
        return str(configured)

    @property
    def location(self):
        return str(Path(self.base_location).resolve())
