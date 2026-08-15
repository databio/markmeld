"""Tests for the authormark author-block integration in markmeld.

These tests exercise the `authormark:` config key end to end: the build-time
fetch + inject hook (`MarkdownMelder.preprocess_authormark`), the source/base-URL
resolution helper, cache behavior, failure handling, and a small render against a
Jinja template that references the injected author variables.

All network access is mocked via `respx` (the HTTP layer the
`authormark_client.AuthormarkClient` uses). No live authormark calls are made.
"""

import os
import shutil
import tempfile

import pytest
import yaml

httpx = pytest.importorskip("httpx")
respx = pytest.importorskip("respx")

import markmeld
import markmeld.melder
from markmeld.melder import (
    MarkdownMelder,
    Target,
    process_data,
    resolve_authormark_source,
)
from markmeld.const import (
    AUTHORMARK_DEFAULT_BASE_URL,
    AUTHORMARK_BASE_URL_ENV,
    EXTRACT_TITLE_KEY,
)

import logmuse

_LOGGER = logmuse.init_logger(name="markmeld", level="DEBUG")

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "test_data", "authormark", "manuscript.jinja")

BASE_URL = "https://authormark.test"
SLUG = "abc123capslug"

# A canned markmeld-shaped author block matching the frozen integration schema.
CANNED_MARKMELD = {
    "title": "A Study of Authormark",
    "authors": [
        {
            "given": "Ada",
            "family": "Lovelace",
            "orcid": "0000-0001-0000-0001",
            "email": "ada@example.org",
            "corresponding": True,
            "affiliation_markers": [1],
            "roles": [
                {
                    "role": "writing-original-draft",
                    "label": "Writing - original draft",
                    "degree": "lead",
                }
            ],
        },
        {
            "given": "Charles",
            "family": "Babbage",
            "orcid": None,
            "email": None,
            "corresponding": False,
            "affiliation_markers": [2],
            "roles": [
                {
                    "role": "conceptualization",
                    "label": "Conceptualization",
                    "degree": "equal",
                }
            ],
        },
    ],
    "affiliations": [
        {"marker": 1, "name": "Analytical Engine Lab", "ror_id": None, "address": None},
        {"marker": 2, "name": "Cambridge", "ror_id": None, "address": None},
    ],
    "author_contributions": "Ada Lovelace: Writing - original draft. "
    "Charles Babbage: Conceptualization.",
    "byline_latex": r"\author{Ada Lovelace$^{1}$, Charles Babbage$^{2}$}",
    "affiliations_latex": "",
}


def _modified_payload(version=1, state="active"):
    return {
        "slug": SLUG,
        "modified": "2026-06-18T00:00:00Z",
        "version": version,
        "state": state,
    }


def _make_config(cache_root, authormark_value=SLUG, extra_target=None, extra_root=None):
    """Build a programmatic markmeld config with one authormark target."""
    target = {
        "_workpath": cache_root,
        "_defpath": cache_root,
        "jinja_template": TEMPLATE,
        "authormark": authormark_value,
        "command": None,
    }
    if extra_target:
        target.update(extra_target)
    cfg = {
        "_cfg_file_path": os.path.join(cache_root, "_markmeld.yaml"),
        "_cache_root": cache_root,
        "authormark_base_url": BASE_URL,
        "targets": {"manuscript": target},
    }
    if extra_root:
        cfg.update(extra_root)
    return cfg


@pytest.fixture
def cache_root():
    d = tempfile.mkdtemp(prefix="mm_authormark_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# resolve_authormark_source
# --------------------------------------------------------------------------- #


def test_resolve_bare_slug_default_base():
    base, slug = resolve_authormark_source("xyz", {})
    assert base == AUTHORMARK_DEFAULT_BASE_URL
    assert slug == "xyz"


def test_resolve_bare_slug_config_base():
    base, slug = resolve_authormark_source(
        "xyz", {"authormark_base_url": "https://cfg.example/"}
    )
    assert base == "https://cfg.example"
    assert slug == "xyz"


def test_resolve_bare_slug_env_base(monkeypatch):
    monkeypatch.setenv(AUTHORMARK_BASE_URL_ENV, "https://env.example")
    base, slug = resolve_authormark_source("xyz", {})
    assert base == "https://env.example"
    assert slug == "xyz"


def test_resolve_full_url():
    base, slug = resolve_authormark_source("https://host.example/p/abc999.yaml", {})
    assert base == "https://host.example"
    assert slug == "abc999"


def test_resolve_full_url_no_ext():
    base, slug = resolve_authormark_source("https://host.example/p/abc999", {})
    assert base == "https://host.example"
    assert slug == "abc999"


def test_resolve_empty_raises():
    with pytest.raises(ValueError):
        resolve_authormark_source("", {})


def test_resolve_bad_url_raises():
    with pytest.raises(ValueError):
        resolve_authormark_source("https://host.example/notapaper", {})


# --------------------------------------------------------------------------- #
# Context injection
# --------------------------------------------------------------------------- #


@respx.mock
def test_context_injection(cache_root):
    """A config with `authormark:` injects top-level author variables."""
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(
            200, json=_modified_payload(), headers={"ETag": '"v1"'}
        )
    )
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )

    cfg = _make_config(cache_root)
    mm = MarkdownMelder(cfg)
    res = mm.build_target("manuscript", print_only=True)

    assert res is not None
    mi = res.melded_input
    # Top-level (template-visible) keys.
    assert mi["title"] == "A Study of Authormark"
    assert mi["byline_latex"] == CANNED_MARKMELD["byline_latex"]
    assert mi["author_contributions"] == CANNED_MARKMELD["author_contributions"]
    assert [a["family"] for a in mi["authors"]] == ["Lovelace", "Babbage"]
    assert [a["marker"] for a in mi["affiliations"]] == [1, 2]


@respx.mock
def test_root_level_authormark(cache_root):
    """authormark set at project/root level (not on target) still injects."""
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload())
    )
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )

    cfg = _make_config(cache_root, authormark_value=SLUG)
    # Move authormark from the target to the root config.
    del cfg["targets"]["manuscript"]["authormark"]
    cfg["authormark"] = SLUG

    mm = MarkdownMelder(cfg)
    res = mm.build_target("manuscript", print_only=True)
    assert res is not None
    assert res.melded_input["title"] == "A Study of Authormark"


# --------------------------------------------------------------------------- #
# Override precedence
# --------------------------------------------------------------------------- #


@respx.mock
def test_authormark_overrides_inline_block(cache_root):
    """Stale inline author values are overridden by authormark values."""
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload())
    )
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )

    cfg = _make_config(cache_root)
    # Simulate a stale inline author block via frontmatter (lower precedence).
    cfg["targets"]["manuscript"]["frontmatter"] = {
        "title": "STALE TITLE",
        "byline_latex": "STALE BYLINE",
    }

    mm = MarkdownMelder(cfg)
    res = mm.build_target("manuscript", print_only=True)
    assert res.melded_input["title"] == "A Study of Authormark"
    assert res.melded_input["byline_latex"] == CANNED_MARKMELD["byline_latex"]


# --------------------------------------------------------------------------- #
# Cache behavior
# --------------------------------------------------------------------------- #


@respx.mock
def test_cache_avoids_refetch(cache_root):
    """Second build with unchanged version uses cache (no second .yaml fetch)."""
    modified_route = respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(
            200, json=_modified_payload(version=1), headers={"ETag": '"v1"'}
        )
    )
    yaml_route = respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )

    cfg = _make_config(cache_root)

    # First build: full fetch (.yaml downloaded once).
    mm1 = MarkdownMelder(cfg)
    mm1.build_target("manuscript", print_only=True)
    assert yaml_route.call_count == 1

    # Second build (fresh melder, same DirCache on disk): version unchanged ->
    # cache HIT, no new .yaml download.
    mm2 = MarkdownMelder(cfg)
    mm2.build_target("manuscript", print_only=True)
    assert yaml_route.call_count == 1  # still 1 — cache hit
    assert modified_route.call_count >= 2  # cheap probe ran each build


@respx.mock
def test_cache_refetch_on_version_change(cache_root):
    """A bumped version triggers a fresh .yaml fetch."""
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload(version=1))
    )
    cfg = _make_config(cache_root)
    MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    first_yaml_calls = respx.get(f"{BASE_URL}/p/{SLUG}.yaml").call_count
    assert first_yaml_calls == 1

    # Bump the version -> cache is stale -> refetch.
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload(version=2))
    )
    MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert respx.get(f"{BASE_URL}/p/{SLUG}.yaml").call_count == 2


@respx.mock
def test_force_refresh_bypasses_cache(cache_root):
    """force_refresh re-downloads the .yaml even when the cache is fresh."""
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload(version=1))
    )
    yaml_route = respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )

    cfg = _make_config(cache_root)
    MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert yaml_route.call_count == 1

    # force_refresh -> full fetch again despite an unchanged version.
    MarkdownMelder(cfg).build_target("manuscript", print_only=True, force_refresh=True)
    assert yaml_route.call_count == 2


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #


@respx.mock
def test_missing_slug_returns_none(cache_root):
    cfg = _make_config(cache_root, authormark_value="")
    res = MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert res is None


@respx.mock
def test_404_returns_none(cache_root):
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(404, text="not found")
    )
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(404, text="not found")
    )
    cfg = _make_config(cache_root)
    res = MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert res is None


@respx.mock
def test_unreachable_with_cache_falls_back(cache_root):
    """Network error after a successful build falls back to the cached block."""
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload(version=1))
    )
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )
    cfg = _make_config(cache_root)
    # Prime the cache with a successful build.
    MarkdownMelder(cfg).build_target("manuscript", print_only=True)

    # Now make the service unreachable; cached payload should be used.
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        side_effect=httpx.ConnectError("boom")
    )
    res = MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert res is not None
    assert res.melded_input["title"] == "A Study of Authormark"


@respx.mock
def test_unreachable_without_cache_returns_none(cache_root):
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(side_effect=httpx.ConnectError("boom"))
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        side_effect=httpx.ConnectError("boom")
    )
    cfg = _make_config(cache_root)
    res = MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    assert res is None


# --------------------------------------------------------------------------- #
# End-to-end render
# --------------------------------------------------------------------------- #


@respx.mock
def test_end_to_end_render(cache_root):
    respx.get(f"{BASE_URL}/p/{SLUG}/modified").mock(
        return_value=httpx.Response(200, json=_modified_payload())
    )
    respx.get(f"{BASE_URL}/p/{SLUG}.yaml").mock(
        return_value=httpx.Response(200, text=yaml.safe_dump(CANNED_MARKMELD))
    )
    cfg = _make_config(cache_root)
    res = MarkdownMelder(cfg).build_target("manuscript", print_only=True)
    out = res.melded_output
    assert "A Study of Authormark" in out
    assert "Ada Lovelace" in out
    assert "Charles Babbage" in out
    assert "Analytical Engine Lab" in out
    assert "(corresponding)" in out
    assert r"\author{" in out


# --------------------------------------------------------------------------- #
# Payload splitting: content keys vs. the reserved `metadata` block
# --------------------------------------------------------------------------- #

PAPER_TEMPLATE = os.path.join(HERE, "test_data", "authormark", "paper.jinja")


def _stub_client(monkeypatch, payload):
    """Make AuthormarkClient.get_markmeld_data return `payload` verbatim.

    Returns the exact object passed in (not a copy), so tests can assert that
    preprocess_authormark does not mutate a shared/cached payload.
    """
    import authormark_client

    def _get(self, slug, use_cache=True):
        return payload

    monkeypatch.setattr(authormark_client.AuthormarkClient, "get_markmeld_data", _get)


def _payload_with_metadata(metadata):
    p = dict(CANNED_MARKMELD)
    p["metadata"] = metadata
    return p


def _preprocessed_target(cfg, target_name="manuscript"):
    """Run preprocess_authormark on a fresh Target and return it."""
    mm = MarkdownMelder(cfg)
    tgt = Target(root_cfg=cfg, target_name=target_name)
    return mm.preprocess_authormark(tgt)


def test_content_keys_go_to_frontmatter_overrides(cache_root, monkeypatch):
    """Content keys land in frontmatter_overrides, not data.variables."""
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))
    cfg = _make_config(cache_root)
    tgt = _preprocessed_target(cfg)

    overrides = tgt.meta["frontmatter_overrides"]
    assert overrides["title"] == CANNED_MARKMELD["title"]
    assert overrides["byline_latex"] == CANNED_MARKMELD["byline_latex"]
    assert [a["family"] for a in overrides["authors"]] == ["Lovelace", "Babbage"]

    # The old data.variables route is gone entirely.
    variables = tgt.meta.get("data", {}).get("variables", {})
    assert "title" not in variables
    assert "authors" not in variables


def test_metadata_not_leaked_into_frontmatter(cache_root, monkeypatch):
    """`metadata` is config, not content -- it must not become frontmatter."""
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))
    cfg = _make_config(cache_root)
    tgt = _preprocessed_target(cfg)
    assert "metadata" not in tgt.meta["frontmatter_overrides"]


def test_metadata_promoted_to_target_config(cache_root, monkeypatch):
    """`metadata: {extract_title: true}` sets the target's extract_title flag."""
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))
    cfg = _make_config(cache_root)
    tgt = _preprocessed_target(cfg)
    assert tgt.meta["extract_title"] is True


def test_local_target_config_wins_over_metadata(cache_root, monkeypatch):
    """An explicit local extract_title is not overridden by authormark."""
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))
    cfg = _make_config(cache_root, extra_target={"extract_title": False})
    tgt = _preprocessed_target(cfg)
    assert tgt.meta["extract_title"] is False


def test_disallowed_metadata_key_is_dropped(cache_root, monkeypatch, caplog):
    """A non-whitelisted metadata key is ignored and warned about."""
    _stub_client(
        monkeypatch,
        _payload_with_metadata({"command": "rm -rf /", "extract_title": True}),
    )
    cfg = _make_config(cache_root)
    tgt = _preprocessed_target(cfg)

    # `command` is None in the base test config; it must not become the payload's.
    assert tgt.meta.get("command") is None
    assert tgt.meta["extract_title"] is True
    assert "command" not in tgt.meta["frontmatter_overrides"]


def test_cached_payload_is_not_mutated(cache_root, monkeypatch):
    """preprocess_authormark copies before popping -- the cache entry survives."""
    payload = _payload_with_metadata({"extract_title": True})
    _stub_client(monkeypatch, payload)
    cfg = _make_config(cache_root)
    _preprocessed_target(cfg)
    assert "metadata" in payload
    assert payload["metadata"] == {"extract_title": True}


def test_metadata_absent_is_fine(cache_root, monkeypatch):
    """A payload with no `metadata` key still injects its content keys."""
    _stub_client(monkeypatch, dict(CANNED_MARKMELD))
    cfg = _make_config(cache_root)
    tgt = _preprocessed_target(cfg)
    assert tgt.meta["frontmatter_overrides"]["title"] == CANNED_MARKMELD["title"]
    assert EXTRACT_TITLE_KEY not in tgt.meta


def test_authormark_runs_before_extract_title_is_read(cache_root, monkeypatch):
    """Ordering guard: injection happens before build_target_meta reads the flag.

    If a future refactor reorders these, `extract_title` from a payload's
    `metadata` block would be silently ignored again.
    """
    calls = []

    real_preprocess = MarkdownMelder.preprocess_authormark
    real_process_data = markmeld.melder.process_data

    def spy_preprocess(self, tgt):
        calls.append("preprocess_authormark")
        return real_preprocess(self, tgt)

    def spy_process_data(*args, **kwargs):
        calls.append(("process_data", kwargs.get("extract_title")))
        return real_process_data(*args, **kwargs)

    monkeypatch.setattr(MarkdownMelder, "preprocess_authormark", spy_preprocess)
    monkeypatch.setattr(markmeld.melder, "process_data", spy_process_data)
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))

    cfg = _make_config(cache_root)
    MarkdownMelder(cfg).build_target("manuscript", print_only=True)

    assert calls[0] == "preprocess_authormark"
    # The flag the melder actually used came from the authormark payload.
    assert ("process_data", True) in calls


# --------------------------------------------------------------------------- #
# Integration: frontmatter_overrides reaches the global frontmatter
# --------------------------------------------------------------------------- #


def test_frontmatter_overrides_reach_global_frontmatter(cache_root):
    """Regression guard: an override `title` shows up in pandoc frontmatter."""
    data = process_data(
        {"md_content": {"body": "## Introduction\n\nText.\n"}},
        os.path.join(cache_root, "_markmeld.yaml"),
        frontmatter_overrides={"title": "A Study of Authormark"},
    )
    assert "title:" in data["_global_frontmatter"]["fenced"]
    assert data["_global_frontmatter"]["dict"]["title"] == "A Study of Authormark"


def test_authormark_title_renders_and_h1_is_stripped(cache_root, monkeypatch):
    """End-to-end: authormark supplies the title, extract_title strips the H1."""
    _stub_client(monkeypatch, _payload_with_metadata({"extract_title": True}))
    cfg = _make_config(
        cache_root,
        extra_target={
            "jinja_template": PAPER_TEMPLATE,
            "data": {
                "md_content": {
                    "body": "# Body Heading Title\n\n## Introduction\n\nText.\n"
                }
            },
        },
    )
    out = MarkdownMelder(cfg).build_target("manuscript", print_only=True).melded_output

    assert "title: A Study of Authormark" in out
    assert "# Body Heading Title" not in out
    assert "## Introduction" in out
