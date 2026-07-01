from dataclasses import dataclass, field
from pathlib import Path
from typing import List

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass
class MediaFiles:
    all_files: List[Path] = field(default_factory=list)

    @property
    def images(self) -> List[Path]:
        return [f for f in self.all_files if f.suffix.lower() in IMAGE_EXTENSIONS]

    @property
    def videos(self) -> List[Path]:
        return [f for f in self.all_files if f.suffix.lower() in VIDEO_EXTENSIONS]

    def ad_names(self) -> List[str]:
        return [f.stem for f in self.all_files]


def scan_media(folder: Path) -> MediaFiles:
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    )

    if not files:
        raise ValueError(f"No media files found in {folder}")

    return MediaFiles(all_files=files)
