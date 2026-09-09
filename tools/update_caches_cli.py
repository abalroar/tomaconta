#!/usr/bin/env python3
"""CLI para atualizar caches do IFData/BCB.

Exemplos:
  .venv/bin/python tools/update_caches_cli.py --tipo principal --ano-inicial 2023 --mes-inicial 03 --ano-final 2024 --mes-final 12
  .venv/bin/python tools/update_caches_cli.py --tipo bloprudencial --mensal-inicio 202401 --mensal-fim 202412 --modo overwrite
  .venv/bin/python tools/update_caches_cli.py --all --ano-inicial 2023 --mes-inicial 03 --ano-final 2024 --mes-final 12
"""

from __future__ import annotations

import argparse
from datetime import date
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache import CacheManager, gerar_periodos_trimestrais
from utils.ifdata_cache import (
    describe_support_window,
    filter_supported_periods,
)
from utils.ifdata_cache.release_ops import materialize_for_publication
from utils.ifdata_cache.update_state import mutation_lock
from utils.ifdata_cache.scr_data import PRIMEIRO_ANO as SCR_PRIMEIRO_ANO


DEFAULT_TIPOS = [
    "principal",
    "principal_individual",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "dre_individual",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
    "bloprudencial",
    "mercado_credito_sgs",
]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _parse_periodos_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts


def _gerar_periodos_mensais(inicio: str, fim: str) -> List[str]:
    if len(inicio) != 6 or len(fim) != 6 or not inicio.isdigit() or not fim.isdigit():
        raise ValueError("mensal-inicio/mensal-fim devem ser YYYYMM válidos")
    ano_i = int(inicio[:4])
    mes_i = int(inicio[4:6])
    ano_f = int(fim[:4])
    mes_f = int(fim[4:6])
    date(ano_i, mes_i, 1)
    date(ano_f, mes_f, 1)
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

    parser.add_argument("--mensal-inicio", help="início mensal YYYYMM (BLOPRUDENCIAL ou mercado_credito_sgs)")
    parser.add_argument("--mensal-fim", help="fim mensal YYYYMM (BLOPRUDENCIAL ou mercado_credito_sgs)")

    parser.add_argument("--force-refresh", action="store_true", help="forçar download (bloprudencial)")

    parser.add_argument(
        "--scr-ano-inicial",
        type=int,
        help="ano inicial da ingestão do scr_data (default: 2012, início da série)",
    )
    parser.add_argument(
        "--scr-ano-final",
        type=int,
        help="ano final da ingestão do scr_data (default: ano corrente)",
    )
    parser.add_argument(
        "--spb-datasets",
        help=(
            "lista de datasets SPB separados por vírgula (para spb_meios_pagamento); "
            "vazio = todos os 12 (ex: nucleo_trimestral,intercambio,atm)"
        ),
    )

    args = parser.parse_args()
    try:
        _validate_cli_inputs(args)
    except ValueError as exc:
        parser.error(str(exc))

    manager = CacheManager()
    if args.list:
        _listar_caches(manager)
        return 0

    with mutation_lock(manager.base_dir):
        return _execute(args, manager)


def _validate_cli_inputs(args) -> None:
    if args.intervalo < 1:
        raise ValueError("intervalo deve ser pelo menos 1")
    for value in (args.mensal_inicio, args.mensal_fim):
        if value:
            _gerar_periodos_mensais(value, value)
    if args.mensal_inicio and args.mensal_fim:
        _gerar_periodos_mensais(args.mensal_inicio, args.mensal_fim)
    quarter_args = (args.ano_inicial, args.mes_inicial, args.ano_final, args.mes_final)
    if any(value is not None for value in quarter_args):
        if any(value is None for value in quarter_args):
            raise ValueError("informe o intervalo trimestral completo")
        if date(args.ano_inicial, int(args.mes_inicial), 1) > date(args.ano_final, int(args.mes_final), 1):
            raise ValueError("intervalo trimestral invertido")
    if args.scr_ano_inicial is not None and args.scr_ano_inicial < SCR_PRIMEIRO_ANO:
        raise ValueError("ano SCR anterior ao início da série")
    if args.scr_ano_final is not None and args.scr_ano_final < (args.scr_ano_inicial or SCR_PRIMEIRO_ANO):
        raise ValueError("intervalo SCR invertido")

    periodos = _parse_periodos_list(args.periodos)
    for periodo in periodos:
        _gerar_periodos_mensais(periodo, periodo)
    tipos = set(DEFAULT_TIPOS if args.all else ()) | set(args.tipo or ())
    quarterly_types = set(DEFAULT_TIPOS) - {"bloprudencial", "mercado_credito_sgs"}
    if tipos & quarterly_types and any(int(value[4:6]) not in (3, 6, 9, 12) for value in periodos):
        raise ValueError("IFData trimestral exige competências de março, junho, setembro ou dezembro")


def _execute(args, manager) -> int:
    _validate_cli_inputs(args)
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

    tipos_atualizados = set()
    for tipo in tipos:
        if tipo == "mercado_credito_sgs":
            cache = manager.get_cache("mercado_credito_sgs")
            inicio = args.mensal_inicio or "201101"
            fim = args.mensal_fim
            inicio_data = f"{inicio[:4]}-{inicio[4:6]}-01"
            fim_data = None
            if fim:
                from calendar import monthrange

                fim_data = f"{fim[:4]}-{fim[4:6]}-{monthrange(int(fim[:4]), int(fim[4:6]))[1]:02d}"
            _print(
                f"==> Atualizando cache 'mercado_credito_sgs' ({inicio}–{fim or 'atual'}), modo={args.modo}"
            )
            result = cache.materialize_history(
                start=inicio_data,
                end=fim_data,
                overwrite=(args.modo == "overwrite"),
                progress_callback=lambda p, m: _print(f"[{p:.0%}] {m}"),
            )
            if result.sucesso:
                _print(f"OK: {result.mensagem}")
                tipos_atualizados.add(tipo)
            else:
                _print(f"ERRO: {result.mensagem}")
                return 1
            continue

        if tipo == "spb_meios_pagamento":
            cache = manager.get_cache("spb_meios_pagamento")
            datasets = _parse_periodos_list(args.spb_datasets) or None
            _print(
                f"==> Atualizando cache 'spb_meios_pagamento' (datasets={datasets or 'todos'}), modo={args.modo}"
            )
            result = cache.materialize_history(
                datasets=datasets,
                overwrite=(args.modo == "overwrite"),
                progress_callback=lambda p, m: _print(f"[{p:.0%}] {m}"),
                log_callback=_print,
            )
            if result.sucesso:
                _print(f"OK: {result.mensagem}")
                tipos_atualizados.add(tipo)
            else:
                _print(f"ERRO: {result.mensagem}")
                return 1
            continue

        if tipo == "scr_data":
            cache = manager.get_cache("scr_data")
            ano_inicial = args.scr_ano_inicial or SCR_PRIMEIRO_ANO
            ano_final = args.scr_ano_final
            _print(
                f"==> Atualizando cache 'scr_data' (anos {ano_inicial}-{ano_final or 'corrente'}), "
                f"modo={args.modo}"
            )
            result = cache.materialize_history(
                ano_inicial=ano_inicial,
                ano_final=ano_final,
                overwrite=(args.modo == "overwrite"),
                log_callback=_print,
            )
            if result.sucesso:
                _print(f"OK: {result.mensagem}")
                tipos_atualizados.add(tipo)
            else:
                _print(f"ERRO: {result.mensagem}")
                return 1
            continue

        periodos_tipo = list(periodos)
        if tipo == "bloprudencial":
            if args.mensal_inicio and args.mensal_fim:
                periodos_tipo = _gerar_periodos_mensais(args.mensal_inicio, args.mensal_fim)
            elif not periodos_tipo:
                _print("Para bloprudencial, informe --mensal-inicio e --mensal-fim (YYYYMM) ou --periodos.")
                return 1
        elif not periodos_tipo:
            _print("Informe --periodos ou --ano/mes inicial/final para caches trimestrais.")
            return 1

        periodos_suportados, periodos_ignorados = filter_supported_periods(tipo, periodos_tipo)
        if periodos_ignorados:
            _print(
                f"[SKIP] {tipo}: ignorando {len(periodos_ignorados)} período(s) fora da janela suportada "
                f"({describe_support_window(tipo)}): {', '.join(periodos_ignorados[:6])}"
            )
        if not periodos_suportados:
            _print(f"[SKIP] {tipo}: nenhum período suportado após filtrar a janela disponível.")
            continue

        _print(f"==> Atualizando cache '{tipo}' ({len(periodos_suportados)} períodos), modo={args.modo}")
        kwargs = {}
        if tipo == "bloprudencial":
            kwargs["force_refresh"] = bool(args.force_refresh)
            kwargs["cache_dir"] = "data/cache/bcb_bloprudencial"

        result = manager.extrair_periodos_com_salvamento(
            tipo=tipo,
            periodos=list(periodos_suportados),
            modo=args.modo,
            intervalo_salvamento=args.intervalo,
            **kwargs,
        )

        if result.sucesso:
            _print(f"OK: {result.mensagem}")
            tipos_atualizados.add(tipo)
        else:
            _print(f"ERRO: {result.mensagem}")
            return 1

    details = materialize_for_publication(
        manager, cache_names=tipos_atualizados, base_dir=manager.base_dir,
        force=True, save_bundled=False,
    )
    for item in details:
        _print(f"{item['status'].upper()}: {item['cache']}: {item['message']}")
    if any(item["status"] != "ok" for item in details):
        return 1

    _print("\\nConcluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
