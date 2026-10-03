"""
Swift Parser Python package

A Python parser for ISO 15022 messages used for messaging in securities trading
by the SWIFT network.
"""

__version__ = "0.5.0"

from .swift_parser import SwiftParser

__all__ = ["SwiftParser"]