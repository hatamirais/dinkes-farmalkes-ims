from functools import wraps


class SecureClientDefaultsMixin:
    secure_test_host = "localhost"

    def setUp(self):
        super().setUp()
        self.client.get = self._secure_client_method(self.client.get)
        self.client.post = self._secure_client_method(self.client.post)

    def _secure_client_method(self, method):
        @wraps(method)
        def wrapped(path, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers = {"host": self.secure_test_host, **headers}
            kwargs["secure"] = True
            kwargs["headers"] = headers
            return method(path, *args, **kwargs)

        return wrapped

    def secure_get(self, path, data=None, follow=False, **extra):
        headers = extra.pop("headers", {})
        headers = {"host": self.secure_test_host, **headers}
        return self.client.get(
            path,
            data=data,
            follow=follow,
            secure=True,
            headers=headers,
            **extra,
        )

    def secure_post(self, path, data=None, follow=False, **extra):
        headers = extra.pop("headers", {})
        headers = {"host": self.secure_test_host, **headers}
        return self.client.post(
            path,
            data=data,
            follow=follow,
            secure=True,
            headers=headers,
            **extra,
        )
