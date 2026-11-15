"""Consulta da DRE IFData, com identidade, unidade e recuperação explícitas.

Os endpoints de valores do IFData fornecem reais. O motor gerencial recebe
milhares de reais: a conversão acontece somente nesta fronteira de entrada.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

import pandas as pd
import requests

from utils.ifdata_cache.ifdata_web import BASE_URL as WEB_URL, IFDataWeb, SELECTORS
from utils.ifdata_cache.institution_registry import registry_name_map, validate_institution_names
from utils.ifdata_cache.institutions import normalize_institution_code

OLINDA_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
SOURCE_PAGE = "https://www3.bcb.gov.br/ifdata/"
CACHE_TTL_SECONDS = 6 * 3600
IDENTIFIERS = {"CodInst", "Instituição", "Período", "TipoInstituicao", "AnoMes"}


def _validate_selection(period: str, kind: int) -> None:
    if not re.fullmatch(r"202[5-9](03|06|09|12)|2030(03|06|09|12)", str(period)):
        raise ValueError("A DRE gerencial utiliza competências trimestrais a partir de 2025.")
    if kind not in (1, 3):
        raise ValueError("Selecione o perímetro prudencial ou individual.")


def period_label(period: str) -> str:
    months = {"03": "Mar", "06": "Jun", "09": "Set", "12": "Dez"}
    return f"{months[period[4:6]]}/{period[2:4]}"


def _period_code(value) -> str | None:
    text = str(value)
    match = re.fullmatch(r"([1-4])/([0-9]{4})", text)
    if match:
        return f"{match[2]}{int(match[1]) * 3:02d}"
    return text if re.fullmatch(r"[0-9]{4}(03|06|09|12)", text) else None


def _published_raw(kind: int, base_dir: Path) -> tuple[pd.DataFrame, dict]:
    from utils.ifdata_cache import CacheManager

    cache = CacheManager(base_dir=base_dir).get_cache("dre" if kind == 1 else "dre_individual")
    path = cache.arquivo_dados
    if not path.exists():
        return pd.DataFrame(), {}
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError):
        return pd.DataFrame(), {}
    try:
        meta = json.loads(cache.arquivo_metadata.read_text()) if cache.arquivo_metadata.exists() else {}
    except (OSError, ValueError):
        meta = {}
    return frame, {"published_file": str(path), "published_metadata": meta,
                   "published_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def available_periods(kind: int, base_dir: Path) -> list[str]:
    """O catálogo oficial define o corte; a base publicada permite uso offline."""
    if kind not in (1, 3):
        raise ValueError("Perímetro inválido")
    periods = set()
    try:
        response = requests.get(f"{WEB_URL}/relatorios2025a2030", timeout=(8, 25))
        response.raise_for_status()
        for item in response.json():
            for file in item.get("files", []):
                report = file.get("trel", {})
                if report.get("n") == "Demonstração de Resultado" and {"id": SELECTORS[kind]} in report.get("s", []):
                    periods.add(str(item["dt"]))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    frame, _ = _published_raw(kind, base_dir)
    if "Período" in frame:
        periods.update(p for p in frame["Período"].map(_period_code).dropna() if p >= "202503")
    return sorted(periods, reverse=True)


def normalize_reais(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    """Contrato explícito R$ -> R$ mil, mantendo células ausentes e zero."""
    if frame.attrs.get("monetary_unit") == "R$ mil":
        raise ValueError("A fonte já está em R$ mil; conversão duplicada rejeitada")
    result = frame.copy()
    for col in result.columns:
        if col not in IDENTIFIERS and not str(col).startswith("__"):
            result[col] = pd.to_numeric(result[col], errors="raise") / 1000.0
    result["__arquivo_origem"] = source
    result["__linha_origem"] = result["CodInst"].astype(str)
    result.attrs["monetary_unit"] = "R$ mil"
    return result


def _wide_values(values: pd.DataFrame, registry: pd.DataFrame, period: str, kind: int) -> pd.DataFrame:
    required = {"CodInst", "NomeColuna", "Saldo", "AnoMes"}
    if values.empty or not required.issubset(values.columns):
        raise ValueError("Relatório vazio ou incompleto no Banco Central")
    if not values["AnoMes"].astype(str).eq(period).all():
        raise ValueError("Competência divergente na resposta do Banco Central")
    if "TipoInstituicao" in values and not pd.to_numeric(values["TipoInstituicao"]).eq(kind).all():
        raise ValueError("Perímetro divergente na resposta do Banco Central")
    data = values.copy()
    data["CodInst"] = data["CodInst"].map(normalize_institution_code)
    data["NomeColuna"] = data["NomeColuna"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    data["Saldo"] = pd.to_numeric(data["Saldo"], errors="raise")
    data = data[["CodInst", "NomeColuna", "Saldo"]].drop_duplicates()
    if data.duplicated(["CodInst", "NomeColuna"]).any():
        raise ValueError("Rubricas conflitantes para a mesma instituição; consulta não agregada")
    # pivot, sem soma: ausências não se transformam em zero.
    wide = data.pivot(index="CodInst", columns="NomeColuna", values="Saldo").reset_index()
    names = registry_name_map(registry)
    wide["Instituição"] = wide["CodInst"].map(names)
    if wide["Instituição"].isna().any():
        raise ValueError("Cadastro oficial não cobre todas as instituições da DRE")
    wide["Período"] = f"{int(period[4:6]) // 3}/{period[:4]}"
    wide.columns.name = None
    return wide


def _olinda_values(period: str, kind: int, report: int) -> tuple[pd.DataFrame, str]:
    url = f"{OLINDA_URL}/IfDataValores(AnoMes={period},TipoInstituicao={kind},Relatorio='{report}')"
    response = requests.get(url, params={"$format": "json", "$top": 500000}, timeout=(8, 30))
    response.raise_for_status()
    payload = response.json()
    if payload.get("@odata.nextLink") or payload.get("odata.nextLink"):
        raise ValueError("Resposta paginada incompleta; utilizar API IFData")
    return pd.DataFrame(payload["value"]), response.url


def _query_olinda(period: str, kind: int) -> tuple[pd.DataFrame, dict]:
    values, url = _olinda_values(period, kind, 4)
    response = requests.get(f"{OLINDA_URL}/IfDataCadastro(AnoMes={period})",
                            params={"$format": "json", "$top": 50000}, timeout=(8, 30))
    response.raise_for_status()
    payload = response.json()
    if payload.get("@odata.nextLink") or payload.get("odata.nextLink"):
        raise ValueError("Cadastro paginado incompleto")
    registry = pd.DataFrame(payload["value"])
    if "Data" in registry and not registry["Data"].astype(str).eq(period).all():
        raise ValueError("Cadastro com competência divergente")
    wide = _wide_values(values, registry, period, kind)
    sources = [url, response.url]
    try:
        summary, summary_url = _olinda_values(period, kind, 1)
        wide = _attach_assets(wide, summary, period, kind)
        sources.append(summary_url)
    except (requests.RequestException, ValueError, KeyError):
        pass  # Ativo total é contexto opcional, permanece N/D se não publicado.
    return wide, {"api": "Olinda / IFData", "source_urls": sources, "report_urls": [url]}


def _attach_assets(wide: pd.DataFrame, summary: pd.DataFrame, period: str, kind: int) -> pd.DataFrame:
    assets = summary[summary["NomeColuna"].eq("Ativo Total")].copy()
    if assets.empty or "Ativo Total" in wide:
        return wide
    if not assets["AnoMes"].astype(str).eq(period).all():
        raise ValueError("Competência divergente no ativo total")
    if "TipoInstituicao" in assets and not pd.to_numeric(assets["TipoInstituicao"]).eq(kind).all():
        raise ValueError("Perímetro divergente no ativo total")
    assets["CodInst"] = assets["CodInst"].map(normalize_institution_code)
    assets = assets[["CodInst", "Saldo"]].drop_duplicates()
    return wide.merge(assets.rename(columns={"Saldo": "Ativo Total"}), on="CodInst", how="left", validate="one_to_one")


def _query_web(period: str, kind: int) -> tuple[pd.DataFrame, dict]:
    # Diretório temporário força consulta nova no botão Atualizar e no vencimento
    # do TTL. Os JSON persistidos do backend geral não são tratados como novos.
    with tempfile.TemporaryDirectory(prefix="dre-bcb-") as temporary:
        source = IFDataWeb(period, Path(temporary))
        wide = _wide_values(source.valores(4, kind), source.cadastro_frame(kind), period, kind)
        report_urls = [item["url"] for name, item in source.sources.items() if name.startswith("dados")]
        try:
            wide = _attach_assets(wide, source.valores(1, kind), period, kind)
        except (requests.RequestException, ValueError, KeyError):
            pass
        return wide, {"api": "IFData / API do site BCB", "source_urls": [s["url"] for s in source.sources.values()],
                      "report_urls": report_urls,
                      "source_files": source.sources}


def _paths(period: str, kind: int, base_dir: Path) -> tuple[Path, Path]:
    folder = base_dir / "data/cache/dre_consulta_bcb" / str(kind)
    return folder / f"{period}.parquet", folder / f"{period}.json"


def _read_saved(period: str, kind: int, base_dir: Path) -> tuple[pd.DataFrame, dict]:
    parquet, manifest = _paths(period, kind, base_dir)
    try:
        meta = json.loads(manifest.read_text())
        if (meta["period"] != period or meta["kind"] != kind or meta["unit"] != "R$ mil"
                or meta["sha256"] != hashlib.sha256(parquet.read_bytes()).hexdigest()):
            raise ValueError("Consulta persistida divergente")
        frame = pd.read_parquet(parquet)
        registry_name_map(frame)
        if not frame["Período"].map(_period_code).eq(period).all():
            raise ValueError("Competência divergente na consulta persistida")
        queried = datetime.fromisoformat(meta["queried_at_utc"])
        if queried.tzinfo is None:
            raise ValueError("Consulta persistida sem fuso horário")
        return frame, meta
    except (OSError, ValueError, KeyError, TypeError):
        return pd.DataFrame(), {}


def _save(frame: pd.DataFrame, meta: dict, base_dir: Path) -> None:
    parquet, manifest = _paths(meta["period"], meta["kind"], base_dir)
    parquet.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parquet.parent) as temporary:
        temp_data, temp_meta = Path(temporary) / "dados.parquet", Path(temporary) / "meta.json"
        frame.to_parquet(temp_data, index=False)
        meta["sha256"] = hashlib.sha256(temp_data.read_bytes()).hexdigest()
        temp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        temp_data.replace(parquet)
        temp_meta.replace(manifest)


def consult_dre(period: str, kind: int, base_dir: Path, *, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    _validate_selection(period, kind)
    base_dir = Path(base_dir)
    saved, saved_meta = _read_saved(period, kind, base_dir)
    if not refresh and not saved.empty:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(saved_meta["queried_at_utc"])).total_seconds()
        if 0 <= age < CACHE_TTL_SECONDS:
            return saved, {**saved_meta, "fallback": False}
    errors = []
    for query in (_query_olinda, _query_web):
        try:
            raw, provenance = query(period, kind)
            frame = normalize_reais(raw, provenance.get("report_urls", provenance["source_urls"])[0])
            meta = {**provenance, "period": period, "kind": kind, "unit": "R$ mil", "source_unit": "R$",
                    "queried_at_utc": datetime.now(timezone.utc).isoformat(), "fallback": False}
            try:
                _save(frame, meta, base_dir)
            except OSError:
                meta["persistence_available"] = False
            return frame, meta
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{query.__name__}: {exc}")
    if not saved.empty:
        return saved, {**saved_meta, "fallback": True, "errors": errors}
    raw, published_meta = _published_raw(kind, base_dir)
    if "Período" in raw:
        raw = raw[raw["Período"].map(_period_code).eq(period)].copy()
    else:
        raw = pd.DataFrame()
    if raw.empty:
        raise ValueError("O Banco Central está indisponível e não há DRE validada para esta competência e perímetro.")
    valid, reason = validate_institution_names(raw)
    if not valid:
        raise ValueError(reason)
    frame = normalize_reais(raw, published_meta["published_file"])
    return frame, {**published_meta, "period": period, "kind": kind, "unit": "R$ mil", "source_unit": "R$",
                   "queried_at_utc": None, "api": "Base IFData publicada", "fallback": True, "errors": errors,
                   "source_urls": [SOURCE_PAGE]}


def published_history(kind: int, base_dir: Path) -> pd.DataFrame:
    raw, meta = _published_raw(kind, Path(base_dir))
    if "Período" not in raw:
        return pd.DataFrame()
    raw = raw[raw["Período"].map(_period_code).fillna("").ge("202503")].copy()
    if raw.empty:
        return raw
    valid, reason = validate_institution_names(raw)
    if not valid:
        raise ValueError(reason)
    return normalize_reais(raw, meta["published_file"])
