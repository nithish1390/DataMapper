"""
Field pattern parser for SWIFT message fields

This module implements a parser for SWIFT field patterns like:
- 16x
- 35x
- 3!n
- 6*35x
- etc.
"""

import re
import json
from typing import Dict, List, Any, Union, Optional

# Use string constants instead of Enum for better serialization
class NodeType:
    SEQUENCE = "sequence"
    FIELD = "field"
    LITERAL = "literal"
    
    def __repr__(self):
        return self

class Node:
    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        attrs = ", ".join(f"{k}={v}" for k, v in self.__dict__.items() if k != "type")
        return f"{self.type}({attrs})"
    
    def to_dict(self):
        """Convert node to a dictionary for serialization"""
        return {k: v for k, v in self.__dict__.items()}


def parse(pattern: str) -> Dict[str, Any]:
    """
    Parse a SWIFT field pattern string
    
    Args:
        pattern: A field pattern like '16x', '35*3n', etc.
        
    Returns:
        A parsed structure representing the pattern
    """
    tokens = tokenize(pattern)
    return parse_tokens(tokens)


def tokenize(pattern: str) -> List[str]:
    """
    Tokenize a pattern string
    
    Args:
        pattern: A field pattern
        
    Returns:
        List of tokens
    """
    tokens = []
    i = 0
    
    while i < len(pattern):
        char = pattern[i]
        
        if char in "[]":
            tokens.append(char)
            i += 1
        elif char.isdigit():
            # Parse number
            start = i
            while i < len(pattern) and pattern[i].isdigit():
                i += 1
            tokens.append(pattern[start:i])
        elif char in "ndxcaze":
            # Character set
            tokens.append(char)
            i += 1
        elif char in "!*$":
            # Special characters
            tokens.append(char)
            i += 1
        else:
            # Treat as literal
            tokens.append(char)
            i += 1
    
    return tokens


def parse_tokens(tokens: List[str]) -> Dict[str, Any]:
    """
    Parse tokens into a structure
    
    Args:
        tokens: List of tokens
        
    Returns:
        Parsed structure
    """
    result, remaining = parse_parts(tokens)
    
    if remaining:
        raise ValueError(f"Unexpected tokens: {remaining}")
    
    return {"type": NodeType.SEQUENCE, "optional": False, "parts": result}


def parse_parts(tokens: List[str]) -> tuple:
    """
    Parse parts of a pattern
    
    Args:
        tokens: List of tokens
        
    Returns:
        Tuple of (parsed parts, remaining tokens)
    """
    parts = []
    i = 0
    
    while i < len(tokens):
        token = tokens[i]
        
        if token == "[":
            # Optional sequence
            sequence_tokens = tokens[i+1:]
            sequence_parts, remaining = parse_parts(sequence_tokens)
            
            if not remaining or remaining[0] != "]":
                raise ValueError("Missing closing bracket")
            
            parts.append(Node(
                NodeType.SEQUENCE,
                optional=True,
                parts=sequence_parts
            ).to_dict())
            
            i = len(tokens) - len(remaining) + 1
        elif token == "]":
            # End of optional sequence
            return parts, tokens[i:]
        elif token.isdigit():
            # Field
            count = int(token)
            i += 1
            
            if i < len(tokens) and tokens[i] == "!":
                # Exact count
                i += 1
                if i >= len(tokens):
                    raise ValueError("Expected character set after '!'")
                set_type = tokens[i]
                parts.append(Node(
                    NodeType.FIELD,
                    count=count,
                    set=set_type,
                    exact=True
                ).to_dict())
                i += 1
            elif i < len(tokens) and tokens[i] == "*":
                # Multiple lines
                i += 1
                if i >= len(tokens) or not tokens[i].isdigit():
                    raise ValueError("Expected number after '*'")
                line_count = int(tokens[i])
                i += 1
                if i >= len(tokens):
                    raise ValueError("Expected character set after line count")
                set_type = tokens[i]
                parts.append(Node(
                    NodeType.FIELD,
                    count=line_count,
                    set=set_type,
                    lines=count
                ).to_dict())
                i += 1
            elif i < len(tokens) and tokens[i] in "ndxcaze":
                # Regular field
                set_type = tokens[i]
                parts.append(Node(
                    NodeType.FIELD,
                    count=count,
                    set=set_type
                ).to_dict())
                i += 1
            else:
                raise ValueError(f"Expected field type after {count}")
        else:
            # Literal
            parts.append(Node(
                NodeType.LITERAL,
                value=token
            ).to_dict())
            i += 1
    
    return parts, [] 