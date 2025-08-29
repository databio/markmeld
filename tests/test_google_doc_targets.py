"""
Tests for Google Doc target functionality
"""

import pytest
import os
from markmeld.melder import MarkdownMelder, Target


def test_google_doc_target_creation():
    """Test that Google Doc targets are properly created"""
    config = {
        "targets": {
            "gdoc": {
                "type": "google-doc",
                "jinja_template": "template.jinja",
                "output_file": "output.pdf",
                "data": {
                    "google_docs": {
                        "doc_id": "test_doc_id",
                        "folder_id": "test_folder_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "gdoc")
    
    assert tgt.target_name == "gdoc"
    assert "type" in tgt.meta
    assert tgt.meta["type"] == "google-doc"
    assert "data" in tgt.meta
    assert "google_docs" in tgt.meta["data"]
    assert tgt.meta["data"]["google_docs"]["doc_id"] == "test_doc_id"


def test_google_doc_alternate_field_names():
    """Test that 'manuscript' field works as alternative to 'doc_id'"""
    config = {
        "targets": {
            "manuscript": {
                "type": "google-doc",
                "jinja_template": "template.jinja",
                "data": {
                    "google_docs": {
                        "manuscript": "manuscript_id"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    tgt = Target(config, "manuscript")
    
    assert "google_docs" in tgt.meta["data"]
    assert tgt.meta["data"]["google_docs"]["manuscript"] == "manuscript_id"


def test_google_doc_type_alongside_existing_types():
    """Test that google-doc type coexists with raw and meta types"""
    config = {
        "targets": {
            "gdoc": {
                "type": "google-doc",
                "data": {"google_docs": {"doc_id": "123"}}
            },
            "raw": {
                "type": "raw",
                "command": "echo test"
            },
            "meta": {
                "type": "meta"
            },
            "normal": {
                "jinja_template": "template.jinja"
            }
        },
        "_cfg_file_path": os.getcwd()
    }
    
    # Test each target type
    gdoc_tgt = Target(config, "gdoc")
    assert gdoc_tgt.meta["type"] == "google-doc"
    
    raw_tgt = Target(config, "raw")
    assert raw_tgt.meta["type"] == "raw"
    
    meta_tgt = Target(config, "meta")
    assert meta_tgt.meta["type"] == "meta"
    
    normal_tgt = Target(config, "normal")
    assert "type" not in normal_tgt.meta or normal_tgt.meta.get("type") == None


def test_google_doc_missing_config():
    """Test error handling for missing Google Doc configuration"""
    mm = MarkdownMelder({
        "targets": {
            "bad": {
                "type": "google-doc",
                "data": {}  # Missing google_docs section
            }
        },
        "_cfg_file_path": os.getcwd()
    })
    
    tgt = Target(mm.cfg, "bad")
    result = mm.preprocess_google_doc(tgt)
    
    # Should return None on missing config
    assert result is None


def test_google_doc_missing_doc_id():
    """Test error handling for missing doc_id"""
    mm = MarkdownMelder({
        "targets": {
            "bad": {
                "type": "google-doc",
                "data": {
                    "google_docs": {
                        # Missing both doc_id and manuscript
                        "folder_id": "some_folder"
                    }
                }
            }
        },
        "_cfg_file_path": os.getcwd()
    })
    
    tgt = Target(mm.cfg, "bad")
    result = mm.preprocess_google_doc(tgt)
    
    # Should return None on missing doc_id
    assert result is None