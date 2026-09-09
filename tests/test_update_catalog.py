from types import SimpleNamespace

from utils.ifdata_cache.update_catalog import (
    get_update_capabilities, publication_status, resolve_cache_release,
    updateable_cache_names,
)


def test_capabilities_preserve_special_adapters_and_current_scope():
    for name in ("taxas_juros", "taxas_juros_historico", "mercado_credito_sgs", "spb_meios_pagamento", "bloprudencial"):
        assert not get_update_capabilities(name)["background"]
        assert not get_update_capabilities(name)["resume"]
        assert get_update_capabilities(name)["updateable"]
    assert get_update_capabilities("taxas_juros_historico")["native_resume"]
    assert get_update_capabilities("principal")["background"]
    manager = SimpleNamespace(listar_caches=lambda: ["principal", "scr_data", "derived_metrics", "taxas_juros_historico"])
    assert updateable_cache_names(manager) == ["principal", "taxas_juros_historico"]
    assert not get_update_capabilities("unknown")["updateable"]


def test_diagnostic_resolves_source_release_instead_of_assuming_global():
    global_release = SimpleNamespace(repo="org/data", tag="v-global")
    scr = SimpleNamespace(release_repo="org/data", release_tag="v-scr")
    assert resolve_cache_release(scr, global_release) == ("org/data", "v-scr")
    assert resolve_cache_release(SimpleNamespace(), global_release) == ("org/data", "v-global")


def test_remote_existence_never_proves_version_or_activation():
    local = {"existe": True, "sha256": "new"}
    assert publication_status(local, {"existe": True}) == "Disponível no release (versão não verificada)"
    assert publication_status(local, {"existe": True, "sha256": "old"}) == "Versão local diferente"
    assert publication_status(local, {"existe": True, "sha256": "new"}) == "Versão correspondente no release"
    assert publication_status(local, {"verification_error": "timeout"}) == "Verificação indisponível"
    assert publication_status(local, {"existe": False}) == "Somente local"
