"""Strict, lossless import of the BCB public prudential file.

Unlike the discovery parser, this ingestion never skips a malformed record.
An import replaces an entire reference period: deleted accounts in a corrected
BCB file must not survive a refresh. Official revisions remain read-only.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd

from .bloprudencial import inspect_bloprudencial_csv, build_bloprudencial_url
from .bloprudencial_cache import BloprudencialCache

KEY = ["DATA_BASE", "DOCUMENTO", "COD_CONGL", "CONTA"]


def read_source(path: Path) -> tuple[pd.DataFrame, dict]:
    info = inspect_bloprudencial_csv(path)
    frame = pd.read_csv(path, sep=info["delimiter_used"], encoding=info["encoding_used"],
                        skiprows=info["header_offset"], dtype=str, keep_default_na=False,
                        on_bad_lines="error")
    frame.columns = frame.columns.str.lstrip("#").str.strip()
    required = {*KEY, "CNPJ", "NOME_CONGL", "NOME_CONTA", "SALDO"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Colunas ausentes: {sorted(required - set(frame.columns))}")
    for col in frame:
        frame[col] = frame[col].str.strip()
    if len(frame) != info["line_count"] - info["header_offset"] - 1:
        raise ValueError("Contagem de registros diferente da contagem de linhas do CSV")
    if not frame.DATA_BASE.str.fullmatch(r"\d{4}(0[1-9]|1[0-2])").all():
        raise ValueError("Competência inválida")
    if frame.DATA_BASE.nunique() != 1 or not frame.DOCUMENTO.isin(["4060", "4066"]).all():
        raise ValueError("Esperado um mês e documentos 4060/4066")
    if not frame.CONTA.str.fullmatch(r"(?:\d{8}|\d{10})").all():
        raise ValueError("Código COSIF inválido")
    if frame[KEY].eq("").any().any() or frame.duplicated(KEY).any():
        raise ValueError("Chave contábil vazia ou duplicada")
    # The public source is in reais, decimal comma, without thousands marks.
    if not frame.SALDO.str.fullmatch(r"-?\d+(?:,\d{1,2})?").all():
        raise ValueError("Saldo ausente ou inválido; nenhum saldo foi convertido para zero")
    frame["SALDO"] = pd.to_numeric(frame.SALDO.str.replace(",", ".", regex=False), errors="raise")
    frame["Período"] = frame.DATA_BASE
    manifest = {
        "source_url": build_bloprudencial_url(frame.DATA_BASE.iloc[0]),
        "filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(frame), "period": frame.DATA_BASE.iloc[0], "unit": "BRL",
        "documents": frame.groupby("DOCUMENTO").size().to_dict(),
        "institutions": frame.COD_CONGL.nunique(), "parser": "strict-v1",
        "header": path.read_bytes().decode(info["encoding_used"]).splitlines()[:info["header_offset"]],
    }
    return frame, manifest


def normalize_cache(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in frame.columns:
        if col == "SALDO":
            frame[col] = pd.to_numeric(frame[col], errors="raise")
        else:
            frame[col] = frame[col].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
    frame["CNPJ"] = frame.CNPJ.str.zfill(8)
    frame["Período"] = frame.DATA_BASE
    return frame


def ingest_source(path: Path, root: Path, *, decisions=None) -> dict:
    cache = BloprudencialCache(root)
    cache._assert_writable()
    incoming, manifest = read_source(path)
    existing = normalize_cache(pd.read_parquet(cache.arquivo_dados)) if cache.arquivo_dados.exists() else incoming.iloc[:0]
    previous = existing[existing.DATA_BASE.eq(manifest["period"])]
    comparison = previous.merge(incoming, on=KEY, how="outer", suffixes=("_old", "_new"), indicator=True)
    manifest["comparison"] = {
        "previous_rows": len(previous),
        "added": int(comparison._merge.eq("right_only").sum()),
        "removed": int(comparison._merge.eq("left_only").sum()),
        "changed_balances": int((comparison._merge.eq("both") &
                                 (comparison.SALDO_old - comparison.SALDO_new).abs().gt(.005)).sum()),
    }
    merged = pd.concat([existing[~existing.DATA_BASE.eq(manifest["period"])], incoming], ignore_index=True)
    # Do not silently repair unrelated historical periods during this import.
    # The export rejects any duplicate in its selected institution/periods.
    manifest["historical_duplicate_rows_preserved"] = int(merged.duplicated(KEY).sum())
    merged = merged.sort_values(KEY).reset_index(drop=True)
    # Preserve the original bytes and validate the archived source independently.
    archive_dir = root / "data/cache/bcb_bloprudencial/sources"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{manifest['period']}-{manifest['sha256'][:12]}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(path.name, path.read_bytes())
    with zipfile.ZipFile(archive) as zipped:
        assert hashlib.sha256(zipped.read(path.name)).hexdigest() == manifest["sha256"]
    manifest["archive"] = archive.relative_to(root).as_posix()
    saved = cache.salvar_local(merged, fonte="bcb_cosif", info_extra={"source_import": manifest},
                               metadata_extra={"cosif_decisions": decisions} if decisions else None)
    if not saved.sucesso:
        raise ValueError(saved.mensagem)
    reread = normalize_cache(pd.read_parquet(cache.arquivo_dados))
    pd.testing.assert_frame_equal(merged, reread, check_dtype=False, check_exact=True)
    manifest["cache_sha256"] = hashlib.sha256(cache.arquivo_dados.read_bytes()).hexdigest()
    archive.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
