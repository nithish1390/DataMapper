import re
from typing import Dict, Any, Union

def parse(input_data: Union[str, Dict, Any]) -> Dict[str, Any]:
    """
    Parse Block 5 (Trailer) of a SWIFT message

    Block 5 is the trailer block that contains service information.
    Common tags include:
    - CHK: Checksum (mandatory)
    - TNG: Test & Training Message (optional)
    - PDE: Possible Duplicate Emission (optional)
    - DLM: Delayed Message (optional)
    - MRF: Message Reference (optional)
    - PDM: Possible Duplicate Message (optional)
    - SYS: System Originated Message (optional)

    Args:
        input_data: The data of Block 5, could be:
            - A string (raw input)
            - A dictionary (pre-parsed by FinParser)
            - Any other format from FinParser

    Returns:
        Dictionary with parsed data
    """
    result = {
        "block_id": 5,
        "tags": {}
    }

    # Check if we have a full block structure from FinParser
    if isinstance(input_data, dict) and "name" in input_data and input_data["name"] == "5":
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

                    # Ensure empty values are stored as empty strings, not empty lists
                    if isinstance(tag_value, list) and not tag_value:
                        tag_value = ""
                    elif isinstance(tag_value, str) and not tag_value.strip():
                        tag_value = ""

                    result["tags"][tag_name] = tag_value

        return result

    # Handle raw string input
    elif isinstance(input_data, str):
        result["content"] = input_data

        # Parse the tags in Block 5
        # The format is typically {TAG:value}
        tag_pattern = re.compile(r'\{([A-Z]+):([^}]*)\}')
        tags = tag_pattern.findall(input_data)

        for tag, value in tags:
            # Ensure empty values are stored as empty strings, not empty lists
            result["tags"][tag] = value.strip() if value.strip() else ""

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

                # Ensure empty values are stored as empty strings, not empty lists
                if isinstance(tag_value, list) and not tag_value:
                    tag_value = ""
                elif isinstance(tag_value, str) and not tag_value.strip():
                    tag_value = ""

                result["tags"][tag_name] = tag_value

    # Parse specific trailer fields
    parse_trailer_fields(result)

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

    # Look for patterns like "CHK:123456789ABC" or just simple values
    tag_value_pattern = re.compile(r'([A-Z]+):([^\n]+)')
    matches = tag_value_pattern.findall(text)

    if matches:
        for tag, value in matches:
            items[tag] = value.strip()

    return items

def parse_trailer_fields(result: Dict[str, Any]) -> None:
    """
    Parse specific trailer fields and add structured data

    Args:
        result: The result dictionary to update with parsed fields
    """
    tags = result.get("tags", {})

    # Parse CHK (Checksum) - Mandatory
    if "CHK" in tags:
        # No additional parsing needed for checksum
        pass

    # Parse TNG (Test & Training) - Optional
    if "TNG" in tags:
        # TNG is typically empty, just indicates test mode
        pass

    # Parse PDE (Possible Duplicate Emission) - Optional
    if "PDE" in tags:
        pde_value = tags["PDE"]
        if pde_value:
            # Format: {PDE:1348120811BANKFRPPAXXX2222123456}
            # Time (4 chars) + Date (6 chars) + BIC (12 chars) + Session (4 chars) + Sequence (6 chars)
            pde_pattern = re.compile(r'(\d{4})(\d{6})([A-Z0-9]{12})(\d{4})(\d{6})')
            match = pde_pattern.match(pde_value)

            if match:
                result["pde_details"] = {
                    "time": match.group(1),
                    "date": match.group(2),
                    "bic": match.group(3),
                    "session_number": match.group(4),
                    "sequence_number": match.group(5)
                }

    # Parse DLM (Delayed Message) - Optional
    if "DLM" in tags:
        # DLM is typically empty, just indicates delayed message
        pass

    # Parse MRF (Message Reference) - Optional
    if "MRF" in tags:
        mrf_value = tags["MRF"]
        if mrf_value:
            # Format: {MRF:1806271539180626BANKFRPPAXXX2222123456}
            # Date (6 chars) + Time (4 chars) + Original message date (6 chars) + BIC (12 chars) + Session (4 chars) + Sequence (6 chars)
            mrf_pattern = re.compile(r'(\d{6})(\d{4})(\d{6})([A-Z0-9]{12})(\d{4})(\d{6})')
            match = mrf_pattern.match(mrf_value)

            if match:
                result["mrf_details"] = {
                    "date": match.group(1),
                    "time": match.group(2),
                    "original_date": match.group(3),
                    "bic": match.group(4),
                    "session_number": match.group(5),
                    "sequence_number": match.group(6)
                }

    # Parse PDM (Possible Duplicate Message) - Optional
    if "PDM" in tags:
        pdm_value = tags["PDM"]
        if pdm_value:
            # Format: {PDM:1213120811BANKFRPPAXXX2222123456}
            # Time (4 chars) + Date (6 chars) + BIC (12 chars) + Session (4 chars) + Sequence (6 chars)
            pdm_pattern = re.compile(r'(\d{4})(\d{6})([A-Z0-9]{12})(\d{4})(\d{6})')
            match = pdm_pattern.match(pdm_value)

            if match:
                result["pdm_details"] = {
                    "time": match.group(1),
                    "date": match.group(2),
                    "bic": match.group(3),
                    "session_number": match.group(4),
                    "sequence_number": match.group(5)
                }

    # Parse SYS (System Originated Message) - Optional
    if "SYS" in tags:
        sys_value = tags["SYS"]
        if sys_value:
            # Format: {SYS:1454120811BANKFRPPAXXX2222123456}
            # Time (4 chars) + Date (6 chars) + BIC (12 chars) + Session (4 chars) + Sequence (6 chars)
            sys_pattern = re.compile(r'(\d{4})(\d{6})([A-Z0-9]{12})(\d{4})(\d{6})')
            match = sys_pattern.match(sys_value)

            if match:
                result["sys_details"] = {
                    "time": match.group(1),
                    "date": match.group(2),
                    "bic": match.group(3),
                    "session_number": match.group(4),
                    "sequence_number": match.group(5)
                }
