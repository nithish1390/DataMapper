import re
from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class Block1:
    """Class for storing Block 1 data"""
    block_id: int = 1
    content: str = None
    application_id: str = None
    service_id: str = None
    receiving_lt_id: str = None
    session_number: str = None
    sequence_number: str = None

def parse(input_text: str) -> Dict[str, Any]:
    """
    Parse Block 1 of a SWIFT message
    
    Args:
        input_text: The content of Block 1
        
    Returns:
        Dictionary with parsed Block 1 data
    """
    result = Block1()
    result.content = input_text
    
    pattern = re.compile(r'(.)(..)(............)(....)(.*)')
    match = pattern.match(input_text)
    
    if match:
        result.application_id = match.group(1)
        result.service_id = match.group(2)
        result.receiving_lt_id = match.group(3)
        result.session_number = match.group(4)
        result.sequence_number = match.group(5)
    
    # Convert dataclass to dictionary for JSON serialization
    return asdict(result) 