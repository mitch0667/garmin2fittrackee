import logging
import zipfile
from pathlib import Path

from garmin2fittrackee import ArchiveError

logger = logging.getLogger(__name__)


def _extract_nested_zips(directory: Path) -> None:
    for zip_path in sorted(directory.rglob("*.zip")):
        target = zip_path.parent / zip_path.stem
        logger.info("Extracting nested archive: %s", zip_path)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(target)
        except zipfile.BadZipFile:
            logger.warning(
                "Skipping invalid nested ZIP: %s",
                zip_path,
            )
        zip_path.unlink()
        _extract_nested_zips(target)


def extract_archive(archive_path: Path, extract_folder: Path) -> Path:
    if not archive_path.exists():
        raise ArchiveError(f"Archive not found: {archive_path}")

    if not archive_path.is_file():
        raise ArchiveError(f"Not a file: {archive_path}")

    if not zipfile.is_zipfile(archive_path):
        raise ArchiveError(f"Not a valid ZIP archive: {archive_path}")

    archive_stem = archive_path.stem
    target_dir = extract_folder / archive_stem

    extract_folder.mkdir(parents=True, exist_ok=True)

    if target_dir.exists():
        logger.warning(
            "Extraction target already exists, overwriting: %s",
            target_dir,
        )

    logger.info("Extracting %s to %s", archive_path, target_dir)

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(target_dir)

    _extract_nested_zips(target_dir)

    logger.info("Extraction complete: %s", target_dir)
    return target_dir
