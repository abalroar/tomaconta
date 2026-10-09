"""Cadastro oficial por competência e CodInst, com recuperação persistida."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode

import pandas as pd

from .institutions import normalize_institution_code

logger = logging.getLogger("ifdata_cache")
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
IFDATA_CACHE_NAMES = frozenset({
    "principal", "principal_individual", "capital", "ativo", "passivo", "dre",
    "dre_individual", "carteira_pf", "carteira_pj", "carteira_instrumentos",
})
INSTITUTION_NAMED_CACHE_NAMES = IFDATA_CACHE_NAMES | {
    "derived_metrics", "derived_metrics_individual", "critical_screens",
}


def unresolved_name(value) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip()
    return (text.upper() in {"", "NAN", "NONE", "<NA>", "SEM NOME", "N/D", "N/A", "-"}
            or bool(re.fullmatch(r"\[IF\s+[^\]]+\]", text, re.IGNORECASE))
            or bool(re.fullmatch(r"(?:C?\d+(?:\.0)?|CODINST\s*[:=]\s*\w+|\d+[_\-.:]\w+)", text, re.IGNORECASE)))


def registry_name_map(frame: pd.DataFrame) -> dict[str, str]:
    """Exige correspondência exata; C e zeros à esquerda distinguem identidades."""
    name_col = next((c for c in ("NomeInstituicao", "NomeInstituição", "Instituição")
                     if c in frame.columns), None)
    if frame.empty or "CodInst" not in frame.columns or name_col is None:
        raise ValueError("Cadastro sem CodInst/nomes de instituições")
    pairs = pd.DataFrame({
        "code": frame["CodInst"].map(normalize_institution_code),
        "name": frame[name_col].astype("string").fillna("").str.strip(),
    })
    bad = pairs["code"].eq("") | pairs["name"].map(unresolved_name)
    if bad.any():
        raise ValueError(f"Cadastro com {int(bad.sum())} identidade(s)/nome(s) não resolvido(s)")
    conflicts = pairs.groupby("code")["name"].nunique().gt(1)
    if conflicts.any():
        raise ValueError("Cadastro com nomes conflitantes para CodInst: "
                         + ", ".join(conflicts[conflicts].index[:5]))
    return dict(pairs.drop_duplicates("code")[["code", "name"]].itertuples(index=False, name=None))


def _root(base_dir=None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2]


def _registry_paths(periodo: str, base_dir=None) -> tuple[Path, Path]:
    if not re.fullmatch(r"\d{4}(03|06|09|12)", str(periodo)):
        raise ValueError(f"Competência inválida para cadastro: {periodo}")
    root = _root(base_dir)
    runtime = Path(os.getenv("TOMACONTA_IFDATA_REGISTRY_DIR") or root / "data/cache/institution_registry")
    return runtime / f"{periodo}.json", root / "data/bundled/institution_registry" / f"{periodo}.json"


def save_registry(frame: pd.DataFrame, periodo: str, *, source: str, base_dir=None) -> Path:
    mapping = registry_name_map(frame)
    records = [{"CodInst": code, "NomeInstituicao": name} for code, name in sorted(mapping.items())]
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True).encode()
    payload = {
        "periodo": periodo, "source": source,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256_records": hashlib.sha256(encoded).hexdigest(), "records": records,
    }
    path, _ = _registry_paths(periodo, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem, suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_persisted_registry(periodo: str, base_dir=None) -> pd.DataFrame:
    for path in _registry_paths(periodo, base_dir):
        try:
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict):
                raise ValueError("estrutura inválida")
            encoded = json.dumps(payload["records"], ensure_ascii=False, sort_keys=True).encode()
            if payload["periodo"] != periodo or hashlib.sha256(encoded).hexdigest() != payload["sha256_records"]:
                raise ValueError("competência/checksum divergente")
            frame = pd.DataFrame(payload["records"])
            registry_name_map(frame)
            frame.attrs["institution_registry_source"] = str(path)
            frame.attrs["institution_registry_upstream_source"] = payload["source"]
            return frame
        except FileNotFoundError:
            continue
        except (OSError, KeyError, ValueError) as exc:
            logger.warning("Cadastro persistido inválido em %s: %s", path, exc)
    return pd.DataFrame()


def _web_registry(periodo):
    from .ifdata_web import get_web_source
    source = get_web_source(periodo)
    frame = source.cadastro_frame()
    if f"cadastro{periodo}_1005.json" in source.files:
        financial = source.cadastro_frame(tipo=2)
        # Acrescenta somente chaves financeiras sem contraparte no cadastro
        # geral. Nomes de perímetros diferentes nunca substituem os existentes.
        extras = financial[~financial["CodInst"].isin(frame["CodInst"])]
        frame = pd.concat([frame, extras], ignore_index=True)
    return frame


def extract_registry(periodo: str, fetch_json, *, base_dir=None) -> pd.DataFrame:
    """Só persiste cadastro completo; falhas recuperam a mesma competência."""
    _registry_paths(periodo, base_dir)
    try:
        if os.getenv("TOMACONTA_IFDATA_SOURCE") == "web":
            frame = _web_registry(periodo)
            source = "https://www3.bcb.gov.br/ifdata/"
        else:
            page_size, skip, rows = 5000, 0, []
            seen_pages = set()
            while True:
                query = urlencode({"$format": "json", "$top": page_size, "$skip": skip, "$orderby": "CodInst"})
                url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(periodo)})?{query}"
                payload = fetch_json(url, timeout=60)
                if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                    raise ValueError(f"Cadastro incompleto: falha na página {skip // page_size + 1}")
                page = payload["value"]
                page_key = hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()
                if page and page_key in seen_pages:
                    raise ValueError("Cadastro incompleto: página repetida pela API")
                seen_pages.add(page_key)
                rows.extend(page)
                if len(page) < page_size:
                    break
                skip += page_size
            frame = pd.DataFrame(rows)
            if "Data" in frame and not frame["Data"].astype(str).eq(periodo).all():
                raise ValueError("Cadastro com competência divergente")
            source = f"{BASE_URL}/IfDataCadastro(AnoMes={int(periodo)})"
        registry_name_map(frame)
        previous = load_persisted_registry(periodo, base_dir)
        if not previous.empty:
            extras = previous[~previous["CodInst"].isin(frame["CodInst"])]
            if not extras.empty:
                frame = pd.concat([frame, extras], ignore_index=True)
                sources = [*source.split("; "), *previous.attrs.get("institution_registry_upstream_source", "").split("; ")]
                source = "; ".join(dict.fromkeys(s for s in sources if s))
        save_registry(frame, periodo, source=source, base_dir=base_dir)
        frame.attrs["institution_registry_source"] = source
        return frame
    except Exception as exc:
        persisted = load_persisted_registry(periodo, base_dir)
        if not persisted.empty:
            logger.warning("Cadastro %s recuperado da cópia validada: %s", periodo, exc)
            return persisted
        # Os arquivos oficiais do IF.data fornecem a mesma chave/competência.
        if int(periodo[:4]) >= 2025 and os.getenv("TOMACONTA_IFDATA_SOURCE") != "web":
            try:
                frame = _web_registry(periodo)
                source = "https://www3.bcb.gov.br/ifdata/"
                save_registry(frame, periodo, source=source, base_dir=base_dir)
                frame.attrs["institution_registry_source"] = source
                logger.warning("Cadastro %s recuperado dos arquivos oficiais: %s", periodo, exc)
                return frame
            except Exception as fallback_error:
                raise ValueError(f"Cadastro {periodo} indisponível: {exc}; IF.data: {fallback_error}") from exc
        raise ValueError(f"Cadastro {periodo} indisponível: {exc}") from exc


def attach_institution_names(frame: pd.DataFrame, registry: pd.DataFrame, periodo: str,
                             *, name_column="Instituição", base_dir=None) -> pd.DataFrame:
    mapping = registry_name_map(registry)
    out = frame.copy()
    codes = out["CodInst"].map(normalize_institution_code)
    names = codes.map(mapping)
    if names.isna().any():
        persisted = load_persisted_registry(periodo, base_dir)
        if not persisted.empty:
            names = names.where(names.notna(), codes.map(registry_name_map(persisted)))
    if names.isna().any() and int(periodo[:4]) >= 2025:
        try:
            supplemental = _web_registry(periodo)
            supplemental_map = registry_name_map(supplemental)
            names = names.where(names.notna(), codes.map(supplemental_map))
            if not names.isna().any():
                additions = supplemental[~supplemental["CodInst"].isin(registry["CodInst"])]
                complete = pd.concat([registry, additions], ignore_index=True)
                source = registry.attrs.get("institution_registry_upstream_source",
                                            registry.attrs.get("institution_registry_source", BASE_URL))
                if not str(source).startswith("https://"):
                    source = BASE_URL
                save_registry(complete, periodo, source=f"{source}; https://www3.bcb.gov.br/ifdata/", base_dir=base_dir)
        except Exception as exc:
            logger.warning("Cadastro complementar %s indisponível: %s", periodo, exc)
    if names.isna().any():
        missing = codes[names.isna()].unique().tolist()
        raise ValueError(f"Cadastro {periodo} não cobre {len(missing)} CodInst: " + ", ".join(missing[:5]))
    out[name_column] = names
    out.attrs["institution_registry_source"] = registry.attrs.get("institution_registry_source", "cadastro")
    return out


def validate_institution_names(frame: pd.DataFrame) -> tuple[bool, str]:
    if frame.empty:
        return False, "Dataset de instituições vazio"
    name_col = next((c for c in ("Instituição", "NomeInstituicao", "NomeInstituição") if c in frame), None)
    if name_col is None:
        return False, "Coluna de nome da instituição ausente"
    invalid = frame[name_col].astype("string").map(unresolved_name)
    if invalid.any():
        return False, f"{int(invalid.sum())} nome(s) de instituição não resolvido(s); cache anterior preservado"
    return True, "OK"
