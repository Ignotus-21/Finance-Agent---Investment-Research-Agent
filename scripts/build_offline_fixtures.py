"""Record real SEC EDGAR filings as the offline fixture corpus.

Run deliberately, never in CI: it makes ~90 requests to sec.gov and takes a
few minutes. The output, ``datasets/sec_fixtures_fy2024.json``, is what
``OFFLINE_MODE=true`` serves, so committing it is what makes offline runs
reproducible without also making them fictional.

The selection logic is *not* reimplemented here. This calls the same
``SECEdgarHTTPClient`` the live path uses, so a fixture can never disagree
with what a live run would have returned.

    python scripts/build_offline_fixtures.py [--fiscal-year 2024]

Tickers are read from the golden dataset, so the corpus covers exactly the
scenarios the evaluation harness exercises.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from src.tools.sec_edgar_http import XBRL_CONCEPTS, SECEdgarHTTPClient

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "datasets" / "golden_evaluation_dataset.json"
OUTPUT = REPO / "datasets" / "sec_fixtures_fy2024.json"

# ExxonMobil reorganised into a holding company in 2025. The XOM ticker now
# resolves to the new entity, which has never filed a 10-K; the FY2024 annual
# report belongs to the predecessor registrant. Mapping the ticker by hand is
# honest here - we are naming the filer that actually filed the document -
# whereas a generic successor-chasing heuristic would be a lot of machinery
# for one company.
CIK_OVERRIDES = {"XOM": "0000034088"}

# MD&A is narrative and has no XBRL representation, so it is stored as text.
# Truncated: the fixture exists to give the synthesis step genuine language to
# work with, not to mirror a 200-page filing.
MDA_CHARS = 2000


async def fetch_ticker(
    edgar: SECEdgarHTTPClient,
    client: httpx.AsyncClient,
    ticker: str,
    fiscal_year: int,
) -> dict[str, Any]:
    """Record one registrant's annual filing, or raise."""
    cik = CIK_OVERRIDES.get(ticker) or await edgar.resolve_cik(ticker, client)
    filing = await edgar.find_filing(cik, "10-K", fiscal_year, client)
    period_end = filing.get("report_date", "")

    current = await edgar.fetch_xbrl_facts(cik, fiscal_year, client, period_end=period_end)
    prior = await edgar.fetch_xbrl_facts(cik, fiscal_year - 1, client)

    if "revenue" not in current:
        raise ValueError(f"no revenue tagged for FY{fiscal_year}; tried {XBRL_CONCEPTS['revenue']}")

    mda = await edgar.fetch_mda_text(
        cik, filing["accession_number"], filing["primary_document"], client, max_chars=MDA_CHARS
    )

    return {
        "ticker": ticker,
        "cik": cik,
        "company_name": filing["company_name"],
        "fiscal_year": fiscal_year,
        "accession_number": filing["accession_number"],
        "filing_date": filing["filing_date"],
        "period_end": period_end,
        "primary_document": filing["primary_document"],
        "current": current,
        "prior": prior,
        "mda_item_7": mda,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fiscal-year", type=int, default=2024)
    parser.add_argument(
        "--user-agent",
        default="IRA Research contact@example.com",
        help="SEC requires a contact address; they ban callers who omit one.",
    )
    args = parser.parse_args()

    scenarios = json.loads(DATASET.read_text(encoding="utf-8"))
    # "NONE" marks out-of-scope scenarios, which never reach the SEC client.
    tickers = sorted({s["ticker"] for s in scenarios if s["ticker"] != "NONE"})

    edgar = SECEdgarHTTPClient(user_agent=args.user_agent)
    corpus: dict[str, Any] = {}
    failures: list[tuple[str, str]] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0),
        headers={"User-Agent": args.user_agent, "Accept-Encoding": "gzip, deflate"},
        limits=httpx.Limits(max_connections=2),
        follow_redirects=True,
    ) as client:
        for ticker in tickers:
            try:
                record = await fetch_ticker(edgar, client, ticker, args.fiscal_year)
            except Exception as exc:  # noqa: BLE001 - report and continue
                failures.append((ticker, f"{type(exc).__name__}: {exc}"))
                continue

            corpus[ticker] = record
            missing = sorted(set(XBRL_CONCEPTS) - set(record["current"]))
            print(
                f"  {ticker:6} {record['current']['revenue'] / 1e9:9,.1f}B  "
                f"{record['accession_number']}  mda={len(record['mda_item_7']):>5}c  "
                f"missing={','.join(missing) or '-'}"
            )

    OUTPUT.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(corpus)} / {len(tickers)} -> {OUTPUT.relative_to(REPO)}")
    for ticker, why in failures:
        print(f"  FAILED {ticker}: {why}")


if __name__ == "__main__":
    asyncio.run(main())
