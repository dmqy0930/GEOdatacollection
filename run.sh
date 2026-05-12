#!/bin/bash
# GEOdatacollection — Full pipeline
#
# Usage:
#   # From a GEO search query (auto-download results)
#   ./run.sh --query '(((eCLIP) AND Homo sapiens[Organism]) AND ("2022/07/01"[Publication Date]))'
#
#   # From an existing txt file
#   ./run.sh /path/to/existing_results.txt
#
#   # With custom output directory
#   ./run.sh --query '...' /path/to/output_dir
#   ./run.sh input.txt /path/to/output_dir
#
# Steps:
#   0. (if --query) Search GEO and download results txt
#   1. Extract GSE accessions from txt
#   2. Fetch per-GSE metadata from NCBI GEO
#   3. Download SraRunTable for each BioProject
#   4. Generate 15-column summary CSV

set -e

DATE=$(date +%Y%m%d)
SCRIPT_DIR="$(cd "$(dirname "$0")/scripts" && pwd)"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT_FILE=""
QUERY=""
OUTPUT_DIR=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --query|-q)
            QUERY="$2"
            shift 2
            ;;
        -h|--help)
            head -30 "$0" | tail -18
            exit 0
            ;;
        *)
            if [ -z "$INPUT_FILE" ]; then
                INPUT_FILE="$1"
            elif [ -z "$OUTPUT_DIR" ]; then
                OUTPUT_DIR="$1"
            fi
            shift
            ;;
    esac
done

# Validate input
if [ -z "$INPUT_FILE" ] && [ -z "$QUERY" ]; then
    echo "Error: provide an input txt file or use --query"
    echo "Usage:"
    echo "  ./run.sh /path/to/input.txt"
    echo "  ./run.sh --query 'GEO search query'"
    exit 1
fi

OUTPUT_DIR="${OUTPUT_DIR:-$REPO_DIR/data/$DATE}"

echo "========================================="
echo "GEOdatacollection Pipeline"
echo "Date: $DATE"
echo "Output: $OUTPUT_DIR"
echo "========================================="
echo ""

# Step 0: Search GEO (if query provided)
if [ -n "$QUERY" ]; then
    echo "=== Step 0: Search GEO ==="
    SEARCH_OUTPUT="$REPO_DIR/output/geo_search_results.txt"
    python3 "$SCRIPT_DIR/00_search_geo.py" "$QUERY" --output "$SEARCH_OUTPUT"
    INPUT_FILE="$SEARCH_OUTPUT"
    echo ""
fi

# Step 1
echo "=== Step 1: Extract GSE accessions ==="
echo "Input: $INPUT_FILE"
python3 "$SCRIPT_DIR/01_extract_gse.py" "$INPUT_FILE" --output-dir "$REPO_DIR/output"
echo ""

# Step 2
echo "=== Step 2: Fetch GSE metadata ==="
python3 "$SCRIPT_DIR/02_fetch_gse_details.py" --date "$DATE" --output-dir "$OUTPUT_DIR"
echo ""

# Step 3
echo "=== Step 3: Download SRA metadata ==="
python3 "$SCRIPT_DIR/03_download_sra.py" --date "$DATE" --output-dir "$OUTPUT_DIR"
echo ""

# Step 4
echo "=== Step 4: Generate summary CSV ==="
python3 "$SCRIPT_DIR/04_generate_summary.py" --date "$DATE" --output-dir "$OUTPUT_DIR"
echo ""

echo "========================================="
echo "Pipeline complete!"
echo "Output directory: $OUTPUT_DIR"
echo "Summary CSV: $OUTPUT_DIR/summary.csv"
echo "========================================="
