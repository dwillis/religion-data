#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "playwright",
# ]
# ///

import sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


CHURCHES = [
    ("https://stjamesmr.org/bulletins",               "bulletins/stjames_mr"),
    ("https://stmatthias.org/bulletins",               "bulletins/stmatthias"),
    ("https://stcolumbacatholicchurch.net/bulletins",  "bulletins/stcolumba"),
    ("https://ascensionbowie.org/bulletins",           "bulletins/ascension_bowie"),
    ("https://holyfamilyparishmd.org/bulletins",       "bulletins/holy_family"),
]


def download_bulletins(page, url: str, out_dir: str) -> None:
    out_path = Path(out_dir)

    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return

    title = page.title()
    if "Just a moment" in title:
        print(f"Cloudflare blocked {url} — save the page manually to use as input")
        return

    pdf_links = page.eval_on_selector_all(
        "a[href*='ecatholic.com'][href*='/bulletins/']",
        "els => els.map(el => el.href)",
    )

    if not pdf_links:
        print(f"No bulletins found at {url}")
        return

    out_path.mkdir(parents=True, exist_ok=True)
    print(f"{out_dir}: found {len(pdf_links)} bulletins")

    for pdf_url in pdf_links:
        filename = urlparse(pdf_url).path.split("/")[-1]
        dest = out_path / filename
        if dest.exists():
            continue
        try:
            pdf_response = page.request.get(pdf_url)
            dest.write_bytes(pdf_response.body())
        except Exception as e:
            print(f"Failed: {pdf_url} — {e}", file=sys.stderr)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = context.new_page()

        for url, out_dir in CHURCHES:
            download_bulletins(page, url, out_dir)

        browser.close()
    print("Done")


if __name__ == "__main__":
    main()
