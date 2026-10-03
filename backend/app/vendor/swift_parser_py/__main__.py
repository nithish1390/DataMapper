#!/usr/bin/env python3
"""
SWIFT Parser CLI Entry Point

This module provides the command-line interface for the SWIFT parser.
It handles module import warnings and provides a clean entry point.
"""

import sys
import os

# Add the parent directory to the path to ensure proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swift_parser_py.swift_parser import main

if __name__ == "__main__":
    # Run the main CLI function
    main()