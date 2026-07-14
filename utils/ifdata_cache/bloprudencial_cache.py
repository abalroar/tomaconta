"""CacheManager adapter para BLOPRUDENCIAL mensal (arquivo estático BCB)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd

from .base import BaseCache, CacheConfig, CacheResult
from .bloprudencial import load_bloprudencial_df
from .release_config import get_release_config


BLOPRUDENCIAL_CONFIG = CacheConfig(
    nome="bloprudencial",
    descricao="Conglomerados Prudenciais (BLOPRUDENCIAL) - CSV mensal",
    subdir="bloprudencial",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período", "DATA_BASE"],
)


class BloprudencialCache(BaseCache):
    """Cache parquet para dados BLOPRUDENCIAL carregados do módulo dedicado."""

    def __init__(self, base_dir: Path):
        release_config = get_release_config()
        runtime_config = replace(BLOPRUDENCIAL_CONFIG, github_url_base=release_config.release_base_url)
        super().__init__(runtime_config, base_dir)

    def baixar_remoto(self) -> CacheResult:
        # Sem artefato remoto publicado por padrão; o fluxo principal é extração local.
        return CacheResult(
            sucesso=False,
            mensagem="Cache BLOPRUDENCIAL remoto não configurado",
            fonte="nenhum",
        )

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        force_refresh = bool(kwargs.get("force_refresh", False))
        base_cache_dir = kwargs.get("cache_dir", self.base_dir / "data" / "cache" / "bcb_bloprudencial")

        try:
            df = load_bloprudencial_df(periodo, cache_dir=base_cache_dir, force_refresh=force_refresh)
            if "Período" not in df.columns:
                df["Período"] = str(periodo)
            return CacheResult(
                sucesso=True,
                mensagem=f"Extração BLOPRUDENCIAL concluída para {periodo}",
                dados=df,
                fonte="api",
            )
        except Exception as exc:
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao extrair BLOPRUDENCIAL {periodo}: {exc}",
                fonte="nenhum",
            )

    def extrair_periodos(self, periodos: List[str], **kwargs) -> CacheResult:
        dfs = []
        for per in periodos:
            res = self.extrair_periodo(per, **kwargs)
            if not res.sucesso or res.dados is None:
                return res
            dfs.append(res.dados)

        if not dfs:
            return CacheResult(sucesso=False, mensagem="Nenhum período extraído", fonte="nenhum")

        merged = pd.concat(dfs, ignore_index=True)
        return CacheResult(
            sucesso=True,
            mensagem=f"Extração BLOPRUDENCIAL concluída ({len(periodos)} competências)",
            dados=merged,
            fonte="api",
        )


def load_bloprudencial_parquet_slice(
    cache: BaseCache,
    *,
    periodos_yyyymm: Sequence[str],
    contas_cosif: Optional[Sequence[str]] = None,
    documentos: Optional[Sequence[str]] = None,
    columns: Optional[Sequence[str]] = None,
    batch_size: int = 32_768,
) -> pd.DataFrame:
    """Lê um recorte do parquet BLOPRUDENCIAL sem materializar o arquivo inteiro.

    O parquet histórico pode ocupar centenas de MiB quando convertido para
    pandas, apesar de ser pequeno em disco. A leitura em batches mantém apenas
    as competências/contas/cadernos pedidos e também aceita colunas numéricas
    ou strings canônicas nos parquets legados.
    """
    parquet_path = cache.arquivo_dados
    requested_periods = tuple(
        value
        for value in ("".join(ch for ch in str(item) if ch.isdigit())[:6] for item in periodos_yyyymm)
        if len(value) == 6
    )
    requested_accounts = tuple(
        value
        for value in ("".join(ch for ch in str(item) if ch.isdigit()) for item in (contas_cosif or ()))
        if value
    )
    requested_documents = tuple(
        value
        for value in ("".join(ch for ch in str(item) if ch.isdigit()) for item in (documentos or ()))
        if value
    )

    if not requested_periods:
        raise ValueError("periodos_yyyymm deve conter ao menos uma competência YYYYMM")
    if not parquet_path.exists():
        return pd.DataFrame(columns=list(columns or ()))

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(parquet_path)
    schema = parquet_file.schema_arrow
    schema_names = set(schema.names)
    period_column = next(
        (name for name in ("DATA_BASE", "Data_Base", "data_base", "Período") if name in schema_names),
        None,
    )
    account_column = next(
        (name for name in ("CONTA", "Conta", "codigo_conta", "COD_CONTA") if name in schema_names),
        None,
    )
    document_column = next(
        (name for name in ("DOCUMENTO", "Documento", "doc", "cadoc") if name in schema_names),
        None,
    )
    if period_column is None:
        raise ValueError("parquet BLOPRUDENCIAL sem coluna de competência")
    if requested_accounts and account_column is None:
        return pd.DataFrame(columns=list(columns or ()))
    if requested_documents and document_column is None:
        return pd.DataFrame(columns=list(columns or ()))

    requested_columns = schema.names if columns is None else list(columns)
    output_columns = [name for name in requested_columns if name in schema_names]
    filter_columns = [period_column]
    if requested_accounts and account_column is not None:
        filter_columns.append(account_column)
    if requested_documents and document_column is not None:
        filter_columns.append(document_column)
    read_columns = list(dict.fromkeys([*output_columns, *filter_columns]))
    if not output_columns:
        return pd.DataFrame(columns=list(columns or ()))

    def _digits_mask(
        batch: pa.RecordBatch,
        column_name: str,
        accepted: Sequence[str],
        *,
        max_length: Optional[int] = None,
    ):
        values = batch.column(batch.schema.get_field_index(column_name))
        as_text = pc.cast(values, pa.string())
        canonical = pc.replace_substring_regex(as_text, pattern=r"\D", replacement="")
        if max_length is not None:
            canonical = pc.utf8_slice_codeunits(canonical, start=0, stop=int(max_length))
        return pc.is_in(canonical, value_set=pa.array(list(accepted), type=pa.string()))

    frames: list[pd.DataFrame] = []
    for batch in parquet_file.iter_batches(
        batch_size=max(1, int(batch_size)),
        columns=read_columns,
        use_threads=False,
    ):
        mask = _digits_mask(batch, period_column, requested_periods, max_length=6)
        if requested_accounts and account_column is not None:
            mask = pc.and_(mask, _digits_mask(batch, account_column, requested_accounts))
        if requested_documents and document_column is not None:
            mask = pc.and_(mask, _digits_mask(batch, document_column, requested_documents))
        filtered = batch.filter(pc.fill_null(mask, False))
        if filtered.num_rows == 0:
            continue
        frame = filtered.select(output_columns).to_pandas()
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=output_columns)
    return pd.concat(frames, ignore_index=True, copy=False)
