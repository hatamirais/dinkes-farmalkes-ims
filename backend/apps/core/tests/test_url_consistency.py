"""
URL consistency tests to prevent 301 redirect issues.

These tests ensure all URL patterns follow the trailing slash convention
and that test client calls use consistent URLs.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver, reverse
from django.contrib.auth import get_user_model


User = get_user_model()


class URLTrailingSlashConsistencyTests(SimpleTestCase):
    """Verify all URL patterns end with trailing slashes to prevent 301 redirects."""

    def test_all_url_patterns_end_with_trailing_slash(self):
        """All URL patterns (except empty root paths) must end with /."""
        resolver = get_resolver()
        violations = []

        for pattern in resolver.url_patterns:
            self._check_pattern(pattern, violations)

        if violations:
            self.fail(
                f"The following URL patterns do not end with a trailing slash:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nAll patterns must end with / to prevent 301 redirects."
            )

    def _check_pattern(self, pattern, violations, prefix=""):
        """Recursively check URL patterns for trailing slash compliance."""
        from django.urls.resolvers import RoutePattern, URLResolver

        if hasattr(pattern, "pattern"):
            route = str(pattern.pattern)

            # Skip empty root paths (path(""))
            # Skip regex patterns (Django admin internals, catch-alls)
            # Skip paths starting with ^ (regex patterns)
            if route and route != "" and not route.startswith("^"):
                # Skip Django admin internal patterns
                if "admin/" in route or route.startswith("^(?P<app_label>"):
                    return

                # Check if it's a concrete path (not a parameter-only path like "<int:pk>/")
                # Parameter paths should still end with /
                if not route.endswith("/"):
                    full_path = prefix + route
                    violations.append(full_path)

            # Recursively check included URLconfs
            if isinstance(pattern, URLResolver):
                new_prefix = prefix + route
                for sub_pattern in pattern.url_patterns:
                    self._check_pattern(sub_pattern, violations, new_prefix)

    def test_root_url_patterns_have_trailing_slashes(self):
        """Verify root URLconf patterns all end with /."""
        from config import urls

        violations = []
        for pattern in urls.urlpatterns:
            route = str(pattern.pattern)
            # Skip the debug catch-all pattern
            if route and not route.startswith("^") and not route.endswith("/"):
                violations.append(route)

        if violations:
            self.fail(
                f"Root URL patterns missing trailing slashes:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    def test_no_hardcoded_urls_without_trailing_slashes_in_tests(self):
        """Ensure test files don't use hardcoded URLs without trailing slashes."""
        import os
        import re
        from pathlib import Path

        test_dir = Path(__file__).parent.parent
        violations = []

        # Pattern to match self.client.get/post/put/delete with hardcoded URLs
        # that don't have trailing slashes
        pattern = re.compile(
            r'self\.client\.(get|post|put|delete)\(\s*["\'](/[^"\']*)["\']'
        )

        for test_file in test_dir.rglob("tests.py"):
            content = test_file.read_text()
            for match in pattern.finditer(content):
                url = match.group(2)
                # Skip URLs that end with /
                if not url.endswith("/"):
                    # Find line number
                    line_num = content[:match.start()].count("\n") + 1
                    violations.append(f"{test_file.relative_to(test_dir.parent)}:{line_num} - {url}")

        if violations:
            self.fail(
                f"The following test URLs are missing trailing slashes:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nAll hardcoded URLs in tests must end with / to prevent 301 redirects."
            )


class RedirectBehaviorTests(TestCase):
    """Test that URLs follow trailing slash convention to prevent 301 redirect issues."""

    def test_reverse_urls_have_trailing_slashes(self):
        """Verify that reverse() generates URLs with trailing slashes."""
        url_names = [
            'dashboard',
            'settings',
            'numbering_settings',
            'users:user_list',
            'items:item_list',
            'stock:stock_list',
            'receiving:receiving_list',
            'distribution:distribution_list',
            'reports:index',
        ]
        
        for url_name in url_names:
            url = reverse(url_name)
            self.assertTrue(
                url.endswith('/'),
                f"reverse('{url_name}') = '{url}' should end with trailing slash"
            )

    def test_urls_with_trailing_slash_do_not_redirect_to_without_slash(self):
        """Critical test: URLs with trailing slashes should not 301 to URLs without slashes.
        
        This was the core issue from GitHub #26 - the debug catch-all route was
        intercepting URLs and causing incorrect redirect behavior.
        """
        # These URLs should NOT redirect from /path/ to /path
        urls_to_check = [
            '/settings/',
            '/settings/numbering/',
            '/users/',
            '/items/',
        ]
        
        for url in urls_to_check:
            response = self.client.get(url)
            # Should not be a 301 redirect (could be 200, 302 to login, or 403)
            if response.status_code == 301:
                # If it is 301, verify it's not stripping the trailing slash
                redirect_url = response.url
                # Extract path from redirect URL
                if '://' in redirect_url:
                    from urllib.parse import urlparse
                    redirect_path = urlparse(redirect_url).path
                else:
                    redirect_path = redirect_url
                
                self.assertTrue(
                    redirect_path.endswith('/'),
                    f"URL '{url}' redirected to '{redirect_path}' which is missing trailing slash"
                )
