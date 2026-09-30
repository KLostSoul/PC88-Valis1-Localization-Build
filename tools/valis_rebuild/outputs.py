"""Publish complete build artifacts and restore prior files on failure."""

from pathlib import Path
import shutil

from .errors import BuildError


def publish_outputs(reports: tuple[dict, ...], output: Path, inputs: set[Path]) -> None:
    destinations: list[tuple[dict, str, Path, Path, Path | None]] = []
    for report in reports:
        for artifact in ("output", "ips"):
            if artifact not in report:
                continue
            staged = Path(report[artifact]["path"])
            destination = output / staged.name
            if destination.resolve() in inputs:
                raise BuildError(f"출력이 원본 입력을 덮어씁니다: {destination}")
            if destination.exists() and not destination.is_file():
                raise BuildError(f"출력 경로가 파일이 아닙니다: {destination}")
            previous = staged.with_name(staged.name + ".previous") if destination.exists() else None
            if previous is not None:
                shutil.copy2(destination, previous)
            destinations.append((report, artifact, staged, destination, previous))
    published: list[tuple[Path, Path | None]] = []
    try:
        for report, artifact, staged, destination, previous in destinations:
            staged.replace(destination)
            published.append((destination, previous))
            report[artifact]["path"] = str(destination)
    except OSError:
        for destination, previous in reversed(published):
            if previous is None:
                destination.unlink()
            else:
                previous.replace(destination)
        raise
