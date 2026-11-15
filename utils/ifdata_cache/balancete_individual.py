"""Balancetes individuais (COSIF 4010) para o Balanço e a DRE por instituição.

Guarda só fins de trimestre e os grupos das demonstrações. O histórico tem milhões de
linhas: a leitura é sempre por instituição e nenhuma etapa o carrega inteiro em memória.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .base import BaseCache, CacheConfig, CacheResult
from .cosif_4010 import Cosif4010Cache
from .release_config import get_release_config

COLUMNS = ["DATA_BASE", "Período", "CNPJ", "CONTA", "NOME_CONTA", "SALDO", "NOME_INSTITUICAO", "TAXONOMIA", "GRUPO_FONTE"]
STATEMENT_GROUPS = tuple("124678")
QUARTER_ENDS = ("03", "06", "09", "12")
ROW_GROUP = 50_000
CONFIG = CacheConfig(
    nome="balancete_individual", descricao="Balancetes individuais (COSIF 4010) - fins de trimestre",
    subdir="balancete_individual", arquivo_dados="dados.parquet", arquivo_metadata="metadata.json",
    github_url_base=None, max_idade_horas=168.0, colunas_obrigatorias=["Período", "DATA_BASE"],
)


def statement_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[frame.CONTA.str[0].isin(STATEMENT_GROUPS), COLUMNS]


def write_table(frames, path: Path) -> None:
    """Ordena por instituição: a leitura filtrada só abre os blocos daquele CNPJ."""
    table = pa.concat_tables(frames, promote_options="permissive").sort_by([("CNPJ", "ascending"), ("DATA_BASE", "ascending"), ("CONTA", "ascending")])
    pq.write_table(table, path, compression="zstd", row_group_size=ROW_GROUP)


def file_metadata(path: Path, *, fonte: str = "bcb_cosif") -> dict:
    periods = pq.read_table(path, columns=["DATA_BASE"]).column("DATA_BASE")
    unique = sorted(str(value) for value in pc.unique(periods).to_pylist())
    return {"fonte": fonte, "periodos": unique, "total_periodos": len(unique), "total_registros": len(periods), "colunas": COLUMNS}


class BalanceteIndividualCache(BaseCache):
    def __init__(self, base_dir: Path):
        release = get_release_config()
        super().__init__(replace(CONFIG, github_url_base=release.release_base_url), base_dir)

    def baixar_remoto(self) -> CacheResult:
        return CacheResult(sucesso=False, mensagem="A versão publicada é adotada pela conferência de release", fonte="nenhum")

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        result = Cosif4010Cache(self.base_dir).extrair_periodo(periodo, **kwargs)
        if not result.sucesso:
            return result
        return CacheResult(True, result.mensagem, statement_rows(result.dados), result.metadata, result.fonte)

    @property
    def read_data_file(self) -> Path:
        return self.arquivo_dados

    def available_periods(self) -> list[str]:
        if not self.existe_leitura():
            return []
        return sorted(pc.unique(pq.read_table(self.arquivo_dados, columns=["DATA_BASE"]).column("DATA_BASE")).to_pylist())

    def catalog(self) -> pd.DataFrame:
        """Instituições e datas, sem ler os saldos."""
        table = pq.read_table(self.arquivo_dados, columns=["CNPJ", "NOME_INSTITUICAO", "DATA_BASE"])
        return table.group_by(["CNPJ", "NOME_INSTITUICAO", "DATA_BASE"]).aggregate([]).to_pandas()

    def load_institution(self, code: str, periods=None) -> pd.DataFrame:
        filters = [("CNPJ", "=", str(code))]
        if periods:
            filters.append(("DATA_BASE", "in", list(periods)))
        return pq.read_table(self.arquivo_dados, filters=filters).to_pandas()

    def load_period(self, period: str, columns=None) -> pd.DataFrame:
        return pq.read_table(self.arquivo_dados, columns=columns, filters=[("DATA_BASE", "=", period)]).to_pandas()

    def add_period(self, frame: pd.DataFrame) -> dict:
        """Substitui a competência e grava a nova geração sem carregar o restante em pandas."""
        period = str(frame.DATA_BASE.iloc[0])
        tables = [pa.Table.from_pandas(frame[COLUMNS], preserve_index=False)]
        if self.existe_leitura():
            tables.insert(0, pq.read_table(self.arquivo_dados, filters=[("DATA_BASE", "!=", period)]))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="balancete-", dir=self.cache_dir) as directory:
            candidate = Path(directory) / "novo.parquet"
            write_table(tables, candidate)
            metadata = file_metadata(candidate)
            result = self.salvar_arquivo_local(candidate, metadata)
        if not result.sucesso:
            raise ValueError(result.mensagem)
        return metadata


def adopt_file(cache, source: Path, metadata_path: Path) -> None:
    """Promove uma geração pronta, conservando os bytes, sem passar por pandas."""
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    metadata.pop("integridade", None)
    metadata.pop("sha256", None)
    result = cache.salvar_arquivo_local(Path(source), metadata)
    if not result.sucesso:
        raise ValueError(result.mensagem)
