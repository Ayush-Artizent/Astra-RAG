"""File filter (§4.1 step 4): skip vendored, build output, lockfiles, minified, generated, binary.

Default rules plus per-tenant overrides. Excluding generated/vendored code is also a large
index-size and embedding-cost reduction (§11).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import PurePosixPath

DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        "third_party",
        "bower_components",
        ".git",
        "dist",
        "build",
        "out",
        "target",
        "bin",
        "obj",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        ".nuxt",
        "coverage",
        ".gradle",
        ".idea",
        ".vscode",
        "Pods",
        "packages",
    }
)

DEFAULT_EXCLUDE_GLOBS = (
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.bundle.js",
    "*.pb.go",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.g.cs",
    "*.designer.cs",
    "*.generated.*",
)

BINARY_EXTS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".jar",
        ".war",
        ".dll",
        ".exe",
        ".so",
        ".dylib",
        ".class",
        ".pyc",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".parquet",
    }
)


@dataclass(frozen=True)
class FileFilter:
    max_bytes: int = 1_000_000
    extra_exclude_globs: tuple[str, ...] = ()
    force_include_globs: tuple[str, ...] = ()  # per-tenant override wins over defaults
    exclude_dirs: frozenset[str] = field(default=DEFAULT_EXCLUDE_DIRS)

    def should_index(self, path: str, size: int | None = None, head: bytes | None = None) -> bool:
        p = PurePosixPath(path)
        if any(fnmatch.fnmatch(path, g) for g in self.force_include_globs):
            return True
        if any(part in self.exclude_dirs for part in p.parts[:-1]):
            return False
        if p.suffix.lower() in BINARY_EXTS:
            return False
        if any(
            fnmatch.fnmatch(p.name, g) for g in (*DEFAULT_EXCLUDE_GLOBS, *self.extra_exclude_globs)
        ):
            return False
        if size is not None and size > self.max_bytes:
            return False
        return not (head is not None and b"\x00" in head[:8192])
