from django.conf import settings


def app_version(_request):
    return {"app_version": settings.APP_VERSION}
