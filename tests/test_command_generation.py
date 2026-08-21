"""
Test suite for default pandoc command generation in Target class

This tests the logic in Target.__init__() that generates default pandoc commands
when no explicit 'command' field is provided in the target configuration.
"""

import pytest

from markmeld.melder import Target


def make_target(target_name="test", **target_kwargs):
    """Build a Target with the repeated _workpath/_defpath/output_file scaffolding."""
    config = {
        "_cfg_file_path": "/tmp/test.yaml",
        "targets": {
            target_name: {
                "_workpath": "/tmp",
                "_defpath": "/tmp",
                "output_file": "output.pdf",
                **target_kwargs,
            }
        },
    }
    return Target(config, target_name)


class TestDefaultCommandGeneration:
    """Test cases for default command generation in Target class"""

    @pytest.mark.parametrize(
        "field_kwargs, present, absent",
        [
            ({"latex_template": "article.tex"}, ["--template"], []),
            ({"bibdb": "references.bib"}, ["--bibliography"], []),
            ({"csl": "biomed-central.csl"}, ["--csl"], []),
            (
                {
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "citeproc": True,
                },
                ["--citeproc"],
                [],
            ),
            (
                {
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "citeproc": False,
                },
                [],
                ["--citeproc"],
            ),
        ],
    )
    def test_config_field_generates_expected_flag(self, field_kwargs, present, absent):
        command = make_target(**field_kwargs).meta.get("command", "")
        for flag in present:
            assert flag in command, f"{flag!r} missing: {command}"
        for flag in absent:
            assert flag not in command, f"{flag!r} should not be present: {command}"

    def test_output_file_in_command(self):
        """output_file field generates -o flag (may or may not be substituted yet)"""
        command = make_target().meta.get("command", "")
        assert "-o " in command
        assert "output.pdf" in command or "{output_file}" in command

    def test_lua_filters_generates_flags(self):
        """lua_filters array generates --lua-filter flags in configured order"""
        target = make_target(lua_filters=["figczar.lua", "change-marker.lua", "multi-refs.lua"])
        command = target.meta.get("command", "")

        assert "--lua-filter" in command

        # The three configured filters, plus the always-on unicode-symbols filter.
        filter_count = command.count("--lua-filter")
        assert filter_count == 4, f"Expected 4 --lua-filter flags, found {filter_count}"

        figczar_pos = command.find("figczar")
        marker_pos = command.find("change-marker")
        multirefs_pos = command.find("multi-refs")
        assert figczar_pos > 0
        assert marker_pos > 0
        assert multirefs_pos > 0
        assert figczar_pos < marker_pos < multirefs_pos, (
            f"Filters not in correct order: figczar@{figczar_pos}, "
            f"marker@{marker_pos}, multirefs@{multirefs_pos}"
        )

    def test_citeproc_and_filters_together(self):
        """citeproc: true and lua_filters work together"""
        target = make_target(
            csl="biomed-central.csl",
            bibdb="references.bib",
            lua_filters=["figczar.lua"],
            citeproc=True,
        )
        command = target.meta.get("command", "")
        assert "--citeproc" in command
        assert "--lua-filter" in command

    def test_all_fields_together(self):
        """Comprehensive test with ALL command generation fields"""
        target = make_target(
            latex_template="article.tex",
            csl="biomed-central.csl",
            bibdb="references.bib",
            lua_filters=["figczar.lua", "change-marker.lua"],
            citeproc=True,
        )
        command = target.meta.get("command", "")

        assert command.startswith("pandoc ")
        assert "--template" in command
        assert "--bibliography" in command
        assert "--csl" in command
        assert "--lua-filter" in command
        # The two configured filters, plus the always-on unicode-symbols filter.
        assert command.count("--lua-filter") == 3, (
            f"Expected 3 --lua-filter flags, found {command.count('--lua-filter')}"
        )
        assert "unicode-symbols.lua" in command
        assert "--citeproc" in command
        assert "-o " in command

    def test_existing_command_prevents_generation(self):
        """
        An existing 'command' field prevents default command generation.
        This documents the behavior: if command exists, it's preserved as-is.
        """
        target = make_target(
            command="pandoc -o output.pdf",
            citeproc=True,  # ignored
            bibdb="references.bib",  # ignored
        )
        command = target.meta.get("command", "")

        assert command == "pandoc -o output.pdf"
        assert "--citeproc" not in command
        assert "--bibliography" not in command


class TestSpecialVariables:
    """Test cases for special variables available in target metadata"""

    def test_target_name_in_metadata(self):
        """target_name is available as a special variable in metadata"""
        target = make_target(
            target_name="my-test-target",
            output_file="out/{target_name}.pdf",
            data={},
        )
        assert target.meta["target_name"] == "my-test-target"

    def test_target_name_in_command(self):
        """target_name is substituted in command templates"""
        target = make_target(
            target_name="manuscript",
            command="echo Building {target_name} && pandoc -o out/{target_name}.pdf",
            data={},
        )
        command = target.meta.get("command", "")

        assert target.meta.get("target_name") == "manuscript"
        assert "Building manuscript" in command

    @pytest.mark.parametrize("var_name", ["today", "now"])
    def test_special_variable_in_metadata(self, var_name):
        target = make_target(output_file=f"out/test-{{{var_name}}}.pdf", data={})
        assert var_name in target.meta
        assert target.meta[var_name]
