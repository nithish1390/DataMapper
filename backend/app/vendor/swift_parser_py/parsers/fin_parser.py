import re
import time
from typing import Dict, List, Any, Optional

class TimeoutException(Exception):
    """Exception raised when parsing exceeds time limit"""
    pass

# Cross-platform timeout implementation
def run_with_timeout(func, args=(), kwargs=None, timeout=30):
    """Run a function with timeout support (cross-platform)"""
    if kwargs is None:
        kwargs = {}
    
    import threading
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

class FinParser:
    """
    Parser for FIN messages structure
    
    This parses the high-level block structure of SWIFT messages.
    """
    
    @staticmethod
    def parse(input_text: str, timeout_seconds: int = 30) -> Dict[str, Any]:
        """
        Parse a SWIFT message into blocks
        
        Args:
            input_text: The SWIFT message text
            timeout_seconds: Maximum time allowed for parsing
            
        Returns:
            Dictionary with blocks mapped as block1, block2, etc.
        """
        def _parse_blocks():
            result = parse_blocks(input_text)
            block_map = {}
            
            for block in result:
                block_map[f"block{block['name']}"] = block
                
            return block_map
        
        # Use cross-platform timeout implementation
        return run_with_timeout(_parse_blocks, timeout=timeout_seconds)


def parse_blocks(input_text: str) -> List[Dict[str, Any]]:
    """
    Parse the blocks in a SWIFT message
    
    Args:
        input_text: The SWIFT message text
        
    Returns:
        List of blocks with name and content
    """
    blocks = []
    # Fixed regex pattern with atomic grouping to prevent catastrophic backtracking
    # Using possessive quantifiers and atomic groups to prevent exponential backtracking
    block_pattern = re.compile(r'{([^{}:]+):((?>[^{}]|{(?>[^{}]|{[^{}]*}+)}+)*)}')
    
    try:
        for match in block_pattern.finditer(input_text):
            name = match.group(1)
            content_text = match.group(2)
            
            # Check if this is a Block 5 trailer tag (starts with letter, not number)
            if name.isalpha() and len(name) <= 4:
                # This is a Block 5 trailer tag - group under block5
                existing_block5 = next((b for b in blocks if b['name'] == '5'), None)
                if existing_block5:
                    # Add to existing block5 content
                    if isinstance(existing_block5['content'], list):
                        existing_block5['content'].append({
                            "name": name,
                            "content": [content_text]
                        })
                else:
                    # Create new block5
                    blocks.append({
                        "name": "5",
                        "content": [{
                            "name": name,
                            "content": [content_text]
                        }]
                    })
            else:
                # Regular block (1-4)
                # Process content which might contain nested blocks
                content = process_content(content_text, max_depth=10)
                
                blocks.append({
                    "name": name,
                    "content": content
                })
    except TimeoutException:
        # If regex times out, fall back to safer parsing
        return _safe_parse_blocks(input_text)
    
    return blocks


def _safe_parse_blocks(input_text: str) -> List[Dict[str, Any]]:
    """
    Safe fallback parsing that avoids catastrophic backtracking
    
    Args:
        input_text: The SWIFT message text
        
    Returns:
        List of blocks with name and content
    """
    blocks = []
    # Simple iterative approach without complex nested regex
    i = 0
    while i < len(input_text):
        if input_text[i] == '{':
            # Find the matching closing brace
            brace_count = 1
            start = i + 1
            j = start
            
            while j < len(input_text) and brace_count > 0:
                if input_text[j] == '{':
                    brace_count += 1
                elif input_text[j] == '}':
                    brace_count -= 1
                j += 1
            
            if brace_count == 0:
                # Found complete block
                block_content = input_text[start:j-1]
                # Split on first colon to get block name
                colon_pos = block_content.find(':')
                if colon_pos != -1:
                    name = block_content[:colon_pos]
                    content_text = block_content[colon_pos+1:]
                    
                    blocks.append({
                        "name": name,
                        "content": [content_text]  # Simple content without nested parsing
                    })
                i = j
            else:
                i += 1
        else:
            i += 1
    
    return blocks


def process_content(content_text: str, max_depth: int = 10, current_depth: int = 0) -> List[Any]:
    """
    Process block content, which may contain nested blocks
    
    Args:
        content_text: The content part of a block
        max_depth: Maximum recursion depth
        current_depth: Current recursion depth
        
    Returns:
        List of text and block content
    """
    # Prevent infinite recursion
    if current_depth >= max_depth:
        return [content_text]
    
    result = []
    
    # Fixed regex pattern with atomic grouping
    nested_block_pattern = re.compile(r'{([^{}:]+):((?>[^{}]|{(?>[^{}]|{[^{}]*}+)}+)*)}')
    
    try:
        last_end = 0
        for match in nested_block_pattern.finditer(content_text):
            # Add text before the block
            if match.start() > last_end:
                text = content_text[last_end:match.start()]
                if text.strip():
                    result.append(text)
            
            # Add the nested block
            name = match.group(1)
            nested_content = process_content(match.group(2), max_depth, current_depth + 1)
            
            result.append({
                "name": name,
                "content": nested_content
            })
            
            last_end = match.end()
        
        # Add remaining text
        if last_end < len(content_text):
            text = content_text[last_end:]
            if text.strip():
                result.append(text)
    except TimeoutException:
        # If regex times out, return simple content
        return [content_text]
    
    return result