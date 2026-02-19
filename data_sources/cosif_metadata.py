from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable

CACHE_PATH = Path("data/cache/cosif/cosif_metadata.json")
MANUAL_HTML_CACHE_DIR = Path("data/cache/cosif/manual_html")

# URLs reportadas pelo usuário como origem real de conteúdo no COSIF público
KNOWN_MANUAL_PAGE_IDS = [
    "0902177186cfda51",
    "0902177186cfda43",
    "0902177186cfda50",
    "0902177186cfda52",
    "0902177186cfda53",
]


def ifdata_to_cosif_code(n: str | int) -> str:
    """Converte conta IFData (10 dígitos) para formato COSIF: A.B.C.DE.FG.HI-J."""
    digits = re.sub(r"\D", "", str(n or ""))
    if len(digits) != 10:
        raise ValueError(f"Conta IFData inválida (esperado 10 dígitos): {n!r}")
    a, b, c, de, fg, hi, j = digits[0], digits[1], digits[2], digits[3:5], digits[5:7], digits[7:9], digits[9]
    return f"{a}.{b}.{c}.{de}.{fg}.{hi}-{j}"


def normalize_digits(code: str | int) -> str:
    return re.sub(r"\D", "", str(code or ""))


def _ensure_cache_dir() -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_cache() -> Dict[str, Dict[str, str]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    items = payload.get("items")
    return items if isinstance(items, dict) else {}


def _save_cache(items: Dict[str, Dict[str, str]]) -> None:
    _ensure_cache_dir()
    CACHE_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "source": "cosif_public_site",
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _request_text(url: str, timeout_s: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; toma.conta/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_labeled_field(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        pattern = rf"(?:^|\s){re.escape(label)}\s*[:\-]\s*(.+?)(?=\s(?:T[íi]tulo|Fun[cç][aã]o|Base normativa|Base legal|Normativo|Observa[cç][õo]es?|Conta|$)\b|$)"
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .;")
    return ""


def _candidate_urls(cosif_code: str) -> list[str]:
    q = urllib.parse.quote(cosif_code)
    urls = []
    # padrão explícito informado pelo usuário (manual + âncora da conta)
    for page_id in KNOWN_MANUAL_PAGE_IDS:
        urls.append(f"https://www3.bcb.gov.br/aplica/cosif/manual/{page_id}.htm#{q}")

    # candidatos genéricos públicos
    urls.extend([
        f"https://www3.bcb.gov.br/aplica/cosif/conta/{q}",
        f"https://www3.bcb.gov.br/aplica/cosif/manual/contas/{q}.htm",
        f"https://www3.bcb.gov.br/aplica/cosif/manual/contas/{q}.html",
        f"https://www3.bcb.gov.br/aplica/cosif?conta={q}",
        f"https://www3.bcb.gov.br/aplica/cosif?codigo={q}",
    ])
    return urls


def _manual_page_url(page_id: str) -> str:
    return f"https://www3.bcb.gov.br/aplica/cosif/manual/{page_id}.htm"


def _load_or_fetch_manual_page(page_id: str) -> str:
    _ensure_cache_dir()
    path = MANUAL_HTML_CACHE_DIR / f"{page_id}.htm"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")

    html = _request_text(_manual_page_url(page_id))
    path.write_text(html, encoding="utf-8")
    return html


def _extract_account_block_from_manual(html: str, cosif_code: str) -> str:
    """Extrai janela textual da conta no HTML manual usando a âncora/código."""
    normalized_html = html.replace("\r", "")
    idx = normalized_html.find(cosif_code)
    if idx < 0:
        return ""
    start = max(0, idx - 1500)
    end = min(len(normalized_html), idx + 5000)
    return normalized_html[start:end]


def _parse_metadata_from_text(text: str, cosif_code: str) -> Dict[str, str]:
    plain = _strip_tags(text)
    titulo = _extract_labeled_field(plain, ["Título", "Titulo"]) or ""
    funcao = _extract_labeled_field(plain, ["Função", "Funcao", "Finalidade"]) or ""
    base_normativa = _extract_labeled_field(plain, ["Base normativa", "Base legal", "Normativo"]) or ""

    if not titulo:
        m_title = re.search(rf"{re.escape(cosif_code)}\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9\-\s]{{8,}})", plain)
        if m_title:
            titulo = m_title.group(1).strip()

    if not funcao:
        m_func = re.search(r"(?:FUNÇÃO|FUNCAO|FINALIDADE)\s*[:\-]?\s*(.+?)(?=\s(?:BASE\s+NORMATIVA|BASE\s+LEGAL|NORMATIVO|$))", plain, flags=re.IGNORECASE)
        if m_func:
            funcao = m_func.group(1).strip(" .;")

    return {
        "titulo": titulo,
        "funcao": funcao,
        "base_normativa": base_normativa,
    }


def fetch_cosif_metadata(cosif_code: str) -> Dict[str, str]:
    """Busca metadados oficiais COSIF para uma conta pontuada (quando disponível)."""
    normalized = normalize_digits(cosif_code)
    if len(normalized) != 10:
        raise ValueError(f"Código COSIF inválido: {cosif_code!r}")

    code = ifdata_to_cosif_code(normalized)
    last_error = ""

    # 1) tentativa priorizada no padrão do manual informado pelo usuário
    for page_id in KNOWN_MANUAL_PAGE_IDS:
        source_url = f"{_manual_page_url(page_id)}#{urllib.parse.quote(code)}"
        try:
            html = _load_or_fetch_manual_page(page_id)
            block = _extract_account_block_from_manual(html, code)
            if not block:
                continue
            parsed = _parse_metadata_from_text(block, code)
            if parsed["titulo"] or parsed["funcao"] or parsed["base_normativa"]:
                return {
                    "cosif_code": code,
                    "titulo": parsed["titulo"],
                    "funcao": parsed["funcao"],
                    "base_normativa": parsed["base_normativa"],
                    "source_url": source_url,
                    "source_status": "ok",
                }
        except Exception as exc:
            last_error = str(exc)

    # 2) fallback para URLs públicas candidatas
    for url in _candidate_urls(code):
        try:
            html = _request_text(url)
        except Exception as exc:
            last_error = str(exc)
            continue

        parsed = _parse_metadata_from_text(html, code)
        if parsed["titulo"] or parsed["funcao"] or parsed["base_normativa"]:
            return {
                "cosif_code": code,
                "titulo": parsed["titulo"],
                "funcao": parsed["funcao"],
                "base_normativa": parsed["base_normativa"],
                "source_url": url,
                "source_status": "ok",
            }

    return {
        "cosif_code": code,
        "titulo": "",
        "funcao": "",
        "base_normativa": "",
        "source_url": "",
        "source_status": f"not_found_or_unreachable:{last_error}" if last_error else "not_found",
    }


def get_cosif_metadata_for_accounts(accounts_ifdata: Iterable[str | int], force_refresh: bool = False) -> Dict[str, Dict[str, str]]:
    """Retorna metadados por conta IFData (10 dígitos), com cache persistido."""
    cache = {} if force_refresh else _load_cache()
    changed = False

    for account in accounts_ifdata:
        digits = normalize_digits(account)
        if len(digits) != 10:
            continue
        if digits in cache and cache[digits].get("source_status") == "ok" and not force_refresh:
            continue
        cache[digits] = fetch_cosif_metadata(ifdata_to_cosif_code(digits))
        changed = True

    if changed:
        _save_cache(cache)

    return cache
