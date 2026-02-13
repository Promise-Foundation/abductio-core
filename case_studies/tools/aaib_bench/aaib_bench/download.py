from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from .hashutil import sha256_file

GOVUK_SEARCH_API = "https://www.gov.uk/api/search.json"
DEFAULT_USER_AGENT = "abductio-aaib-bench/0.1"


@dataclass(frozen=True)
class DownloadResult:
    case_id: str
    pdf_url: str
    pdf_path: Path
    sha256: str
    downloaded: bool


def _http_get_bytes(url: str, timeout_s: float) -> bytes:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=timeout_s) as response:
        return response.read()


def _http_get_text(url: str, timeout_s: float) -> str:
    payload = _http_get_bytes(url, timeout_s=timeout_s)
    return payload.decode("utf-8", errors="replace")


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _tokenize(value: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def _extract_pdf_links(html: str, base_url: str) -> List[str]:
    links: List[str] = []
    for raw in re.findall(r'href=["\']([^"\']+?\.pdf(?:\?[^"\']*)?)["\']', html, flags=re.IGNORECASE):
        href = raw.replace("&amp;", "&")
        links.append(urljoin(base_url, href))
    seen: set[str] = set()
    unique: List[str] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        unique.append(link)
    return unique


def _score_pdf_link(row: Dict[str, str], link: str) -> int:
    lower_link = link.lower()
    score = 0

    pdf_filename = (row.get("pdf_filename") or "").strip().lower()
    if pdf_filename:
        if lower_link.endswith(pdf_filename):
            score += 1000
        filename_tokens = _tokenize(Path(pdf_filename).stem)
    else:
        filename_tokens = []

    seeded_terms = [
        row.get("source_doc_id", ""),
        row.get("registration", ""),
        row.get("case_id", ""),
        row.get("doc_title", ""),
        row.get("aircraft_type", ""),
    ]
    for token in filename_tokens:
        if len(token) >= 2 and token in lower_link:
            score += 40
    for seed in seeded_terms:
        for token in _tokenize(seed):
            if len(token) >= 2 and token in lower_link:
                score += 20

    if "glossary" in lower_link:
        score -= 100
    if "bulletin" in lower_link:
        score -= 20
    return score


def _govuk_search_links(query: str, timeout_s: float) -> List[str]:
    if not query.strip():
        return []
    url = f"{GOVUK_SEARCH_API}?q={quote_plus(query)}&count=20"
    payload = _http_get_text(url, timeout_s=timeout_s)
    data = json.loads(payload)
    results = data.get("results", [])
    links: List[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link", "")).strip()
        if not link:
            continue
        links.append(urljoin("https://www.gov.uk", link))
    return links


def _slugify(text: str) -> str:
    pieces = [token for token in re.split(r"[^A-Za-z0-9]+", text.lower()) if token]
    return "-".join(pieces)


def _candidate_case_pages(row: Dict[str, str], timeout_s: float) -> List[str]:
    candidates: List[str] = []

    source_url = (row.get("source_url") or "").strip()
    if source_url and not _is_pdf_url(source_url):
        candidates.append(source_url)

    aircraft_type = (row.get("aircraft_type") or "").strip()
    registration = (row.get("registration") or "").strip()
    if aircraft_type and registration:
        slug = _slugify(f"aaib investigation to {aircraft_type} {registration}")
        if slug:
            candidates.append(f"https://www.gov.uk/aaib-reports/{slug}")

    search_terms = [
        row.get("source_doc_id", ""),
        row.get("doc_title", ""),
        row.get("case_id", "").replace("_", " "),
        f"AAIB investigation to {aircraft_type}, {registration}" if aircraft_type and registration else "",
    ]
    for term in search_terms:
        try:
            links = _govuk_search_links(term, timeout_s=timeout_s)
        except Exception:
            links = []
        for link in links:
            if "/aaib-reports/" in link or "/government/publications/" in link:
                candidates.append(link)

    unique: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def resolve_pdf_url(row: Dict[str, str], timeout_s: float = 30.0) -> str:
    preferred = [
        row.get("source_pdf_url", ""),
        row.get("pdf_url", ""),
        row.get("source_url", ""),
    ]
    for url in preferred:
        value = str(url or "").strip()
        if value and _is_pdf_url(value):
            return value

    best_link = ""
    best_score = -10_000
    for page_url in _candidate_case_pages(row, timeout_s=timeout_s):
        try:
            html = _http_get_text(page_url, timeout_s=timeout_s)
        except Exception:
            continue
        links = _extract_pdf_links(html, base_url=page_url)
        for link in links:
            score = _score_pdf_link(row, link)
            if score > best_score:
                best_score = score
                best_link = link

    if best_link:
        return best_link
    raise ValueError(f"Unable to resolve report PDF URL for case_id={row.get('case_id', '')}")


def download_case_pdf(
    row: Dict[str, str],
    destination_dir: Path,
    *,
    force: bool = False,
    timeout_s: float = 30.0,
) -> DownloadResult:
    case_id = row.get("case_id", "")
    if not case_id:
        raise ValueError("case_id is required")

    destination_dir.mkdir(parents=True, exist_ok=True)
    pdf_url = resolve_pdf_url(row, timeout_s=timeout_s)
    pdf_filename = (row.get("pdf_filename") or "").strip()
    if not pdf_filename:
        parsed = urlparse(pdf_url)
        pdf_filename = Path(parsed.path).name or f"{case_id}.pdf"
    pdf_path = destination_dir / pdf_filename

    if pdf_path.exists() and not force:
        return DownloadResult(
            case_id=case_id,
            pdf_url=pdf_url,
            pdf_path=pdf_path,
            sha256=sha256_file(pdf_path),
            downloaded=False,
        )

    payload = _http_get_bytes(pdf_url, timeout_s=timeout_s)
    if not payload.startswith(b"%PDF"):
        raise ValueError(f"Resolved URL is not a PDF payload: {pdf_url}")
    pdf_path.write_bytes(payload)

    return DownloadResult(
        case_id=case_id,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        sha256=sha256_file(pdf_path),
        downloaded=True,
    )


def select_case_ids(
    rows: Iterable[Dict[str, str]],
    *,
    case_id: str | None = None,
    use_all: bool = False,
    use_selected: bool = False,
) -> List[str]:
    if case_id:
        return [case_id]
    if use_all:
        return [row.get("case_id", "") for row in rows if row.get("case_id")]
    if use_selected:
        selected: List[str] = []
        for row in rows:
            value = str(row.get("selected_for_corpus", "")).strip().upper()
            if value in {"Y", "YES", "TRUE", "1"} and row.get("case_id"):
                selected.append(row["case_id"])
        return selected
    raise ValueError("One of case_id/use_all/use_selected must be provided")
