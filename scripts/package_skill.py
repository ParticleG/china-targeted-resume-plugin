#!/usr/bin/env python3
"""Create a curated, installable archive of this Skill."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

_ALLOWED_FILES = frozenset({"README.md", "SKILL.md", "pyproject.toml", "uv.lock"})
_ALLOWED_DIRECTORIES = frozenset({"references", "assets", "schemas", "scripts", "src"})
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".skill-staging",
        ".venv",
        "__pycache__",
        "browser-assets",
        "build",
        "career-data",
        "dist",
        "eval-output",
        "eval-results",
        "evals",
        "htmlcov",
        "ms-playwright",
        "output",
        "outputs",
        "package-staging",
        "playwright-report",
        "private-source",
        "real-data",
        "real-output",
        "real-source",
        "runs",
        "tests",
        "venv",
    }
)
_ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _is_excluded(relative_path: Path) -> bool:
    parts = tuple(part.lower() for part in relative_path.parts)
    name = parts[-1] if parts else ""
    return (
        any(part in _EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts)
        or name in {".coverage", ".ds_store", "coverage.xml"}
        or name.endswith((".pyc", ".pyo"))
        or (name.startswith("test_") and name.endswith(".py"))
        or name.endswith("_test.py")
    )


def _check_symlink(path: Path, project_root: Path) -> None:
    if not path.is_symlink():
        return
    try:
        target = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"Broken symlink is not packageable: {path}") from error
    if not target.is_relative_to(project_root):
        raise ValueError(f"Symlink escapes the project: {path} -> {target}")


def _iter_selected(project_root: Path) -> list[Path]:
    selected: list[Path] = []
    for name in sorted(_ALLOWED_FILES | _ALLOWED_DIRECTORIES):
        candidate = project_root / name
        if not candidate.exists() and not candidate.is_symlink():
            continue
        _check_symlink(candidate, project_root)
        selected.append(candidate)
        if candidate.is_dir() and not candidate.is_symlink():
            for descendant in sorted(candidate.rglob("*")):
                relative = descendant.relative_to(project_root)
                if _is_excluded(relative):
                    continue
                _check_symlink(descendant, project_root)
                selected.append(descendant)
    return selected


def _stage(project_root: Path, staging_root: Path) -> Path:
    staged_project = staging_root / project_root.name
    staged_project.mkdir(mode=0o700)
    for source in _iter_selected(project_root):
        relative = source.relative_to(project_root)
        if _is_excluded(relative):
            continue
        destination = staged_project / relative
        source_stat = source.lstat()
        if stat.S_ISLNK(source_stat.st_mode):
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.symlink_to(os.readlink(source))
        elif stat.S_ISDIR(source_stat.st_mode):
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copystat(source, destination, follow_symlinks=False)
        elif stat.S_ISREG(source_stat.st_mode):
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source, destination, follow_symlinks=False)
        else:
            raise ValueError(f"Unsupported filesystem entry: {source}")
    return staged_project


def _find_skill_creator_script() -> Path | None:
    configured = os.environ.get("SKILL_CREATOR_PACKAGE_SCRIPT")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Configured package script does not exist: {candidate}")
        return candidate

    for distribution_name in ("skill-creator", "skill_creator"):
        try:
            distribution = importlib.metadata.distribution(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for file in distribution.files or ():
            if PurePosixPath(str(file)).as_posix().endswith("scripts/package_skill.py"):
                candidate = Path(distribution.locate_file(file)).resolve()
                if candidate.is_file() and candidate != Path(__file__).resolve():
                    return candidate
    return None


def _validate_archive(archive: Path, skill_name: str) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Unsafe archive member: {member.filename}")
            parts = path.parts[1:] if path.parts[0] == skill_name else path.parts
            if not parts:
                continue
            if parts[0] not in _ALLOWED_FILES | _ALLOWED_DIRECTORIES:
                raise ValueError(f"Unexpected archive member: {member.filename}")
            if _is_excluded(Path(*parts)):
                raise ValueError(f"Excluded archive member: {member.filename}")


def _external_package(script: Path, staged_project: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="skill-package-output-") as output_text:
        output_directory = Path(output_text)
        os.chmod(output_directory, 0o700)
        subprocess.run(
            [sys.executable, str(script), str(staged_project), str(output_directory)],
            check=True,
        )
        archives = sorted(output_directory.rglob("*.skill"))
        if len(archives) != 1:
            raise RuntimeError(
                f"Skill creator produced {len(archives)} .skill archives; expected exactly one"
            )
        _validate_archive(archives[0], staged_project.name)
        shutil.copyfile(archives[0], destination)


def _zip_entry(archive: zipfile.ZipFile, path: Path, archive_name: str) -> None:
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    info = zipfile.ZipInfo(archive_name, _ARCHIVE_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    if stat.S_ISLNK(metadata.st_mode):
        info.external_attr = (stat.S_IFLNK | mode) << 16
        archive.writestr(info, os.readlink(path).encode("utf-8"))
    elif stat.S_ISDIR(metadata.st_mode):
        info.filename = archive_name.rstrip("/") + "/"
        info.external_attr = (stat.S_IFDIR | mode) << 16
        archive.writestr(info, b"")
    else:
        info.external_attr = (stat.S_IFREG | mode) << 16
        with path.open("rb") as source:
            archive.writestr(info, source.read())


def _deterministic_package(staged_project: Path, destination: Path) -> None:
    entries = [staged_project, *sorted(staged_project.rglob("*"))]
    with zipfile.ZipFile(destination, "w") as archive:
        for path in entries:
            relative = path.relative_to(staged_project.parent).as_posix()
            _zip_entry(archive, path, relative)


def package(project_root: Path, destination: Path) -> Path:
    project_root = project_root.resolve(strict=True)
    if not project_root.is_dir():
        raise NotADirectoryError(project_root)

    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)

    with tempfile.TemporaryDirectory(prefix="china-targeted-resume-package-") as staging_text:
        staging_root = Path(staging_text)
        os.chmod(staging_root, 0o700)
        staged_project = _stage(project_root, staging_root)
        external_script = _find_skill_creator_script()
        if external_script is None:
            _deterministic_package(staged_project, destination)
        else:
            _external_package(external_script, staged_project, destination)

    os.chmod(destination, 0o600)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("output", nargs="?", type=Path)
    arguments = parser.parse_args()
    output = arguments.output or arguments.project_root / "dist" / (
        arguments.project_root.resolve().name + ".skill"
    )
    print(package(arguments.project_root, output))


if __name__ == "__main__":
    main()
