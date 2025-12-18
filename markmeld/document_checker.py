"""Document validation and inspection utilities.

This module provides pure markdown validation and analysis functionality,
with no external dependencies beyond standard library and typing.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


class FigureReference(NamedTuple):
    """A reference to a figure found in markdown content.

    Attributes:
        text: The reference text like "(Fig. 3B)".
        figure_num: The figure number like "3" or "S2" or label like "fig:methods".
        panels: Panel letters like "B" or "B-D" or empty string.
        line_num: Line number in document.
        context: Surrounding text for context.
    """

    text: str
    figure_num: str
    panels: str
    line_num: int
    context: str


@dataclass
class ValidationIssue:
    """A validation problem found in the document.

    Attributes:
        type: Issue type identifier.
        severity: 'error' or 'warning'.
        message: Human-readable description.
        line: Line number (0 if not applicable).
        context: Surrounding text.
        figure: Optional figure number if applicable.
        panel: Optional panel letter if applicable.
    """

    type: str
    severity: str
    message: str
    line: int
    context: str
    figure: Optional[str] = None
    panel: Optional[str] = None


class DocumentChecker:
    """Validates and inspects document content.

    Provides pure markdown validation functionality including:
    - Figure reference extraction and parsing
    - Figure and panel order validation
    - Prefix consistency checking
    - Report generation
    """

    def parse_figure_reference(self, ref_text: str) -> Optional[Tuple[str, str]]:
        """Parse a figure reference to extract figure number and panels.

        Args:
            ref_text: Reference text like "(Fig. 3B)", "Figure S2", etc.

        Returns:
            Tuple of (figure_number, panel_letters) or None if parsing fails.
        """
        # Clean up the text - remove parentheses and trailing punctuation
        ref_text = ref_text.strip('()')
        if ref_text and ref_text[-1] in ',;':
            ref_text = ref_text[:-1]

        # Handle LaTeX \ref{} style
        if '\\ref{' in ref_text:
            # Extract the label
            label_match = re.search(r'\\ref\{([^}]+)\}', ref_text)
            if label_match:
                label = label_match.group(1)
                # Check for panel letters IMMEDIATELY after the ref (NO space allowed)
                # Spaces before panel letters are LaTeX errors
                panel_match = re.search(r'\\ref\{[^}]+\}([A-Z](?:-[A-Z])?)', ref_text)
                panels = panel_match.group(1) if panel_match else ''
                return (label, panels)

        # Handle regular figure references
        # Match patterns like "Fig. 3B", "Figure S2", "Supplemental Figure 2"
        # Now also handles spaces before panels
        patterns = [
            # Standard format with optional space before panel
            r'(?:Supplemental\s+)?Fig(?:ure)?\.?\s*(S?\d+)\s*([A-Z](?:-[A-Z])?)?',
            # Handle single panel letter
            r'(?:Supplemental\s+)?Fig(?:ure)?\.?\s*(S?\d+)\s*([A-Z])',
            # Handle comma-separated panels like "3B, 3C"
            r'(\d+)\s*([A-Z](?:\s*,\s*[A-Z])*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, ref_text, re.IGNORECASE)
            if match:
                figure_num = match.group(1)
                panels = match.group(2) if len(match.groups()) > 1 and match.group(2) else ''
                # Clean up panels - remove spaces
                if panels:
                    panels = panels.replace(' ', '')
                return (figure_num, panels)

        return None

    def parse_multi_figure_reference(
        self, ref_text: str
    ) -> Optional[List[Tuple[str, str]]]:
        """Parse multi-figure references like "(Fig. 3A, 3B)" or "(Fig. S3, S4)".

        Args:
            ref_text: Reference text that might contain multiple figures.

        Returns:
            List of tuples (figure_number, panel_letters) or None if not multi-ref.
        """
        # First try to find all complete figure references with "Fig." prefix
        # Pattern to match "Fig. X" or "Figure X" with optional panel
        complete_fig_pattern = r'Fig(?:ure)?\.?\s*(S?\d+)([A-Z](?:-[A-Z])?)?'
        complete_matches = list(re.finditer(complete_fig_pattern, ref_text, re.IGNORECASE))

        if len(complete_matches) > 1:
            # Multiple complete figure references like "(Fig. 2C, Fig. S2)"
            refs = []
            for match in complete_matches:
                fig_num = match.group(1)
                panel = match.group(2) or ''
                refs.append((fig_num, panel))
            return refs

        # Fall back to original abbreviated format handling: "(Fig. 3A, 3B)" or "(Fig. S3, S4)"
        # Pattern: Fig. followed by figure number, then comma-separated additional refs
        pattern = r'\(?\s*Fig(?:ure)?\.?\s*(S?\d+)([A-Z](?:-[A-Z])?)?(?:\s*,\s*([S\d]+[A-Z]?(?:-[A-Z])?(?:\s*,\s*[S\d]+[A-Z]?(?:-[A-Z])?)*))?\)?'

        match = re.match(pattern, ref_text, re.IGNORECASE)
        if match and match.group(3):  # Has comma-separated parts
            refs = []

            # First figure
            fig_num = match.group(1)
            panel = match.group(2) or ''
            refs.append((fig_num, panel))

            # Additional figures
            additional = match.group(3)
            if additional:
                # Split by comma and process each
                for part in additional.split(','):
                    part = part.strip()
                    # Check if it's just a panel letter (e.g., "3B")
                    if re.match(r'^[A-Z](?:-[A-Z])?$', part):
                        # Just a panel for the same figure
                        refs.append((fig_num, part))
                    elif re.match(r'^S?\d+[A-Z]?(?:-[A-Z])?$', part):
                        # Parse figure number and optional panel
                        num_match = re.match(r'^(S?\d+)([A-Z](?:-[A-Z])?)?$', part)
                        if num_match:
                            refs.append((num_match.group(1), num_match.group(2) or ''))

            return refs if len(refs) > 1 else None

        return None

    def extract_figure_references(
        self, markdown_content: str
    ) -> List[FigureReference]:
        """Extract all figure references from markdown content.

        Finds references in formats like:
        - (Fig. 2), (Figure 2), (Fig 2)
        - (Fig. 2A), (Fig. 3B, 3C), (Figure 3B-D)
        - (Figure S2), (Supplemental Figure 2)
        - Figure \\ref{fig:label}
        - Non-parenthetic references: "as shown in Figure 2"

        Args:
            markdown_content: The markdown document to analyze.

        Returns:
            List of FigureReference objects found in the content.
        """
        references = []
        lines = markdown_content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Skip lines that are image definitions
            if line.strip().startswith('![') or re.match(r'^\s*\[[^\]]+\]:\s*', line):
                continue

            # Track positions already matched to avoid duplicates
            matched_positions = set()

            # Simplified patterns - handle each type separately for better control
            # Order matters! More specific patterns should come first to avoid being masked by general ones
            patterns = [
                # Context phrases (including "shown in") - MUST come first to capture the full phrase
                r'(?:as\s+shown\s+in\s+|see\s+|shown\s+in\s+|described\s+in\s+|illustrated\s+in\s+)Fig(?:ure)?\.?\s*(?:\\ref\{[^}]+\}|S?\d+)[A-Z]?(?:-[A-Z])?',
                # LaTeX ref style with panel - NO space allowed before panel letter
                # Include optional parentheses in capture
                r'\(?\s*Fig(?:ure)?\.?\s*\\ref\{[^}]+\}[A-Z]?(?:-[A-Z])?\)?',
                # LaTeX ref style WITHOUT panel but potentially with space (error case)
                r'\(\s*Fig(?:ure)?\.?\s*\\ref\{[^}]+\}\s+[A-Z]?\)',
                # Multi-panel references in parentheses - MUST come before simple pattern
                # Matches "(Fig. 3A, 3B)" or "(Fig. S3, S4)" etc.
                r'\(\s*Fig(?:ure)?\.?\s*S?\d+[A-Z]?(?:-[A-Z])?(?:\s*,\s*(?:Fig(?:ure)?\.?\s*)?[S\d]+[A-Z]?(?:-[A-Z])?)*\s*\)',
                # Simple figure references (parenthetic or not) - catches figures anywhere including inside parentheses
                # This will match Fig. 2C even when preceded by other text like "AUC >98%; Fig. 2C"
                # Include optional parentheses in capture
                r'\(?\s*(?:Supplemental\s+)?Fig(?:ure)?\.?\s*S?\d+[A-Z]?(?:-[A-Z])?\)?',
            ]

            for pattern in patterns:
                for match in re.finditer(pattern, line, re.IGNORECASE):
                    # Check if any part of this match overlaps with already matched positions
                    if any(pos in matched_positions for pos in range(match.start(), match.end())):
                        continue

                    # Mark this position range as matched
                    for pos in range(match.start(), match.end()):
                        matched_positions.add(pos)

                    ref_text = match.group(0).strip()

                    # Clean up the reference text (remove trailing punctuation that's not part of parentheses)
                    if ref_text and ref_text[-1] in ',;' and not ref_text.startswith('('):
                        ref_text = ref_text[:-1]

                    # Check if this is a multi-figure reference
                    multi_refs = self.parse_multi_figure_reference(ref_text)

                    if multi_refs:
                        # Get context once for all references in this match
                        start_pos = max(0, match.start() - 30)
                        end_pos = min(len(line), match.end() + 30)
                        context = line[start_pos:end_pos].strip()

                        # Add each figure reference separately
                        # Include match position for sorting (will be removed before return)
                        for figure_num, panels in multi_refs:
                            references.append((
                                ref_text,  # Keep original text for reporting
                                figure_num,
                                panels,
                                line_num,
                                context,
                                match.start()  # Track position within line for sorting
                            ))
                    else:
                        # Single reference - parse normally
                        parsed = self.parse_figure_reference(ref_text)
                        if parsed:
                            figure_num, panels = parsed

                            # Get context (surrounding text)
                            start_pos = max(0, match.start() - 30)
                            end_pos = min(len(line), match.end() + 30)
                            context = line[start_pos:end_pos].strip()

                            references.append((
                                ref_text,
                                figure_num,
                                panels,
                                line_num,
                                context,
                                match.start()  # Track position within line for sorting
                            ))

        # Sort by (line_number, position) to ensure correct text order
        # Multiple patterns can match different references out of order
        references.sort(key=lambda x: (x[3], x[5]))

        # Convert to FigureReference NamedTuple (removing position element)
        return [FigureReference(ref[0], ref[1], ref[2], ref[3], ref[4]) for ref in references]

    def extract_figure_labels(
        self, markdown_content: str
    ) -> Dict[str, Tuple[int, str]]:
        r"""Extract figure label definitions from figure captions.

        Finds labels in patterns like:
        - ![**\label{overview} Figure 1.** Caption](path.svg)
        - ![**\label{supp-data} Supplemental Figure 1.** Caption](path.svg)

        Args:
            markdown_content: The full markdown document content.

        Returns:
            Dict mapping label names to (line_number, figure_type) tuples,
            where figure_type is 'main' or 'supplemental'.
        """
        labels = {}
        lines = markdown_content.split('\n')

        # Pattern to match: ![**\label{name} Supplemental Figure ...
        # or: ![**\label{name} Figure ...
        pattern = r'!\[\*\*\\label\{([^}]+)\}\s*(Supplemental\s+)?Figure'

        for line_num, line in enumerate(lines, 1):
            # Only look at lines that start image definitions
            if not line.strip().startswith('!['):
                continue

            match = re.search(pattern, line)
            if match:
                label_name = match.group(1)
                is_supplemental = match.group(2) is not None
                figure_type = 'supplemental' if is_supplemental else 'main'

                labels[label_name] = (line_num, figure_type)

        return labels

    def build_label_order_map(
        self, label_definitions: Dict[str, Tuple[int, str]]
    ) -> Dict[str, int]:
        """Build mapping from label names to sequential order within figure type.

        Args:
            label_definitions: Dict from extract_figure_labels().

        Returns:
            Dict mapping label names to order number (1, 2, 3, etc.).
            Main and supplemental figures numbered separately.
        """
        # Separate main and supplemental figures
        main_labels = [(label, line_num) for label, (line_num, fig_type) in label_definitions.items()
                       if fig_type == 'main']
        supp_labels = [(label, line_num) for label, (line_num, fig_type) in label_definitions.items()
                       if fig_type == 'supplemental']

        # Sort by line number (definition order)
        main_labels.sort(key=lambda x: x[1])
        supp_labels.sort(key=lambda x: x[1])

        # Assign order numbers
        label_order = {}
        for i, (label, _) in enumerate(main_labels, 1):
            label_order[label] = i
        for i, (label, _) in enumerate(supp_labels, 1):
            label_order[label] = i

        return label_order

    def validate_figure_order(
        self,
        references: List[FigureReference],
        markdown_content: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Validate that figure references appear in logical order.

        Checks both numeric and LaTeX label references. Detects:
        - Out-of-order citations (e.g., Fig 5 before Fig 3)
        - Gaps in numbering (e.g., Fig 1, then Fig 5, missing 2-4)

        Args:
            references: List of FigureReference objects.
            markdown_content: Optional markdown for label extraction.

        Returns:
            List of order violation dictionaries with details.
        """
        violations = []

        # Track first occurrence of each figure (both numeric and label-based)
        first_occurrences = {}
        figure_order = []
        label_references = []  # Track label-based references separately

        for ref in references:
            ref_text, fig_num, panels, line_num, context = ref

            # Handle LaTeX label references
            if '\\ref{' in str(ref_text):
                # Store label references for later processing
                label_references.append((fig_num, line_num, ref_text, context))
                continue

            # Track first occurrence of numeric references
            if fig_num not in first_occurrences:
                first_occurrences[fig_num] = {
                    'line': line_num,
                    'text': ref_text,
                    'context': context
                }
                figure_order.append(fig_num)

        # Check if main figures are in order
        main_figures = [f for f in figure_order if not f.startswith('S')]
        supplemental_figures = [f for f in figure_order if f.startswith('S')]

        # Check main figure ordering
        for i in range(1, len(main_figures)):
            try:
                curr_num = int(main_figures[i])
                prev_num = int(main_figures[i-1])

                if curr_num < prev_num:
                    violations.append({
                        'type': 'out_of_order',
                        'figure': main_figures[i],
                        'expected_after': main_figures[i-1],
                        'line': first_occurrences[main_figures[i]]['line'],
                        'context': first_occurrences[main_figures[i]]['context'],
                        'message': f"Figure {curr_num} appears after Figure {prev_num}"
                    })
            except ValueError:
                # Skip if not a simple number
                pass

        # Check supplemental figure ordering
        for i in range(1, len(supplemental_figures)):
            try:
                curr_num = int(supplemental_figures[i][1:])  # Remove 'S' prefix
                prev_num = int(supplemental_figures[i-1][1:])

                if curr_num < prev_num:
                    violations.append({
                        'type': 'out_of_order',
                        'figure': supplemental_figures[i],
                        'expected_after': supplemental_figures[i-1],
                        'line': first_occurrences[supplemental_figures[i]]['line'],
                        'context': first_occurrences[supplemental_figures[i]]['context'],
                        'message': f"Figure {supplemental_figures[i]} appears after Figure {supplemental_figures[i-1]}"
                    })
            except (ValueError, IndexError):
                # Skip if not a simple number
                pass

        # Check for gaps in main figure sequence
        if len(main_figures) > 1:
            try:
                main_nums = [int(f) for f in main_figures]
                expected_figures = list(range(min(main_nums), max(main_nums) + 1))
                missing_figures = [f for f in expected_figures if str(f) not in main_figures]

                for missing in missing_figures:
                    # Find the first figure after the gap
                    later_figures = [f for f in main_nums if f > missing]
                    if later_figures:
                        first_later = str(later_figures[0])
                        violations.append({
                            'type': 'missing_figure',
                            'figure': str(missing),
                            'referenced_after': first_later,
                            'line': first_occurrences[first_later]['line'],
                            'context': first_occurrences[first_later]['context'],
                            'message': f"Figure {first_later} referenced, but Figure {missing} was never referenced"
                        })
            except (ValueError, TypeError):
                pass

        # Check for gaps in supplemental figure sequence
        if len(supplemental_figures) > 1:
            try:
                # Extract numeric parts
                supp_nums = [int(f[1:]) for f in supplemental_figures]
                expected_supps = list(range(min(supp_nums), max(supp_nums) + 1))
                missing_supps = [f for f in expected_supps if f'S{f}' not in supplemental_figures]

                for missing in missing_supps:
                    # Find the first figure after the gap
                    later_supps = [f for f in supp_nums if f > missing]
                    if later_supps:
                        first_later = f'S{later_supps[0]}'
                        violations.append({
                            'type': 'missing_figure',
                            'figure': f'S{missing}',
                            'referenced_after': first_later,
                            'line': first_occurrences[first_later]['line'],
                            'context': first_occurrences[first_later]['context'],
                            'message': f"Figure {first_later} referenced, but Figure S{missing} was never referenced"
                        })
            except (ValueError, TypeError, IndexError):
                pass

        # Validate LaTeX label-based figures if markdown_content provided
        if markdown_content and label_references:
            try:
                # Extract label definitions from markdown
                label_definitions = self.extract_figure_labels(markdown_content)

                if label_definitions:
                    # Build label-to-order mapping
                    label_order_map = self.build_label_order_map(label_definitions)

                    # Track label references by type
                    label_ref_order = []  # List of (label, line_num, text, context, fig_type)

                    for label, line_num, ref_text, context in label_references:
                        if label in label_definitions:
                            _, fig_type = label_definitions[label]
                            label_ref_order.append((label, line_num, ref_text, context, fig_type))

                    # Separate main and supplemental label references
                    main_label_refs = [r for r in label_ref_order if r[4] == 'main']
                    supp_label_refs = [r for r in label_ref_order if r[4] == 'supplemental']

                    # Check supplemental label order
                    for i in range(1, len(supp_label_refs)):
                        curr_label, curr_line, curr_text, curr_context, _ = supp_label_refs[i]
                        prev_label, prev_line, prev_text, prev_context, _ = supp_label_refs[i-1]

                        curr_order = label_order_map.get(curr_label, 0)
                        prev_order = label_order_map.get(prev_label, 0)

                        if curr_order > 0 and prev_order > 0 and curr_order < prev_order:
                            violations.append({
                                'type': 'label_out_of_order',
                                'figure': curr_label,
                                'expected_after': prev_label,
                                'line': curr_line,
                                'context': curr_context,
                                'message': f"Supplemental figure '{curr_label}' (appears {curr_order} in supplement) "
                                          f"is referenced before '{prev_label}' (appears {prev_order} in supplement)"
                            })

                    # Check for gaps in supplemental label references
                    if len(supp_label_refs) > 1:
                        referenced_orders = sorted([label_order_map[label] for label, _, _, _, _ in supp_label_refs
                                                   if label in label_order_map])

                        if referenced_orders:
                            expected_range = list(range(min(referenced_orders), max(referenced_orders) + 1))
                            missing_orders = [o for o in expected_range if o not in referenced_orders]

                            if missing_orders:
                                # Find which labels correspond to missing orders
                                for missing_order in missing_orders:
                                    missing_labels = [label for label, order in label_order_map.items()
                                                     if order == missing_order and label_definitions.get(label, (0, ''))[1] == 'supplemental']

                                    for missing_label in missing_labels:
                                        violations.append({
                                            'type': 'missing_supplemental_label',
                                            'figure': missing_label,
                                            'message': f"Supplemental figure '{missing_label}' (position {missing_order}) "
                                                      f"is never referenced in text"
                                        })

                    # Check for mixed referencing style (warning only)
                    numeric_supps = [f for f in supplemental_figures if f.startswith('S') and f[1:].isdigit()]
                    label_supps = [label for label, (_, fig_type) in label_definitions.items()
                                  if fig_type == 'supplemental']

                    if numeric_supps and label_supps:
                        violations.append({
                            'type': 'mixed_reference_style',
                            'message': f"Document uses both numeric ({len(numeric_supps)} refs) and "
                                      f"label-based ({len(label_supps)} refs) for supplemental figures. "
                                      f"Consider using one consistent style."
                        })

            except Exception as e:
                # Don't fail validation if label processing has issues
                logger.debug(f"Label validation error: {e}")

        return violations

    def validate_panel_order(
        self, references: List[FigureReference]
    ) -> List[Dict[str, Any]]:
        """Validate that figure panels appear in correct alphabetical order.

        Args:
            references: List of FigureReference objects.

        Returns:
            List of panel order violation dictionaries.
        """
        violations = []

        # Track panels seen for each figure
        figure_panels = {}  # figure_num -> {panel -> (line, context)}

        for ref in references:
            ref_text, fig_num, panels, line_num, context = ref

            # Skip LaTeX references with labels for now
            if '\\ref{' in str(fig_num):
                # For LaTeX refs, extract base figure name without 'fig:' prefix
                if fig_num.startswith('fig:'):
                    fig_num = fig_num[4:]

            # Skip if no panels
            if not panels:
                continue

            # Initialize tracking for this figure if needed
            if fig_num not in figure_panels:
                figure_panels[fig_num] = {}

            # Handle multi-panel references (e.g., "B-D")
            if '-' in panels:
                # Extract range (e.g., "B-D" -> ['B', 'C', 'D'])
                start_panel = panels[0]
                end_panel = panels[2] if len(panels) >= 3 else panels[0]
                for p in range(ord(start_panel), ord(end_panel) + 1):
                    panel = chr(p)
                    if panel not in figure_panels[fig_num]:
                        figure_panels[fig_num][panel] = (line_num, context)
            else:
                # Single panel or comma-separated panels
                panel_list = panels.split(',') if ',' in panels else [panels]
                for panel in panel_list:
                    panel = panel.strip()
                    if panel and panel not in figure_panels[fig_num]:
                        figure_panels[fig_num][panel] = (line_num, context)

        # Check each figure for panel order violations
        for fig_num, panels_dict in figure_panels.items():
            if not panels_dict:
                continue

            # Get sorted list of panels that were referenced
            panels_seen = sorted(panels_dict.keys())

            # Check if first panel is not 'A'
            if panels_seen and panels_seen[0] != 'A':
                first_panel = panels_seen[0]
                line_num, context = panels_dict[first_panel]
                violations.append({
                    'type': 'missing_panel_A',
                    'figure': fig_num,
                    'first_panel': first_panel,
                    'line': line_num,
                    'context': context,
                    'message': f"Figure {fig_num} starts with panel {first_panel}, but panel A was never referenced"
                })

            # Check for gaps in panel sequence
            if len(panels_seen) > 1:
                expected_panels = [chr(ord('A') + i) for i in range(ord(panels_seen[-1]) - ord('A') + 1)]
                missing_panels = [p for p in expected_panels if p not in panels_seen]

                if missing_panels:
                    # Find the first referenced panel after the gap
                    for missing in missing_panels:
                        # Find panels that come after the missing one
                        later_panels = [p for p in panels_seen if p > missing]
                        if later_panels:
                            first_later = later_panels[0]
                            line_num, context = panels_dict[first_later]
                            violations.append({
                                'type': 'missing_panel',
                                'figure': fig_num,
                                'missing_panel': missing,
                                'referenced_panel': first_later,
                                'line': line_num,
                                'context': context,
                                'message': f"Figure {fig_num} panel {first_later} referenced, but panel {missing} was never referenced"
                            })

            # Check if panels appear in correct alphabetical order
            # Sort by line number to get the order panels were first mentioned
            panel_order_by_line = sorted(panels_dict.items(), key=lambda x: x[1][0])
            prev_panel = None
            for panel, (line_num, context) in panel_order_by_line:
                if prev_panel and panel < prev_panel:
                    violations.append({
                        'type': 'panel_out_of_order',
                        'figure': fig_num,
                        'panel': panel,
                        'expected_after': prev_panel,
                        'line': line_num,
                        'context': context,
                        'message': f"Figure {fig_num} panel {panel} appears before panel {prev_panel} (expected alphabetical order)"
                    })
                prev_panel = panel

        return violations

    def detect_figure_warnings(
        self, references: List[FigureReference]
    ) -> List[Dict[str, Any]]:
        """Detect potential issues with figure references.

        Args:
            references: List of FigureReference objects.

        Returns:
            List of warning dictionaries with details.
        """
        warnings = []

        # Check for non-parenthetic references that might need parentheses
        for ref in references:
            ref_text, fig_num, panels, line_num, context = ref

            # Skip if it's in a figure caption (starts with **)
            if context.startswith('**'):
                continue

            # Check if ref_text starts with '(' or if it's within parentheses in the context
            in_parentheses = ref_text.startswith('(')

            # If ref_text doesn't start with '(', check if it appears within parentheses in context
            if not in_parentheses and context:
                # Find where the reference appears in the context
                # Strip the leading/trailing parts of ref_text that might include closing parens
                ref_core = ref_text.rstrip(')')
                ref_pos = context.find(ref_core)
                if ref_pos > 0:
                    # Check if there's an opening paren before the reference
                    text_before = context[:ref_pos]
                    # Count parens - if there's an unmatched '(' before us, we're in parentheses
                    open_count = text_before.count('(')
                    close_count = text_before.count(')')
                    in_parentheses = open_count > close_count

            # Warning for references not in parentheses (unless in specific contexts)
            if not in_parentheses:
                # Check if the reference text itself contains acceptable context phrases
                # These are typically part of the match when using our combined pattern
                acceptable_starts = [
                    'as shown in',
                    'see fig',
                    'shown in fig',
                    'described in fig',
                    'illustrated in fig'
                ]

                ref_lower = ref_text.lower()
                if not any(ref_lower.startswith(ctx) for ctx in acceptable_starts):
                    # For standalone "Figure X" references, check context
                    if ref_lower.startswith('fig'):
                        # This is a standalone figure reference - warn about it
                        warnings.append({
                            'type': 'no_parentheses',
                            'figure': fig_num,
                            'line': line_num,
                            'text': ref_text,
                            'context': context,
                            'message': f"Figure reference '{ref_text}' is not in parentheses"
                        })

        return warnings

    def check_prefix_consistency(
        self, references: List[FigureReference]
    ) -> List[Dict[str, Any]]:
        """Check for inconsistent use of "Fig." vs "Figure" prefixes.

        Args:
            references: List of FigureReference objects.

        Returns:
            List of warnings about prefix inconsistencies.
        """
        warnings = []

        # Count the usage of different prefixes
        prefix_counts = {
            'Fig.': 0,
            'Figure': 0,
            'Fig': 0  # Without period
        }

        prefix_examples = {
            'Fig.': [],
            'Figure': [],
            'Fig': []
        }

        for ref in references:
            ref_text, fig_num, panels, line_num, context = ref

            # Skip LaTeX references as they might have different patterns
            if '\\ref{' in ref_text:
                continue

            # Determine which prefix is used
            ref_lower = ref_text.lower()
            if 'fig.' in ref_lower:
                prefix_counts['Fig.'] += 1
                prefix_examples['Fig.'].append((ref_text, line_num, context))
            elif 'figure' in ref_lower:
                prefix_counts['Figure'] += 1
                prefix_examples['Figure'].append((ref_text, line_num, context))
            elif 'fig' in ref_lower:
                prefix_counts['Fig'] += 1
                prefix_examples['Fig'].append((ref_text, line_num, context))

        # Determine the dominant prefix
        total_refs = sum(prefix_counts.values())
        if total_refs == 0:
            return warnings

        dominant_prefix = max(prefix_counts, key=prefix_counts.get)
        dominant_count = prefix_counts[dominant_prefix]

        # If one prefix is used >80% of the time, warn about the minority uses
        if dominant_count > 0.8 * total_refs:
            for prefix, count in prefix_counts.items():
                if prefix != dominant_prefix and count > 0:
                    # Add warnings for the minority prefix usage
                    for ref_text, line_num, context in prefix_examples[prefix][:3]:  # Show first 3 examples
                        warnings.append({
                            'type': 'prefix_inconsistency',
                            'prefix': prefix,
                            'dominant_prefix': dominant_prefix,
                            'line': line_num,
                            'text': ref_text,
                            'context': context,
                            'message': f"Inconsistent prefix: '{prefix}' used here, but '{dominant_prefix}' is used in {dominant_count}/{total_refs} references"
                        })

                    # If there are more than 3, add a summary
                    if len(prefix_examples[prefix]) > 3:
                        remaining = len(prefix_examples[prefix]) - 3
                        warnings.append({
                            'type': 'prefix_inconsistency_summary',
                            'prefix': prefix,
                            'dominant_prefix': dominant_prefix,
                            'line': 0,
                            'text': '',
                            'context': '',
                            'message': f"... and {remaining} more instances of '{prefix}' instead of '{dominant_prefix}'"
                        })

        return warnings

    def generate_figure_analysis_report(self, markdown_content: str) -> str:
        """Generate a comprehensive figure reference analysis report.

        Extracts all figure references and validates figure order, panel order,
        and prefix consistency.

        Args:
            markdown_content: The markdown content to analyze.

        Returns:
            Formatted report string, or empty string if no references found.
        """
        # Extract references
        references = self.extract_figure_references(markdown_content)

        if not references:
            return ""

        # Validate figure order
        figure_violations = self.validate_figure_order(references, markdown_content)

        # Validate panel order
        panel_violations = self.validate_panel_order(references)

        # Detect warnings
        warnings = self.detect_figure_warnings(references)

        # Check for prefix consistency
        prefix_warnings = self.check_prefix_consistency(references)

        # Build report
        report_lines = []

        # Summary
        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("FIGURE REFERENCE ANALYSIS")
        report_lines.append("=" * 70)
        report_lines.append("")
        report_lines.append(f"Total figure references found: {len(references)}")

        # Count unique figures (including all panels)
        unique_figures = set()
        unique_figure_bases = set()  # Just the figure numbers without panels
        for ref in references:
            _, fig_num, panels, _, _ = ref
            if not '\\ref{' in str(fig_num):
                # Add the full figure+panel combination
                if panels:
                    unique_figures.add(f"{fig_num}{panels}")
                else:
                    unique_figures.add(fig_num)
                # Also track just the base figure number
                unique_figure_bases.add(fig_num)

        report_lines.append(f"Unique figures referenced: {len(unique_figure_bases)}")
        report_lines.append("")

        # List first occurrences - SORTED BY LINE NUMBER
        first_occurrences = {}
        for ref in references:
            ref_text, fig_num, panels, line_num, context = ref
            # Create a unique key for each figure+panel combination
            if panels:
                key = f"{fig_num}_{panels}"
                display_text = f"Fig. {fig_num}{panels}"  # Normalized display
            else:
                key = fig_num
                display_text = f"Fig. {fig_num}"  # Normalized display

            if key not in first_occurrences:
                first_occurrences[key] = {
                    'line': line_num,
                    'text': display_text,  # Use normalized text for cleaner display
                    'panels': panels,
                    'fig_num': fig_num,
                    'original_text': ref_text  # Keep original for reference
                }

        if first_occurrences:
            report_lines.append("First occurrence of each figure (ordered by appearance):")
            # Sort by line number (order of appearance)
            for key in sorted(first_occurrences.keys(),
                            key=lambda x: first_occurrences[x]['line']):
                info = first_occurrences[key]
                # No need for panel_info since it's in the normalized text
                report_lines.append(f"  Line {info['line']:4d}: {info['text']}")
            report_lines.append("")

        # Report figure order violations (separate numeric and label-based)
        numeric_violations = [v for v in figure_violations
                             if v['type'] in ['out_of_order', 'missing_figure']]
        label_violations = [v for v in figure_violations
                           if v['type'] in ['label_out_of_order', 'missing_supplemental_label', 'mixed_reference_style']]

        if numeric_violations:
            report_lines.append("NUMERIC FIGURE ORDER VIOLATIONS:")
            report_lines.append("")
            for violation in numeric_violations:
                report_lines.append(f"  - {violation['message']}")
                if 'line' in violation and violation['line'] > 0:
                    report_lines.append(f"    Line {violation['line']}: {violation.get('context', '')}")
                report_lines.append("")

        if label_violations:
            report_lines.append("LABEL-BASED FIGURE ORDER VIOLATIONS:")
            report_lines.append("")
            for violation in label_violations:
                report_lines.append(f"  - {violation['message']}")
                if 'line' in violation and violation['line'] > 0:
                    report_lines.append(f"    Line {violation['line']}: {violation.get('context', '')}")
                report_lines.append("")

        # Report panel order violations
        if panel_violations:
            report_lines.append("PANEL ORDER VIOLATIONS:")
            report_lines.append("")
            for violation in panel_violations:
                report_lines.append(f"  - {violation['message']}")
                if violation['line'] > 0:  # Some violations may not have a specific line
                    report_lines.append(f"    Line {violation['line']}: {violation['context']}")
                report_lines.append("")

        # Report prefix consistency warnings
        if prefix_warnings:
            report_lines.append("FIGURE PREFIX INCONSISTENCIES:")
            report_lines.append("")
            for warning in prefix_warnings:
                report_lines.append(f"  - {warning['message']}")
                if warning['line'] > 0:
                    report_lines.append(f"    Line {warning['line']}: {warning['context']}")
                report_lines.append("")

        # Report other warnings
        if warnings:
            report_lines.append("FIGURE REFERENCE WARNINGS:")
            report_lines.append("")
            for warning in warnings:
                report_lines.append(f"  - {warning['message']}")
                report_lines.append(f"    Line {warning['line']}: {warning['context']}")
                report_lines.append("")

        if not numeric_violations and not label_violations and not panel_violations and not warnings and not prefix_warnings:
            report_lines.append("All figure references appear to be in order!")
            report_lines.append("")

        report_lines.append("=" * 70)
        report_lines.append("")

        return '\n'.join(report_lines)
