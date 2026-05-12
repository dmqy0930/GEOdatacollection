#!/usr/bin/env python3
"""
Step 4: Generate a comprehensive 15-column summary CSV from all per-GSE data.

Reads data/{date}/{GSE}/gse_metadata.csv and sra_runinfo.csv,
merges on GSM=Sample, looks up PMID metadata, and outputs summary.

Usage:
  python 04_generate_summary.py --date 20260512
  python 04_generate_summary.py --date 20260512 --output-dir /path/to/data
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict

import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DELAY = 0.5
MAX_RETRIES = 3

# ── Summary CSV columns ────────────────────────────────────────────────
SUMMARY_COLS = [
    "GSE",
    "SRP",
    "SRR",
    "data_publication_year",
    "data_collected_date",
    "is_single_end",
    "sample_title",
    "GSM",
    "cell_line_tissue",
    "是否有其他干扰",
    "数据类型",
    "相关的其他GSE数据",
    "PMID期刊名称",
    "发表年度",
    "文献标题",
]

# Known cell line patterns for extraction
CELL_LINE_PATTERNS = [
    r'\b(HEK293T?)\b', r'\b(HeLa)\b', r'\b(K562)\b', r'\b(MOLM13)\b',
    r'\b(Jurkat)\b', r'\b(HCT116)\b', r'\b(U2OS)\b', r'\b(HepG2)\b',
    r'\b(A549)\b', r'\b(MCF7)\b', r'\b(MDA[-\s]MB[-\s]?\d+)\b',
    r'\b(PC[-\s]?3)\b', r'\b(LNCaP)\b', r'\b(DU145)\b', r'\b(THP[-\s]?1)\b',
    r'\b(U937)\b', r'\b(NIH[-\s]?3T3)\b', r'\b(COS[-\s]?7)\b',
    r'\b(CHO)\b', r'\b(S2)\b', r'\b(GM12878)\b', r'\b(NALM6)\b',
    r'\b(697)\b', r'\b(Reh)\b', r'\b(HG3)\b', r'\b(TMD8)\b', r'\b(iSLK)\b',
    r'\b(iPSC)\b', r'\b(NSC)\b', r'\b(ES[-\s]?cell)\b', r'\b(fibroblast)\b',
    r'\b(myeloid)\b', r'\b(lymphoid)\b', r'\b(neural)\b', r'\b(embryonic)\b',
]

# Perturbation keywords for 是否有其他干扰
# Perturbation keyword groups for detailed classification
PERTURB_GROUPS = [
    (re.compile(r'\bsi\w+', re.IGNORECASE), 'siRNA'),
    (re.compile(r'\bsh\w+', re.IGNORECASE), 'shRNA'),
    (re.compile(r'\bsg\w+', re.IGNORECASE), 'sgRNA'),
    (re.compile(r'\bshRNA\b', re.IGNORECASE), 'shRNA'),
    (re.compile(r'\bsiRNA\b', re.IGNORECASE), 'siRNA'),
    (re.compile(r'\bsgRNA\b', re.IGNORECASE), 'sgRNA'),
    (re.compile(r'\bKO\b', re.IGNORECASE), 'knockout'),
    (re.compile(r'\bKD\b', re.IGNORECASE), 'knockdown'),
    (re.compile(r'knock\s*out', re.IGNORECASE), 'knockout'),
    (re.compile(r'knock\s*down', re.IGNORECASE), 'knockdown'),
    (re.compile(r'\bCRISPR\b', re.IGNORECASE), 'CRISPR'),
    (re.compile(r'\bCas9\b', re.IGNORECASE), 'CRISPR'),
    (re.compile(r'over\s*expression|overexpression', re.IGNORECASE), 'overexpression'),
    (re.compile(r'\bOE\b', re.IGNORECASE), 'overexpression'),
    (re.compile(r'\bDMSO\b', re.IGNORECASE), 'DMSO'),
    (re.compile(r'Venetoclax', re.IGNORECASE), 'Venetoclax'),
    (re.compile(r'sodium\s*butyrate', re.IGNORECASE), 'sodium butyrate'),
    (re.compile(r'doxycycline', re.IGNORECASE), 'doxycycline'),
]


def read_metadata(metadata_path):
    """Read per-GSE metadata CSV, return (gse_meta dict, sample list)."""
    gse_meta = {}
    samples = []
    with open(metadata_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gse_id = row.get("GSE_ID", "").strip()
            if gse_id and not gse_meta:
                gse_meta = {
                    "gse_id": gse_id,
                    "title": row.get("Title", ""),
                    "status": row.get("Status", ""),
                    "overall_design": row.get("Overall_design", ""),
                    "series_type": row.get("Series_type", ""),
                    "pmid": row.get("PMID", ""),
                    "pmid_link": row.get("PMID_Link", ""),
                    "super_series_of": row.get("SuperSeries_of", ""),
                    "sub_series_of": row.get("SubSeries_of", ""),
                }
            gsm = row.get("GSM", "").strip()
            if gsm:
                samples.append({
                    "gsm": gsm,
                    "sample_title": row.get("sample_title", "").strip(),
                    "source_name": row.get("source_name", "").strip(),
                    "characteristics": row.get("characteristics", "").strip(),
                })
    return gse_meta, samples


def read_sra(sra_path):
    """Read SraRunTable, return dict: GSM -> list of run rows.
    The GSM may be in 'LibraryName' or 'SampleName' column."""
    sra_data = defaultdict(list)
    if not os.path.exists(sra_path):
        return sra_data
    with open(sra_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gsm = row.get("LibraryName", "").strip()
            if not gsm:
                gsm = row.get("SampleName", "").strip()
            if gsm:
                sra_data[gsm].append(row)
    return sra_data


def fetch_pubmed_batch(pmids):
    """Batch-fetch PubMed metadata. Returns dict: pmid -> {source, pubdate, title}."""
    if not pmids:
        return {}

    pmid_list = list(pmids)
    results = {}
    # Batch by 200 PMIDs per request
    for i in range(0, len(pmid_list), 200):
        batch = pmid_list[i:i + 200]
        batch_str = ",".join(batch)
        url = f"{EUTILS_BASE}/esummary.fcgi"
        params = {"db": "pubmed", "id": batch_str, "retmode": "json"}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(url, params=params, timeout=60)
                if resp.status_code == 429:
                    time.sleep(5 * attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                for uid, info in data.get("result", {}).items():
                    if uid == "uids":
                        continue
                    results[uid] = {
                        "source": info.get("source", ""),
                        "pubdate": info.get("pubdate", ""),
                        "title": info.get("title", ""),
                    }
                break
            except (requests.RequestException, KeyError, ValueError) as e:
                print(f"  [WARN] PubMed batch failed: {e}", file=sys.stderr)
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)
        if i + 200 < len(pmid_list):
            time.sleep(DELAY)
    return results


def extract_year_from_status(status):
    """Extract year from 'Public on Oct 28 2022'."""
    m = re.search(r'(\d{4})', status)
    return m.group(1) if m else ""


def extract_cell_line(source_name, characteristics):
    """Extract cell line / tissue from source_name and characteristics."""
    combined = f"{source_name} {characteristics}"

    # Try known cell line patterns
    for pat in CELL_LINE_PATTERNS:
        m = re.search(pat, combined, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Try characteristics key-value pairs
    kv_pattern = re.compile(r'cell\s*(type|line|source)\s*:\s*(.+?)(?:;|$)', re.IGNORECASE)
    m = kv_pattern.search(characteristics)
    if m:
        return m.group(2).strip()

    # Try tissue patterns
    tissue_pattern = re.compile(r'tissue\s*:\s*(.+?)(?:;|$)', re.IGNORECASE)
    m = tissue_pattern.search(characteristics)
    if m:
        return m.group(1).strip()

    # Fallback: source_name
    if source_name:
        return source_name
    return ""


def check_perturbation(sample_title, characteristics):
    """Return comma-separated normalized perturbation keywords."""
    combined = f"{sample_title} {characteristics}"
    found = []
    seen = set()
    for pattern, label in PERTURB_GROUPS:
        if pattern.search(combined) and label not in seen:
            found.append(label)
            seen.add(label)
    return ", ".join(found)


def _format_release_date(release_dates):
    """Format SRA ReleaseDate to YYYY/MM/DD."""
    if not release_dates:
        return ""
    formatted = set()
    for d in sorted(release_dates):
        date_part = d.strip().split(" ")[0].split("T")[0]  # keep YYYY-MM-DD only
        formatted.add(date_part.replace("-", "/"))
    return "; ".join(sorted(formatted))


def classify_data_type(library_strategy, series_type, overall_design):
    """Determine data type from SRA strategy or SOFT type."""
    strategy_map = {
        'RNA-Seq': 'RNA-seq',
        'RIP-Seq': 'CLIP-seq',
        'ChIP-Seq': 'ChIP-seq',
        'miRNA-Seq': 'small RNA-seq',
        'ncRNA-Seq': 'small RNA-seq',
        'ATAC-seq': 'ATAC-seq',
        'WGS': 'WGS',
        'WES': 'WES',
        'Bisulfite-Seq': 'Bisulfite-Seq',
    }
    if library_strategy and library_strategy in strategy_map:
        return strategy_map[library_strategy]

    # 'OTHER' or unknown strategy → check SOFT type and overall_design
    type_lower = (series_type or "").lower()
    od_lower = (overall_design or "").lower()

    if "expression profiling" in type_lower:
        return "RNA-seq"
    if "genome binding" in type_lower:
        return "ChIP-seq"
    if "non-coding rna" in type_lower:
        return "small RNA-seq"
    if "methylation" in type_lower:
        return "Methylation profiling"

    # Derive from overall_design keywords
    if "eclip" in od_lower or "clip" in od_lower or "rip" in od_lower:
        return "CLIP-seq"
    if "chip" in od_lower or "chirp" in od_lower:
        return "ChIP-seq"
    if "rna-seq" in od_lower or "transcriptom" in od_lower:
        return "RNA-seq"
    if "small rna" in od_lower or "mirna" in od_lower:
        return "small RNA-seq"
    if "methylation" in od_lower or "medip" in od_lower:
        return "Methylation profiling"

    return "Other"


def main():
    parser = argparse.ArgumentParser(description="Generate summary CSV from per-GSE data.")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYYMMDD)")
    parser.add_argument("--output-dir", "-o", default=None, help="Data output dir")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(script_dir, "..")

    if args.output_dir is None:
        data_dir = os.path.join(repo_root, "data", args.date)
    else:
        data_dir = args.output_dir

    if not os.path.isdir(data_dir):
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # Discover GSE directories
    gse_dirs = sorted(
        d for d in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, d)) and d.startswith("GSE")
    )
    if not gse_dirs:
        print(f"Error: no GSE directories found in {data_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(gse_dirs)} GSE directories. Processing...\n")

    # ── Phase 1: Load all data ─────────────────────────────────────────
    all_samples = []  # list of dicts (one per GSM)
    all_pmids = set()

    for gse in gse_dirs:
        gse_path = os.path.join(data_dir, gse)
        metadata_path = os.path.join(gse_path, "gse_metadata.csv")
        sra_path = os.path.join(gse_path, "sra_runinfo.csv")

        if not os.path.exists(metadata_path):
            print(f"  [SKIP] {gse} — no gse_metadata.csv", file=sys.stderr)
            continue

        gse_meta, samples = read_metadata(metadata_path)
        sra_data = read_sra(sra_path)

        if gse_meta.get("pmid"):
            all_pmids.add(gse_meta["pmid"])

        related_gse = "; ".join(filter(None, [
            gse_meta.get("super_series_of", ""),
            gse_meta.get("sub_series_of", ""),
        ]))

        pub_year = extract_year_from_status(gse_meta.get("status", ""))

        for smp in samples:
            gsm = smp["gsm"]
            sra_rows = sra_data.get(gsm, [])

            # Collect SRR and other SRA fields
            srrs = []
            srps = set()
            lib_strats = set()
            lib_layouts = set()
            release_dates = set()

            for sr in sra_rows:
                run = sr.get("Run", "").strip()
                srp = sr.get("SRAStudy", "").strip()
                lib = sr.get("LibraryStrategy", "").strip()
                layout = sr.get("LibraryLayout", "").strip()
                rdate = sr.get("ReleaseDate", "").strip()
                if run:
                    srrs.append(run)
                if srp:
                    srps.add(srp)
                if lib:
                    lib_strats.add(lib)
                if layout:
                    lib_layouts.add(layout)
                if rdate:
                    release_dates.add(rdate)

            # Determine is_single_end
            layouts = "; ".join(sorted(lib_layouts))
            if "PAIRED" in layouts:
                is_se = "PE"
            elif "SINGLE" in layouts:
                is_se = "SE"
            else:
                is_se = ""

            # Data type
            data_type = classify_data_type(
                "; ".join(sorted(lib_strats)),
                gse_meta.get("series_type", ""),
                gse_meta.get("overall_design", ""),
            )

            # Cell line / tissue
            cell_line = extract_cell_line(smp["source_name"], smp["characteristics"])

            # Perturbation
            perturb = check_perturbation(smp["sample_title"], smp["characteristics"])

            all_samples.append({
                "gse": gse,
                "srp": "; ".join(sorted(srps)),
                "srr": "; ".join(srrs),
                "pub_year": pub_year,
                "release_date": _format_release_date(release_dates),
                "is_se": is_se,
                "sample_title": smp["sample_title"],
                "gsm": gsm,
                "cell_line": cell_line,
                "perturb": perturb,
                "data_type": data_type,
                "related_gse": related_gse,
                "pmid": gse_meta.get("pmid", ""),
            })

    # ── Phase 2: Fetch PubMed metadata ─────────────────────────────────
    print(f"Fetching PubMed metadata for {len(all_pmids)} PMIDs...")
    pubmed_data = fetch_pubmed_batch(all_pmids)

    # ── Phase 3: Write summary CSV ─────────────────────────────────────
    summary_path = os.path.join(data_dir, "summary.csv")

    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLS, extrasaction="ignore")
        writer.writeheader()

        for smp in all_samples:
            pmid_info = pubmed_data.get(smp["pmid"], {})
            writer.writerow({
                "GSE": smp["gse"],
                "SRP": smp["srp"],
                "SRR": smp["srr"],
                "data_publication_year": smp["pub_year"],
                "data_collected_date": smp["release_date"],
                "is_single_end": smp["is_se"],
                "sample_title": smp["sample_title"],
                "GSM": smp["gsm"],
                "cell_line_tissue": smp["cell_line"],
                "是否有其他干扰": smp["perturb"],
                "数据类型": smp["data_type"],
                "相关的其他GSE数据": smp["related_gse"],
                "PMID期刊名称": pmid_info.get("source", ""),
                "发表年度": pmid_info.get("pubdate", "").split()[0] if pmid_info.get("pubdate") else "",
                "文献标题": pmid_info.get("title", ""),
            })

    print(f"\nDone. {len(all_samples)} samples → {summary_path}")


if __name__ == "__main__":
    main()
