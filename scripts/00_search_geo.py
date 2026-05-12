#!/usr/bin/env python3
"""
Step 0: Search NCBI GEO with a query and download all results as text.

Simulates the "Send to → File" download from the GEO search results page.
Output is a txt file with entries in the same format as the manually
downloaded file, ready for 01_extract_gse.py.

Usage:
  # Direct query string
  python 00_search_geo.py '(((eCLIP) AND Homo sapiens[Organism]) AND ("2022/07/01"[Publication Date] : "2022/12/31"[Publication Date]))'

  # Read query from file
  python 00_search_geo.py --query-file query.txt

  # Specify output
  python 00_search_geo.py '...' --output results.txt
"""

import argparse
import os
import sys
import time

import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DELAY = 1.0
MAX_RETRIES = 3
TIMEOUT = 120
BATCH_SIZE = 500


def _encode_query(query, entry_type="gse"):
    """Build E-utilities term with entry type filter, preserving brackets."""
    entry_filters = {
        "gse": " AND gse[Entry Type]",
        "gpl": " AND gpl[Entry Type]",
        "gsm": " AND gsm[Entry Type]",
        "all": "",
    }
    term = query.strip() + entry_filters.get(entry_type, "")
    # requests will encode the params dict; we must keep [ ] unencoded.
    # We'll pass the term as a pre-encoded string with safe chars.
    return term


def esearch(term, retmax=100000):
    """Search GEO database. Returns (idlist, count, webenv, querykey)."""
    params = {
        "db": "gds",
        "term": term,
        "retmax": retmax,
        "usehistory": "y",
        "retmode": "json",
    }
    # Build URL manually to keep brackets unencoded
    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{EUTILS_BASE}/esearch.fcgi?{query_str}"
    # But spaces need to be +, brackets stay as-is
    url = url.replace(" ", "+")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 429:
                wait = 5 * attempt
                print(f"  Rate-limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            result = resp.json()
            es = result["esearchresult"]
            return (
                es.get("idlist", []),
                int(es.get("count", 0)),
                es.get("webenv"),
                es.get("querykey"),
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"  [WARN] esearch attempt {attempt}/{MAX_RETRIES}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return [], 0, None, None


def efetch_batch(uids, retstart=0, retmax=BATCH_SIZE):
    """Fetch summary text for a batch of GDS UIDs."""
    params = {
        "db": "gds",
        "id": ",".join(uids),
        "rettype": "summary",
        "retmode": "text",
        "retstart": str(retstart),
        "retmax": str(retmax),
    }
    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{EUTILS_BASE}/efetch.fcgi?{query_str}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 429:
                wait = 5 * attempt
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  [WARN] efetch attempt {attempt}/{MAX_RETRIES}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def efetch_by_history(webenv, querykey, count):
    """Fetch all results using NCBI history server in batches."""
    all_entries = []
    for start in range(0, count, BATCH_SIZE):
        params = {
            "db": "gds",
            "query_key": querykey,
            "WebEnv": webenv,
            "rettype": "summary",
            "retmode": "text",
            "retstart": str(start),
            "retmax": str(BATCH_SIZE),
        }
        query_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{EUTILS_BASE}/efetch.fcgi?{query_str}"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                if resp.status_code == 429:
                    time.sleep(5 * attempt)
                    continue
                resp.raise_for_status()
                all_entries.append(resp.text)
                break
            except requests.RequestException as e:
                print(f"  [WARN] efetch batch failed: {e}", file=sys.stderr)
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)

        sys.stderr.write(
            f"\r  Fetching... {min(start + BATCH_SIZE, count)}/{count}"
        )
        sys.stderr.flush()
        if start + BATCH_SIZE < count:
            time.sleep(DELAY)

    sys.stderr.write("\n")
    return "\n\n".join(filter(None, all_entries))


def main():
    parser = argparse.ArgumentParser(
        description="Search NCBI GEO and download all results as text."
    )
    parser.add_argument(
        "query", nargs="?", default=None,
        help="GEO search query string (same as used on NCBI website)"
    )
    parser.add_argument(
        "--query-file", "-f", default=None,
        help="Read query from file instead of command line"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output txt file path (default: geo_search_results.txt in CWD)"
    )
    parser.add_argument(
        "--entry-type", "-t", default="gse",
        help="Filter by entry type: gse (default), gpl, gsm, or all"
    )
    args = parser.parse_args()

    # Get query
    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as f:
            query = f.read().strip()
    elif args.query:
        query = args.query
    else:
        print("Error: provide a query string or use --query-file", file=sys.stderr)
        sys.exit(1)

    if not query:
        print("Error: empty query", file=sys.stderr)
        sys.exit(1)

    # Build query with entry type filter
    term = _encode_query(query, args.entry_type)

    print(f"Searching GEO: {query}")
    print(f"Entry type filter: {args.entry_type.upper()}")
    print()

    # Step 1: Search
    idlist, count, webenv, querykey = esearch(term)
    if count == 0 or not idlist:
        print("No results found.")
        sys.exit(0)

    print(f"Found {count} results.")

    # Step 2: Fetch all results
    if count <= BATCH_SIZE:
        text = efetch_batch(idlist, retmax=count)
        if text is None:
            print("Error: fetch failed", file=sys.stderr)
            sys.exit(1)
    else:
        text = efetch_by_history(webenv, querykey, count)
        if not text:
            print("Error: batch fetch failed", file=sys.stderr)
            sys.exit(1)

    # Step 3: Save
    output_file = args.output or "geo_search_results.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")

    print(f"Saved {count} entries to: {output_file}")


if __name__ == "__main__":
    main()
