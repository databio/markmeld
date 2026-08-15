"""
Tests for Google Doc target functionality
"""

import pytest
import os
from markmeld.melder import MarkdownMelder, Target
from markmeld.const import GOOGLE_DOCS_KEY, TARGET_TYPE_KEY, GOOGLE_DOC_TARGET_TYPE


@pytest.mark.parametrize(
    "data",
    [
        {},
        {GOOGLE_DOCS_KEY: {}},
        {GOOGLE_DOCS_KEY: "not_a_dict"},
    ],
    ids=["missing_key", "empty_dictionary", "non_dictionary"],
)
def test_preprocess_google_doc_returns_none_on_bad_config(data):
    """preprocess_google_doc should fail closed on missing/empty/malformed config."""
    mm = MarkdownMelder(
        {
            "targets": {
                "bad": {
                    TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                    "data": data,
                }
            },
            "_cfg_file_path": os.getcwd(),
        }
    )

    tgt = Target(mm.cfg, "bad")
    assert mm.preprocess_google_doc(tgt) is None
