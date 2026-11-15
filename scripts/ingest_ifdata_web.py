#!/usr/bin/env python3
"""Atualiza os dez caches trimestrais com os arquivos oficiais do site IF.data.

Uso: python scripts/ingest_ifdata_web.py 202606
Preserva o histórico e deixa publicação/derivados para a validação final.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.ifdata_cache import CacheManager
from utils.ifdata_cache.ifdata_web import get_web_source

CACHES = ["principal", "principal_individual", "capital", "ativo", "passivo", "dre",
          "dre_individual", "carteira_pf", "carteira_pj", "carteira_instrumentos"]


def ingest(base_dir: Path, periodo: str):
    os.environ["TOMACONTA_IFDATA_SOURCE"] = "web"
    os.environ["TOMACONTA_IFDATA_WEB_DIR"] = str(base_dir / "data/cache/bcb_ifdata_web")
    get_web_source.cache_clear()
    manager = CacheManager(base_dir)
    results = []
    for name in CACHES:
        cache = manager.get_cache(name)
        if not cache.existe():
            baseline = cache.carregar_local() if cache.existe_leitura() else cache.baixar_remoto()
            if not baseline.sucesso:
                raise RuntimeError(f"Histórico anterior indisponível para {name}: {baseline.mensagem}")
            saved = cache.salvar_local(baseline.dados, baseline.fonte)
            if not saved.sucesso:
                raise RuntimeError(saved.mensagem)
        before = cache.carregar_local()
        if not before.sucesso:
            raise RuntimeError(before.mensagem)
        historical_periods = set(before.dados["Período"].unique())
        result = manager.extrair_periodos_com_salvamento(name, [periodo], modo="incremental")
        if not result.sucesso:
            raise RuntimeError(f"{name}: {result.mensagem}")
        verified = cache.carregar_local()
        if not verified.sucesso or not historical_periods.issubset(verified.metadata["periodos"]):
            raise RuntimeError(f"Histórico não preservado: {name}")
        quarter = f"{int(periodo[4:]) // 3}/{periodo[:4]}"
        selected = verified.dados.loc[verified.dados["Período"].eq(quarter)]
        if selected.empty or selected.duplicated(["CodInst", "Período"]).any():
            raise RuntimeError(f"Competência vazia ou com identidades duplicadas: {name}")
        meta = json.loads(cache.arquivo_metadata_runtime.read_text())
        meta["fonte"] = "ifdata_web"
        meta.setdefault("extra", {})["ifdata_web"] = {
            "periodo": periodo, "source": "https://www3.bcb.gov.br/ifdata/",
            "files": get_web_source(periodo).sources,
            "registros_periodo": len(selected), "unidade": "R$; razões em decimal",
        }
        cache.arquivo_metadata_runtime.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        item = {"cache": name, "periodo": periodo, "registros_periodo": len(selected),
                "total_registros": len(verified.dados), "historico_preservado": True}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("periodo")
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    ingest(args.base_dir, args.periodo)
