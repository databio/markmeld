"""
Tests for CloudCacheManager (disk cache metadata for cached Google Drive
figures/CSVs/bibliographies) and the GoogleDriveProcessor disk-cache paths
that build on it.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

try:
    from markmeld.google_drive import CloudCacheManager

    GOOGLE_DEPS_AVAILABLE = True
except ImportError:
    GOOGLE_DEPS_AVAILABLE = False


@pytest.mark.skipif(
    not GOOGLE_DEPS_AVAILABLE, reason="Google Drive dependencies not available"
)
def test_cache_manager_resolves_relative_and_absolute_paths(tmp_path):
    """cache_root is always resolved to an absolute path, whichever form it's given in."""
    for relative in (Path("relative/.cache"), "test/.cache"):
        manager = CloudCacheManager(cache_root=relative, create_dirs=False)
        assert manager.cache_root.is_absolute()

    absolute_cache = tmp_path / ".cache"
    manager = CloudCacheManager(cache_root=str(absolute_cache), create_dirs=False)
    assert manager.cache_root.is_absolute()
    assert manager.cache_root == absolute_cache.resolve()


class TestGoogleDriveDiskCache:
    """Disk cache save/load/invalidate behavior of GoogleDriveProcessor.

    See test_google_drive.py::test_google_drive_processor_initialization for
    the canonical cache_root-resolution assertion (absolute path + name).
    """

    def test_disk_cache_save_and_load(self, google_drive_processor, tmp_path):
        processor = google_drive_processor(
            save_to_disk=True, cache_root=str(tmp_path / ".cache")
        ).processor
        processor.get_metadata = MagicMock(
            return_value={
                "name": "test_document",
                "modifiedTime": "2024-01-01T10:00:00Z",
                "md5Checksum": "abc123",
            }
        )
        processor._document_has_suggestions = MagicMock(return_value=False)
        processor._download_first_tab = MagicMock(return_value="# Test\n\nContent")

        content1 = processor._download_raw_markdown("test_doc_id")
        assert "Test" in content1
        assert processor._download_first_tab.call_count == 1

        # modifiedTime is unchanged, so the second call is served from cache.
        content2 = processor._download_raw_markdown("test_doc_id")
        assert content2 == content1
        assert processor._download_first_tab.call_count == 1

    def test_disk_cache_disabled(self, google_drive_processor):
        processor = google_drive_processor(save_to_disk=False).processor
        assert processor.save_to_disk is False
        assert processor._load_from_disk("any_doc_id") is None

    def test_disk_cache_invalidation_on_modification(
        self, google_drive_processor, tmp_path
    ):
        processor = google_drive_processor(
            save_to_disk=True, cache_root=str(tmp_path / ".cache")
        ).processor
        processor._document_has_suggestions = MagicMock(return_value=False)
        processor.get_metadata = MagicMock(
            return_value={
                "name": "test_document",
                "modifiedTime": "2024-01-01T10:00:00Z",
                "md5Checksum": "abc123",
            }
        )
        processor._download_first_tab = MagicMock(return_value="# Original\n\nContent")
        content1 = processor._download_raw_markdown("test_doc_id")
        assert "Original" in content1

        # modifiedTime advances -> cache is invalidated, re-download happens.
        processor._download_first_tab = MagicMock(return_value="# Modified\n\nContent")
        processor.get_metadata = MagicMock(
            return_value={
                "name": "test_document",
                "modifiedTime": "2024-06-18T12:00:00Z",
                "md5Checksum": "def456",
            }
        )
        content2 = processor._download_raw_markdown("test_doc_id")
        assert "Modified" in content2


@pytest.mark.parametrize(
    "stored_metadata, get_metadata_result, expected",
    [
        pytest.param(
            None,
            {"modifiedTime": "2024-01-01T10:00:00Z"},
            True,
            id="no-stored-metadata",
        ),
        pytest.param(
            {"document": {"modified_time": "2024-01-01T10:00:00Z"}},
            {"modifiedTime": "2024-01-01T10:00:00Z"},
            False,
            id="matching-modified-time",
        ),
        pytest.param(
            {"document": {"modified_time": "2024-01-01T10:00:00Z"}},
            {"modifiedTime": "2024-06-18T12:00:00Z"},
            True,
            id="differing-modified-time",
        ),
        pytest.param(
            {"document": {"modified_time": "2024-01-01T10:00:00Z"}},
            RuntimeError("Drive API down"),
            True,
            id="get-metadata-error-fails-open",
        ),
    ],
)
def test_document_has_changed(
    google_drive_processor, stored_metadata, get_metadata_result, expected
):
    """_document_has_changed compares stored vs. live modifiedTime, failing open on error."""
    processor = google_drive_processor().processor
    processor.cache_manager.load_metadata = MagicMock(return_value=stored_metadata)
    if isinstance(get_metadata_result, Exception):
        processor.get_metadata = MagicMock(side_effect=get_metadata_result)
    else:
        processor.get_metadata = MagicMock(return_value=get_metadata_result)

    assert processor._document_has_changed("doc_id") is expected


class TestCloudCacheManagerMetadata:
    """v3.x metadata recording, file categorization, and cache stats."""

    @pytest.mark.parametrize(
        "filename, source_path, size, category, conversion_status",
        [
            pytest.param(
                "image.svg", "fig/image.svg", 1234, "figures", "pending", id="svg"
            ),
            pytest.param("data.csv", "csv/data.csv", 5678, "csvs", "pending", id="csv"),
            pytest.param(
                "photo.png",
                "fig/photo.png",
                9999,
                "figures",
                "skipped",
                id="png-no-conversion",
            ),
            pytest.param(
                "references.bib",
                "bib/references.bib",
                1024,
                "bibliographies",
                "skipped",
                id="bib",
            ),
        ],
    )
    def test_record_cached_file_by_category(
        self, ccm, filename, source_path, size, category, conversion_status
    ):
        ccm.record_cached_file(
            doc_id="test_doc", filename=filename, source_path=source_path, size=size
        )
        metadata = ccm.load_metadata("test_doc")
        assert metadata["cache_version"] == "3.3"
        assert len(metadata[category]) == 1

        entry = metadata[category][0]
        assert entry["filename"] == filename
        assert entry["source_path"] == source_path
        assert entry["size"] == size
        assert entry["conversion"]["status"] == conversion_status

    @pytest.mark.parametrize(
        "filename",
        ["references.bib", "paper.bib", "refs.BIB"],
        ids=["lower", "lower2", "upper"],
    )
    def test_bibliography_file_category(self, ccm, filename):
        assert ccm._get_file_category(filename) == "bibliographies"

    def test_non_bibliography_extension_has_no_category(self, ccm):
        assert ccm._get_file_category("document.pdf") is None

    def test_bibliography_cache_subdir(self, ccm):
        bib_dir = ccm.get_cache_dir("doc123", "bib")
        assert bib_dir.exists()
        assert bib_dir.name == "bib"
        assert "doc123" in str(bib_dir)

    def test_record_cached_file_legend_label(self, ccm):
        ccm.record_cached_file(
            doc_id="test_doc",
            filename="tss.svg",
            source_path="fig/tss.svg",
            size=1234,
            legend="\\label{tss} Fig: TSS enrichment",
            label="tss",
        )
        fig = ccm.load_metadata("test_doc")["figures"][0]
        assert fig["legend"] == "\\label{tss} Fig: TSS enrichment"
        assert fig["label"] == "tss"

    def test_update_cached_file_preserves_legend_label(self, ccm):
        """update_cached_file must not erase legend/label set by record_cached_file."""
        ccm.record_cached_file(
            doc_id="test_doc",
            filename="tss.svg",
            source_path="fig/tss.svg",
            size=10,
            legend="Fig: TSS",
            label="tss",
        )
        cache_path = ccm.cache_root / "test_doc" / "fig" / "tss.svg"
        ccm.update_cached_file(cache_path, content="<svg>new</svg>")

        fig = ccm.load_metadata("test_doc")["figures"][0]
        assert fig["legend"] == "Fig: TSS"
        assert fig["label"] == "tss"

    def test_record_conversion_success(self, ccm):
        ccm.record_cached_file(
            doc_id="test_doc",
            filename="image.svg",
            source_path="fig/image.svg",
            size=1234,
        )
        ccm.record_conversion(
            doc_id="test_doc",
            filename="image.svg",
            output_path="converted/fig/image.pdf",
            output_size=5678,
            status="success",
        )
        fig = ccm.load_metadata("test_doc")["figures"][0]
        assert fig["conversion"]["status"] == "success"
        assert fig["conversion"]["output_path"] == "converted/fig/image.pdf"
        assert fig["conversion"]["output_size"] == 5678
        assert fig["conversion"]["converted_at"] is not None

    def test_record_conversion_failed(self, ccm):
        ccm.record_cached_file(
            doc_id="test_doc",
            filename="broken.svg",
            source_path="fig/broken.svg",
            size=100,
        )
        ccm.record_conversion(
            doc_id="test_doc",
            filename="broken.svg",
            status="failed",
            error="Inkscape conversion failed",
        )
        fig = ccm.load_metadata("test_doc")["figures"][0]
        assert fig["conversion"]["status"] == "failed"
        assert fig["conversion"]["error"] == "Inkscape conversion failed"
        assert fig["conversion"]["converted_at"] is None

    def test_cache_stats_update(self, ccm):
        ccm.record_cached_file("test_doc", "img1.svg", "fig/img1.svg", 1000)
        ccm.record_cached_file("test_doc", "img2.png", "fig/img2.png", 2000)
        ccm.record_cached_file("test_doc", "data.csv", "csv/data.csv", 3000)
        ccm.record_cached_file("test_doc", "refs.bib", "bib/refs.bib", 500)
        ccm.record_conversion(
            "test_doc", "img1.svg", "converted/fig/img1.pdf", 1500, "success"
        )

        stats = ccm.load_metadata("test_doc")["cache_stats"]
        assert stats["total_files"] == 4
        assert stats["figures_count"] == 2
        assert stats["csvs_count"] == 1
        assert stats["bibliographies_count"] == 1
        assert stats["total_size"] == 1000 + 2000 + 3000 + 500 + 1500
        assert stats["conversions_successful"] == 1
        assert stats["conversions_failed"] == 0
        assert stats["conversions_pending"] == 1

    def test_update_existing_file_record(self, ccm):
        ccm.record_cached_file(
            "test_doc", "img.svg", "fig/img.svg", 1000, digest="old_digest"
        )
        ccm.record_cached_file(
            "test_doc", "img.svg", "fig/img.svg", 1100, digest="new_digest"
        )

        metadata = ccm.load_metadata("test_doc")
        assert len(metadata["figures"]) == 1
        fig = metadata["figures"][0]
        assert fig["size"] == 1100
        assert fig["digest"] == "new_digest"

    def test_no_backward_compatibility_v2(self, ccm):
        """v2.0 metadata is rejected, not silently upgraded."""
        old_metadata = {
            "doc_id": "test_doc_123",
            "doc_name": "Test Document",
            "cache_version": "2.0",
        }
        metadata_path = ccm.cache_root / "test_doc" / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(old_metadata))

        assert ccm.load_metadata("test_doc") is None

    def test_corrupt_metadata_handling(self, ccm):
        metadata_path = ccm.cache_root / "test_doc" / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text("{invalid json}")

        assert ccm.load_metadata("test_doc") is None

    def test_in_memory_cache_performance(self, ccm):
        ccm.record_cached_file("test_doc", "test.svg", "fig/test.svg", 1000)
        metadata1 = ccm.load_metadata("test_doc")
        metadata2 = ccm.load_metadata("test_doc")
        assert metadata1 == metadata2
        assert "metadata_test_doc" in ccm._metadata_cache

    def test_get_cached_files_summary(self, ccm):
        ccm.record_cached_file("test_doc", "img1.svg", "fig/img1.svg", 1000)
        ccm.record_cached_file("test_doc", "data.csv", "csv/data.csv", 2000)
        ccm.record_cached_file("test_doc", "refs.bib", "bib/refs.bib", 500)
        ccm.record_conversion(
            "test_doc", "img1.svg", "converted/fig/img1.pdf", 1500, "success"
        )

        summary = ccm.get_cached_files_summary("test_doc")
        assert "document" in summary
        assert len(summary["figures"]) == 1
        assert len(summary["csvs"]) == 1
        assert len(summary["bibliographies"]) == 1
        assert summary["cache_stats"]["conversions_successful"] == 1
        assert summary["cache_stats"]["bibliographies_count"] == 1

    def test_empty_summary_for_nonexistent_doc(self, ccm):
        assert ccm.get_cached_files_summary("nonexistent_doc") == {}

    def test_get_folder_id_with_v3_metadata(self, ccm):
        metadata = {
            "document": {"doc_id": "test_doc", "folder_id": "folder123"},
            "figures": [],
            "csvs": [],
            "cache_stats": ccm._init_cache_stats(),
            "cache_version": "3.0",
        }
        ccm.save_metadata("test_doc", metadata)
        assert ccm.get_folder_id("test_doc") == "folder123"
