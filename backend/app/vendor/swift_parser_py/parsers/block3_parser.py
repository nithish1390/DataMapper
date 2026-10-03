import re
from typing import Dict, Any, List, Union

def parse(input_data: Union[str, Dict, List]) -> Dict[str, Any]:
    """
    Parse Block 3 (User Header) of a SWIFT message
    
    Block 3 is optional and contains various header fields with tags.
    Common tags include:
    - 103: Service Identifier (for FINCopy)
    - 108: Message User Reference 
    - 113: Banking Priority
    - 119: Validation Flag
    - 121: Unique End-to-End Transaction Reference
    
    Args:
        input_data: The data of Block 3, could be:
            - A string (raw input)
            - A dictionary (pre-parsed by FinParser)
            - A list (pre-processed content from FinParser)
        
    Returns:
        Dictionary with parsed data
    """
    result = {
        "block_id": 3,
        "tags": {}
    }
    
    # Check if we have a full block structure from FinParser
    if isinstance(input_data, dict) and "name" in input_data and input_data["name"] == "3":
        result["content"] = input_data.get("content", [])
        
        # Process the content items which are individual tags
        if isinstance(result["content"], list):
            for item in result["content"]:
                if isinstance(item, dict) and "name" in item and "content" in item:
                    tag_name = item["name"]
                    
                    # Get the actual tag value
                    if isinstance(item["content"], list) and item["content"]:
                        tag_value = item["content"][0]
                    else:
                        tag_value = item["content"]
                    
                    result["tags"][tag_name] = tag_value
        
        return result
    
    # Handle raw string input (uncommon but supported)
    elif isinstance(input_data, str):
        result["content"] = input_data
        
        # Parse the tags in Block 3
        # The format is typically {tag}:{value}
        tag_pattern = re.compile(r'\{(\d+):([^}]*)\}')
        tags = tag_pattern.findall(input_data)
        
        for tag, value in tags:
            result["tags"][tag] = value.strip()
        
        # If no tags match the expected pattern, try another format
        if not result["tags"]:
            block_items = extract_block_items(input_data)
            if block_items:
                result["tags"] = block_items
    
    # Handle case where input is a list of pre-parsed blocks
    elif isinstance(input_data, list):
        result["content"] = input_data
        
        # Process each item in the list which might be a tag
        for item in input_data:
            if isinstance(item, dict) and "name" in item:
                tag_name = item["name"]
                
                # Extract the value from content
                if isinstance(item.get("content"), list) and item["content"]:
                    tag_value = item["content"][0]
                else:
                    tag_value = item.get("content", "")
                    
                result["tags"][tag_name] = tag_value
    
    return result

def extract_block_items(text: str) -> Dict[str, str]:
    """
    Extract tag-value pairs from a differently formatted block content
    
    This handles cases where the block might be pre-processed or in a different format
    
    Args:
        text: The input text to parse
        
    Returns:
        Dictionary of tag-value pairs
    """
    items = {}
    
    # Look for patterns like "103:TESTVALUE" or just simple values
    tag_value_pattern = re.compile(r'(\d+):([^\n]+)')
    matches = tag_value_pattern.findall(text)
    
    if matches:
        for tag, value in matches:
            items[tag] = value.strip()
    
    return items 