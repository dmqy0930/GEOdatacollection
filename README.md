# GEOdatacollection

A fully automated pipeline for collecting, organizing, and summarizing NCBI GEO (Gene Expression Omnibus) metadata and linked SRA (Sequence Read Archive) run information.

## Overview

Starting from a GEO search query or an existing results file, the pipeline:

1. **Search** GEO and download all matching entries
2. **Extract** unique GSE accession numbers
3. **Fetch** per-GSE metadata (title, summary, status, organism, overall design, PMID, citations, sample details, SuperSeries/SubSeries relationships)
4. **Download** SRA Run Tables (SraRunTable) for each BioProject via NCBI E-utilities
5. **Generate** a comprehensive 15-column summary CSV

## Quick Start

### Prerequisites

- Python 3.7+
- `requests` library

```bash
pip install requests
```

### Usage

```bash
# From a GEO search query
./run.sh --query '(((eCLIP) AND Homo sapiens[Organism]) AND ("2022/07/01"[Publication Date] : "2022/12/31"[Publication Date]))'

# From an existing txt file
./run.sh /path/to/geo_results.txt

# Specify a custom output directory
./run.sh --query '...' /path/to/custom_output
```

## Pipeline

```
                   ┌────────────────────┐
                   │  GEO Search Query  │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 00_search_geo.py   │  E-utilities esearch + efetch
                   │ → search_results   │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 01_extract_gse.py  │  Regex extraction
                   │ → gse_accessions   │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 02_fetch_gse_      │  GEO SOFT format parsing
                   │    details.py      │  → gse_metadata.csv × N
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 03_download_sra.py │  SRA efetch (runinfo)
                   │ → sra_runinfo.csv  │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 04_generate_       │  Merge + PubMed lookup
                   │    summary.py      │  → summary.csv
                   └────────────────────┘
```

## Directory Structure

```
GEOdatacollection/
├── run.sh                        # Master orchestration script
├── scripts/
│   ├── 00_search_geo.py          # Search GEO + download results
│   ├── 01_extract_gse.py         # Extract GSE accessions
│   ├── 02_fetch_gse_details.py   # Per-GSE metadata from SOFT format
│   ├── 03_download_sra.py        # Download SraRunTable
│   └── 04_generate_summary.py    # Generate 15-column summary
├── output/                       # Intermediate files (gse_accessions.txt, etc.)
├── data/                         # Runtime output directory
│   └── {YYYYMMDD}/
│       ├── GSE{number}/
│       │   ├── gse_metadata.csv
│       │   └── sra_runinfo.csv
│       └── summary.csv
└── .gitignore
```

## Output: Summary CSV

The final `summary.csv` contains 15 columns, one row per sample (GSM):

| Column | Description | Source |
|--------|-------------|--------|
| **GSE** | GEO Series accession | GEO |
| **SRP** | SRA Study accession | SRA |
| **SRR** | SRA Run accession(s) | SRA |
| **data_publication_year** | Year from GEO Status | GEO |
| **data_collected_date** | SRA ReleaseDate (`YYYY/MM/DD`) | SRA |
| **is_single_end** | `SE` (single-end) or `PE` (paired-end) | SRA LibraryLayout |
| **sample_title** | Sample name from GEO | GEO |
| **GSM** | GEO Sample accession | GEO |
| **cell_line_tissue** | Cell line / tissue source | GEO source_name / characteristics |
| **是否有其他干扰** | Perturbation keywords (siRNA, sgRNA, CRISPR, DMSO, etc.) | GEO sample_title |
| **数据类型** | Data type (CLIP-seq, RNA-seq, ChIP-seq, etc.) | SRA LibraryStrategy + GEO |
| **相关的其他GSE数据** | Related GSE (SuperSeries/SubSeries) | GEO |
| **PMID期刊名称** | Journal name | PubMed |
| **发表年度** | Publication year | PubMed |
| **文献标题** | Article title | PubMed |

## Individual Scripts

Each script can also be used independently:

```bash
# Step 0: Search GEO
python scripts/00_search_geo.py 'query terms here' --output results.txt

# Step 1: Extract GSE accessions
python scripts/01_extract_gse.py results.txt --output-dir ./output

# Step 2: Fetch GSE metadata
python scripts/02_fetch_gse_details.py --date 20260512 --output-dir ./data/20260512

# Step 3: Download SRA metadata
python scripts/03_download_sra.py --date 20260512 --output-dir ./data/20260512

# Step 4: Generate summary
python scripts/04_generate_summary.py --date 20260512 --output-dir ./data/20260512
```

## Dependencies

| Library | Used by | Purpose |
|---------|---------|---------|
| `requests` | all | HTTP requests to NCBI E-utilities |
| Standard library (`csv`, `re`, `json`, `argparse`, etc.) | all | Data processing |

## API Rate Limits

All scripts respect NCBI E-utilities rate limits (~3 requests/second). Built-in retry logic with exponential backoff handles temporary failures.

## License

MIT
