"""
Test suite for utilities.py functions.
Specifically tests for check_and_fix_latex_incompatible_chars function.
"""

import pytest
from markmeld.google_drive.markdown_clean import check_and_fix_latex_incompatible_chars


class TestCheckAndFixLatexIncompatibleChars:
    """Test suite for the check_and_fix_latex_incompatible_chars function."""
    
    def test_regular_ascii_not_replaced(self):
        """Test that regular ASCII characters are not replaced."""
        text = 'This is regular text with "quotes" and spaces.'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == text, "Regular ASCII text should not be modified"
        
    def test_no_break_space_replaced(self):
        """Test that NO-BREAK SPACE (U+00A0) is replaced with regular space."""
        text = 'Text with\u00A0no-break\u00A0space'
        expected = 'Text with no-break space'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "NO-BREAK SPACE should be replaced with regular space"
        
    def test_left_double_quote_replaced(self):
        """Test that LEFT DOUBLE QUOTATION MARK (U+201C) is replaced."""
        text = 'Text with \u201Cleft curly quote'
        expected = 'Text with "left curly quote'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "Left curly quote should be replaced with straight quote"
        
    def test_right_double_quote_replaced(self):
        """Test that RIGHT DOUBLE QUOTATION MARK (U+201D) is replaced."""
        text = 'Text with right curly quote\u201D'
        expected = 'Text with right curly quote"'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "Right curly quote should be replaced with straight quote"
        
    def test_curly_quotes_pair_replaced(self):
        """Test that both curly quotes are replaced correctly."""
        text = '\u201CHello World\u201D'
        expected = '"Hello World"'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "Both curly quotes should be replaced"
        
    def test_mixed_problematic_chars(self):
        """Test replacement of multiple problematic characters."""
        text = 'Text\u00A0with\u201Cmixed\u201D\u2014characters\u2026'
        expected = 'Text with"mixed"---characters...'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "All problematic characters should be replaced"
        
    def test_single_quotes_not_replaced(self):
        """Test that the function doesn't break on text without problematic chars."""
        # The single quotes U+2018 and U+2019 are in the dict but with actual Unicode chars
        # This test just verifies regular text passes through unchanged
        text = "Text with 'regular' quotes"
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == text, "Regular text should be unchanged"
        
    def test_mathematical_symbols(self):
        """Test that mathematical symbols are correctly replaced."""
        text = 'Temperature: 25\u00B0C, \u00B15\u00B0'
        expected = 'Temperature: 25$^\\circ$C, +/-5$^\\circ$'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "Mathematical symbols should be replaced with LaTeX"
        
    def test_empty_string(self):
        """Test that empty string is handled correctly."""
        result = check_and_fix_latex_incompatible_chars('')
        assert result == '', "Empty string should remain empty"
        
    def test_no_replacements_needed(self):
        """Test that text without problematic characters is unchanged."""
        text = 'Simple ASCII text 123 !@#$%^&*()'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == text, "Text without problematic chars should be unchanged"
        
        
    def test_multiple_occurrences(self):
        """Test that multiple occurrences of same character are all replaced."""
        text = '\u00A0\u00A0\u00A0Multiple\u00A0spaces\u00A0'
        expected = '   Multiple spaces '
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "All occurrences should be replaced"
        
    def test_preserves_regular_whitespace(self):
        """Test that regular spaces, tabs, and newlines are preserved."""
        text = 'Text with  spaces\tand\ttabs\nand newlines'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == text, "Regular whitespace should be preserved"
        
    def test_zero_width_space_removed(self):
        """Test that ZERO WIDTH SPACE is removed entirely."""
        text = 'Text\u200Bwith\u200Bzero\u200Bwidth'
        expected = 'Textwithzerowidth'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "Zero width spaces should be removed"
        
    def test_all_dash_types(self):
        """Test that all dash types are replaced correctly."""
        text = 'En\u2013dash, Em\u2014dash, and hyphen\u2010minus'
        expected = 'En--dash, Em---dash, and hyphen-minus'
        result = check_and_fix_latex_incompatible_chars(text)
        assert result == expected, "All dash types should be replaced correctly"


def test_would_fail_with_bug():
    """
    This test specifically verifies the bug is fixed.
    With the bug, regular quotes and spaces were being replaced.
    """
    # This text has only regular ASCII - should NOT be modified
    text = 'Regular text with "quotes" and spaces'
    result = check_and_fix_latex_incompatible_chars(text)
    assert result == text, "Bug test: Regular ASCII should not trigger replacements"
    
    # This text has the actual problematic Unicode characters
    unicode_text = 'Text with \u201Cquotes\u201D and\u00A0spaces'
    expected = 'Text with "quotes" and spaces'
    result = check_and_fix_latex_incompatible_chars(unicode_text)
    assert result == expected, "Bug test: Only Unicode chars should be replaced"