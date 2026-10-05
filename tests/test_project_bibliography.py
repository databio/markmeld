"""A `bib_source: gdrive` target fetches its `bibliography` from Drive on every build.

Regression: the Research Strategy built with a week-old ref.bib because the
Drive fetch was triggered by a `bibliography:` line inside the Google Doc, and
someone typed notes above it. The target's `bibliography` is what pandoc reads
(markmeld puts it into the document metadata at top priority), so the target
setting decides the fetch, and every target of a project shares one copy under
`<cache_root>/_project/bib/`.
"""

import contextlib
import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from markmeld.const import GOOGLE_DOC_TARGET_TYPE, PROJECT_CACHE_SUBDIR
from markmeld.exceptions import BibliographyFetchError

BIB = b"@article{a, title={A}}\n"
BIB_MD5 = hashlib.md5(BIB).hexdigest()


# ---------------------------------------------------------------------------
# GoogleDriveProcessor.find_file_in_drive / fetch_project_bibliography
# ---------------------------------------------------------------------------


@pytest.fixture
def gdp(google_drive_processor, tmp_path):
    services = google_drive_processor(cache_root=str(tmp_path / "cache"))
    return services


def test_find_file_in_drive_asks_for_checksum(gdp):
    files = gdp.drive.files.return_value
    files.list.return_value.execute.return_value = {
        "files": [{"id": "F1", "name": "ref.bib", "md5Checksum": BIB_MD5}]
    }
    info = gdp.processor.find_file_in_drive("bib/ref.bib", "FOLDER")
    assert info["md5Checksum"] == BIB_MD5
    fields = files.list.call_args.kwargs["fields"]
    assert "md5Checksum" in fields
    assert "'FOLDER' in parents" in files.list.call_args.kwargs["q"]
    assert "name='ref.bib'" in files.list.call_args.kwargs["q"]


def test_find_file_in_drive_raises_on_api_error(gdp):
    """A Drive failure must not look like 'file not found'."""
    gdp.drive.files.return_value.list.return_value.execute.side_effect = RuntimeError("503")
    with pytest.raises(RuntimeError):
        gdp.processor.find_file_in_drive("ref.bib", "FOLDER")


def _fake_download(content=BIB):
    def _dl(file_id, destination_path):
        Path(destination_path).write_bytes(content)

    return _dl


def _dest(processor):
    return processor.cache_manager.cache_root / PROJECT_CACHE_SUBDIR / "bib" / "ref.bib"


def test_fetch_downloads_when_no_cached_copy(gdp):
    p = gdp.processor
    info = {"id": "F1", "name": "ref.bib", "md5Checksum": BIB_MD5}
    with (
        patch.object(p, "find_file_in_drive", return_value=info) as find,
        patch.object(p, "download_file", side_effect=_fake_download()) as dl,
    ):
        result = p.fetch_project_bibliography("bib/ref.bib", "FOLDER")

    find.assert_called_once_with("ref.bib", "FOLDER")
    dl.assert_called_once()
    assert dl.call_args.args[0] == "F1"
    assert result == {"path": str(_dest(p)), "status": "downloaded"}
    assert _dest(p).read_bytes() == BIB


def test_fetch_skips_download_when_md5_matches(gdp):
    p = gdp.processor
    _dest(p).parent.mkdir(parents=True)
    _dest(p).write_bytes(BIB)
    info = {"id": "F1", "name": "ref.bib", "md5Checksum": BIB_MD5}
    with (
        patch.object(p, "find_file_in_drive", return_value=info),
        patch.object(p, "download_file") as dl,
    ):
        result = p.fetch_project_bibliography("bib/ref.bib", "FOLDER")

    dl.assert_not_called()
    assert result == {"path": str(_dest(p)), "status": "unchanged"}


@pytest.mark.parametrize("force_refresh,remote_md5", [(False, "different"), (True, BIB_MD5)])
def test_fetch_redownloads_on_change_or_force(gdp, force_refresh, remote_md5):
    p = gdp.processor
    _dest(p).parent.mkdir(parents=True)
    _dest(p).write_bytes(BIB)
    new = b"@article{b, title={B}}\n"
    info = {"id": "F1", "name": "ref.bib", "md5Checksum": remote_md5}
    with (
        patch.object(p, "find_file_in_drive", return_value=info),
        patch.object(p, "download_file", side_effect=_fake_download(new)) as dl,
    ):
        result = p.fetch_project_bibliography("bib/ref.bib", "FOLDER", force_refresh=force_refresh)

    dl.assert_called_once()
    assert result["status"] == "downloaded"
    assert _dest(p).read_bytes() == new


def test_fetch_raises_when_file_not_in_folder(gdp):
    p = gdp.processor
    with (
        patch.object(p, "find_file_in_drive", return_value=None),
        pytest.raises(BibliographyFetchError, match="ref.bib"),
    ):
        p.fetch_project_bibliography("bib/ref.bib", "FOLDER")


def test_fetch_records_drive_sidecar(gdp):
    """The Drive file id is kept next to the bib so the UI can link and edit it."""
    import json

    p = gdp.processor
    info = {"id": "F1", "name": "ref.bib", "md5Checksum": BIB_MD5}
    with (
        patch.object(p, "find_file_in_drive", return_value=info),
        patch.object(p, "download_file", side_effect=_fake_download()),
    ):
        p.fetch_project_bibliography("bib/ref.bib", "FOLDER")

    sidecar = json.loads(_dest(p).with_name("ref.bib.drive.json").read_text())
    assert sidecar["drive_file_id"] == "F1"
    assert sidecar["folder_id"] == "FOLDER"
    assert sidecar["md5Checksum"] == BIB_MD5


# ---------------------------------------------------------------------------
# MarkdownMelder.preprocess_google_doc
# ---------------------------------------------------------------------------

# The Doc carries no `bibliography:` line at all.
DOC_MD = "Some text citing [@a].\n"


class _FakeCacheManager:
    def __init__(self, cache_root):
        self.cache_root = Path(cache_root).resolve()

    def doc_lock(self, doc_id):
        return contextlib.nullcontext()


def _fake_gdp_class(fetch, resolve_folder="PARENT"):
    """A GoogleDriveProcessor stand-in whose Docs are always unchanged."""

    class _FakeGDP:
        instances = []

        def __init__(self, cache_root=".cache", **kwargs):
            self.cache_manager = _FakeCacheManager(cache_root)
            self.fetch_project_bibliography = MagicMock(side_effect=fetch(self))
            self._resolve_folder_id = MagicMock(return_value=resolve_folder)
            _FakeGDP.instances.append(self)

        def project_bibliography_path(self, name):
            return self.cache_manager.cache_root / PROJECT_CACHE_SUBDIR / "bib" / Path(name).name

        def process_document_figures(self, doc_id, folder_id=None, **kwargs):
            return {"document": DOC_MD, "results": {"skipped": ["fig.svg"]}}

    return _FakeGDP


def _ok_fetch(gdp):
    def _f(name, folder_id, force_refresh=False):
        path = gdp.project_bibliography_path(name)
        return {"path": str(path), "status": "unchanged"}

    return _f


def _target(tmp_path, **cfg):
    from markmeld.melder import MarkdownMelder, Target

    target = {
        "type": GOOGLE_DOC_TARGET_TYPE,
        "command": None,
        "_workpath": str(tmp_path),
        "_defpath": str(tmp_path),
        "data": {"google_docs": {"content": "DOC1", "folder_id": "FOLDER"}},
        **cfg,
    }
    mm = MarkdownMelder(
        {
            "_cfg_file_path": str(tmp_path / "_markmeld.yaml"),
            "_cache_root": str(tmp_path / "cache"),
            "targets": {"t": target},
        }
    )
    return mm, Target(mm.cfg, "t")


def _project_bib(tmp_path):
    return (tmp_path / "cache" / PROJECT_CACHE_SUBDIR / "bib" / "ref.bib").resolve()


def test_gdrive_target_fetches_bib_even_when_docs_unchanged(tmp_path):
    """The original failure: no Doc change, no `bibliography:` line, still checked."""
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    assert out is not None
    gdp = fake.instances[-1]
    gdp.fetch_project_bibliography.assert_called_once_with("bib/ref.bib", "FOLDER", False)
    assert out.meta["bibliography"] == str(_project_bib(tmp_path))
    assert out.meta["data"]["md_content"]["content"] == DOC_MD


def test_gdrive_target_without_folder_id_uses_first_docs_parent(tmp_path):
    fake = _fake_gdp_class(_ok_fetch, resolve_folder="PARENT")
    mm, tgt = _target(
        tmp_path,
        bib_source="gdrive",
        bibliography="bib/ref.bib",
        data={"google_docs": {"content": "DOC1"}},
    )
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    gdp = fake.instances[-1]
    gdp._resolve_folder_id.assert_called_once_with("DOC1")
    gdp.fetch_project_bibliography.assert_called_once_with("bib/ref.bib", "PARENT", False)
    assert out.meta["bibliography"] == str(_project_bib(tmp_path))


def test_two_targets_of_one_project_read_the_same_bib(tmp_path):
    fake = _fake_gdp_class(_ok_fetch)
    paths = []
    for doc in ("DOC1", "DOC2"):
        mm, tgt = _target(
            tmp_path,
            bib_source="gdrive",
            bibliography="bib/ref.bib",
            data={"google_docs": {"content": doc, "folder_id": "FOLDER"}},
        )
        with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
            paths.append(mm.preprocess_google_doc(tgt).meta["bibliography"])
    assert paths[0] == paths[1] == str(_project_bib(tmp_path))


@pytest.mark.parametrize("cfg", [{}, {"bib_source": "lumenoia"}])
def test_non_gdrive_target_makes_no_drive_bib_call(tmp_path, cfg):
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(tmp_path, bibliography="bib/ref.bib", **cfg)
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    fake.instances[-1].fetch_project_bibliography.assert_not_called()
    assert out.meta["bibliography"] == "bib/ref.bib"


def test_gdrive_target_with_absolute_bibliography_skips_fetch(tmp_path):
    """An absolute path is a local file: there is no Drive file to fetch."""
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="/abs/lab/master.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    assert out is not None
    fake.instances[-1].fetch_project_bibliography.assert_not_called()
    assert out.meta["bibliography"] == "/abs/lab/master.bib"


def test_gdrive_list_fetches_relative_and_keeps_absolute(tmp_path):
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(
        tmp_path, bib_source="gdrive", bibliography=["bib/ref.bib", "/abs/lab/master.bib"]
    )
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    fake.instances[-1].fetch_project_bibliography.assert_called_once_with(
        "bib/ref.bib", "FOLDER", False
    )
    assert out.meta["bibliography"] == [str(_project_bib(tmp_path)), "/abs/lab/master.bib"]


@pytest.mark.parametrize("value", [None, ""])
def test_gdrive_target_without_bibliography_fails(tmp_path, value, melder_log):
    fake = _fake_gdp_class(_ok_fetch)
    cfg = {"bib_source": "gdrive"}
    if value is not None:
        cfg["bibliography"] = value
    mm, tgt = _target(tmp_path, **cfg)
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        assert mm.preprocess_google_doc(tgt) is None
    assert "bib_source: gdrive needs a bibliography" in melder_log.text


@pytest.fixture
def melder_log(caplog):
    """caplog wired straight to markmeld's logger (other tests turn off propagation)."""
    import logging

    from markmeld import melder

    melder._LOGGER.addHandler(caplog.handler)
    level = melder._LOGGER.level
    melder._LOGGER.setLevel(logging.INFO)
    yield caplog
    melder._LOGGER.setLevel(level)
    melder._LOGGER.removeHandler(caplog.handler)


def test_gdrive_target_logs_the_check(tmp_path, melder_log):
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        mm.preprocess_google_doc(tgt)
    assert "MM | Bibliography ref.bib: unchanged (Drive md5)" in melder_log.text


def _raising_fetch(exc):
    def _factory(gdp):
        def _f(*args, **kwargs):
            raise exc

        return _f

    return _factory


def test_drive_error_with_cached_copy_warns_and_uses_cache(tmp_path, melder_log):
    _project_bib(tmp_path).parent.mkdir(parents=True)
    _project_bib(tmp_path).write_bytes(BIB)
    fake = _fake_gdp_class(_raising_fetch(RuntimeError("Drive 503")))
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.preprocess_google_doc(tgt)

    assert out is not None
    assert out.meta["bibliography"] == str(_project_bib(tmp_path))
    assert "Drive 503" in melder_log.text


@pytest.mark.parametrize(
    "exc", [RuntimeError("Drive 503"), BibliographyFetchError("ref.bib not found")]
)
def test_fetch_failure_without_usable_cache_fails_build(tmp_path, exc):
    fake = _fake_gdp_class(_raising_fetch(exc))
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        assert mm.preprocess_google_doc(tgt) is None


def test_missing_drive_file_fails_even_with_stale_cache(tmp_path):
    """A bib deleted from Drive is a config error, not a network blip."""
    _project_bib(tmp_path).parent.mkdir(parents=True)
    _project_bib(tmp_path).write_bytes(BIB)
    fake = _fake_gdp_class(_raising_fetch(BibliographyFetchError("ref.bib not found")))
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        assert mm.preprocess_google_doc(tgt) is None


def test_gdrive_bib_lands_in_document_metadata(tmp_path):
    """The fetched path reaches pandoc through metadata, not --bibliography."""
    fake = _fake_gdp_class(_ok_fetch)
    mm, tgt = _target(tmp_path, bib_source="gdrive", bibliography="bib/ref.bib")
    with patch("markmeld.google_drive.GoogleDriveProcessor", fake):
        out = mm.build_target("t", vardump=True, report=False)
    assert out.melded_output["_global_frontmatter"]["dict"]["bibliography"] == str(
        _project_bib(tmp_path)
    )
    assert os.path.isabs(out.meta["bibliography"])
