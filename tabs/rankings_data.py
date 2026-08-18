"""Camada de dados da aba Rankings, isolada do monólito `app1.py`.

Primeira fatia da extração de abas para `tabs/` (padrão iniciado em
`tabs/carteira_4966.py`). Reúne o que responde às perguntas de *cobertura* —
quais períodos existem e de onde vieram — sem depender de Streamlit nem do
restante do app, o que torna a camada testável sem executar a UI inteira.

Regra que este módulo materializa: **o parquet é a fonte de verdade**. O
`metadata.json` é reescrito por `salvar_local()` a cada download ou extração e
pode listar um subconjunto dos períodos; usá-lo para montar filtros fazia a UI
esconder períodos que existiam no dataset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Protocol

import pandas as pd


class CacheLike(Protocol):
    """Contrato mínimo de um cache consumido por esta camada."""

    arquivo_dados: Path
    arquivo_metadata: Path


def _data_file(cache_obj: Optional[CacheLike]) -> Optional[Path]:
    if cache_obj is None:
        return None
    return getattr(cache_obj, "read_data_file", getattr(cache_obj, "arquivo_dados", None))


def _metadata_file(cache_obj: Optional[CacheLike]) -> Optional[Path]:
    if cache_obj is None:
        return None
    return getattr(cache_obj, "read_metadata_file", getattr(cache_obj, "arquivo_metadata", None))


def periodos_do_parquet(cache_obj: Optional[CacheLike]) -> tuple[str, ...]:
    """Períodos presentes no parquet de um cache, sem materializar o dataset.

    Lê apenas a coluna de período (com projeção no parquet) e aceita as duas
    grafias usadas pelas fontes do BCB. Devolve tupla ordenada e sem duplicatas;
    tupla vazia quando não há arquivo legível.
    """
    if cache_obj is None:
        return ()
    arquivo = _data_file(cache_obj)
    if arquivo is None or not arquivo.exists():
        return ()
    for coluna in ("Período", "Periodo"):
        try:
            df_periodos = pd.read_parquet(arquivo, columns=[coluna])
        except Exception:
            continue
        if df_periodos.empty or coluna not in df_periodos.columns:
            continue
        valores = df_periodos[coluna].dropna().astype(str).str.strip()
        return tuple(sorted({valor for valor in valores if valor}))
    return ()


def _chave_cronologica(periodo: str) -> tuple[int, int]:
    """Ordena `trimestre/ano` cronologicamente (ordem textual coloca 4/2025 > 1/2026)."""
    texto = str(periodo).strip()
    if "/" in texto:
        parte, _, ano = texto.partition("/")
        if parte.isdigit() and ano.isdigit():
            valor = int(parte)
            mes = {1: 3, 2: 6, 3: 9, 4: 12}.get(valor, valor)
            return (int(ano), mes)
    if texto.isdigit() and len(texto) == 6:
        return (int(texto[:4]), int(texto[4:]))
    return (0, 0)


def periodo_mais_recente(periodos) -> Optional[str]:
    """Período cronologicamente mais recente da coleção, ou None se vazia."""
    validos = [str(p) for p in (periodos or ()) if str(p).strip()]
    if not validos:
        return None
    return max(validos, key=_chave_cronologica)


def ler_metadata(cache_obj: Optional[CacheLike]) -> dict:
    """Metadata do cache como dicionário; vazio quando ausente ou ilegível."""
    if cache_obj is None:
        return {}
    arquivo = _metadata_file(cache_obj)
    if arquivo is None or not arquivo.exists():
        return {}
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except Exception:
        return {}


def origem_do_cache(cache_obj: Optional[CacheLike]) -> str:
    """Indica se a leitura vem do artefato versionado ou do cache de runtime."""
    if cache_obj is None:
        return "indisponivel"
    arquivo = _data_file(cache_obj)
    if arquivo is None or not arquivo.exists():
        return "indisponivel"
    return "bundled" if "bundled" in arquivo.parts else "runtime"


def cobertura_do_cache(nome_cache: str, cache_obj: Optional[CacheLike]) -> dict[str, Any]:
    """Cobertura real de um cache: períodos, registros, origem e frescor.

    Base da observabilidade exposta na UI. A contagem de períodos vem do parquet;
    o metadata entra apenas para os campos descritivos.
    """
    periodos = periodos_do_parquet(cache_obj)
    metadata = ler_metadata(cache_obj)
    arquivo = _data_file(cache_obj)
    return {
        "cache": nome_cache,
        "existe": bool(arquivo is not None and arquivo.exists()),
        "periodos": periodos,
        "total_periodos": len(periodos),
        "periodo_mais_recente": periodo_mais_recente(periodos),
        "total_registros": metadata.get("total_registros"),
        "origem": origem_do_cache(cache_obj),
        "fonte": metadata.get("fonte") or "—",
        "atualizado_em": str(metadata.get("timestamp_salvamento") or "")[:19] or "—",
    }
