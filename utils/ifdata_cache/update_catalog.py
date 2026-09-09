"""Capacidades operacionais das fontes, sem duplicar sua ingestão."""

from __future__ import annotations

from typing import Mapping

from .release_config import get_release_config


QUARTERLY_CACHES = (
    "principal", "capital", "ativo", "passivo", "dre", "principal_individual",
    "dre_individual", "carteira_pf", "carteira_pj", "carteira_instrumentos",
)
_CATALOG = {
    name: {"unit": "competência trimestral", "background": True, "resume": True,
           "updateable": True, "modes": ("incremental", "overwrite")}
    for name in QUARTERLY_CACHES
}
_CATALOG.update({
    "bloprudencial": {"unit": "competência mensal", "background": False, "resume": False,
                      "updateable": True, "modes": ("incremental", "overwrite")},
    "taxas_juros": {"unit": "intervalo diário", "background": False, "resume": False,
                    "updateable": True, "modes": ("incremental", "overwrite")},
    "taxas_juros_historico": {"unit": "janela oficial", "background": False, "resume": False,
                             "native_resume": True, "updateable": True,
                             "modes": ("incremental", "overwrite")},
    "spb_meios_pagamento": {"unit": "dataset", "background": False, "resume": False,
                           "updateable": True, "modes": ("incremental", "overwrite")},
    "mercado_credito_sgs": {"unit": "série mensal", "background": False, "resume": False,
                           "updateable": True, "modes": ("incremental", "overwrite")},
    "scr_data": {"unit": "arquivo anual", "background": False, "resume": False,
                 "native_resume": True, "updateable": False, "modes": ()},
})


def get_update_capabilities(cache_name: str) -> dict:
    """Fontes desconhecidas não ganham controles operacionais por inferência."""
    return dict(_CATALOG.get(cache_name, {
        "unit": "artefato", "background": False, "resume": False,
        "updateable": False, "modes": (),
    }))


def updateable_cache_names(manager) -> list[str]:
    return [name for name in manager.listar_caches() if get_update_capabilities(name)["updateable"]]


def resolve_cache_release(cache, release_config=None) -> tuple[str, str]:
    """Usa o destino efetivo da fonte, inclusive a tag independente do SCR."""
    release = release_config or get_release_config()
    return (
        str(getattr(cache, "release_repo", None) or release.repo),
        str(getattr(cache, "release_tag", None) or release.tag),
    )


def publication_status(info_local: Mapping, info_remote: Mapping) -> str:
    """Existência remota e correspondência de versão são evidências distintas."""
    if info_remote.get("verification_error") or info_remote.get("verification") in {"unavailable", "unknown"}:
        return "Verificação indisponível"
    if not info_remote.get("existe"):
        return "Somente local" if info_local.get("existe") else "Ausente"
    local_hash = info_local.get("sha256") or info_local.get("artifact_sha256")
    remote_hash = info_remote.get("sha256")
    if info_local.get("existe") and local_hash and remote_hash:
        return "Versão correspondente no release" if local_hash == remote_hash else "Versão local diferente"
    return "Disponível no release (versão não verificada)"
