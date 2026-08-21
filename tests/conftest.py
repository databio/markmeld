"""Shared pytest fixtures for the markmeld test suite."""

from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture
def mm_target(tmp_path):
    """Factory fixture for building and running a markmeld target.

    Writes a jinja template (and optional markdown/YAML data files) into
    `tmp_path`, assembles a target config, and calls
    ``MarkdownMelder.build_target`` on it.

    Usage:
        result = mm_target("{{ content }}", md_files={"content": "Hello"})
        assert "Hello" in result.melded_output

        # Target-level config keys pass straight through, and build_target
        # kwargs (input_file/output_file/force_refresh) go in build_kwargs:
        result = mm_target(
            "{{ content }}",
            output_file="original.pdf",
            build_kwargs={"input_file": "/tmp/in.md", "output_file": "/tmp/out.pdf"},
        )

        # Multiple targets (e.g. for inherit_from) via `targets`:
        result = mm_target(
            None, target_name="child",
            inherit_from="base",
            targets={"base": {"jinja_template": tpl_path, "command": None}},
        )
    """

    def _write(name, content, ext):
        path = tmp_path / f"{name}{ext}"
        if isinstance(content, str):
            path.write_text(content)
        else:
            path.write_text(yaml.dump(content))
        return str(path)

    def _build(
        jinja_template=None,
        target_name="test_target",
        md_files=None,
        yaml_files=None,
        targets=None,
        build_kwargs=None,
        print_only=True,
        **target_data,
    ):
        if jinja_template is not None:
            template_path = tmp_path / "template.jinja"
            template_path.write_text(jinja_template)
            target_data.setdefault("jinja_template", str(template_path))
        target_data.setdefault("command", None)
        target_data.setdefault("_workpath", str(tmp_path))
        target_data.setdefault("_defpath", str(tmp_path))

        data = target_data.pop("data", None) or {}
        if md_files:
            data = {
                **data,
                "md_files": {
                    **data.get("md_files", {}),
                    **{k: _write(k, v, ".md") for k, v in md_files.items()},
                },
            }
        if yaml_files:
            data = {
                **data,
                "yaml_files": {
                    **data.get("yaml_files", {}),
                    **{k: _write(k, v, ".yaml") for k, v in yaml_files.items()},
                },
            }
        if data:
            target_data["data"] = data

        all_targets = {target_name: target_data}
        for name, tgt in (targets or {}).items():
            tgt.setdefault("_workpath", str(tmp_path))
            tgt.setdefault("_defpath", str(tmp_path))
            all_targets[name] = tgt

        config = {
            "_cfg_file_path": str(tmp_path / "_markmeld.yaml"),
            "targets": all_targets,
        }

        from markmeld import MarkdownMelder

        mm = MarkdownMelder(config)
        result = mm.build_target(target_name, print_only=print_only, **(build_kwargs or {}))
        result.mm = mm
        return result

    return _build


@pytest.fixture
def google_drive_processor():
    """Factory fixture for a GoogleDriveProcessor with mocked Drive/Docs services.

    Usage:
        services = google_drive_processor()
        services.drive.comments().list().execute.return_value = {"comments": []}
        services.processor._check_for_active_changes("doc_id")

        # save_to_disk / cache_root are forwarded to GoogleDriveProcessor:
        services = google_drive_processor(save_to_disk=True, cache_root="/tmp/x")

    Returns an object with `.processor`, `.drive` (mocked Drive service),
    and `.docs` (mocked Docs service) attributes. The `service_account.Credentials`
    and `build` patches stay active for the life of the test (docs_service is
    built lazily on first use, not in __init__), and are torn down when the
    test ends. Skips the test if the optional google extras are not installed.
    """
    try:
        from markmeld.google_drive import GoogleDriveProcessor
    except ImportError:
        pytest.skip("Google Drive dependencies not installed")

    patchers = []

    class _Services:
        def __init__(self, processor, drive, docs):
            self.processor = processor
            self.drive = drive
            self.docs = docs

    def _make(save_to_disk=False, cache_root=None, credentials_dict=None):
        mock_drive_service = MagicMock()
        mock_docs_service = MagicMock()

        def build_side_effect(service_name, version, credentials=None, **kwargs):
            if service_name == "drive":
                return mock_drive_service
            elif service_name == "docs":
                return mock_docs_service
            return MagicMock()

        creds_patcher = patch("markmeld.google_drive.processor.service_account.Credentials")
        build_patcher = patch(
            "markmeld.google_drive.processor.build", side_effect=build_side_effect
        )
        mock_creds = creds_patcher.start()
        build_patcher.start()
        patchers.extend([creds_patcher, build_patcher])

        mock_creds_instance = MagicMock()
        mock_creds_instance.service_account_email = "test@example.com"
        mock_creds.from_service_account_info.return_value = mock_creds_instance

        kwargs = {"save_to_disk": save_to_disk}
        if cache_root is not None:
            kwargs["cache_root"] = cache_root

        processor = GoogleDriveProcessor(
            credentials_dict=credentials_dict
            or {
                "type": "service_account",
                "project_id": "test",
                "client_email": "test@example.com",
            },
            **kwargs,
        )

        return _Services(processor, mock_drive_service, mock_docs_service)

    yield _make

    for p in patchers:
        p.stop()


@pytest.fixture
def ccm(tmp_path):
    """A CloudCacheManager rooted at a fresh tmp_path.

    Skips the test if the optional google extras are not installed.
    """
    try:
        from markmeld.google_drive import CloudCacheManager
    except ImportError:
        pytest.skip("Google Drive dependencies not installed")

    return CloudCacheManager(cache_root=tmp_path)
