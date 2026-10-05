"""`bibliography` is the one bibliography setting, and the target's value wins.

pandoc reads its bibliography from document metadata. markmeld used to carry a
second name, `bibdb`, and turn it into `--bibliography` on the command line,
which silently replaced whatever the metadata said. Now a target (or a target
it inherits from) sets `bibliography`; markmeld puts it into the document
metadata at top priority and never adds `--bibliography` to the default
pandoc command. `bibdb` is an error.

A `bibliography:` line in a document (local markdown or a Google Doc) is
ordinary pandoc metadata: it is left in place, and used when the target sets
none.
"""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from markmeld import MarkdownMelder
from markmeld.exceptions import ConfigError
from markmeld.melder import Target

BIB_SRC = Path(__file__).parent / "test_data" / "citation_groups" / "references.bib"


def _cfg(tmp_path, targets):
    for t in targets.values():
        t.setdefault("_workpath", str(tmp_path))
        t.setdefault("_defpath", str(tmp_path))
    return {"_cfg_file_path": str(tmp_path / "_markmeld.yaml"), "targets": targets}


def _vardump(tmp_path, targets, name="t"):
    """Build `name` with vardump; return the melded input."""
    mm = MarkdownMelder(_cfg(tmp_path, targets))
    return mm.build_target(name, vardump=True, report=False).melded_output


def _fm(melded):
    return melded["_global_frontmatter"]["dict"]


# ---------------------------------------------------------------------------
# precedence
# ---------------------------------------------------------------------------


def test_target_bibliography_beats_every_other_source(tmp_path):
    for name in ("t.bib", "fm.bib", "doc.bib", "yaml.bib"):
        (tmp_path / name).write_text("")
    (tmp_path / "doc.md").write_text("---\nbibliography: doc.bib\n---\n\nBody\n")
    (tmp_path / "frontmatter_x.yaml").write_text("bibliography: yaml.bib\n")
    melded = _vardump(
        tmp_path,
        {
            "t": {
                "command": None,
                "bibliography": "t.bib",
                "frontmatter": {"bibliography": "fm.bib"},
                "data": {
                    "md_files": {"content": "doc.md"},
                    "yaml_files": {"frontmatter_x": "frontmatter_x.yaml"},
                },
            }
        },
    )
    expected = str(tmp_path / "t.bib")
    assert _fm(melded)["bibliography"] == expected
    assert melded["bibliography"] == expected


def test_local_markdown_bibliography_used_when_target_sets_none(tmp_path):
    (tmp_path / "doc.md").write_text("---\nbibliography: doc.bib\n---\n\nBody\n")
    melded = _vardump(
        tmp_path, {"t": {"command": None, "data": {"md_files": {"content": "doc.md"}}}}
    )
    assert _fm(melded)["bibliography"] == "doc.bib"


def test_empty_target_bibliography_means_none(tmp_path):
    (tmp_path / "doc.md").write_text("---\nbibliography: doc.bib\n---\n\nBody\n")
    melded = _vardump(
        tmp_path,
        {"t": {"command": None, "bibliography": "", "data": {"md_files": {"content": "doc.md"}}}},
    )
    assert _fm(melded)["bibliography"] == "doc.bib"


def test_inherited_bibliography_applies(tmp_path):
    """A project base target holds `bibliography`; targets inherit it."""
    (tmp_path / "ref.bib").write_text("")
    melded = _vardump(
        tmp_path,
        {
            "t": {"inherit_from": "project", "command": None},
            "project": {"bibliography": "ref.bib"},
        },
    )
    assert _fm(melded)["bibliography"] == str(tmp_path / "ref.bib")


def test_relative_bibliography_resolves_against_defpath(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ref.bib").write_text("")
    melded = _vardump(
        tmp_path,
        {"t": {"command": None, "bibliography": "ref.bib", "_defpath": str(src)}},
    )
    assert melded["bibliography"] == str(src / "ref.bib")


def test_relative_bibliography_not_found_stays_relative(tmp_path):
    """Left for pandoc's --resource-path (sciquill's project cache)."""
    melded = _vardump(tmp_path, {"t": {"command": None, "bibliography": "bib/references.bib"}})
    assert melded["bibliography"] == "bib/references.bib"


def test_list_bibliography_resolved_per_item(tmp_path):
    (tmp_path / "a.bib").write_text("")
    melded = _vardump(tmp_path, {"t": {"command": None, "bibliography": ["a.bib", "/abs/b.bib"]}})
    assert melded["bibliography"] == [str(tmp_path / "a.bib"), "/abs/b.bib"]


# ---------------------------------------------------------------------------
# no --bibliography on the command line
# ---------------------------------------------------------------------------


def test_default_command_has_no_bibliography_flag(tmp_path):
    cfg = _cfg(
        tmp_path, {"t": {"bibliography": "ref.bib", "citeproc": True, "output_file": "o.pdf"}}
    )
    command = Target(cfg, "t").meta["command"]
    assert "--bibliography" not in command
    assert "--citeproc" in command


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_bibliography_reaches_pandoc_even_if_template_drops_metadata(tmp_path):
    """The template emits only the body; pandoc must still cite from the target bib."""
    shutil.copy(BIB_SRC, tmp_path / "references.bib")
    (tmp_path / "doc.md").write_text("Cites [@Alpha2020].\n")
    (tmp_path / "body.jinja").write_text("{{ content }}")
    mm = MarkdownMelder(
        _cfg(
            tmp_path,
            {
                "t": {
                    "jinja_template": str(tmp_path / "body.jinja"),
                    "bibliography": "references.bib",
                    "citeproc": True,
                    "output_file": str(tmp_path / "out.html"),
                    "data": {"md_files": {"content": "doc.md"}},
                }
            },
        )
    )
    res = mm.build_target("t", report=False)
    assert res.returncode == 0, res.stderr
    html = (tmp_path / "out.html").read_text()
    assert "First Study on Alpha" in html


# ---------------------------------------------------------------------------
# bibdb is gone
# ---------------------------------------------------------------------------


def test_bibdb_key_is_an_error(tmp_path):
    cfg = _cfg(tmp_path, {"t": {"bibdb": "ref.bib"}})
    with pytest.raises(ConfigError, match=r"`bibdb` was renamed to `bibliography` \(target t\)"):
        Target(cfg, "t")


def test_inherited_bibdb_is_an_error(tmp_path):
    cfg = _cfg(tmp_path, {"t": {"inherit_from": "base"}, "base": {"bibdb": "x.bib"}})
    with pytest.raises(ConfigError, match="renamed to `bibliography`"):
        Target(cfg, "t")


def test_bibdb_placeholder_in_command_is_an_error(tmp_path):
    cfg = _cfg(tmp_path, {"t": {"command": "pandoc --bibliography {bibdb} -o x.pdf"}})
    with pytest.raises(ConfigError, match=r"`bibdb` was renamed to `bibliography` \(target t\)"):
        Target(cfg, "t")


def test_bibliography_placeholder_in_custom_command_works(tmp_path):
    """A custom command may still pass the target value with `{bibliography}`."""
    from markmeld.utilities import format_command

    cfg = _cfg(
        tmp_path,
        {"t": {"bibliography": "/abs/ref.bib", "command": "pandoc --bibliography {bibliography}"}},
    )
    assert format_command(Target(cfg, "t")) == "pandoc --bibliography /abs/ref.bib"


# ---------------------------------------------------------------------------
# Google Doc metadata is left alone
# ---------------------------------------------------------------------------

DOC_WITH_BIB = "Title notes\n\n---\nbibliography: doc.bib\n---\n\nCites [@a].\n"


class _FakeCache:
    cache_root = Path("/nonexistent")

    def doc_lock(self, doc_id):
        import contextlib

        return contextlib.nullcontext()


class _FakeGDP:
    def __init__(self, cache_root=".cache", **kwargs):
        self.cache_manager = _FakeCache()

    def process_document_figures(self, doc_id, folder_id=None, **kwargs):
        return {"document": DOC_WITH_BIB, "results": {}}


def _gdoc_build(tmp_path, **cfg):
    (tmp_path / "t.bib").write_text("")
    target = {
        "type": "google-doc",
        "command": None,
        "data": {"google_docs": {"content": "DOC1"}},
        **cfg,
    }
    config = _cfg(tmp_path, {"t": target})
    config["_cache_root"] = str(tmp_path / "cache")
    with patch("markmeld.google_drive.GoogleDriveProcessor", _FakeGDP):
        return MarkdownMelder(config).build_target("t", vardump=True, report=False)


def test_target_bibliography_overrides_doc_line(tmp_path):
    melded = _gdoc_build(tmp_path, bibliography="t.bib").melded_output
    assert _fm(melded)["bibliography"] == str(tmp_path / "t.bib")


def test_doc_line_left_in_place_when_target_sets_none(tmp_path):
    res = _gdoc_build(tmp_path)
    assert res.meta["data"]["md_content"]["content"] == DOC_WITH_BIB
    assert "bibliography" not in res.meta


def test_appended_block_is_the_last_metadata_word(tmp_path):
    """The block markmeld appends must beat a Doc block, by pandoc's own rule."""
    from markmeld.melder import append_bibliography_block
    from markmeld.metadata_blocks import find_bibliography

    out = append_bibliography_block(DOC_WITH_BIB, "/abs/t.bib")
    assert find_bibliography(out) == "/abs/t.bib"
    assert yaml.safe_load(out.rsplit("---\n", 2)[1]) == {"bibliography": "/abs/t.bib"}
    assert append_bibliography_block(DOC_WITH_BIB, None) == DOC_WITH_BIB


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_pandoc_takes_the_later_metadata_block(tmp_path):
    """Guards the assumption behind append_bibliography_block."""
    from markmeld.melder import append_bibliography_block

    md = append_bibliography_block("---\nbibliography: doc.bib\n---\n\nx\n", "t.bib")
    out = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "native", "-s"],
        input=md.encode(),
        capture_output=True,
        check=True,
    ).stdout.decode()
    assert "t.bib" in out and "doc.bib" not in out


def test_custom_command_stdin_gets_no_appended_block(tmp_path):
    """A custom command may not be pandoc; markmeld only appends for its own."""
    (tmp_path / "doc.md").write_text("Body\n")
    (tmp_path / "body.jinja").write_text("{{ content }}")
    out = tmp_path / "out.txt"
    mm = MarkdownMelder(
        _cfg(
            tmp_path,
            {
                "t": {
                    "jinja_template": str(tmp_path / "body.jinja"),
                    "bibliography": "/abs/ref.bib",
                    "command": f"cat > {out}",
                    "data": {"md_files": {"content": "doc.md"}},
                }
            },
        )
    )
    res = mm.build_target("t", report=False)
    assert res.returncode == 0
    assert "bibliography" not in out.read_text()
