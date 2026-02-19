#!/usr/bin/env python3
"""CLI para atualizar caches do IFData/BCB.

Exemplos:
  .venv/bin/python tools/update_caches_cli.py --tipo principal --ano-inicial 2023 --mes-inicial 03 --ano-final 2024 --mes-final 12
  .venv/bin/python tools/update_caches_cli.py --tipo bloprudencial --mensal-inicio 202401 --mensal-fim 202412 --modo overwrite
  .venv/bin/python tools/update_caches_cli.py --all --ano-inicial 2023 --mes-inicial 03 --ano-final 2024 --mes-final 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from utils.ifdata_cache import CacheManager, gerar_periodos_trimestrais


DEFAULT_TIPOS = [
    "principal",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
    "bloprudencial",
]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _parse_periodos_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts


def _gerar_periodos_mensais(inicio: str, fim: str) -> List[str]:
    if len(inicio) != 6 or len(fim) != 6:
        raise ValueError("mensal-inicio/mensal-fim devem ser YYYYMM")
    ano_i = int(inicio[:4])
    mes_i = int(inicio[4:6])
    ano_f = int(fim[:4])
    mes_f = int(fim[4:6])
    if (ano_i, mes_i) > (ano_f, mes_f):
        raise ValueError("mensal-inicio deve ser <= mensal-fim")

    periodos = []
    ano, mes = ano_i, mes_i
    while (ano, mes) <= (ano_f, mes_f):
        periodos.append(f"{ano}{mes:02d}")
        if mes == 12:
            ano += 1
            mes = 1
        else:
            mes += 1
    return periodos


def _resolver_aliases_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    candidatos = [
        base / "data" / "Aliases.xlsx",
        base / "data" / "alias.xlsx",
        base / "Data" / "Aliases.xlsx",
        base / "Data" / "alias.xlsx",
        base / "data_sources" / "Aliases.xlsx",
    ]
    for caminho in candidatos:
        if caminho.exists():
            return caminho
    return candidatos[0]


def _carregar_aliases() -> Dict[str, str]:
    path = _resolver_aliases_path()
    if not path.exists():
        return {}
    try:
        df = pd.read_excel(path)
    except Exception:
        return {}

    col_inst = None
    col_alias = None
    for c in df.columns:
        if str(c).strip().lower() in {"instituição", "instituicao", "instituicao_original"}:
            col_inst = c
        if str(c).strip().lower() in {"alias banco", "alias", "apelido"}:
            col_alias = c
    if not col_inst or not col_alias:
        return {}

    mapping = {}
    for _, row in df.iterrows():
        inst = str(row.get(col_inst, "")).strip()
        alias = str(row.get(col_alias, "")).strip()
        if inst and alias:
            mapping[inst] = alias
    return mapping


def _listar_caches(manager: CacheManager) -> None:
    _print("Caches disponíveis:")
    for nome in manager.listar_caches():
        _print(f"- {nome}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Atualiza caches do IFData/BCB via CLI")
    parser.add_argument("--tipo", action="append", help="tipo de cache (pode repetir)")
    parser.add_argument("--all", action="store_true", help="atualizar tipos padrão")
    parser.add_argument("--list", action="store_true", help="listar caches disponíveis")

    parser.add_argument("--modo", choices=["incremental", "overwrite"], default="incremental")
    parser.add_argument("--intervalo", type=int, default=4, help="salvar a cada N períodos")

    parser.add_argument("--periodos", help="lista de períodos YYYYMM separados por vírgula")
    parser.add_argument("--ano-inicial", type=int, help="ano inicial (trimestral)")
    parser.add_argument("--mes-inicial", choices=["03", "06", "09", "12"], help="mês inicial (trimestral)")
    parser.add_argument("--ano-final", type=int, help="ano final (trimestral)")
    parser.add_argument("--mes-final", choices=["03", "06", "09", "12"], help="mês final (trimestral)")

    parser.add_argument("--mensal-inicio", help="início mensal YYYYMM (para bloprudencial)")
    parser.add_argument("--mensal-fim", help="fim mensal YYYYMM (para bloprudencial)")

    parser.add_argument("--force-refresh", action="store_true", help="forçar download (bloprudencial)")
    parser.add_argument("--sem-aliases", action="store_true", help="não carregar Aliases.xlsx")

    args = parser.parse_args()

    manager = CacheManager()
    if args.list:
        _listar_caches(manager)
        return 0

    tipos = []
    if args.all:
        tipos = DEFAULT_TIPOS.copy()
    if args.tipo:
        tipos.extend(args.tipo)
    tipos = list(dict.fromkeys([t.strip() for t in tipos if t and t.strip()]))

    if not tipos:
        _print("Nenhum tipo selecionado. Use --tipo ou --all.")
        return 1

    periodos = _parse_periodos_list(args.periodos)
    if not periodos:
        if args.ano_inicial and args.mes_inicial and args.ano_final and args.mes_final:
            periodos = gerar_periodos_trimestrais(args.ano_inicial, args.mes_inicial, args.ano_final, args.mes_final)

    aliases = {} if args.sem_aliases else _carregar_aliases()

    for tipo in tipos:
        if tipo == "bloprudencial":
            if not periodos:
                if args.mensal_inicio and args.mensal_fim:
                    periodos = _gerar_periodos_mensais(args.mensal_inicio, args.mensal_fim)
                else:
                    _print("Para bloprudencial, informe --mensal-inicio e --mensal-fim (YYYYMM) ou --periodos.")
                    return 1
        elif not periodos:
            _print("Informe --periodos ou --ano/mes inicial/final para caches trimestrais.")
            return 1

        _print(f"==> Atualizando cache '{tipo}' ({len(periodos)} períodos), modo={args.modo}")
        kwargs = {}
        if tipo == "bloprudencial":
            kwargs["force_refresh"] = bool(args.force_refresh)
            kwargs["cache_dir"] = "data/cache/bcb_bloprudencial"

        result = manager.extrair_periodos_com_salvamento(
            tipo=tipo,
            periodos=list(periodos),
            modo=args.modo,
            intervalo_salvamento=args.intervalo,
            dict_aliases=aliases,
            **kwargs,
        )

        if result.sucesso:
            _print(f"OK: {result.mensagem}")
        else:
            _print(f"ERRO: {result.mensagem}")
            return 1

    _print("\\nConcluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
