from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


DEFAULT_VERSION = "1.0.0"
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw_value: str) -> "SemanticVersion":
        value = raw_value.strip()
        match = SEMVER_PATTERN.fullmatch(value)
        if not match:
            raise ValueError(
                "Invalid semantic version. Expected format: MAJOR.MINOR.PATCH"
            )
        return cls(*(int(part) for part in match.groups()))

    def bump_major(self) -> "SemanticVersion":
        return SemanticVersion(self.major + 1, 0, 0)

    def bump_minor(self) -> "SemanticVersion":
        return SemanticVersion(self.major, self.minor + 1, 0)

    def bump_patch(self) -> "SemanticVersion":
        return SemanticVersion(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def read_version(version_file: Path) -> SemanticVersion:
    if not version_file.exists():
        return SemanticVersion.parse(DEFAULT_VERSION)
    return SemanticVersion.parse(version_file.read_text(encoding="utf-8"))


def write_version(version_file: Path, version: SemanticVersion) -> None:
    version_file.write_text(f"{version}\n", encoding="utf-8")


def get_version_file(project_root: Path) -> Path:
    return project_root / "VERSION"
