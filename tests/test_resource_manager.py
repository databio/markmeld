"""
Tests for the ResourceManager class.

This module tests the resource discovery, path resolution, and variable
substitution functionality of the ResourceManager.
"""

import os
import pytest

from markmeld.resource_manager import ResourceManager, list_filters, get_filter_path


@pytest.fixture
def rm():
    return ResourceManager()


def test_resource_dirs_include_known_types(rm):
    assert {"filter", "template", "csl"} <= set(rm.resource_dirs)


def test_list_filters(rm):
    filters = rm.list_resources("filter")
    assert filters, "Expected at least one filter to be discovered"
    assert "multi-refs" in filters

    filter_path = rm.get_resource_path("filter", "multi-refs")
    assert filter_path is not None
    assert os.path.exists(filter_path)
    assert filter_path.endswith(".lua")


@pytest.mark.parametrize(
    "resource_type, name, suffix, expected_subset",
    [
        ("template", "generic", ".jinja", {"generic", "letter", "manuscript"}),
        ("csl", "nature", ".csl", {"nature", "bioinformatics"}),
    ],
)
def test_list_and_resolve_resources(rm, resource_type, name, suffix, expected_subset):
    resources = rm.list_resources(resource_type)
    assert resources, f"Expected {resource_type} resources to be discovered"
    assert expected_subset <= set(resources)

    path = rm.get_resource_path(resource_type, name)
    assert path is not None
    assert os.path.exists(path)
    assert path.endswith(suffix)


def test_validate_resource(rm):
    assert rm.validate_resource("template", "generic") is True
    assert rm.validate_resource("csl", "nature") is True
    assert rm.validate_resource("template", "nonexistent") is False
    assert rm.validate_resource("csl", "nonexistent") is False
    assert rm.validate_resource("invalid_type", "anything") is False


def test_get_all_resource_variables(rm):
    variables = rm.get_all_resource_variables()
    assert variables, "Expected resource variables to be discovered"

    for var_name, var_path in variables.items():
        assert var_name.startswith("mm-")
        assert os.path.exists(var_path)
        if "filter" in var_name:
            assert var_name.startswith("mm-filter-")
        elif "template" in var_name:
            assert var_name.startswith("mm-template-")
        elif "csl" in var_name:
            assert var_name.startswith("mm-csl-")

    assert "mm-template-generic" in variables
    assert "mm-csl-nature" in variables


def test_csl_variable_naming_drops_extension(rm):
    variables = rm.get_all_resource_variables()
    csl_vars = {k: v for k, v in variables.items() if k.startswith("mm-csl-")}
    assert csl_vars, "Expected at least one mm-csl- variable"

    for var, path in csl_vars.items():
        assert not var.endswith(".csl"), f"CSL variable {var} should drop the extension"
        assert path.endswith(".csl"), f"CSL variable {var} should point at a .csl file"


def test_backward_compatibility_functions():
    """list_filters()/get_filter_path() are the pre-ResourceManager API, kept
    for compatibility with the older filter_manager module."""
    filters = list_filters()
    assert filters, "Expected list_filters() to discover filters"

    filter_path = get_filter_path(filters[0])
    assert filter_path is not None
    assert os.path.exists(filter_path)

    assert get_filter_path("nonexistent-filter") is None
