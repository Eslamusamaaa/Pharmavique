"""Read-only probe: one polite request per SFDA list, report its structure. Not part of the repo."""

import re
import sys
import time

import httpx
from bs4 import BeautifulSoup

UA = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"
BASE = "https://www.sfda.gov.sa"
PATHS = sys.argv[1:]


def clean(text: str) -> str:
    return " ".join(text.split())


with httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True) as client:
    for path in PATHS:
        time.sleep(3)
        try:
            response = client.get(BASE + path)
        except Exception as error:  # noqa: BLE001
            print(f"\n== {path}: ERROR {error}")
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        pages = [int(m) for m in re.findall(r'href="\?page=(\d+)"', response.text)]
        captcha = bool(re.search(r"captcha_response|g-recaptcha|hcaptcha", response.text, re.I))
        files = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx?|csv|pdf|zip))"', response.text, re.I)))
        print(f"\n== {path}: HTTP {response.status_code}, {len(response.text)} bytes, tables={len(tables)}")
        print(f"   captcha markers: {captcha} | pager max page: {max(pages) if pages else None} | file links: {len(files)}")
        for table in tables[:2]:
            headers = [clean(th.get_text(' ')) for th in table.find_all("th")]
            rows = [tr for tr in table.find_all("tr") if tr.find("td")]
            print(f"   table headers: {headers}")
            print(f"   rows on this page: {len(rows)}")
            if rows:
                cells = [clean(td.get_text(' '))[:28] for td in rows[0].find_all("td")]
                links = [a["href"][:70] for a in rows[0].find_all("a", href=True)]
                print(f"   first row: {cells}")
                print(f"   first row links: {links}")
        for name in files[:4]:
            print(f"   file: {name[:110]}")
        if not tables:
            text = [clean(t) for t in soup.get_text("\n").split("\n") if clean(t)]
            interesting = [t for t in text if re.search(r"list|total|download|search|filter", t, re.I)][:6]
            print(f"   no table; page text hints: {interesting}")
