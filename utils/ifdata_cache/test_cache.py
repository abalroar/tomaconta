#!/usr/bin/env python3
"""
test_cache.py - Testes do sistema unificado de cache

Executa: python -m utils.ifdata_cache.test_cache
"""

# Este arquivo é um smoke test operacional destrutivo (limpa caches reais).
# Ele só deve rodar pelo comando acima, nunca durante a coleta normal do pytest.
__test__ = False

import sys
import logging
from datetime import datetime
from pathlib import Path

# Adicionar diretorio raiz ao path
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)


def print_header(titulo: str):
    print("\n" + "=" * 60)
    print(f" {titulo}")
    print("=" * 60)


def print_result(nome: str, passou: bool, detalhes: str = ""):
    status = "PASSOU" if passou else "FALHOU"
    simbolo = "[OK]" if passou else "[X]"
    print(f"  {simbolo} {nome}: {status}")
    if detalhes:
        print(f"      {detalhes}")


def test_imports():
    """Testa imports dos modulos."""
    print_header("TESTE: Imports")
    resultados = []

    try:
        from utils.ifdata_cache import base
        print_result("base", True)
        resultados.append(True)
    except Exception as e:
        print_result("base", False, str(e))
        resultados.append(False)

    try:
        from utils.ifdata_cache import manager
        print_result("manager", True)
        resultados.append(True)
    except Exception as e:
        print_result("manager", False, str(e))
        resultados.append(False)

    try:
        from utils.ifdata_cache import principal
        print_result("principal", True)
        resultados.append(True)
    except Exception as e:
        print_result("principal", False, str(e))
        resultados.append(False)

    try:
        from utils.ifdata_cache import capital
        print_result("capital", True)
        resultados.append(True)
    except Exception as e:
        print_result("capital", False, str(e))
        resultados.append(False)

    try:
        from utils.ifdata_cache import compat
        print_result("compat", True)
        resultados.append(True)
    except Exception as e:
        print_result("compat", False, str(e))
        resultados.append(False)

    try:
        from utils.ifdata_cache import (
            CacheManager,
            CacheResult,
            carregar,
            salvar,
            info,
        )
        print_result("__init__ exports", True)
        resultados.append(True)
    except Exception as e:
        print_result("__init__ exports", False, str(e))
        resultados.append(False)

    return all(resultados)


def test_cache_manager():
    """Testa o gerenciador de caches."""
    print_header("TESTE: CacheManager")

    from utils.ifdata_cache import CacheManager

    resultados = []

    # Criar manager
    manager = CacheManager()

    # Listar caches
    caches = manager.listar_caches()
    passou = "principal" in caches and "capital" in caches
    print_result("Caches registrados", passou, f"{caches}")
    resultados.append(passou)

    # Verificar get_cache
    cache_capital = manager.get_cache("capital")
    passou = cache_capital is not None
    print_result("get_cache(capital)", passou)
    resultados.append(passou)

    # Verificar cache inexistente
    cache_fake = manager.get_cache("fake")
    passou = cache_fake is None
    print_result("get_cache(fake) retorna None", passou)
    resultados.append(passou)

    return all(resultados)


def test_cache_operations():
    """Testa operacoes basicas de cache."""
    print_header("TESTE: Operacoes de Cache")

    import pandas as pd
    from utils.ifdata_cache import CacheManager

    resultados = []
    manager = CacheManager()

    # Limpar caches de teste
    manager.limpar("capital")

    # Verificar que nao existe
    passou = not manager.existe("capital")
    print_result("Cache capital nao existe inicialmente", passou)
    resultados.append(passou)

    # Criar DataFrame de teste
    df_teste = pd.DataFrame({
        "Periodo": ["202312", "202312", "202403"],
        "CodInst": [1, 2, 1],
        "NomeInstituicao": ["Banco A", "Banco B", "Banco A"],
        "Capital Principal": [1000, 2000, 1100],
    })

    # Salvar
    resultado = manager.salvar("capital", df_teste, fonte="teste")
    passou = resultado.sucesso
    print_result("Salvar cache", passou, resultado.mensagem)
    resultados.append(passou)

    # Verificar que existe
    passou = manager.existe("capital")
    print_result("Cache existe apos salvar", passou)
    resultados.append(passou)

    # Carregar
    resultado = manager.carregar("capital")
    passou = resultado.sucesso and resultado.dados is not None
    print_result("Carregar cache", passou, f"{len(resultado.dados) if resultado.dados is not None else 0} registros")
    resultados.append(passou)

    # Verificar dados
    if resultado.dados is not None:
        passou = len(resultado.dados) == 3
        print_result("Quantidade de registros", passou)
        resultados.append(passou)

    # Info
    info_dict = manager.info("capital")
    passou = info_dict.get("existe") and info_dict.get("total_registros") == 3
    print_result("Info correto", passou, f"registros={info_dict.get('total_registros')}")
    resultados.append(passou)

    # Limpar
    resultado = manager.limpar("capital")
    passou = resultado.sucesso and not manager.existe("capital")
    print_result("Limpar cache", passou)
    resultados.append(passou)

    return all(resultados)


def test_compat_functions():
    """Testa funcoes de compatibilidade."""
    print_header("TESTE: Funcoes de Compatibilidade")

    import pandas as pd
    from utils.ifdata_cache.compat import (
        carregar_cache_capital,
        salvar_cache_capital,
        get_capital_cache_info,
        gerar_periodos_capital,
        get_campos_capital_info,
    )
    from utils.ifdata_cache import CacheManager

    resultados = []

    # Limpar
    manager = CacheManager()
    manager.limpar("capital")

    # Gerar periodos
    periodos = gerar_periodos_capital(2023, "03", 2023, "12")
    passou = periodos == ["202303", "202306", "202309", "202312"]
    print_result("gerar_periodos_capital", passou, f"{periodos}")
    resultados.append(passou)

    # Campos de capital
    campos = get_campos_capital_info()
    passou = len(campos) > 0 and "Capital Principal" in campos.values()
    print_result("get_campos_capital_info", passou, f"{len(campos)} campos")
    resultados.append(passou)

    # Salvar no formato antigo
    dados_antigo = {
        "202312": pd.DataFrame({
            "Periodo": ["202312", "202312"],
            "CodInst": [1, 2],
            "NomeInstituicao": ["Banco A", "Banco B"],
        })
    }

    resultado = salvar_cache_capital(dados_antigo, "teste compat", incremental=False)
    passou = resultado.get("sucesso", False)
    print_result("salvar_cache_capital", passou)
    resultados.append(passou)

    # Carregar no formato antigo
    dados_carregados = carregar_cache_capital()
    passou = dados_carregados is not None and "202312" in dados_carregados
    print_result("carregar_cache_capital", passou)
    resultados.append(passou)

    # Info
    info_dict = get_capital_cache_info()
    passou = info_dict.get("existe", False)
    print_result("get_capital_cache_info", passou)
    resultados.append(passou)

    # Limpar
    manager.limpar("capital")

    return all(resultados)


def test_cache_result():
    """Testa classe CacheResult."""
    print_header("TESTE: CacheResult")

    import pandas as pd
    from utils.ifdata_cache import CacheResult

    resultados = []

    # Sucesso
    df = pd.DataFrame({"A": [1, 2]})
    result = CacheResult(sucesso=True, mensagem="OK", dados=df, fonte="teste")
    passou = result.sucesso and result.dados is not None
    print_result("CacheResult sucesso", passou)
    resultados.append(passou)

    # Falha
    result = CacheResult(sucesso=False, mensagem="Erro", fonte="nenhum")
    passou = not result.sucesso and result.dados is None
    print_result("CacheResult falha", passou)
    resultados.append(passou)

    # Repr
    result = CacheResult(sucesso=True, mensagem="OK", dados=df, fonte="x")
    passou = "OK" in repr(result) and "registros=2" in repr(result)
    print_result("CacheResult repr", passou, repr(result))
    resultados.append(passou)

    return all(resultados)


def run_all_tests():
    """Executa todos os testes."""
    print("\n")
    print("*" * 60)
    print(" TESTES DO SISTEMA UNIFICADO DE CACHE")
    print(f" Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*" * 60)

    resultados = {}

    resultados["imports"] = test_imports()
    resultados["cache_manager"] = test_cache_manager()
    resultados["cache_operations"] = test_cache_operations()
    resultados["compat_functions"] = test_compat_functions()
    resultados["cache_result"] = test_cache_result()

    # Resumo
    print_header("RESUMO")

    total = len(resultados)
    passou = sum(1 for v in resultados.values() if v)
    falhou = total - passou

    for nome, resultado in resultados.items():
        status = "PASSOU" if resultado else "FALHOU"
        print(f"  {nome}: {status}")

    print("\n" + "-" * 40)
    print(f"  Total: {total} | Passou: {passou} | Falhou: {falhou}")
    print("-" * 40)

    if falhou == 0:
        print("\n  TODOS OS TESTES PASSARAM\n")
        return 0
    else:
        print(f"\n  {falhou} TESTE(S) FALHARAM\n")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
