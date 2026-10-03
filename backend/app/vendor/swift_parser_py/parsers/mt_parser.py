import re
import threading
import time
from typing import List, Dict, Any

class TimeoutException(Exception):
    """Exception raised when field parsing exceeds time limit"""
    pass

# Cross-platform timeout implementation
def run_with_timeout(func, args=(), kwargs=None, timeout=30):
    """Run a function with timeout support (cross-platform)"""
    if kwargs is None:
        kwargs = {}
    
    result = [None]
    exception = [None]
    
    def target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        raise TimeoutException(f"Operation timed out after {timeout} seconds")
    
    if exception[0]:
        raise exception[0]
    
    return result[0]

class MtParser:
    """
    Parser for MT message fields
    
    This parses the fields within Block 4 of SWIFT messages.
    """
    
    @staticmethod
    def parse(input_text: str, timeout_seconds: int = 30) -> List[Dict[str, Any]]:
        """
        Parse the fields in the MT message
        
        Args:
            input_text: The content of Block 4
            timeout_seconds: Maximum time allowed for parsing
            
        Returns:
            List of field dictionaries
        """
        def _parse_fields():
            fields = []
            
            # Normalize line endings to handle both Unix and Windows formats
            normalized_text = input_text.replace('\r\n', '\n').replace('\r', '\n')
            lines = normalized_text.split('\n')
            
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                # Skip empty lines
                if not line:
                    i += 1
                    continue
                    
                # Check if the line starts with a field header
                field_header_match = re.match(r':(\d{2})([A-Za-z]?):', line)
                if field_header_match:
                    field_type = field_header_match.group(1)
                    field_option = field_header_match.group(2)
                    
                    # Check if it's a complex field (with qualifier)
                    complex_field_match = re.match(r':\d{2}[A-Za-z]?:([^/]+)//(.+)', line)
                    
                    if complex_field_match:
                        # Complex field
                        qualifier = complex_field_match.group(1)
                        field_text = complex_field_match.group(2)
                        
                        # Look ahead for continuation lines
                        field_text, i = collect_field_content(lines, i, field_text)
                        
                        field_value = f":{qualifier}//{field_text}"
                        fields.append({
                            "type": field_type,
                            "option": field_option,
                            "fieldValue": field_value,
                            "content": f":{field_type}{field_option}:{field_value}"
                        })
                    else:
                        # Simple field
                        field_text = line[len(f":{field_type}{field_option}:"):]
                        
                        # Look ahead for continuation lines
                        field_text, i = collect_field_content(lines, i, field_text)
                        
                        fields.append({
                            "type": field_type,
                            "option": field_option,
                            "fieldValue": field_text,
                            "content": f":{field_type}{field_option}:{field_text}"
                        })
                
                i += 1
            
            return fields
        
        # Use cross-platform timeout implementation
        return run_with_timeout(_parse_fields, timeout=timeout_seconds)


def collect_field_content(lines: List[str], current_idx: int, initial_text: str, max_lines: int = 1000) -> tuple:
    """
    Collect content for a field that might span multiple lines
    
    Args:
        lines: All lines in the message
        current_idx: Current line index
        initial_text: Text already collected
        max_lines: Maximum number of lines to collect to prevent infinite loops
        
    Returns:
        Tuple of (complete field content, last line index)
    """
    text = initial_text
    idx = current_idx + 1
    lines_processed = 0
    
    while idx < len(lines) and lines_processed < max_lines:
        next_line = lines[idx].strip()
        
        # Skip empty lines
        if not next_line:
            idx += 1
            lines_processed += 1
            continue
            
        # Check if the next line starts a new field
        if re.match(r':\d{2}[A-Za-z]?:', next_line) or next_line.startswith("-"):
            break
            
        # Otherwise, append the line to the field content
        text += "\n" + next_line
        idx += 1
        lines_processed += 1
    
    # If we hit the max_lines limit, log a warning (could be added to result)
    if lines_processed >= max_lines:
        # This could be logged or returned as a warning
        pass
    
    return text, idx - 1