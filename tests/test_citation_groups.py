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
