"""CacheManager adapter para BLOPRUDENCIAL mensal (arquivo estático BCB)."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

from .base import BaseCache, CacheConfig, CacheResult
from .bloprudencial import load_bloprudencial_df


BLOPRUDENCIAL_CONFIG = CacheConfig(
    nome="bloprudencial",
    descricao="Conglomerados Prudenciais (BLOPRUDENCIAL) - CSV mensal",
    subdir="bloprudencial",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base="https://github.com/abalroar/tomaconta/releases/download/v1.0-cache",
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período", "DATA_BASE"],
)


class BloprudencialCache(BaseCache):
    """Cache parquet para dados BLOPRUDENCIAL carregados do módulo dedicado."""

    def __init__(self, base_dir: Path):
        super().__init__(BLOPRUDENCIAL_CONFIG, base_dir)

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
