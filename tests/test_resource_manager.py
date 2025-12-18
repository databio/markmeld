"""
Tests for the ResourceManager class.

This module tests the resource discovery, path resolution, and variable
substitution functionality of the ResourceManager.
"""

import os
import pytest
from pathlib import Path

from markmeld.resource_manager import ResourceManager, list_filters, get_filter_path


class TestResourceManager:
    """Test suite for ResourceManager functionality."""
    
    def test_resource_manager_initialization(self):
        """Test that ResourceManager initializes correctly."""
        rm = ResourceManager()
        assert rm is not None
        assert "filter" in rm.resource_dirs
        assert "template" in rm.resource_dirs
        assert "csl" in rm.resource_dirs
    
    def test_list_filters(self):
        """Test listing available filters."""
        rm = ResourceManager()
        filters = rm.list_resources("filter")
        
        # Check that we have some filters
        assert isinstance(filters, list)
        
        # Check for known filters if they exist
        if filters:
            # These are the filters we expect from the codebase
            expected_filters = ["change-marker", "figczar", "multi-refs", "supplemental-labels"]
            for expected in expected_filters:
                if expected in filters:
                    assert rm.get_resource_path("filter", expected) is not None
    
    def test_list_templates(self):
        """Test listing available templates."""
        rm = ResourceManager()
        templates = rm.list_resources("template")
        
        # Check that we have templates
        assert isinstance(templates, list)
        assert len(templates) > 0
        
        # Check for some expected templates based on the actual file structure
        expected_templates = [
            "generic",
            "letter",
            "letter-with-signature",
            "manuscript",
            "manuscript-supplement",
            "research-plan",
            "simple-supplement",
            "citation-list-template",
            "citation-list-template-simple",
            "citation-list-template-very-simple"
        ]

        for expected in expected_templates:
            assert expected in templates, f"Expected template {expected} not found. Available: {templates}"
    
    def test_list_csl_files(self):
        """Test listing available CSL files."""
        rm = ResourceManager()
        csl_files = rm.list_resources("csl")
        
        # Check that we have CSL files
        assert isinstance(csl_files, list)
        assert len(csl_files) > 0
        
        # Check for some expected CSL files
        expected_csl = [
            "nature",
            "bioinformatics",
            "bioinformatics-nobib",
            "nucleic-acids-research"
        ]
        
        for expected in expected_csl:
            assert expected in csl_files, f"Expected CSL file {expected} not found"
    
    def test_get_resource_path(self):
        """Test getting paths to specific resources."""
        rm = ResourceManager()
        
        # Test filter path
        filters = rm.list_resources("filter")
        if filters:
            filter_path = rm.get_resource_path("filter", filters[0])
            assert filter_path is not None
            assert os.path.exists(filter_path)
            assert filter_path.endswith(".lua")
        
        # Test template path
        template_path = rm.get_resource_path("template", "generic")
        assert template_path is not None
        assert os.path.exists(template_path)
        assert template_path.endswith(".jinja")
        
        # Test CSL path
        csl_path = rm.get_resource_path("csl", "nature")
        assert csl_path is not None
        assert os.path.exists(csl_path)
        assert csl_path.endswith(".csl")
    
    def test_validate_resource(self):
        """Test resource validation."""
        rm = ResourceManager()
        
        # Test valid resources
        assert rm.validate_resource("template", "generic") is True
        assert rm.validate_resource("csl", "nature") is True
        
        # Test invalid resources
        assert rm.validate_resource("template", "nonexistent") is False
        assert rm.validate_resource("csl", "nonexistent") is False
        assert rm.validate_resource("invalid_type", "anything") is False
    
    def test_get_all_resource_variables(self):
        """Test getting all resource variables for command substitution."""
        rm = ResourceManager()
        variables = rm.get_all_resource_variables()
        
        assert isinstance(variables, dict)
        assert len(variables) > 0
        
        # Check variable naming conventions
        for var_name, var_path in variables.items():
            assert var_name.startswith("mm-")
            assert os.path.exists(var_path)
            
            # Check specific prefixes
            if "filter" in var_name:
                assert var_name.startswith("mm-filter-")
            elif "template" in var_name:
                assert var_name.startswith("mm-template-")
            elif "csl" in var_name:
                assert var_name.startswith("mm-csl-")
        
        # Check for specific expected variables
        expected_vars = [
            "mm-template-generic",
            "mm-template-letter",
            "mm-template-manuscript",
            "mm-csl-nature",
            "mm-csl-bioinformatics"
        ]

        for expected_var in expected_vars:
            assert expected_var in variables, f"Expected variable {expected_var} not found. Available: {list(variables.keys())[:20]}"
    
    def test_backward_compatibility_functions(self):
        """Test backward compatibility functions for filter_manager migration."""
        # Test list_filters function
        filters = list_filters()
        assert isinstance(filters, list)
        
        # Test get_filter_path function
        if filters:
            filter_path = get_filter_path(filters[0])
            assert filter_path is not None
            assert os.path.exists(filter_path)
        
        # Test with non-existent filter
        assert get_filter_path("nonexistent-filter") is None
    
    def test_template_path_structure(self):
        """Test that template paths follow the expected naming structure."""
        rm = ResourceManager()
        variables = rm.get_all_resource_variables()

        # Check manuscript templates
        assert "mm-template-manuscript" in variables
        assert "mm-template-manuscript-supplement" in variables
        assert "mm-template-simple-supplement" in variables

        # Check letter templates
        assert "mm-template-letter" in variables
        assert "mm-template-letter-with-signature" in variables

        # Check citation list templates
        assert "mm-template-citation-list-template" in variables
        assert "mm-template-citation-list-template-simple" in variables
    
    def test_csl_file_naming(self):
        """Test that CSL files are named correctly without extensions."""
        rm = ResourceManager()
        variables = rm.get_all_resource_variables()
        
        # CSL variables should not include .csl extension
        csl_vars = [k for k in variables.keys() if k.startswith("mm-csl-")]
        for var in csl_vars:
            assert not var.endswith(".csl"), f"CSL variable {var} should not include .csl extension"
            # But the path should point to a .csl file
            assert variables[var].endswith(".csl")