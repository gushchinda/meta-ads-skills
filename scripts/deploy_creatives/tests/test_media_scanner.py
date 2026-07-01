import pytest
from pathlib import Path

from deploy_creatives.media_scanner import scan_media, MediaFiles

FIXTURES = Path(__file__).parent / "fixtures" / "sample_concept"


def test_scan_finds_all_media():
    media = scan_media(FIXTURES)
    assert len(media.all_files) == 3


def test_scan_separates_images_and_videos():
    media = scan_media(FIXTURES)
    assert len(media.images) == 2
    assert len(media.videos) == 1


def test_scan_files_sorted_by_name():
    media = scan_media(FIXTURES)
    names = [f.name for f in media.all_files]
    assert names == sorted(names)


def test_scan_ad_names_are_stems():
    media = scan_media(FIXTURES)
    ad_names = media.ad_names()
    assert ad_names == ["001_Test_1x1", "002_Test_9x16", "003_Test_1x1"]


def test_scan_empty_folder_raises():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="No media files"):
            scan_media(Path(tmp))


def test_scan_nonexistent_folder_raises():
    with pytest.raises(FileNotFoundError):
        scan_media(Path("/nonexistent/folder"))
