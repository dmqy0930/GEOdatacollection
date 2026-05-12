#!/usr/bin/env python3
"""
Step 2: Fetch detailed metadata for each GSE from NCBI GEO via SOFT format.

Outputs:
  - Per-GSE CSV: data/{date}/{GSE}/gse_metadata.csv
  - Combined CSV: output/gse_details_combined.csv

Usage:
  python 02_fetch_gse_details.py --date 20260512
  python 02_fetch_gse_details.py --date 20260512 --output-dir /path/to/data
"""

import argparse
import csv
import os
import re
import sys
import time

import requests

# ── config ────────────────────────────────────────────────────────────
SOFT_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
DELAY = 1.0
MAX_RETRIES = 3
TIMEOUT = 120

# ── CSV columns (combined + per-GSE) ───────────────────────────────────
METADATA_COLS = [
    "GSE_ID",
    "Title",
    "Summary",
    "Status",
    "Organism",
    "Overall_design",
    "Series_type",
    "PMID",
    "PMID_Link",
    "Citation(s)",
    "SuperSeries_of",
    "SubSeries_of",
    "SRA_Run_Selector",
    "BioProject",
]

SAMPLE_COLS = ["GSM", "sample_title", "source_name", "characteristics"]


def fetch_soft(gse_id):
    """Fetch SOFT format text for a GSE accession. Returns iterable of lines."""
    params = {"acc": gse_id, "targ": "all", "form": "text", "view": "quick"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(SOFT_URL, params=params, timeout=TIMEOUT, stream=True)
            if resp.status_code == 404:
                print(f"  [WARN] {gse_id} not found (404)", file=sys.stderr)
                return None
            if resp.status_code == 429:
                wait = 5 * attempt
                print(f"  [WARN] rate-limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()

            ct = resp.headers.get("Content-Type", "")
            if "text/html" in ct:
                body_start = resp.raw.read(200).decode("utf-8", errors="ignore")
                if "<html" in body_start.lower():
                    print(f"  [WARN] {gse_id} returned HTML", file=sys.stderr)
                    return None

            return resp.iter_lines(decode_unicode=True)

        except requests.RequestException as e:
            print(f"  [WARN] {gse_id} attempt {attempt}/{MAX_RETRIES}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)

    return None


def parse_soft_lines(gse_id, lines):
    """Parse SOFT format lines into metadata dict and sample list."""
    data = {
        "gse_id": gse_id,
        "title": "",
        "summary": "",
        "status": "",
        "organism": set(),
        "overall_design": "",
        "series_type": "",
        "pmid": "",
        "pmid_link": "",
        "contributors": [],
        "super_series_of": [],
        "sub_series_of": [],
        "sra_run_selector": "",
        "bioproject": "",
    }
    samples = []

    current_gsm = None
    current_title = None
    current_source = None
    current_chars = []

    for raw_line in lines:
        if raw_line is None:
            continue
        line = raw_line.strip()

        # ── Series-level fields ──────────────────────────────────────
        if line.startswith("!Series_title "):
            data["title"] = _extract_value(line)
        elif line.startswith("!Series_summary "):
            data["summary"] = _extract_value(line)
        elif line.startswith("!Series_status "):
            data["status"] = _extract_value(line)
        elif line.startswith("!Series_overall_design "):
            data["overall_design"] = _extract_value(line)
        elif line.startswith("!Series_type "):
            data["series_type"] = _extract_value(line)
        elif line.startswith("!Series_pubmed_id "):
            pid = _extract_value(line).strip()
            if pid:
                data["pmid"] = pid
                data["pmid_link"] = f"https://pubmed.ncbi.nlm.nih.gov/{pid}"
        elif line.startswith("!Series_contributor "):
            data["contributors"].append(_extract_value(line))
        elif line.startswith("!Series_sample_organism "):
            data["organism"].add(_extract_value(line))
        elif line.startswith("!Series_platform_organism "):
            data["organism"].add(_extract_value(line))
        elif line.startswith("!Series_relation "):
            rel = _extract_value(line)
            if rel.startswith("SuperSeries of:"):
                for g in re.findall(r"GSE\d+", rel):
                    if g not in data["super_series_of"]:
                        data["super_series_of"].append(g)
            elif rel.startswith("SubSeries of:"):
                for g in re.findall(r"GSE\d+", rel):
                    if g not in data["sub_series_of"]:
                        data["sub_series_of"].append(g)
            elif rel.lower().startswith("bioproject:"):
                bp_full = rel.split(":", 1)[-1].strip()
                bp_match = re.search(r"(PRJ[A-Z]{2,3}\d+)", bp_full)
                if bp_match:
                    bp = bp_match.group(1)
                    data["bioproject"] = bp
                    data["sra_run_selector"] = (
                        f"https://www.ncbi.nlm.nih.gov/Traces/study/?acc={bp}"
                    )

        # ── Sample section ───────────────────────────────────────────
        elif line.startswith("^SAMPLE = "):
            # Save previous sample
            if current_gsm is not None:
                samples.append((
                    current_gsm,
                    current_title or "",
                    current_source or "",
                    "; ".join(current_chars) if current_chars else "",
                ))
            current_gsm = line.split("=", 1)[-1].strip()
            current_title = None
            current_source = None
            current_chars = []

        elif line.startswith("!Sample_title ") and current_gsm is not None:
            if current_title is None:
                current_title = _extract_value(line)

        elif line.startswith("!Sample_source_name_ch1 ") and current_gsm is not None:
            if current_source is None:
                current_source = _extract_value(line)

        elif line.startswith("!Sample_characteristics_ch1 ") and current_gsm is not None:
            current_chars.append(_extract_value(line))

        elif line.startswith("!Sample_data_processing "):
            pass  # skip long data processing blocks

    # Save last sample
    if current_gsm is not None:
        samples.append((
            current_gsm,
            current_title or "",
            current_source or "",
            "; ".join(current_chars) if current_chars else "",
        ))

    if not samples:
        print(f"  [WARN] {gse_id}: no samples found in SOFT data", file=sys.stderr)

    return data, samples


def _extract_value(line):
    """Extract value after ' = ' delimiter in a SOFT format line."""
    parts = line.split(" = ", 1)
    value = parts[1].strip() if len(parts) == 2 else ""
    if value.endswith(" more..."):
        value = value[:-7].strip()
    return value


def write_per_gse(data, samples, output_dir):
    """Write per-GSE CSV to data/{date}/{GSE}/gse_metadata.csv."""
    gse_dir = os.path.join(output_dir, data["gse_id"])
    os.makedirs(gse_dir, exist_ok=True)
    filepath = os.path.join(gse_dir, "gse_metadata.csv")

    all_cols = METADATA_COLS + SAMPLE_COLS
    metadata_row = [
        data["gse_id"],
        data["title"],
        data["summary"],
        data["status"],
        "; ".join(sorted(data["organism"])),
        data["overall_design"],
        data["series_type"],
        data["pmid"],
        data["pmid_link"],
        "; ".join(data["contributors"]),
        "; ".join(sorted(data["super_series_of"])),
        "; ".join(sorted(data["sub_series_of"])),
        data["sra_run_selector"],
        data["bioproject"],
    ]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(all_cols)
        if not samples:
            w.writerow(metadata_row + ["", "", "", ""])
        else:
            for j, (gsm, title, source, chars) in enumerate(samples):
                if j == 0:
                    w.writerow(metadata_row + [gsm, title, source, chars])
                else:
                    w.writerow([""] * len(METADATA_COLS) + [gsm, title, source, chars])

    return filepath


def write_combined(all_records, output_path):
    """Write combined CSV (legacy format)."""
    all_cols = METADATA_COLS + ["GSM", "sample_title"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(all_cols)
        for i, (data, samples) in enumerate(all_records):
            metadata = [
                data["gse_id"], data["title"], data["summary"], data["status"],
                "; ".join(sorted(data["organism"])), data["overall_design"],
                data["series_type"], data["pmid"], data["pmid_link"],
                "; ".join(data["contributors"]),
                "; ".join(sorted(data["super_series_of"])),
                "; ".join(sorted(data["sub_series_of"])),
                data["sra_run_selector"], data["bioproject"],
            ]
            if not samples:
                w.writerow(metadata + ["", ""])
            else:
                for j, (gsm, title, _src, _chars) in enumerate(samples):
                    if j == 0:
                        w.writerow(metadata + [gsm, title])
                    else:
                        w.writerow([""] * len(metadata) + [gsm, title])
            if i < len(all_records) - 1:
                w.writerow([])
                w.writerow([])


def main():
    parser = argparse.ArgumentParser(description="Fetch GEO details for each GSE.")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYYMMDD)")
    parser.add_argument("--output-dir", "-o", default=None, help="Data output dir (default: ../data/<date>)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(script_dir, "..")

    if args.output_dir is None:
        data_dir = os.path.join(repo_root, "data", args.date)
    else:
        data_dir = args.output_dir
    os.makedirs(data_dir, exist_ok=True)

    input_file = os.path.join(repo_root, "output", "gse_accessions.txt")
    combined_out = os.path.join(repo_root, "output", "gse_details_combined.csv")

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    with open(input_file, "r") as f:
        gse_list = [line.strip() for line in f if line.strip()]

    print(f"Fetching details for {len(gse_list)} GSE accessions...\n")

    all_records = []
    for idx, gse in enumerate(gse_list):
        print(f"[{idx + 1}/{len(gse_list)}] {gse}...")
        lines = fetch_soft(gse)
        if lines is None:
            print(f"  [SKIP] {gse} — could not fetch", file=sys.stderr)
            continue

        data, samples = parse_soft_lines(gse, lines)
        all_records.append((data, samples))

        per_gse_path = write_per_gse(data, samples, data_dir)
        print(f"  -> {len(samples)} samples → {per_gse_path}")

        if idx < len(gse_list) - 1:
            time.sleep(DELAY)

    # Write combined legacy output
    os.makedirs(os.path.dirname(combined_out), exist_ok=True)
    write_combined(all_records, combined_out)
    total = sum(len(s[1]) for s in all_records)
    print(f"\nDone. {len(all_records)} GSEs, {total} samples → {combined_out}")


if __name__ == "__main__":
    main()
