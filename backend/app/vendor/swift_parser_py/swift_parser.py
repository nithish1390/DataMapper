import os
import json
import sys
import threading
import time
from typing import Dict, Any, Optional, Callable, List

from .parsers.fin_parser import FinParser
from .parsers.mt_parser import MtParser
from .parsers.block1_parser import parse as block1_parse
from .parsers.block2_parser import parse as block2_parse
from .parsers.block3_parser import parse as block3_parse
from .parsers.block5_parser import parse as block5_parse
from .utils.field_regexp_factory import FieldParser

class TimeoutException(Exception):
    """Exception raised when parsing exceeds time limit"""
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

def split_messages(content: str, delimiter: str = '$') -> List[str]:
    """
    Split content into individual SWIFT messages using specified delimiter
    
    Args:
        content: Raw content that may contain multiple messages
        delimiter: Message delimiter character (default: '$')
        
    Returns:
        List of individual message strings
    """
    if not content.strip():
        return []
    
    # Split by delimiter and clean up messages
    messages = content.split(delimiter)
    cleaned_messages = []
    
    for msg in messages:
        msg = msg.strip()
        if msg:  # Only include non-empty messages
            # Ensure message starts with {1: and ends with -} or }
            if '{1:' in msg and (msg.rstrip().endswith('-}') or msg.rstrip().endswith('}')):
                cleaned_messages.append(msg)
            elif msg:  # Include even malformed messages for error handling
                cleaned_messages.append(msg)
    
    return cleaned_messages

class SwiftParser:
    def __init__(self, field_patterns=None):
        self.field_patterns = field_patterns
        if not field_patterns:
            # Get the directory of the current file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            patterns_path = os.path.join(current_dir, 'metadata', 'patterns.json')
            with open(patterns_path, 'r') as file:
                self.field_patterns = json.load(file)

        self.field_parser = FieldParser(self.field_patterns)

    def process(self, swift_message: str, timeout_seconds: int = 30) -> Dict[str, Any]:
        """Process a SWIFT message and return its AST (Abstract Syntax Tree)"""
        def _process_message():
            # Parse the complete message structure
            ast = FinParser.parse(swift_message, timeout_seconds)

            # Parse the individual blocks
            ast["block1"] = block1_parse(ast["block1"]["content"][0])
            ast["block2"] = block2_parse(ast["block2"]["content"][0])

            # Parse Block 3 (User Header) if present
            if "block3" in ast:
                # Block 3 is optional - simplify by just passing the content
                ast["block3"] = block3_parse(ast["block3"])

            # Parse the message fields in block4
            ast["block4"]["fields"] = MtParser.parse(ast["block4"]["content"][0], timeout_seconds)

            # Parse each field's content
            for field in ast["block4"]["fields"]:
                field_code = field["type"] + (field.get("option", "") or "")
                parsed_field = self.field_parser.parse(field_code, field["fieldValue"])
                field["ast"] = parsed_field

            # Parse Block 5 (Trailer) if present
            if "block5" in ast:
                # Block 5 is optional - simplify by just passing the content
                ast["block5"] = block5_parse(ast["block5"])

                # Ensure detailed parsing of trailer fields
                from .parsers.block5_parser import parse_trailer_fields
                parse_trailer_fields(ast["block5"])

            return ast
        
        # Use cross-platform timeout implementation
        return run_with_timeout(_process_message, timeout=timeout_seconds)

    def parse(self, swift_message: str, callback: Callable[[Optional[Exception], Optional[Dict[str, Any]]], None], timeout_seconds: int = 30) -> None:
        """Parse a SWIFT message and invoke the callback with the result"""
        try:
            ast = self.process(swift_message, timeout_seconds)
            callback(None, ast)
        except Exception as e:
            callback(e, None)
    
    def process_multiple(self, content: str, delimiter: str = '$', timeout_seconds: int = 30) -> List[Dict[str, Any]]:
        """
        Process multiple SWIFT messages separated by a delimiter
        
        Args:
            content: Raw content containing multiple messages
            delimiter: Message delimiter character (default: '$')
            timeout_seconds: Maximum time allowed per message
            
        Returns:
            List of parsed message ASTs
        """
        messages = split_messages(content, delimiter)
        results = []
        
        for i, message in enumerate(messages):
            try:
                result = self.process(message, timeout_seconds)
                results.append(result)
            except Exception as e:
                # Add error information to results
                error_result = {
                    "error": str(e),
                    "message_index": i,
                    "raw_message": message[:200] + "..." if len(message) > 200 else message
                }
                results.append(error_result)
        
        return results
    
    def parse_multiple(self, content: str, callback: Callable[[Optional[Exception], Optional[List[Dict[str, Any]]]], None], delimiter: str = '$', timeout_seconds: int = 30) -> None:
        """
        Parse multiple SWIFT messages and invoke the callback with the results
        
        Args:
            content: Raw content containing multiple messages
            callback: Function to call with results or error
            delimiter: Message delimiter character (default: '$')
            timeout_seconds: Maximum time allowed per message
        """
        try:
            results = self.process_multiple(content, delimiter, timeout_seconds)
            callback(None, results)
        except Exception as e:
            callback(e, None)


def main():
    """Command-line entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='SWIFT Message Parser')
    parser.add_argument('file', help='Path to SWIFT message file')
    parser.add_argument('-m', '--multi', action='store_true',
                       help='Process multiple messages separated by $ delimiter')
    parser.add_argument('-d', '--delimiter', default='$',
                       help='Message delimiter for multi-message mode (default: $)')
    parser.add_argument('-t', '--timeout', type=int, default=30,
                       help='Timeout in seconds for parsing (default: 30)')
    parser.add_argument('-o', '--output', choices=['json', 'pretty'], default='pretty',
                       help='Output format (default: pretty)')
    
    args = parser.parse_args()
    
    try:
        with open(args.file, 'r', encoding='ascii') as file:
            content = file.read()

        swift_parser = SwiftParser()

        if args.multi:
            # Multi-message processing mode
            def multi_callback(err, results):
                if err:
                    print(f"Error processing messages: {err}", file=sys.stderr)
                    sys.exit(1)
                
                if args.output == 'json':
                    print(json.dumps(results, indent=2))
                else:
                    for i, result in enumerate(results):
                        print(f"\n=== MESSAGE {i+1} ===")
                        if 'error' in result:
                            print(f"Error: {result['error']}")
                            print(f"Raw message: {result.get('raw_message', 'N/A')}")
                        else:
                            print(json.dumps(result, indent=2))
            
            swift_parser.parse_multiple(content, multi_callback, args.delimiter, args.timeout)
        else:
            # Single message processing mode
            def callback(err, ast):
                if err:
                    print(f"Error: {err}", file=sys.stderr)
                    sys.exit(1)
                
                if args.output == 'json':
                    print(json.dumps(ast, indent=2))
                else:
                    print("=== PARSED SWIFT MESSAGE ===")
                    print(json.dumps(ast, indent=2))
            
            swift_parser.parse(content, callback, args.timeout)
    
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found", file=sys.stderr)
        sys.exit(1)
    except TimeoutException as e:
        print(f"Error: Parsing timed out after {args.timeout} seconds", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()