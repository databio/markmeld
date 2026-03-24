"""
Test suite for default pandoc command generation in Target class

This tests the logic in Target.__init__() that generates default pandoc commands
when no explicit 'command' field is provided in the target configuration.
"""

import pytest
from markmeld.melder import Target


class TestDefaultCommandGeneration:
    """Test cases for default command generation in Target class"""

    def test_latex_template_in_command(self):
        """Test that latex_template field generates --template flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "latex_template": "article.tex",
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (LaTeX Template) ===")
        print(f"Command: {command}")

        assert "--template" in command, f"--template flag missing: {command}"


    def test_bibdb_in_command(self):
        """Test that bibdb field generates --bibliography flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "bibdb": "references.bib",
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Bibdb) ===")
        print(f"Command: {command}")

        assert "--bibliography" in command, f"--bibliography flag missing: {command}"


    def test_csl_in_command(self):
        """Test that csl field generates --csl flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "csl": "biomed-central.csl",
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (CSL) ===")
        print(f"Command: {command}")

        assert "--csl" in command, f"--csl flag missing: {command}"


    def test_output_file_in_command(self):
        """Test that output_file field generates -o flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Output File) ===")
        print(f"Command: {command}")

        assert "-o " in command, f"-o flag missing: {command}"
        assert "output.pdf" in command or "{output_file}" in command, \
            f"Output file reference missing: {command}"


    def test_lua_filters_generates_flags(self):
        """Test that lua_filters array generates --lua-filter flags in correct order"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "lua_filters": [
                        "figczar.lua",
                        "change-marker.lua",
                        "multi-refs.lua"
                    ],
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Lua Filters) ===")
        print(f"Command: {command}")

        # Verify --lua-filter flags are present
        assert "--lua-filter" in command, f"--lua-filter flags missing: {command}"

        # Count occurrences
        filter_count = command.count("--lua-filter")
        assert filter_count == 3, f"Expected 3 --lua-filter flags, found {filter_count}"

        # Verify order
        figczar_pos = command.find("figczar")
        marker_pos = command.find("change-marker")
        multirefs_pos = command.find("multi-refs")

        assert figczar_pos > 0, "figczar filter not found in command"
        assert marker_pos > 0, "change-marker filter not found in command"
        assert multirefs_pos > 0, "multi-refs filter not found in command"
        assert figczar_pos < marker_pos < multirefs_pos, \
            f"Filters not in correct order: figczar@{figczar_pos}, marker@{marker_pos}, multirefs@{multirefs_pos}"


    def test_citeproc_true_generates_flag(self):
        """Test that citeproc: true generates --citeproc flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "citeproc": True,
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Citeproc True) ===")
        print(f"Command: {command}")

        assert "--citeproc" in command, f"--citeproc flag missing: {command}"


    def test_citeproc_false_no_flag(self):
        """Test that citeproc: false does NOT generate --citeproc flag"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "citeproc": False,
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Citeproc False) ===")
        print(f"Command: {command}")

        assert "--citeproc" not in command, f"--citeproc should not be present: {command}"


    def test_citeproc_and_filters_together(self):
        """Test that citeproc: true and lua_filters work together"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "lua_filters": ["figczar.lua"],
                    "citeproc": True,
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (Combined) ===")
        print(f"Command: {command}")

        assert "--citeproc" in command, f"--citeproc flag missing: {command}"
        assert "--lua-filter" in command, f"--lua-filter flag missing: {command}"


    def test_all_fields_together(self):
        """Comprehensive test with ALL command generation fields"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "latex_template": "article.tex",
                    "csl": "biomed-central.csl",
                    "bibdb": "references.bib",
                    "lua_filters": ["figczar.lua", "change-marker.lua"],
                    "citeproc": True,
                    "output_file": "output.pdf"
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Generated Command (All Fields) ===")
        print(f"Command: {command}")

        # Verify ALL expected flags are present
        assert command.startswith("pandoc "), f"Command should start with 'pandoc ': {command}"
        assert "--template" in command, f"--template flag missing: {command}"
        assert "--bibliography" in command, f"--bibliography flag missing: {command}"
        assert "--csl" in command, f"--csl flag missing: {command}"
        assert "--lua-filter" in command, f"--lua-filter flags missing: {command}"
        assert command.count("--lua-filter") == 2, \
            f"Expected 2 --lua-filter flags, found {command.count('--lua-filter')}"
        assert "--citeproc" in command, f"--citeproc flag missing: {command}"
        assert "-o " in command, f"-o flag missing: {command}"


    def test_existing_command_prevents_generation(self):
        """
        Test that an existing 'command' field prevents default command generation.
        This documents the behavior: if command exists, it's preserved as-is.
        """
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "command": "pandoc -o output.pdf",
                    "citeproc": True,  # This will be ignored
                    "bibdb": "references.bib"  # This will be ignored
                }
            }
        }

        target = Target(config, "test")
        command = target.meta.get("command", "")

        print(f"\n=== Command with Existing Command Field ===")
        print(f"Command: {command}")

        # The existing command is preserved exactly
        assert command == "pandoc -o output.pdf", \
            f"Existing command should be preserved: {command}"

        # Other fields are ignored when command exists
        assert "--citeproc" not in command, \
            "When command field exists, citeproc setting is ignored"
        assert "--bibliography" not in command, \
            "When command field exists, bibdb setting is ignored"


class TestSpecialVariables:
    """Test cases for special variables available in target metadata"""

    def test_target_name_in_metadata(self):
        """Test that target_name is available as a special variable in metadata"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "my-test-target": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "out/{target_name}.pdf",
                    "data": {}
                }
            }
        }

        target = Target(config, "my-test-target")

        print(f"\n=== Target Metadata ===")
        print(f"target_name: {target.meta.get('target_name')}")

        # Check that target_name is in metadata
        assert "target_name" in target.meta, "target_name should be in target metadata"
        assert target.meta["target_name"] == "my-test-target", \
            f"target_name should be 'my-test-target', got: {target.meta['target_name']}"

    def test_target_name_in_output_file(self):
        """Test that target_name can be used in output_file paths"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "report": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "out/{target_name}-{today}.pdf",
                    "data": {}
                }
            }
        }

        target = Target(config, "report")
        output_file = target.meta.get("output_file", "")

        print(f"\n=== Output File with target_name ===")
        print(f"Output file: {output_file}")

        # The variable should be available for substitution
        # (actual substitution happens in format_command, we're just checking it's in meta)
        assert target.meta.get("target_name") == "report", \
            "target_name should be 'report'"

    def test_target_name_in_command(self):
        """Test that target_name is substituted in command templates"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "manuscript": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "out/output.pdf",
                    "command": "echo Building {target_name} && pandoc -o out/{target_name}.pdf",
                    "data": {}
                }
            }
        }

        target = Target(config, "manuscript")
        command = target.meta.get("command", "")

        print(f"\n=== Command with target_name ===")
        print(f"Command: {command}")
        print(f"target_name in meta: {target.meta.get('target_name')}")

        # The variable should be in metadata
        assert target.meta.get("target_name") == "manuscript", \
            "target_name should be 'manuscript'"

        # The command should have {target_name} substituted
        assert "manuscript" in command, \
            f"Command should have target_name substituted: {command}"
        assert "Building manuscript" in command, \
            f"Command should contain 'Building manuscript': {command}"

    def test_today_variable_in_metadata(self):
        """Test that today variable is still available (existing functionality)"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "out/test-{today}.pdf",
                    "data": {}
                }
            }
        }

        target = Target(config, "test")

        print(f"\n=== Today Variable ===")
        print(f"today: {target.meta.get('today')}")

        # Check that today is still available
        assert "today" in target.meta, "today should be in target metadata"
        assert target.meta["today"], "today should have a value"

    def test_now_variable_in_metadata(self):
        """Test that now variable is still available (existing functionality)"""
        config = {
            "_cfg_file_path": "/tmp/test.yaml",
            "targets": {
                "test": {
                    "_workpath": "/tmp",
                    "_defpath": "/tmp",
                    "output_file": "out/test-{now}.pdf",
                    "data": {}
                }
            }
        }

        target = Target(config, "test")

        print(f"\n=== Now Variable ===")
        print(f"now: {target.meta.get('now')}")

        # Check that now is still available
        assert "now" in target.meta, "now should be in target metadata"
        assert target.meta["now"], "now should have a value"
