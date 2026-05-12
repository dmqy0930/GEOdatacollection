#!/usr/bin/env python3
"""
Step 1: Extract unique GSE accession numbers from a GEO results text file.

Usage:
  python 01_extract_gse.py <input.txt>
  python 01_extract_gse.py <input.txt> --output-dir /path/to/output
"""

import argparse
import os
import re
import sys

GSE_PATTERN = re.compile(r'GSE\d{4,}')


def extract_gse(filepath):
    """Extract unique GSE accession numbers from a file."""
    gse_set = set()
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            gse_set.update(GSE_PATTERN.findall(line))
    return sorted(gse_set)


def main():
    parser = argparse.ArgumentParser(
        description="Extract unique GSE accession numbers from GEO results text."
    )
    parser.add_argument(
        "input_file", nargs="?", default=None,
        help="Path to GEO results txt file"
    )
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="Output directory (default: ../output relative to this script)"
    )
    args = parser.parse_args()

    if not args.input_file:
        print("Error: provide an input txt file", file=sys.stderr)
        parser.print_usage()
        sys.exit(1)

    if not os.path.exists(args.input_file):
        print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    # Default output dir: GEOdatacollection/output/
    if args.output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        args.output_dir = os.path.join(script_dir, "..", "output")

    os.makedirs(args.output_dir, exist_ok=True)
    output_file = os.path.join(args.output_dir, "gse_accessions.txt")

    gse_list = extract_gse(args.input_file)

    print(f"Found {len(gse_list)} unique GSE accession numbers from:\n  {args.input_file}\n")
    for gse in gse_list:
        print(f"  {gse}")

    with open(output_file, 'w') as f:
        f.write('\n'.join(gse_list) + '\n')

    print(f"\nSaved to: {output_file}")


if __name__ == '__main__':
    main()
