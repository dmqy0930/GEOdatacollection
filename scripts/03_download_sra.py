#!/usr/bin/env python3
"""
Step 3: Download SraRunTable (runinfo) for each BioProject from NCBI SRA.

Reads the combined GEO metadata CSV, extracts unique BioProjects,
downloads the SraRunTable CSV via E-utilities, and saves to
data/{date}/{GSE}/sra_runinfo.csv.

Usage:
  python 03_download_sra.py --date 20260512
  python 03_download_sra.py --date 20260512 --output-dir /path/to/data
"""

import argparse
import csv
import os
import re
import sys
import time

import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DELAY = 0.5
MAX_RETRIES = 3
TIMEOUT = 120


def esearch_sra(bioproject):
    """Search SRA for a BioProject, return list of UIDs."""
    url = f"{EUTILS_BASE}/esearch.fcgi"
    params = {
        "db": "sra",
        "term": bioproject,
        "retmode": "json",
        "retmax": 100000,
        "usehistory": "y",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 429:
                time.sleep(5 * attempt)
                continue
            resp.raise_for_status()
            result = resp.json()
            es = result["esearchresult"]
            return es.get("idlist", []), es.get("webenv"), es.get("querykey")
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"  [WARN] esearch failed for {bioproject}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return [], None, None


def efetch_runinfo(query_key, webenv, retstart=0, retmax=10000):
    """Fetch runinfo CSV using history server."""
    url = f"{EUTILS_BASE}/efetch.fcgi"
    params = {
        "db": "sra",
        "query_key": query_key,
        "WebEnv": webenv,
        "rettype": "runinfo",
        "retmode": "text",
        "retstart": retstart,
        "retmax": retmax,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 429:
                time.sleep(5 * attempt)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  [WARN] efetch failed: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def download_sra(bioproject):
    """Download SraRunTable for a BioProject. Returns CSV text or None."""
    uids, webenv, query_key = esearch_sra(bioproject)
    if not uids:
        print(f"  [WARN] {bioproject}: no SRA records found", file=sys.stderr)
        return None

    count = len(uids)
    # For large result sets, fetch in batches
    if count <= 10000:
        text = efetch_runinfo(query_key, webenv, retmax=count)
        return text
    else:
        # Fetch in batches of 10000
        all_lines = []
        for start in range(0, count, 10000):
            batch = efetch_runinfo(query_key, webenv, retstart=start, retmax=10000)
            if batch is None:
                return None
            lines = batch.strip().split("\n")
            if start == 0:
                all_lines.extend(lines)
            else:
                all_lines.extend(lines[1:])  # skip duplicate header
            time.sleep(DELAY)
        return "\n".join(all_lines)


def read_bioproject_gse_map(combined_csv_path):
    """Read combined CSV, return dict: bioproject -> list of GSEs."""
    bp_map = {}
    with open(combined_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bp = row.get("BioProject", "").strip()
            gse = row.get("GSE_ID", "").strip()
            if bp and gse:
                bp_map.setdefault(bp, set()).add(gse)
    return {k: list(v) for k, v in bp_map.items()}


def main():
    parser = argparse.ArgumentParser(description="Download SraRunTable for each BioProject.")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYYMMDD)")
    parser.add_argument("--output-dir", "-o", default=None, help="Data output dir")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(script_dir, "..")

    if args.output_dir is None:
        data_dir = os.path.join(repo_root, "data", args.date)
    else:
        data_dir = args.output_dir

    combined_csv = os.path.join(repo_root, "output", "gse_details_combined.csv")
    if not os.path.exists(combined_csv):
        print(f"Error: combined CSV not found: {combined_csv}", file=sys.stderr)
        print("Run 02_fetch_gse_details.py first.", file=sys.stderr)
        sys.exit(1)

    bp_gse_map = read_bioproject_gse_map(combined_csv)
    bioprojects = sorted(bp_gse_map.keys())

    print(f"Downloading SRA metadata for {len(bioprojects)} BioProjects...\n")

    for idx, bp in enumerate(bioprojects):
        gse_list = bp_gse_map[bp]
        print(f"[{idx + 1}/{len(bioprojects)}] {bp} (GSEs: {', '.join(gse_list)})...")

        text = download_sra(bp)
        if text is None:
            print(f"  [SKIP] {bp} — download failed", file=sys.stderr)
            continue

        # Save to each GSE directory that uses this BioProject
        for gse in gse_list:
            gse_dir = os.path.join(data_dir, gse)
            os.makedirs(gse_dir, exist_ok=True)
            filepath = os.path.join(gse_dir, "sra_runinfo.csv")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"  -> saved to {filepath}")

        if idx < len(bioprojects) - 1:
            time.sleep(DELAY)

    print(f"\nDone. {len(bioprojects)} BioProjects processed.")


if __name__ == "__main__":
    main()
