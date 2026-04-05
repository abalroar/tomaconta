"""
compat.py - Funcoes de compatibilidade com o sistema antigo

Fornece funcoes com assinaturas identicas as do sistema antigo
para facilitar migracao gradual sem quebrar codigo existente.
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .manager import CacheManager
from .capital import CAMPOS_CAPITAL, gerar_periodos_trimestrais

logger = logging.getLogger("ifdata_cache.compat")

# Instancia global do manager
_manager: Optional[CacheManager] = None


def _get_manager() -> CacheManager:
    """Retorna instancia do manager, criando se necessario."""
    global _manager
    if _manager is None:
        _manager = CacheManager()
    return _manager


# =============================================================================
# FUNCOES DE COMPATIBILIDADE - CACHE PRINCIPAL
# =============================================================================

def baixar_cache_inicial() -> Tuple[bool, str]:
    """Baixa cache principal do GitHub se nao existir localmente.

    Compativel com: app1.py baixar_cache_inicial()

    Returns:
        Tupla (sucesso, fonte) onde fonte pode ser 'local', 'github' ou 'nenhuma'
    """
    manager = _get_manager()
    cache = manager.get_cache("principal")

    if cache.existe():
        return True, 'local'

    resultado = cache.carregar()

    if resultado.sucesso:
        if resultado.fonte == "cache_local":
            return True, 'local'
        elif resultado.fonte == "github":
            return True, 'github'

    return False, 'nenhuma'


def carregar_cache() -> Optional[Dict[str, Any]]:
    """Carrega cache principal no formato antigo {periodo: DataFrame}.

    Compativel com: app1.py carregar_cache()

    Returns:
        Dicionario {periodo: DataFrame} ou None
    """
    manager = _get_manager()
    cache = manager.get_cache("principal")
    return cache.carregar_formato_antigo()


def salvar_cache(
    dados_periodos: Dict[str, Any],
    periodo_info: str,
    incremental: bool = True
) -> Dict[str, Any]:
    """Salva cache principal no formato antigo.

    Compativel com: app1.py salvar_cache()

    Returns:
        Dicionario com informacoes do cache salvo
    """
    manager = _get_manager()
    cache = manager.get_cache("principal")

    resultado = cache.salvar_formato_antigo(
        dados_periodos,
        fonte="api",
        info_extra={"periodo_info": periodo_info, "incremental": incremental}
    )

    info = cache.get_info()

    return {
        "caminho": info.get("arquivo_dados", ""),
        "tamanho_formatado": _formatar_tamanho(info.get("tamanho_bytes", 0)),
        "n_periodos": info.get("total_periodos", 0),
        "sucesso": resultado.sucesso,
    }


def get_cache_info() -> Dict[str, Any]:
    """Retorna informacoes do cache principal.

    Compativel com: app1.py get_cache_info()
    """
    manager = _get_manager()
    info = manager.info("principal")

    return {
        "existe": info.get("existe", False),
        "caminho": info.get("arquivo_dados", ""),
        "tamanho_bytes": info.get("tamanho_bytes", 0),
        "tamanho_formatado": _formatar_tamanho(info.get("tamanho_bytes", 0)),
        "n_periodos": info.get("total_periodos", 0),
        "data_extracao": info.get("timestamp_salvamento"),
    }


# =============================================================================
# FUNCOES DE COMPATIBILIDADE - CACHE CAPITAL
# =============================================================================

def baixar_cache_capital_inicial() -> Tuple[bool, str]:
    """Baixa cache de capital do GitHub se nao existir localmente.

    Compativel com: app1.py baixar_cache_capital_inicial()

    Returns:
        Tupla (sucesso, fonte)
    """
    manager = _get_manager()
    cache = manager.get_cache("capital")

    if cache.existe():
        return True, 'local'

    resultado = cache.carregar()

    if resultado.sucesso:
        if resultado.fonte == "cache_local":
            return True, 'local'
        elif resultado.fonte == "github":
            return True, 'github releases'

    return False, 'nenhuma'


def carregar_cache_capital() -> Optional[Dict[str, Any]]:
    """Carrega cache de capital no formato antigo {periodo: DataFrame}.

    Compativel com: capital_extractor.py carregar_cache_capital()

    Returns:
        Dicionario {periodo: DataFrame} ou None
    """
    manager = _get_manager()
    cache = manager.get_cache("capital")
    return cache.carregar_formato_antigo()


def salvar_cache_capital(
    dados_periodos: Dict[str, Any],
    periodo_info: str,
    incremental: bool = True
) -> Dict[str, Any]:
    """Salva cache de capital no formato antigo.

    Compativel com: capital_extractor.py salvar_cache_capital()

    Returns:
        Dicionario com informacoes do cache salvo
    """
    manager = _get_manager()
    cache = manager.get_cache("capital")

    # Se incremental, mesclar com dados existentes
    if incremental:
        dados_existentes = cache.carregar_formato_antigo()
        if dados_existentes:
            dados_existentes.update(dados_periodos)
            dados_periodos = dados_existentes

    resultado = cache.salvar_formato_antigo(
        dados_periodos,
        fonte="api",
        info_extra={"periodo_info": periodo_info, "incremental": incremental}
    )

    info = cache.get_info()

    return {
        "caminho": info.get("arquivo_dados", ""),
        "tamanho_formatado": _formatar_tamanho(info.get("tamanho_bytes", 0)),
        "n_periodos": info.get("total_periodos", 0),
        "sucesso": resultado.sucesso,
    }


def gerar_periodos_capital(
    ano_ini: int,
    mes_ini: str,
    ano_fin: int,
    mes_fin: str
) -> List[str]:
    """Gera lista de periodos trimestrais.

    Compativel com: capital_extractor.py gerar_periodos_capital()
    """
    return gerar_periodos_trimestrais(
        ano_ini, int(mes_ini),
        ano_fin, int(mes_fin)
    )


def processar_todos_periodos_capital(
    periodos: List[str],
    dict_aliases: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    save_callback: Optional[Callable[[Dict, str], None]] = None,
    save_interval: int = 5,
) -> Optional[Dict[str, Any]]:
    """Processa multiplos periodos de capital.

    Compativel com: capital_extractor.py processar_todos_periodos_capital()
    """
    manager = _get_manager()
    cache = manager.get_cache("capital")

    dados_todos = {}
    erros = []

    for i, periodo in enumerate(periodos):
        if progress_callback:
            progress_callback(i, len(periodos), periodo)

        _ = dict_aliases
        resultado = cache.extrair_periodo(periodo)

        if resultado.sucesso and resultado.dados is not None:
            dados_todos[periodo] = resultado.dados

            # Salvamento intermediario
            if save_callback and (i + 1) % save_interval == 0:
                save_callback(dados_todos, f"Periodos 1-{i+1}")
        else:
            erros.append(periodo)
            logger.warning(f"[CAPITAL] Erro em {periodo}: {resultado.mensagem}")

    if not dados_todos:
        return None

    return dados_todos


def get_capital_cache_info() -> Dict[str, Any]:
    """Retorna informacoes do cache de capital.

    Compativel com: capital_extractor.py get_capital_cache_info()
    """
    manager = _get_manager()
    info = manager.info("capital")

    return {
        "existe": info.get("existe", False),
        "caminho": info.get("arquivo_dados", ""),
        "tamanho_bytes": info.get("tamanho_bytes", 0),
        "tamanho_formatado": _formatar_tamanho(info.get("tamanho_bytes", 0)),
        "n_periodos": info.get("total_periodos", 0),
        "data_extracao": info.get("timestamp_salvamento"),
    }


def get_campos_capital_info() -> Dict[str, str]:
    """Retorna mapeamento de campos de capital.

    Compativel com: capital_extractor.py get_campos_capital_info()
    """
    return CAMPOS_CAPITAL.copy()


def ler_info_cache_capital() -> Optional[str]:
    """Le informacoes do cache de capital como string.

    Compativel com: capital_extractor.py ler_info_cache_capital()

    Returns:
        String com informacoes ou None se cache nao existir
    """
    manager = _get_manager()
    cache = manager.get_cache("capital")

    if not cache.existe():
        return None

    info = cache.get_info()

    # Formatar como texto similar ao sistema antigo
    linhas = []
    if info.get("timestamp_salvamento"):
        linhas.append(f"Ultima extracao: {info['timestamp_salvamento']}")
    if info.get("total_periodos"):
        linhas.append(f"Total de periodos: {info['total_periodos']}")
    if info.get("total_registros"):
        linhas.append(f"Total de registros: {info['total_registros']}")
    if info.get("fonte"):
        linhas.append(f"Fonte: {info['fonte']}")

    return "\n".join(linhas) if linhas else None


# =============================================================================
# UTILITARIOS
# =============================================================================

def _formatar_tamanho(bytes: int) -> str:
    """Formata tamanho em bytes para string legivel."""
    if bytes >= 1024 * 1024:
        return f"{bytes / 1024 / 1024:.1f} MB"
    elif bytes >= 1024:
        return f"{bytes / 1024:.1f} KB"
    return f"{bytes} B"
