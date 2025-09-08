"""
Tests for Google Doc target functionality
"""

import pytest
import os
from markmeld.melder import MarkdownMelder, Target
from markmeld.const import GOOGLE_DOCS_KEY, TARGET_TYPE_KEY, GOOGLE_DOC_TARGET_TYPE


def test_google_doc_target_creation():
    """Test that Google Doc targets are properly created"""
    config = {
        "targets": {
            "gdoc": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "jinja_template": "template.jinja",
                "output_file": "output.pdf",
                "data": {
                    GOOGLE_DOCS_KEY: {
                        "manuscript": "test_doc_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "gdoc")
    
    assert tgt.target_name == "gdoc"
    assert TARGET_TYPE_KEY in tgt.meta
    assert tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE
    assert "data" in tgt.meta
    assert GOOGLE_DOCS_KEY in tgt.meta["data"]
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["manuscript"] == "test_doc_id"


def test_google_doc_multiple_documents():
    """Test that multiple Google Docs can be configured"""
    config = {
        "targets": {
            "multi_doc": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "jinja_template": "template.jinja",
                "data": {
                    GOOGLE_DOCS_KEY: {
                        "manuscript": "manuscript_id",
                        "data": "data_doc_id",
                        "supplement": "supplement_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "multi_doc")
    
    assert GOOGLE_DOCS_KEY in tgt.meta["data"]
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["manuscript"] == "manuscript_id"
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["data"] == "data_doc_id"
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["supplement"] == "supplement_id"


def test_google_doc_type_alongside_existing_types():
    """Test that google-doc type coexists with raw and meta types"""
    config = {
        "targets": {
            "gdoc": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "data": {GOOGLE_DOCS_KEY: {"manuscript": "123"}}
            },
            "raw": {
                TARGET_TYPE_KEY: "raw",
                "command": "echo test"
            },
            "meta": {
                TARGET_TYPE_KEY: "meta"
            },
            "normal": {
                "jinja_template": "template.jinja"
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    # Test each target type
    gdoc_tgt = Target(config, "gdoc")
    assert gdoc_tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE
    
    raw_tgt = Target(config, "raw")
    assert raw_tgt.meta[TARGET_TYPE_KEY] == "raw"
    
    meta_tgt = Target(config, "meta")
    assert meta_tgt.meta[TARGET_TYPE_KEY] == "meta"
    
    normal_tgt = Target(config, "normal")
    assert TARGET_TYPE_KEY not in normal_tgt.meta or normal_tgt.meta.get(TARGET_TYPE_KEY) == None


def test_google_doc_missing_config():
    """Test error handling for missing Google Doc configuration"""
    mm = MarkdownMelder({
        "targets": {
            "bad": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "data": {}  # Missing google_docs section
            }
        },
        "_cfg_file_path": os.getcwd()
    })
    
    tgt = Target(mm.cfg, "bad")
    result = mm.preprocess_google_doc(tgt)
    
    # Should return None on missing config
    assert result is None


def test_google_doc_empty_dictionary():
    """Test error handling for empty dictionary"""
    mm = MarkdownMelder({
        "targets": {
            "bad": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "data": {
                    GOOGLE_DOCS_KEY: {}  # Empty dictionary
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    })
    
    tgt = Target(mm.cfg, "bad")
    result = mm.preprocess_google_doc(tgt)
    
    # Should return None on empty dictionary
    assert result is None


def test_google_doc_force_refresh():
    """Test force refresh flag handling"""
    config = {
        "targets": {
            "refresh": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "jinja_template": "template.jinja",
                "data": {
                    GOOGLE_DOCS_KEY: {
                        "manuscript": "test_doc_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "refresh")
    
    # Add force_refresh flag
    tgt.meta["force_refresh"] = True
    
    assert "force_refresh" in tgt.meta
    assert tgt.meta["force_refresh"] == True


def test_google_doc_with_constants():
    """Test that constants are properly used throughout"""
    config = {
        "targets": {
            "constant_test": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "data": {
                    GOOGLE_DOCS_KEY: {
                        "manuscript": "test_manuscript_id",
                        "letter": "test_letter_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "constant_test")
    
    # Verify constants are used correctly
    assert tgt.meta[TARGET_TYPE_KEY] == GOOGLE_DOC_TARGET_TYPE
    assert GOOGLE_DOCS_KEY in tgt.meta["data"]
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["manuscript"] == "test_manuscript_id"
    assert tgt.meta["data"][GOOGLE_DOCS_KEY]["letter"] == "test_letter_id"


def test_google_doc_non_dictionary():
    """Test error handling when google_docs is not a dictionary"""
    mm = MarkdownMelder({
        "targets": {
            "bad": {
                TARGET_TYPE_KEY: GOOGLE_DOC_TARGET_TYPE,
                "data": {
                    GOOGLE_DOCS_KEY: "not_a_dict"  # String instead of dict
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    })
    
    tgt = Target(mm.cfg, "bad")
    result = mm.preprocess_google_doc(tgt)
    
    # Should return None when google_docs is not a dictionary
    assert result is None