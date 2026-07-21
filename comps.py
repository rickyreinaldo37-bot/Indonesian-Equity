"""CLI entry point: build the sector comps workbook.

    python refresh.py && python comps.py
"""
import sys

from src.comps import main

if __name__ == "__main__":
    sys.exit(main())
