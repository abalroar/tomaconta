"""Balancetes individuais 4010: ZIPs mensais BCB -> parquet -> release/bundle.

Os identificadores são texto; o saldo publicado está em reais. O documento
integra a chave e nenhuma linha é consolidada pelo nome do conglomerado.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import zipfile

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .bloprudencial import _file_sha256, _guess_encoding, _validate_yyyymm
from .bloprudencial_cache import load_bloprudencial_parquet_slice
from .release_config import add_release_cache_buster, build_release_base_url, resolve_release_repo

RELEASE_TAG = "v1.1-cache"
LOADER_VERSION = "cosif_4010_v1"
SOURCE_PAGE = "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"
SOURCE_BASE = "https://www.bcb.gov.br/content/estabilidadefinanceira/cosif"
SOURCE_GROUPS = {
    "Bancos": "BANCOS",
    "Cooperativas-de-credito": "COOPERATIVAS",
    "Administradoras-de-consorcios": "CONSORCIOS",
    "Sociedades": "SOCIEDADES",
    "Instituicoes-em-regime-especial": "LIQUIDACAO",
}
KEY_COLUMNS = ["DATA_BASE", "DOCUMENTO", "CNPJ", "CONTA"]
SOURCE_COLUMNS = [
    "DATA_BASE", "DOCUMENTO", "CNPJ", "AGENCIA", "NOME_INSTITUICAO",
    "COD_CONGL", "NOME_CONGL", "TAXONOMIA", "CONTA", "NOME_CONTA", "SALDO",
]
FGC_ACCOUNTS = {"AR": "3822000003", "VR": "9822500002"}
FGC_CR_NOTE = (
    "Captação de Referência (CR): N/D. A subconta 9.8.2.10.03.00-5 não consta "
    "dos arquivos públicos, limitados ao quarto nível. A conta 9821000008 agrega Fundos Garantidores."
)
CONFIG = CacheConfig(
    nome="cosif_4010", descricao="COSIF 4010 - Balancetes individuais (BCB)",
    subdir="cosif_4010", arquivo_dados="dados.parquet", arquivo_metadata="metadata.json",
    colunas_obrigatorias=[*SOURCE_COLUMNS, "Período", "GRUPO_FONTE", "ARQUIVO_FONTE"],
)


def source_url(periodo: str, grupo: str) -> str:
    return f"{SOURCE_BASE}/{grupo}/{_validate_yyyymm(periodo)}{SOURCE_GROUPS[grupo]}.csv.zip"


def read_source_zip(path: Path, periodo: str, grupo: str) -> tuple[pd.DataFrame, dict]:
    """Lê o CSV sem converter CNPJ/contas; exclui 4016 e demais documentos."""
    periodo = _validate_yyyymm(periodo)
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"{path.name}: esperado um CSV, encontrados {len(members)}")
        with archive.open(members[0]) as stream:
            sample = stream.read(8192)
        encoding = _guess_encoding(sample)
        lines = sample.decode(encoding).splitlines()
        offset = next((i for i, line in enumerate(lines) if line.lstrip('#').startswith('DATA_BASE;')), None)
        if offset is None:
            raise ValueError(f"{path.name}: cabeçalho COSIF ausente")
        with archive.open(members[0]) as stream:
            frame = pd.read_csv(stream, sep=";", encoding=encoding, skiprows=offset,
                                dtype=str, keep_default_na=False)
    frame.columns = frame.columns.str.lstrip("#").str.strip()
    missing = set(SOURCE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name}: colunas ausentes {sorted(missing)}")
    frame = frame[SOURCE_COLUMNS].apply(lambda series: series.str.strip())
    documents = frame.groupby("DOCUMENTO").size().to_dict()
    if not frame["DATA_BASE"].eq(periodo).all():
        raise ValueError(f"{path.name}: competência diferente de {periodo}")
    frame = frame.loc[frame["DOCUMENTO"].eq("4010")].copy()
    if not frame["CNPJ"].str.fullmatch(r"\d{8}").all():
        raise ValueError(f"{path.name}: CNPJ-base inválido")
    if not frame["CONTA"].str.fullmatch(r"\d{10}").all():
        raise ValueError(f"{path.name}: conta COSIF inválida")
    # Vazio permanece ausente; zero publicado permanece zero.
    saldo = frame["SALDO"].replace("", pd.NA).str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    frame["SALDO"] = pd.to_numeric(saldo, errors="raise").astype(float)
    frame["Período"] = periodo
    frame["GRUPO_FONTE"] = grupo
    frame["ARQUIVO_FONTE"] = path.name
    source = {
        "grupo": grupo, "url": source_url(periodo, grupo), "arquivo": path.name,
        "sha256_zip": _file_sha256(path), "csv": members[0],
        "preambulo": lines[:offset], "documentos_na_fonte": documents,
        "registros_4010": len(frame), "instituicoes_4010": frame["CNPJ"].nunique(),
    }
    return frame, source


def validate_frame(frame: pd.DataFrame) -> None:
    missing = set(CONFIG.colunas_obrigatorias) - set(frame.columns)
    if missing or frame.empty:
        raise ValueError(f"4010 vazio ou incompleto: {sorted(missing)}")
    if not frame["DOCUMENTO"].eq("4010").all():
        raise ValueError("O cache 4010 contém outro documento")
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("Chave DATA_BASE/DOCUMENTO/CNPJ/CONTA duplicada")
    if not frame["DATA_BASE"].eq(frame["Período"]).all():
        raise ValueError("DATA_BASE e Período divergentes")


def coverage(frame: pd.DataFrame) -> dict:
    output = {}
    for period, data in frame.groupby("DATA_BASE", sort=True):
        output[period] = {
            "registros": len(data), "instituicoes": data["CNPJ"].nunique(),
            "contas": data["CONTA"].nunique(), "saldos_ausentes": int(data["SALDO"].isna().sum()),
            "grupos": data.groupby("GRUPO_FONTE")["CNPJ"].nunique().to_dict(),
            "fgc": {label: {"conta": account, "instituicoes": data.loc[
                data["CONTA"].eq(account) & data["SALDO"].notna(), "CNPJ"].nunique()}
                for label, account in FGC_ACCOUNTS.items()},
        }
    return output


class Cosif4010Cache(BaseCache):
    """Mesmo contrato CacheManager; publicação bundled prevalece sobre runtime antigo."""
    def __init__(self, base_dir: Path):
        # Release dedicado: um TOMACONTA_RELEASE_TAG legado não muda esta fonte.
        self.release_tag = os.getenv("TOMACONTA_COSIF_4010_RELEASE_TAG") or RELEASE_TAG
        base_url = build_release_base_url(resolve_release_repo(), self.release_tag)
        super().__init__(replace(CONFIG, github_url_base=base_url), Path(base_dir))

    def _use_runtime(self) -> bool:
        """Só uma extração sobre a versão publicada pode preceder o bundle."""
        if not self.arquivo_dados_runtime.exists():
            return False
        bundled_meta = self.bundled_dir / "metadata.json"
        if not (self.bundled_dir / "dados.parquet").exists():
            return True
        try:
            runtime = json.loads(self.arquivo_metadata_runtime.read_text())
            bundled = json.loads(bundled_meta.read_text())
            return (
                runtime.get("schema_version") == LOADER_VERSION
                and set(runtime.get("periodos", ())).issuperset(bundled["periodos"])
                and bundled["sha256"] in (runtime.get("sha256"), runtime.get("baseline_sha256"))
                and runtime.get("sha256") == _file_sha256(self.arquivo_dados_runtime)
            )
        except (OSError, ValueError, KeyError):
            return False

    @property
    def arquivo_dados(self) -> Path:
        bundled = self.bundled_dir / self.config.arquivo_dados
        return self.arquivo_dados_runtime if self._use_runtime() or not bundled.exists() else bundled

    @property
    def arquivo_metadata(self) -> Path:
        if not self._use_runtime() and (self.bundled_dir / self.config.arquivo_dados).exists():
            return self.bundled_dir / self.config.arquivo_metadata
        return self.arquivo_metadata_runtime

    def _validar_dados(self, dados):
        try:
            validate_frame(dados)
            return True, "OK"
        except (ValueError, AttributeError, KeyError) as exc:
            return False, str(exc)

    def get_info(self):
        info = super().get_info()
        if self.arquivo_dados.exists() and self.arquivo_metadata.exists():
            metadata = json.loads(self.arquivo_metadata.read_text())
            info.update({key: metadata.get(key) for key in (
                "timestamp_salvamento", "fonte", "total_registros", "total_periodos", "periodos",
            )})
            info.update(existe=True, tamanho_bytes=self.arquivo_dados.stat().st_size,
                        release_tag=self.release_tag, sha256=metadata.get("sha256"))
        return info

    def carregar(self, forcar_remoto=False) -> CacheResult:
        try:
            if forcar_remoto:
                result = self.baixar_remoto()
                if not result.sucesso:
                    return result
                return self.salvar_local(result.dados, result.fonte, result.metadata.get("extra"))
            self.ensure_available()
            return self.carregar_local()
        except Exception as exc:
            return CacheResult(False, str(exc))

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        try:
            periodo = _validate_yyyymm(periodo)
            root = Path(kwargs.get("cache_dir", self.base_dir / "data/cache/bcb_cosif_4010"))
            root.mkdir(parents=True, exist_ok=True)
            frames, sources = [], []
            for grupo, suffix in SOURCE_GROUPS.items():
                path = root / f"{periodo}{suffix}.csv.zip"
                if kwargs.get("force_refresh", False) or not path.exists():
                    response = requests.get(source_url(periodo, grupo), timeout=(15, 120))
                    response.raise_for_status()
                    # Valida ZIP/CRC antes de substituir o arquivo de origem.
                    with zipfile.ZipFile(BytesIO(response.content)) as archive:
                        if archive.testzip() is not None:
                            raise ValueError(f"ZIP corrompido: {path.name}")
                    with tempfile.NamedTemporaryFile(dir=root, delete=False) as temp:
                        temp.write(response.content)
                    Path(temp.name).replace(path)
                data, source = read_source_zip(path, periodo, grupo)
                frames.append(data)
                sources.append(source)
            frame = pd.concat(frames, ignore_index=True)
            validate_frame(frame)
            return CacheResult(True, f"4010 {periodo}: {len(frame):,} registros", frame,
                               {"fontes": sources, "cobertura": coverage(frame)}, "bcb_cosif")
        except Exception as exc:
            return CacheResult(False, f"Extração 4010 falhou: {exc}")

    def salvar_local(self, dados, fonte="bcb_cosif", info_extra=None):
        bundled_meta = self.bundled_dir / "metadata.json"
        baseline = json.loads(bundled_meta.read_text()).get("sha256") if bundled_meta.exists() else None
        result = super().salvar_local(dados, fonte, info_extra)
        if result.sucesso:
            result.metadata.update({
                "schema_version": LOADER_VERSION, "documento": "4010", "perimetro": "individual",
                "unidade": "R$", "release_tag": self.release_tag,
                "sha256": _file_sha256(self.arquivo_dados_runtime), "cobertura": coverage(dados),
                "baseline_sha256": baseline,
            })
            self.arquivo_metadata_runtime.write_text(json.dumps(result.metadata, ensure_ascii=False, indent=2)+"\n")
        return result

    def baixar_remoto(self) -> CacheResult:
        try:
            base = self.config.github_url_base
            url = add_release_cache_buster(f"{base}/cosif_4010_metadata.json", LOADER_VERSION)
            response = requests.get(url, timeout=(15, 60))
            response.raise_for_status()
            metadata = response.json()
            if metadata.get("schema_version") != LOADER_VERSION or "202606" not in metadata.get("periodos", []):
                raise ValueError("Release 4010 incompatível ou sem a competência inicial 202606")
            url = add_release_cache_buster(f"{base}/cosif_4010_dados.parquet", metadata["sha256"])
            response = requests.get(url, timeout=(15, 120))
            response.raise_for_status()
            import hashlib
            if hashlib.sha256(response.content).hexdigest() != metadata["sha256"]:
                raise ValueError("SHA-256 do parquet difere do metadata publicado")
            frame = pd.read_parquet(BytesIO(response.content))
            validate_frame(frame)
            if sorted(frame["Período"].unique()) != metadata["periodos"] or len(frame) != metadata["total_registros"]:
                raise ValueError("Cobertura do parquet difere do metadata publicado")
            return CacheResult(True, f"4010 obtido de {self.release_tag}", frame, metadata, "github_releases")
        except Exception as exc:
            return CacheResult(False, f"Download do cache 4010 falhou: {exc}")

    def ensure_available(self) -> None:
        valid = False
        if self.arquivo_dados.exists() and self.arquivo_metadata.exists():
            try:
                metadata = json.loads(self.arquivo_metadata.read_text())
                valid = (
                    metadata.get("schema_version") == LOADER_VERSION
                    and "202606" in metadata.get("periodos", [])
                    and metadata.get("sha256") == _file_sha256(self.arquivo_dados)
                )
            except (ValueError, OSError):
                pass
        if not valid:
            if (self.bundled_dir / "dados.parquet").exists():
                raise RuntimeError("Bundle 4010 sem metadata compatível; verificar a publicação")
            result = self.baixar_remoto()
            if not result.sucesso:
                raise RuntimeError(result.mensagem)
            saved = self.salvar_local(result.dados, result.fonte, result.metadata.get("extra"))
            if not saved.sucesso:
                raise RuntimeError(saved.mensagem)

    def available_periods(self) -> list[str]:
        self.ensure_available()
        return json.loads(self.arquivo_metadata.read_text())["periodos"]

    def load_slice(self, periodos, *, contas=None, columns=None) -> pd.DataFrame:
        self.ensure_available()
        return load_bloprudencial_parquet_slice(
            self, periodos_yyyymm=periodos, contas_cosif=contas,
            documentos=("4010",), columns=columns,
        )


def fgc_reference_frame(cache: Cosif4010Cache, periods) -> pd.DataFrame:
    """Universo completo; saldos principais e controles separados, sem imputação."""
    columns = ["DATA_BASE", "CNPJ", "NOME_INSTITUICAO", "GRUPO_FONTE"]
    entities = cache.load_slice(periods, columns=columns).drop_duplicates()
    accounts = {**FGC_ACCOUNTS, "AR - controle": "9822000007", "VR - controle": "3822500008"}
    values = cache.load_slice(periods, contas=tuple(accounts.values()), columns=[*KEY_COLUMNS, "SALDO"])
    for label, account in accounts.items():
        selected = values.loc[values["CONTA"].eq(account), ["DATA_BASE", "CNPJ", "SALDO"]]
        entities = entities.merge(selected.rename(columns={"SALDO": label}),
                                  on=["DATA_BASE", "CNPJ"], how="left", validate="one_to_one")
    entities["CR"] = float("nan")
    return entities.sort_values(["DATA_BASE", "NOME_INSTITUICAO", "CNPJ"]).reset_index(drop=True)


def merge_release_manifest(remote: dict, cache: Cosif4010Cache) -> dict:
    """Acrescenta somente o 4010; preserva contratos/períodos de todos os demais caches."""
    from copy import deepcopy
    if not isinstance(remote.get("caches"), dict):
        raise ValueError("Manifest remoto sem catálogo de caches; publicação interrompida")
    metadata = json.loads(cache.arquivo_metadata.read_text())
    payload = deepcopy(remote)
    payload["caches"]["cosif_4010"] = {
        "cache": "cosif_4010", "exists": True, "source": "github_releases",
        "timestamp": metadata["timestamp_salvamento"],
        "max_period": max(metadata["periodos"]), "max_period_ref": max(metadata["periodos"]),
        "period_count": len(metadata["periodos"]), "record_count": metadata["total_registros"],
        "sha256": metadata["sha256"], "schema_version": LOADER_VERSION,
        "release_tag": cache.release_tag, "release_base_url": cache.config.github_url_base,
        "data_asset": "cosif_4010_dados.parquet", "metadata_asset": "cosif_4010_metadata.json",
        "perimetro": "individual", "unidade": "R$", "cobertura": metadata["cobertura"],
    }
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload.setdefault("expected_periods_by_cache", {})["cosif_4010"] = max(metadata["periodos"])
    return payload
