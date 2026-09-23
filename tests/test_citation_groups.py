"""
Acceptance tests for the citation_groups feature.

citation_groups allow multiple targets to share a citation namespace so that
reference numbers are consistent across documents (e.g., grant proposals where
project_summary, project_description, and references_cited must agree on numbering).
"""

import pytest

import markmeld

CFG_PATH = "tests/test_data/citation_groups/_markmeld.yaml"


@pytest.fixture
def mm():
    """Load the citation_groups test config and return a MarkdownMelder."""
    cfg = markmeld.load_config_wrapper(CFG_PATH)
    return markmeld.MarkdownMelder(cfg)


class TestConsistentNumbering:
    """Scenario 1: Citations get consistent numbers across grouped targets."""

    def test_project_summary_citation_numbers(self, mm):
        """Alpha2020 should be [1] and Beta2021 should be [2] in project_summary."""
        res = mm.build_target("project_summary", print_only=True)
        output = res.melded_output
        # Alpha2020 appears first in the group (first in project_summary) -> [1]
        assert "[1]" in output, f"Expected [1] for Alpha2020, got: {output}"
        assert "[2]" in output, f"Expected [2] for Beta2021, got: {output}"
        # Should not contain higher numbers
        assert "[3]" not in output, f"Unexpected [3] in project_summary: {output}"

    def test_project_description_citation_numbers(self, mm):
        """Beta2021 should be [2] (not [1]) and Gamma2022 should be [3] in project_description."""
        res = mm.build_target("project_description", print_only=True)
        output = res.melded_output
        # Beta2021 was already assigned [2] from project_summary
        assert "[2]" in output, f"Expected [2] for Beta2021, got: {output}"
        # Gamma2022 is new, gets next number [3]
        assert "[3]" in output, f"Expected [3] for Gamma2022, got: {output}"
        # Should NOT have [1] (that's Alpha2020 which doesn't appear here)
        assert "[1]" not in output, f"Unexpected [1] in project_description: {output}"


class TestSuppressBibliography:
    """Scenario 2: suppress-bibliography removes the bibliography from individual targets."""

    def test_project_summary_no_bibliography(self, mm):
        """project_summary output should have inline citations but NO bibliography section."""
        res = mm.build_target("project_summary", print_only=True)
        output = res.melded_output
        # Should have inline citations
        assert "[1]" in output or "[2]" in output, f"Expected inline citations: {output}"
        # Should NOT have a references/bibliography section
        # Pandoc citeproc typically generates a div with id "refs"
        assert "refs" not in output.lower() or '<div id="refs"' not in output, (
            f"Bibliography should be suppressed in project_summary: {output}"
        )

    def test_project_description_no_bibliography(self, mm):
        """project_description output should have inline citations but NO bibliography section."""
        res = mm.build_target("project_description", print_only=True)
        output = res.melded_output
        assert "[2]" in output or "[3]" in output, f"Expected inline citations: {output}"
        assert "refs" not in output.lower() or '<div id="refs"' not in output, (
            f"Bibliography should be suppressed in project_description: {output}"
        )


class TestBibliographyOnly:
    """Scenario 3: bibliography-only renders ONLY the bibliography, no body text."""

    def test_references_cited_is_bibliography_only(self, mm):
        """references_cited should contain only the bibliography, not body text from other sections."""
        res = mm.build_target("references_cited", print_only=True)
        output = res.melded_output
        # Should NOT contain body text from project_summary or project_description
        assert "foundational work" not in output, (
            f"Body text from project_summary leaked into references_cited: {output}"
        )
        assert "approach is valid" not in output, (
            f"Body text from project_description leaked into references_cited: {output}"
        )
        # Should contain bibliography entries
        assert "Alpha" in output, f"Expected Alpha in bibliography: {output}"
        assert "Beta" in output, f"Expected Beta in bibliography: {output}"
        assert "Gamma" in output, f"Expected Gamma in bibliography: {output}"


class TestCitationOrdering:
    """Scenario 4: Citation ordering follows first appearance across grouped sources."""

    def test_ordering_follows_group_source_order(self, mm):
        """Numbers should be assigned by first appearance in group order:
        project_summary is listed first, so Alpha2020 (first in summary) -> [1],
        Beta2021 (second in summary) -> [2], Gamma2022 (first new in description) -> [3].
        """
        res_summary = mm.build_target("project_summary", print_only=True)
        res_desc = mm.build_target("project_description", print_only=True)
        mm.build_target("references_cited", print_only=True)

        summary = res_summary.melded_output
        desc = res_desc.melded_output

        # In project_summary: Alpha before Beta
        alpha_pos = summary.find("[1]")
        beta_pos = summary.find("[2]")
        assert alpha_pos < beta_pos, "Alpha [1] should appear before Beta [2] in summary"

        # In project_description: Beta [2] before Gamma [3]
        beta_pos_desc = desc.find("[2]")
        gamma_pos_desc = desc.find("[3]")
        assert beta_pos_desc < gamma_pos_desc, (
            "Beta [2] should appear before Gamma [3] in description"
        )


class TestUngroupedTargetIndependent:
    """Scenario 5: Targets NOT in any citation group build with normal citeproc."""

    def test_budget_justification_independent_numbering(self, mm):
        """budget_justification is not in a citation group, so it gets its own numbering."""
        res = mm.build_target("budget_justification", print_only=True)
        output = res.melded_output
        # It cites Delta2023 and Alpha2020. With normal citeproc and nature style,
        # they get numbered in order of appearance: [1] and [2]
        assert "[1]" in output, f"Expected [1] in budget_justification: {output}"
        assert "[2]" in output, f"Expected [2] in budget_justification: {output}"
        # Should NOT have [3] (only 2 citations)
        assert "[3]" not in output, f"Unexpected [3] in budget_justification: {output}"

    def test_budget_justification_has_bibliography(self, mm):
        """budget_justification should include its own bibliography (not suppressed)."""
        res = mm.build_target("budget_justification", print_only=True)
        output = res.melded_output
        # Should contain both cited references in bibliography
        assert "Delta" in output, f"Expected Delta in bibliography: {output}"
        assert "Alpha" in output, f"Expected Alpha in bibliography: {output}"
        # Should NOT contain Beta or Gamma (not cited in this target)
        assert "Beta" not in output, f"Unexpected Beta in budget_justification: {output}"
        assert "Gamma" not in output, f"Unexpected Gamma in budget_justification: {output}"


class TestCitationGroupConfig:
    """Test that citation_groups is parsed from _markmeld.yaml with its
    expected group membership."""

    def test_citation_groups_parsed_from_config(self, mm):
        groups = mm.cfg["citation_groups"]
        assert "grant" in groups, f"Expected 'grant' group, got: {list(groups.keys())}"
        assert groups["grant"] == [
            "project_summary",
            "project_description",
            "references_cited",
        ]


# ---------------------------------------------------------------------------
# Google Doc members, authored "References" heading, and failure handling
# ---------------------------------------------------------------------------

import contextlib  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

TEST_DATA = Path(__file__).parent / "test_data" / "citation_groups"

DOC1_MD = """Our approach extends prior work [@Beta2021] and the aims framework [@Alpha2020].

\\newpage

# References

<div id="refs"></div>
"""


class _FakeCacheManager:
    def doc_lock(self, doc_id):
        return contextlib.nullcontext()


class _FakeGDP:
    """Stand-in for GoogleDriveProcessor: serves DOC1_MD for any doc id."""

    def __init__(self, cache_root=None, **kwargs):
        self.cache_manager = _FakeCacheManager()

    def download_doc(self, doc_id, **kwargs):
        return DOC1_MD

    def process_document_figures(self, doc_id, folder_id=None, **kwargs):
        return {"document": DOC1_MD, "results": {}, "bibliography_info": {}}


def _group_cfg(tmp_path, targets, group):
    shutil.copy(TEST_DATA / "references.bib", tmp_path / "references.bib")
    (tmp_path / "generic.jinja").write_text("{{ content }}")
    common = {
        "jinja_template": str(tmp_path / "generic.jinja"),
        "csl": "{mm-csl-biomed-central}",
        "bibdb": str(tmp_path / "references.bib"),
        "_workpath": str(tmp_path),
        "_defpath": str(tmp_path),
    }
    return {
        "_cfg_file_path": str(tmp_path / "_markmeld.yaml"),
        "_cache_root": str(tmp_path / "cache"),
        "citation_groups": {"main": group},
        "targets": {name: {**common, **cfg} for name, cfg in targets.items()},
    }


class TestGoogleDocSibling:
    """Google Doc targets take part in citation groups."""

    @pytest.fixture
    def mm(self, tmp_path):
        aims = tmp_path / "aims.md"
        aims.write_text("The aims build on [@Alpha2020].\n")
        cfg = _group_cfg(
            tmp_path,
            {
                "specific_aims": {
                    "type": "markdown-file",
                    "suppress-bibliography": True,
                    "data": {"md_files": {"content": str(aims)}},
                },
                "research_strategy": {
                    "type": "google-doc",
                    "suppress-bibliography": True,
                    "data": {"google_docs": {"content": "DOC1"}},
                },
                "references": {
                    "type": "google-doc",
                    "bibliography-only": True,
                    "data": {"google_docs": {"content": "DOC1"}},
                },
            },
            ["specific_aims", "research_strategy", "references"],
        )
        with patch("markmeld.google_drive.GoogleDriveProcessor", _FakeGDP):
            yield markmeld.MarkdownMelder(cfg)

    def test_research_strategy_numbering_and_no_refs(self, mm):
        res = mm.build_target("research_strategy", print_only=True)
        out = res.melded_output
        # Alpha2020 is numbered from the aims (first in group), Beta2021 next
        assert out.find("[2]") < out.find("[1]"), out
        assert "[1]" in out and "[2]" in out, out
        assert "first study on alpha" not in out.lower(), out
        assert "second study on beta" not in out.lower(), out
        assert "references" not in out.lower(), out

    def test_references_heading_and_entries(self, mm):
        res = mm.build_target("references", print_only=True)
        out = res.melded_output
        assert "references" in out.lower(), out
        assert "first study on alpha" in out.lower(), out
        assert "second study on beta" in out.lower(), out
        assert "prior work" not in out, out

    def test_sources_include_gdoc_once(self, mm, tmp_path):
        res = mm.build_target("research_strategy", print_only=True)
        sources = res.meta["_citation_group_sources"]
        expected = str((tmp_path / "cache").resolve() / "DOC1" / "citation_source.md")
        assert sources.count(expected) == 1, sources
        assert sources[0] == str(tmp_path / "aims.md"), sources
        assert len(sources) == 2, sources
        assert Path(expected).read_text() == DOC1_MD


class TestAuthoredRefsHeading:
    """The filter handles a "# References" heading written before an authored refs div."""

    def _mm(self, tmp_path, body_text):
        body = tmp_path / "body.md"
        body.write_text(body_text)
        cfg = _group_cfg(
            tmp_path,
            {
                "body": {
                    "suppress-bibliography": True,
                    "data": {"md_files": {"content": str(body)}},
                },
                "refs": {
                    "bibliography-only": True,
                    "data": {"md_files": {"content": str(body)}},
                },
            },
            ["body", "refs"],
        )
        return markmeld.MarkdownMelder(cfg)

    def test_authored_heading_dropped_in_body_kept_in_refs(self, tmp_path):
        mm = self._mm(
            tmp_path,
            "# Plan\n\nWe cite [@Alpha2020].\n\n\\newpage\n\n# References\n\n"
            '<div id="refs"></div>\n',
        )
        body = mm.build_target("body", print_only=True).melded_output
        assert "Plan" in body and "[1]" in body, body
        assert "References" not in body, body
        assert "first study on alpha" not in body.lower(), body

        refs = mm.build_target("refs", print_only=True).melded_output
        assert "References" in refs, refs
        assert "first study on alpha" in refs.lower(), refs
        assert "We cite" not in refs, refs

    def test_last_heading_kept_without_authored_refs(self, tmp_path):
        mm = self._mm(tmp_path, "# Plan\n\nIntro.\n\n# Outlook\n\nWe cite [@Alpha2020].\n")
        body = mm.build_target("body", print_only=True).melded_output
        assert "Outlook" in body, body
        assert "We cite" in body, body

        refs = mm.build_target("refs", print_only=True).melded_output
        assert "Outlook" not in refs, refs
        assert "first study on alpha" in refs.lower(), refs


class TestMissingGroupSource:
    def test_missing_sibling_md_fails_build(self, tmp_path):
        body = tmp_path / "body.md"
        body.write_text("We cite [@Alpha2020].\n")
        cfg = _group_cfg(
            tmp_path,
            {
                "body": {
                    "suppress-bibliography": True,
                    "data": {"md_files": {"content": str(body)}},
                },
                "other": {
                    "suppress-bibliography": True,
                    "data": {"md_files": {"content": str(tmp_path / "missing.md")}},
                },
            },
            ["body", "other"],
        )
        mm = markmeld.MarkdownMelder(cfg)
        assert mm.build_target("body", print_only=True) is None


class TestCacheConcurrency:
    def test_doc_lock_serializes_threads(self, tmp_path):
        cm_mod = pytest.importorskip("markmeld.google_drive.cache_manager")
        ccm = cm_mod.CloudCacheManager(cache_root=tmp_path)
        events = []
        first_in = threading.Event()

        def first():
            with ccm.doc_lock("DOC"):
                events.append("first-in")
                first_in.set()
                time.sleep(0.2)
                events.append("first-out")

        def second():
            first_in.wait()
            with ccm.doc_lock("DOC"):
                events.append("second-in")

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert events == ["first-in", "first-out", "second-in"]

    def test_download_file_is_atomic(self, google_drive_processor, tmp_path):
        services = google_drive_processor()
        dest = tmp_path / "fig" / "a.svg"
        dest.parent.mkdir()
        written_to = []

        class FakeDownloader:
            def __init__(self, fh, request):
                self.fh = fh
                self.calls = 0

            def next_chunk(self):
                self.calls += 1
                # Mid-download, the final path must not exist yet
                assert not dest.exists()
                written_to.append(Path(self.fh.name))
                self.fh.write(b"chunk%d" % self.calls)
                return MagicMock(), self.calls >= 2

        with patch("markmeld.google_drive.processor.MediaIoBaseDownload", FakeDownloader):
            services.processor.download_file("FILE", str(dest))

        assert dest.read_bytes() == b"chunk1chunk2"
        assert all(p != dest and p.parent == dest.parent for p in written_to)
        assert list(dest.parent.iterdir()) == [dest]
