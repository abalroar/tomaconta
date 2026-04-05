"""Regras de disponibilidade temporal por tipo de cache."""

from __future__ import annotations

from typing import Iterable, List, Tuple


MIN_API_PERIOD_BY_CACHE = {
    "carteira_pf": "202503",
    "carteira_pj": "202503",
    "carteira_instrumentos": "202503",
}


def _normalize_api_period(periodo: str | None) -> str | None:
    if periodo is None:
        return None
    texto = "".join(ch for ch in str(periodo).strip() if ch.isdigit())
    if len(texto) != 6:
        return None
    return texto


def display_period_to_api(periodo: str | None) -> str | None:
    """Converte período exibido (`1/2025`) em API (`202503`)."""
    if periodo is None:
        return None

    texto = str(periodo).strip()
    normalizado = _normalize_api_period(texto)
    if normalizado:
        return normalizado

    if "/" not in texto:
        return None

    parte_1, parte_2 = [p.strip() for p in texto.split("/", 1)]
    if not parte_1.isdigit() or not parte_2.isdigit():
        return None

    ano = int(parte_2)
    valor = int(parte_1)
    if 1 <= valor <= 4:
        mes = {1: 3, 2: 6, 3: 9, 4: 12}[valor]
        return f"{ano}{mes:02d}"

    if 1 <= valor <= 12:
        return f"{ano}{valor:02d}"

    return None


def api_period_to_display(periodo: str | None) -> str | None:
    """Converte período API (`202503`) para exibição trimestral (`1/2025`)."""
    normalizado = _normalize_api_period(periodo)
    if normalizado is None:
        return None

    ano = int(normalizado[:4])
    mes = int(normalizado[4:6])
    trimestre = {3: 1, 6: 2, 9: 3, 12: 4}.get(mes)
    if trimestre is None:
        return f"{mes:02d}/{ano}"
    return f"{trimestre}/{ano}"


def is_period_supported(cache_name: str, periodo: str | None) -> bool:
    """Retorna se um período é suportado para um tipo de cache."""
    normalizado = display_period_to_api(periodo)
    if normalizado is None:
        return False

    limite_inferior = MIN_API_PERIOD_BY_CACHE.get(cache_name)
    if limite_inferior is None:
        return True
    return normalizado >= limite_inferior


def filter_supported_periods(cache_name: str, periodos: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Separa períodos suportados e ignorados para um tipo de cache."""
    suportados: List[str] = []
    ignorados: List[str] = []
    for periodo in periodos:
        if is_period_supported(cache_name, periodo):
            suportados.append(str(periodo))
        else:
            ignorados.append(str(periodo))
    return suportados, ignorados


def describe_support_window(cache_name: str) -> str:
    """Retorna descrição humana da janela de disponibilidade."""
    limite = MIN_API_PERIOD_BY_CACHE.get(cache_name)
    if not limite:
        return "sem restrição conhecida"
    display = api_period_to_display(limite) or limite
    return f"disponível a partir de {display} ({limite})"
