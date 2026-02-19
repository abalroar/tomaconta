"""Utilitários para construir mapeamento COSIF a partir do PDF oficial (BCB).

Fonte oficial:
https://www3.bcb.gov.br/aplica/cosif/manual/completo_contas.pdf

Fluxo:
1) baixa e cacheia PDF em data/cache/cosif/
2) extrai texto (quando biblioteca de PDF está disponível)
3) parseia linhas "código + descrição"
4) persiste CSV de mapeamento para reuso rápido
"""

from __future__ import annotations

import csv
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

COSIF_PDF_URL = "https://www3.bcb.gov.br/aplica/cosif/manual/completo_contas.pdf"
CACHE_DIR = Path("data/cache/cosif")
PDF_PATH = CACHE_DIR / "completo_contas.pdf"
MAP_CSV_PATH = CACHE_DIR / "cosif_map.csv"
META_PATH = CACHE_DIR / "metadata.json"

COSIF_LINE_RE = re.compile(r"^(?P<code>\d+(?:\.\d+)+-\d)\s+(?P<desc>.+?)\s*$")


def normalize_cosif_code_digits(code: str) -> str:
    """Normaliza código COSIF para chave numérica (somente dígitos)."""
    return re.sub(r"\D", "", str(code or ""))


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def download_cosif_pdf(force_refresh: bool = False, timeout_s: int = 60) -> Path:
    """Baixa o PDF oficial para cache local."""
    _ensure_cache_dir()
    if PDF_PATH.exists() and not force_refresh:
        return PDF_PATH

    req = urllib.request.Request(
        COSIF_PDF_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; toma.conta/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
    PDF_PATH.write_bytes(data)
    return PDF_PATH


def _extract_text_pdf(pdf_path: Path) -> str:
    """Extrai texto do PDF usando pypdf, quando disponível."""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Biblioteca 'pypdf' não disponível para extrair texto do PDF COSIF"
        ) from exc

    reader = PdfReader(str(pdf_path))
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text)


def parse_cosif_pdf_text_to_rows(text: str) -> List[Dict[str, str]]:
    """Parseia texto do PDF para linhas de mapeamento COSIF."""
    rows: List[Dict[str, str]] = []
    seen = set()

    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        m = COSIF_LINE_RE.match(line)
        if not m:
            continue

        code = m.group("code").strip()
        desc = m.group("desc").strip()
        digits = normalize_cosif_code_digits(code)
        if not digits:
            continue

        key = (digits, desc)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "cosif_code": code,
                "cosif_code_digits": digits,
                "description": desc,
            }
        )

    return rows


def _save_rows_csv(rows: List[Dict[str, str]]) -> None:
    _ensure_cache_dir()
    with MAP_CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cosif_code", "cosif_code_digits", "description"])
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _load_rows_csv() -> List[Dict[str, str]]:
    if not MAP_CSV_PATH.exists():
        return []
    with MAP_CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_cosif_map_cache(force_refresh_pdf: bool = False) -> Dict[str, str]:
    """Cria/atualiza cache local de descrição COSIF e retorna dict digits->descrição."""
    _ensure_cache_dir()

    rows = [] if force_refresh_pdf else _load_rows_csv()
    if not rows:
        pdf_path = download_cosif_pdf(force_refresh=force_refresh_pdf)
        text = _extract_text_pdf(pdf_path)
        rows = parse_cosif_pdf_text_to_rows(text)
        if rows:
            _save_rows_csv(rows)

    mapping: Dict[str, str] = {}
    for row in rows:
        digits = normalize_cosif_code_digits(row.get("cosif_code_digits") or row.get("cosif_code"))
        desc = str(row.get("description") or "").strip()
        if digits and desc and digits not in mapping:
            mapping[digits] = desc

    META_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "pdf_url": COSIF_PDF_URL,
                "n_items": len(mapping),
                "source": "pdf_oficial_cosif",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return mapping


def get_cosif_description_map_cached() -> Dict[str, str]:
    """Retorna map digits->descrição a partir do cache local; tenta construir se vazio."""
    rows = _load_rows_csv()
    if rows:
        mapping: Dict[str, str] = {}
        for row in rows:
            digits = normalize_cosif_code_digits(row.get("cosif_code_digits") or row.get("cosif_code"))
            desc = str(row.get("description") or "").strip()
            if digits and desc and digits not in mapping:
                mapping[digits] = desc
        if mapping:
            return mapping

    # tenta construir (pode falhar por ausência de pypdf/rede)
    try:
        return build_cosif_map_cache(force_refresh_pdf=False)
    except Exception:
        return {}


def get_cosif_description(cosif_code: str) -> Optional[str]:
    """Busca descrição COSIF por código (aceita com/sem pontuação)."""
    digits = normalize_cosif_code_digits(cosif_code)
    if not digits:
        return None
    return get_cosif_description_map_cached().get(digits)
