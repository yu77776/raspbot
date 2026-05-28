"""
Reference Verification Script
Searches CNKI / Wanfang / Google Scholar via HTTP proxy 127.0.0.1:7897
Prints FOUND / NOT FOUND / UNCERTAIN for each reference.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import ssl
import re
from html import unescape

# ── Proxy config ──────────────────────────────────────────────
PROXY = "http://127.0.0.1:7897"
os.environ["HTTP_PROXY"] = PROXY
os.environ["HTTPS_PROXY"] = PROXY

# Allow self‑signed certs (some institutional sites)
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ── References to verify ───────────────────────────────────────
REFS = [
    {
        "id": "[10]",
        "title": "基于树莓派的智能小车的设计与开发",
        "authors": ["韩改宁", "苏静池", "张瑞斌"],
        "journal": "电子设计工程",
        "year": "2024",
        "issue": "01",
        "lang": "zh",
    },
    {
        "id": "[11]",
        "title": "基于树莓派4B的循迹避障小车设计",
        "authors": ["李文海", "郭伟", "宋莉"],
        "journal": "计算机与网络",
        "year": "2022",
        "issue": "19",
        "lang": "zh",
    },
    {
        "id": "[12]",
        "title": "基于树莓派和ROS系统的智能语音导盲小车",
        "authors": ["雒洁", "王庆坡", "周庭艳"],
        "journal": "集成电路与嵌入式系统",
        "year": "2023",
        "volume_issue": "23(1)",
        "pages": "50-53",
        "lang": "zh",
    },
    {
        "id": "[13]",
        "title": "面向婴儿安抚与监护的智能交互系统设计与实现",
        "authors": ["庞宏鑫", "钱洪欣", "唐渝"],
        "journal": "计算机科学与应用",
        "year": "2026",
        "volume_issue": "16(1)",
        "pages": "337-352",
        "lang": "zh",
    },
    {
        "id": "[14]",
        "title": "基于STM32的婴儿智能识别追踪监护系统的研究",
        "authors": ["刘任杰", "肖薇", "喻成晨"],
        "journal": "Advances in Computer and Autonomous Intelligence Research",
        "year": "2024",
        "lang": "zh",
    },
    {
        "id": "[15]",
        "title": "The Design and Implementation of Smart Baby Monitor System Based on ZigBee and GoAhead",
        "authors": ["Liu D", "Sun J M", "Zheng H W"],
        "journal": "Applied Mechanics and Materials",
        "year": "2014",
        "volume_issue": "556-562",
        "pages": "2595-2598",
        "lang": "en",
    },
]

RESULTS = {}


def fetch(url, timeout=15):
    """GET url and return (status, body_text)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
        body = resp.read()
        # Try common encodings
        for enc in ("utf-8", "gbk", "gb2312", "gb18030", "latin-1"):
            try:
                return resp.status, body.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return resp.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = str(body)
        return e.code, text
    except Exception as e:
        return None, f"ERROR: {e}"


def strip_tags(text):
    """Remove HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def search_cnki(ref):
    """Search CNKI and return list of (title, link) tuples or None."""
    query = f"{ref['title']} {ref['authors'][0]}"
    encoded = urllib.parse.quote(query)
    url = f"https://kns.cnki.net/kns8s/defaultresult/index?kwd={encoded}"
    status, body = fetch(url, timeout=20)
    if status is None:
        return None, body
    if status != 200:
        return None, f"HTTP {status}"
    if "验证" in body or "captcha" in body.lower() or "人机" in body:
        return None, "CAPTCHA/BLOCK"
    # Look for paper title in the page
    text = strip_tags(body)
    if ref["title"] in text or any(au in text for au in ref["authors"][:2]):
        return [("CNKI search page", url)], None
    return [], f"Title not found on CNKI search page"


def search_scholar(ref):
    """Search Google Scholar and return list of (title, link) tuples."""
    query = f"{ref['title']} {ref['authors'][0]}"
    encoded = urllib.parse.quote(query)
    url = f"https://scholar.google.com/scholar?q={encoded}&hl=zh-CN"
    status, body = fetch(url, timeout=20)
    if status is None:
        return None, body
    if status != 200:
        return None, f"HTTP {status}"
    if "captcha" in body.lower() or "sorry" in body.lower():
        return None, "CAPTCHA/BLOCK"
    # Extract results
    text = strip_tags(body)
    matches = []
    # Simple heuristic: look for the paper title or author names
    if ref["title"][:6] in text or any(au in text for au in ref["authors"][:2]):
        matches.append(("Google Scholar search", url))
    return matches if matches else [], None


def search_wanfang(ref):
    """Search WanFang Data."""
    query = f"{ref['title']} {ref['authors'][0]}"
    encoded = urllib.parse.quote(query)
    url = f"https://s.wanfangdata.com.cn/paper?q={encoded}"
    status, body = fetch(url, timeout=20)
    if status is None:
        return None, body
    if status != 200:
        return None, f"HTTP {status}"
    if "验证" in body or "captcha" in body.lower() or "滑块" in body:
        return None, "CAPTCHA/BLOCK"
    text = strip_tags(body)
    if ref["title"][:6] in text or any(au in text for au in ref["authors"][:2]):
        return [("WanFang search", url)], None
    return [], f"Title not found on WanFang"


def verify(ref):
    """Run all search strategies and return verdict."""
    print(f"\n{'='*70}")
    print(f"  Verifying {ref['id']}: {ref['title']}")
    print(f"  Authors: {', '.join(ref['authors'])}")
    print(f"  Journal: {ref['journal']} ({ref['year']})")
    print(f"{'='*70}")

    all_matches = []
    errors = []

    # Strategy 1: CNKI
    print("  [1/3] Searching CNKI ... ", end="", flush=True)
    matches, err = search_cnki(ref)
    if err:
        print(f"ERROR: {err}")
        errors.append(f"CNKI: {err}")
    elif matches is not None:
        print(f"OK ({len(matches)} potential match(es))")
        all_matches.extend(matches)
    else:
        print("no result")

    time.sleep(2)  # polite delay

    # Strategy 2: Google Scholar
    print("  [2/3] Searching Google Scholar ... ", end="", flush=True)
    matches, err = search_scholar(ref)
    if err:
        print(f"ERROR: {err}")
        errors.append(f"Scholar: {err}")
    elif matches is not None:
        print(f"OK ({len(matches)} potential match(es))")
        all_matches.extend(matches)
    else:
        print("no result")

    time.sleep(2)

    # Strategy 3: WanFang
    print("  [3/3] Searching WanFang ... ", end="", flush=True)
    matches, err = search_wanfang(ref)
    if err:
        print(f"ERROR: {err}")
        errors.append(f"WanFang: {err}")
    elif matches is not None:
        print(f"OK ({len(matches)} potential match(es))")
        all_matches.extend(matches)
    else:
        print("no result")

    # Verdict
    if all_matches:
        verdict = "FOUND"
    elif errors and all("CAPTCHA" in e or "BLOCK" in e or "HTTP" in e for e in errors):
        verdict = "UNCERTAIN (blocked by CAPTCHA / HTTP error)"
    elif errors:
        verdict = "UNCERTAIN (search failed)"
    else:
        verdict = "NOT FOUND"

    result = {
        "id": ref["id"],
        "title": ref["title"],
        "verdict": verdict,
        "matches": [m[1] for m in all_matches],
        "errors": errors,
    }
    RESULTS[ref["id"]] = result

    print(f"\n  >>> VERDICT: {verdict}")
    if all_matches:
        for name, link in all_matches:
            print(f"      [{name}] {link}")

    return result


# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  Academic Reference Verification Tool")
    print(f"  Proxy: {PROXY}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Quick connectivity check
    print("\n[PRE-FLIGHT] Testing proxy connectivity ...")
    status, _ = fetch("https://www.google.com", timeout=10)
    if status == 200:
        print("  Proxy OK - Google reachable")
    else:
        print(f"  WARNING: Google returned status={status}. Proxy may not work.")
        # Try a Chinese site
        status2, _ = fetch("https://www.baidu.com", timeout=10)
        if status2 == 200:
            print("  Baidu reachable, proceeding anyway.")
        else:
            print("  CRITICAL: Cannot reach any site. Check proxy.")
            print("  Continuing anyway ...")

    for ref in REFS:
        time.sleep(1)  # polite delay between references
        verify(ref)

    # ── Summary ─────────────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    for ref_id in [r["id"] for r in REFS]:
        r = RESULTS.get(ref_id, {})
        print(f"  {ref_id}: {r.get('verdict', 'NOT TESTED')}")

    # Save JSON
    report_path = os.path.join(os.path.dirname(__file__), "verify_results.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    print(f"\n  Detailed results saved to: {report_path}")


if __name__ == "__main__":
    main()
