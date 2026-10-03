"""
Field regular expression factory for SWIFT message field parsing

This module generates regular expressions for validating SWIFT message fields
based on their pattern definitions.
"""

import re
from typing import Dict, List, Any, Set, Optional
from .field_peg import parse as parse_pattern, NodeType
from .field_parser_fix import apply_field_fixes


class FieldNames:
    """Class for handling field names in patterns"""

    def __init__(self, field_names_string: str):
        """
        Initialize with field names string

        Args:
            field_names_string: String with field names separated by $
        """
        self.field_names_string = field_names_string
        field_names_parts = field_names_string.split('$')

        self.names = []
        for field_names_part in field_names_parts:
            if field_names_part == "":  # Special handling of empty list
                field_names_part = "(Value)"
            names = FieldNamesParser.parse_field_names(field_names_part)
            self.names.append(names)

        self.flat_names = []
        for section in self.names:
            for name in section:
                self.flat_names.append(name)


class FieldNamesParser:
    """Static utility class for parsing field names"""

    @staticmethod
    def parse_field_names(field_names_string: str) -> List[str]:
        """
        Parse field names from a string

        Args:
            field_names_string: String with field names in parentheses

        Returns:
            List of field names
        """
        if not field_names_string:
            return []

        names = []
        field_names_regexp = re.compile(r'\((.*?)\)')

        for match in field_names_regexp.finditer(field_names_string):
            escaped = FieldNamesParser.escape(match.group(1))
            names.append(escaped)

        if not names:
            raise ValueError(f"Strange field names: {field_names_string}")

        return names

    @staticmethod
    def escape(name: str) -> str:
        """
        Escape spaces and special characters in field names

        Args:
            name: Field name

        Returns:
            Escaped field name
        """
        # Replace special characters that are not valid in regex group names
        name = name.replace(" ", "_")
        name = name.replace("/", "_slash_")
        name = name.replace("-", "_dash_")
        name = name.replace("'", "_apos_")
        name = name.replace("(", "_lparen_")
        name = name.replace(")", "_rparen_")
        name = name.replace("+", "_plus_")
        name = name.replace(".", "_dot_")
        return name

    @staticmethod
    def unescape(name: str) -> str:
        """
        Unescape field names

        Args:
            name: Escaped field name

        Returns:
            Unescaped field name
        """
        # Restore special characters that were escaped
        name = name.replace("_slash_", "/")
        name = name.replace("_dash_", "-")
        name = name.replace("_apos_", "'")
        name = name.replace("_lparen_", "(")
        name = name.replace("_rparen_", ")")
        name = name.replace("_plus_", "+")
        name = name.replace("_dot_", ".")
        name = name.replace("_", " ")
        return name


class FieldContentParser:
    """Parser for field content based on a regexp"""

    def __init__(self, regexp_str: str, field_names: FieldNames):
        """
        Initialize with regexp and field names

        Args:
            regexp_str: Regular expression string
            field_names: FieldNames object
        """
        self.regexp_str = regexp_str
        self.field_names = field_names
        self.regexp = re.compile(regexp_str, re.DOTALL)

    def parse(self, field_value: str) -> Dict[str, str]:
        """
        Parse field value using the regexp

        Args:
            field_value: Field value to parse

        Returns:
            Dictionary with field components
        """
        # Handle fields with multiple lines
        field_value = field_value.replace('\r\n', '\n').replace('\r', '\n')

        match = self.regexp.fullmatch(field_value)

        if not match:
            return {"value": field_value, "error": f"Unable to parse '{field_value}' with regexp '{self.regexp_str}'."}

        result = {}
        for field_name in self.field_names.flat_names:
            try:
                value = match.group(field_name)
                if value:
                    # Clean up the value, especially for multi-line fields
                    cleaned_value = value.strip()

                    # Check if this is a multi-line field
                    if '\n' in cleaned_value:
                        # For multi-line fields, format as an array of strings
                        lines = [line.strip() for line in cleaned_value.split('\n')]
                        # Filter out empty lines
                        lines = [line for line in lines if line]
                        result[FieldNamesParser.unescape(field_name)] = lines
                    else:
                        result[FieldNamesParser.unescape(field_name)] = cleaned_value
            except IndexError:
                # Group not found, skip
                pass
            except Exception as e:
                # Other error, provide diagnostic information
                result["error"] = str(e)

        return result


class PatternNameInjector:
    """Injects field names into pattern nodes"""

    def __init__(self):
        """Initialize the injector"""
        self.remaining_names = []
        self.pattern = None

    def inject_names(self, names: List[str], parsed_pattern: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject names into pattern nodes

        Args:
            names: List of field names
            parsed_pattern: Parsed pattern structure

        Returns:
            Pattern with names injected
        """
        self.remaining_names = names.copy()
        self.pattern = parsed_pattern
        result = self._visit_node(parsed_pattern)

        if self.remaining_names:
            raise ValueError(f"Remaining names after name injection: {self.remaining_names}")

        return result

    def _visit_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Visit a node and inject names

        Args:
            node: Pattern node

        Returns:
            Updated node
        """
        if node["type"] == "literal":
            return self._visit_literal(node)
        elif node["type"] == "sequence":
            for child in node.get("parts", []):
                self._visit_node(child)
            return node
        elif node["type"] == "field":
            return self._visit_field(node)
        else:
            raise ValueError(f"Unknown node type {node['type']}: {node}")

    def _visit_literal(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Visit a literal node

        Args:
            node: Literal node

        Returns:
            Updated node
        """
        if (node["value"] == "N" and self.remaining_names and
                re.search(r'(_|\b)sign(_|\b)', self.remaining_names[0], re.IGNORECASE)):
            # Handle special case for the Sign
            node["name"] = self.remaining_names.pop(0)

        return node

    def _visit_field(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Visit a field node

        Args:
            node: Field node

        Returns:
            Updated node
        """
        if node["set"] == "e":  # Space doesn't get a name
            return node

        if self.remaining_names:
            node["name"] = self.remaining_names.pop(0)

        return node


class MandatoryFieldDetector:
    """Detects if a pattern tree contains mandatory fields"""

    def contains_mandatory(self, tree: Dict[str, Any]) -> bool:
        """
        Check if tree contains mandatory fields

        Args:
            tree: Pattern tree

        Returns:
            True if tree contains mandatory fields
        """
        return self._visit_node(tree)

    def _visit_node(self, node: Dict[str, Any]) -> bool:
        """
        Visit a node to check for mandatory fields

        Args:
            node: Pattern node

        Returns:
            True if node or its children contain mandatory fields
        """
        if node["type"] == NodeType.LITERAL:
            return False
        elif node["type"] == NodeType.SEQUENCE:
            if node.get("optional", False):
                return False

            # Check if any part is mandatory
            for part in node.get("parts", []):
                if self._visit_node(part):
                    return True

            return False
        elif node["type"] == NodeType.FIELD:
            return True
        else:
            # Unknown node type
            return False


class FieldRegexpFactory:
    """Factory for creating regular expressions for SWIFT message fields"""

    def create_regexp(self, pattern: str, field_names_string: str) -> str:
        """
        Create a regular expression for a field pattern

        Args:
            pattern: Field pattern
            field_names_string: Field names as a string

        Returns:
            Regular expression pattern string
        """
        field_names = FieldNames(field_names_string)

        # Split pattern by $ which indicates a newline
        pattern_parts = pattern.split("$")

        if len(pattern_parts) != len(field_names.names):
            raise ValueError('Different count of lines in pattern and field names.')

        regexps = []
        for pattern_part, i in zip(pattern_parts, range(len(pattern_parts))):
            field_names_section = field_names.names[i]
            regexps.append(self._create_regexp_core(pattern_part, field_names_section))

        mandatory_field_detector = MandatoryFieldDetector()

        head, *regexps_rest = regexps
        result = head["regexp"]
        left_mandatory = mandatory_field_detector.contains_mandatory(head["tree"])

        for regexp_part in regexps_rest:
            right_mandatory = mandatory_field_detector.contains_mandatory(regexp_part["tree"])
            if left_mandatory and right_mandatory:
                # Use a pattern that matches both Windows (\r\n) and Unix (\n) line endings
                result = result + r"(?:\r?\n)" + regexp_part["regexp"]
            else:
                result = result + r"(?:\r?\n)?" + regexp_part["regexp"]

        result = "^" + result + "$"
        return result

    def _create_regexp_core(self, pattern: str, field_names: List[str]) -> Dict[str, Any]:
        """
        Create core regexp for a pattern part

        Args:
            pattern: Pattern part
            field_names: Field names for this part

        Returns:
            Dictionary with tree and regexp
        """
        prefix = ""
        if pattern and pattern[0] == ':':
            # Make the leading colon optional
            prefix = ":?"
            pattern = pattern[1:]

        parsed_pattern = parse_pattern(pattern)
        injector = PatternNameInjector()
        injector.inject_names(field_names, parsed_pattern)

        regexp = self._visit_node(parsed_pattern)
        if prefix:
            regexp = prefix + regexp

        return {"tree": parsed_pattern, "regexp": regexp}

    def _visit_nodes(self, nodes: List[Dict[str, Any]]) -> str:
        """
        Visit multiple nodes

        Args:
            nodes: List of nodes

        Returns:
            Combined regular expression
        """
        return "".join(self._visit_node(node) for node in nodes)

    def _visit_node(self, node: Dict[str, Any]) -> str:
        """
        Visit a node to generate regexp

        Args:
            node: Pattern node

        Returns:
            Regular expression string
        """
        if node["type"] == NodeType.LITERAL:
            return self._visit_literal(node)
        elif node["type"] == NodeType.SEQUENCE:
            rx_optional = "?" if node.get("optional", False) else ""
            rx_name = f"?P<{node['name']}>" if "name" in node else ""
            value = self._visit_nodes(node.get("parts", []))

            if not node.get("optional", False) and "name" not in node:
                # No need to add parentheses
                return value

            if (len(node.get("parts", [])) == 1 and "name" not in node and
                    node.get("optional", False) and re.match(r'^\(.*\)$', value)):
                # There are already parentheses
                return value + "?"

            return f"({rx_name}{value}){rx_optional}"
        elif node["type"] == NodeType.FIELD:
            return self._visit_field(node)
        else:
            # Unknown node type, return empty string
            return ""

    def _visit_field(self, node: Dict[str, Any]) -> str:
        """
        Visit a field node to generate regexp

        Args:
            node: Field node

        Returns:
            Regular expression string
        """
        count = node["count"]
        set_type = node["set"]
        lines = node.get("lines", 1)
        exact = node.get("exact", False)

        # Get character set regex
        if set_type == "e":
            rx_set = r" "
        elif set_type == "z":
            rx_set = r"[\s\S]"
        elif set_type == "n":
            rx_set = r"[0-9]"
        elif set_type == "d":
            # For decimal fields, allow for comma or dot decimal separator
            # In SWIFT messages, the decimal separator is typically a comma
            # but we also support dot for compatibility
            rx_set = r"[0-9,\.]"
        elif set_type == "a":
            rx_set = r"[A-Z]"
        elif set_type == "c":
            rx_set = r"[0-9A-Z]"
        elif set_type == "x":
            # Expanded character set for account numbers and identifiers
            rx_set = r"[0-9a-zA-Z/\-\?:\(\)\.,'\+ ]"
        else:
            rx_set = r"."

        # Special handling for multi-line fields
        if lines > 1:
            # This is a multi-line field like an address
            # Format is: line count * line length character set
            # Apply the improved regex generation to all multi-line fields
            # This ensures consistent handling of fields with patterns like n*mx
            if "name" in node:
                # Capture multiple lines for all multi-line fields
                # Allow any character including newlines
                rx_set_for_line = rx_set
                rx_count_for_line = f"{{1,{count}}}"
                rx_name = f"?P<{node['name']}>" if "name" in node else ""

                # Create regex that captures up to 'lines' number of lines
                # with up to 'count' characters each
                # Add a special marker to indicate this is a multi-line field
                # This will be used later to process the field as an array of strings
                node['multi_line'] = True
                return f"({rx_name}(?:.{{1,{count}}}(?:\r?\n)?){{1,{lines}}})"
            else:
                # Standard multi-line field
                rx_count = f"{{{count}}}" if exact else f"{{1,{count}}}"
                rx_name = f"?P<{node['name']}>" if "name" in node else ""
                rx_lines = rf"(?:\r?\n{rx_set}{rx_count}){{0,{lines-1}}}" if lines > 1 else ""

                if rx_name:
                    result = f"({rx_name}{rx_set}{rx_count}{rx_lines})"
                else:
                    result = f"{rx_set}{rx_count}{rx_lines}"

                return result
        else:
            # Single line field
            rx_count = f"{{{count}}}" if exact else f"{{1,{count}}}"
            rx_name = f"?P<{node['name']}>" if "name" in node else ""

            if rx_name:
                result = f"({rx_name}{rx_set}{rx_count})"
            else:
                result = f"{rx_set}{rx_count}"

            return result

    def _visit_literal(self, node: Dict[str, Any]) -> str:
        """
        Visit a literal node to generate regexp

        Args:
            node: Literal node

        Returns:
            Regular expression string
        """
        if "name" in node:
            return f"(?P<{node['name']}>{re.escape(node['value'])})"
        return re.escape(node["value"])


class FieldParser:
    """Parser for SWIFT message fields"""

    def __init__(self, field_patterns: Dict[str, Any]):
        """
        Initialize with field patterns

        Args:
            field_patterns: Dictionary of field metadata
        """
        self.field_patterns = field_patterns
        self.field_parsers = {}
        self.regexp_factory = FieldRegexpFactory()

    def parse(self, field_header: str, field_content: str) -> Dict[str, str]:
        """
        Parse field content

        Args:
            field_header: Field header (e.g., '20C')
            field_content: Field content

        Returns:
            Dictionary with parsed field components
        """
        try:
            # Special handling for structured fields
            if field_header in ["50K", "59"]:
                return self._parse_structured_field(field_header, field_content)

            if field_header not in self.field_parsers:
                field_metadata = self.field_patterns.get(field_header)
                if not field_metadata:
                    return {"value": field_content}  # Return raw value if no pattern

                if field_header == "77E":
                    return {"value": field_content}  # Special handling for 77E

                regexp_str = self.regexp_factory.create_regexp(
                    field_metadata["pattern"],
                    field_metadata["fieldNames"]
                )
                self.field_parsers[field_header] = FieldContentParser(
                    regexp_str,
                    FieldNames(field_metadata["fieldNames"])
                )

            parser = self.field_parsers[field_header]
            result = parser.parse(field_content)

            # Apply fixes for known parsing issues
            fixed_result = apply_field_fixes(field_header, field_content, result)
            return fixed_result
        except Exception as e:
            # If parsing fails, return the raw value with error details
            return {"value": field_content, "error": str(e)}

    def _parse_structured_field(self, field_header: str, field_content: str) -> Dict[str, Any]:
        """
        Special parsing for structured fields like 50K and 59

        Args:
            field_header: Field header (e.g., '50K')
            field_content: Field content

        Returns:
            Dictionary with structured field components
        """
        field_content = field_content.replace('\r\n', '\n').replace('\r', '\n')
        lines = field_content.split('\n')

        result = {}

        # Check if there's an account number (starts with /)
        if lines[0].startswith('/'):
            result["Account"] = lines[0].strip()
            name_address_lines = lines[1:]
        else:
            name_address_lines = lines

        # Process name and address lines
        if name_address_lines:
            # Remove empty lines
            name_address_lines = [line.strip() for line in name_address_lines if line.strip()]

            if len(name_address_lines) > 0:
                result["Name"] = name_address_lines[0]

            if len(name_address_lines) > 1:
                result["Address"] = name_address_lines[1:]

            # Also provide the full name and address as a combined field
            result["Name and Address"] = name_address_lines

        return result