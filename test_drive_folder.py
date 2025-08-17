#!/usr/bin/env python3
"""
Test script for the unified Google Drive folder processing.

This demonstrates how to use the process_drive_folder() method
to process a Google Drive folder containing a manuscript and figures
with a single folder ID.
"""

from markmeld.google_drive import GoogleDriveProcessor

def test_process_folder():
    """Test the unified folder processing."""
    
    # Initialize the processor
    processor = GoogleDriveProcessor(
        local_base_dir="output"
    )
    
    print("Google Drive Processor initialized:")
    print(processor)
    print()
    
    # Example folder ID - replace with your actual folder ID
    folder_id = "YOUR_FOLDER_ID_HERE"
    
    # Process the entire folder with a single call
    results = processor.process_drive_folder(
        folder_id=folder_id,
        process_doc=True,  # Download and clean the manuscript
        process_figs=True,  # Convert SVGs to PDFs
        output_path="output/manuscript.md"  # Save manuscript here
    )
    
    # Check results
    if results['document']:
        print(f"\nDocument successfully processed!")
        print(f"  - Title: {results['document_name']}")
        print(f"  - ID: {results['document_id']}")
        
        # Access the parsed document content
        doc = results['document']
        if hasattr(doc, 'metadata'):
            print(f"  - Metadata keys: {list(doc.metadata.keys())}")
        if hasattr(doc, 'content'):
            print(f"  - Content length: {len(doc.content)} characters")
    
    if results['figs_results']:
        stats = results['figs_results']['stats']
        print(f"\nFigures processed:")
        print(f"  - Total SVGs: {stats['total_svgs']}")
        print(f"  - Converted: {stats['converted']}")
        print(f"  - Skipped: {stats['skipped']}")
        print(f"  - Failed: {stats['failed']}")
    
    if results['errors']:
        print(f"\nErrors encountered:")
        for error in results['errors']:
            print(f"  - {error}")
    
    assert results is not None


def test_doc_only():
    """Test processing only the document."""
    
    processor = GoogleDriveProcessor()
    folder_id = "YOUR_FOLDER_ID_HERE"
    
    # Process only the document
    results = processor.process_drive_folder(
        folder_id=folder_id,
        process_doc=True,
        process_figs=False,  # Skip figure processing
        output_path="output/manuscript_only.md"
    )
    
    assert results is not None


def test_figs_only():
    """Test processing only the figures."""
    
    processor = GoogleDriveProcessor()
    folder_id = "YOUR_FOLDER_ID_HERE"
    
    # Process only the figures
    results = processor.process_drive_folder(
        folder_id=folder_id,
        process_doc=False,  # Skip document processing
        process_figs=True
    )
    
    assert results is not None


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Google Drive Folder Processing")
    print("=" * 60)
    
    # Run the test
    # Note: Replace YOUR_FOLDER_ID_HERE with an actual Google Drive folder ID
    # The folder should contain:
    #   - A Google Doc (preferably with 'manuscript' in the name)
    #   - A subfolder named 'figs' containing SVG files
    
    test_process_folder()