import json
from types import SimpleNamespace

import pandas as pd

import app1
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.institutions import canonicalize_institution_history
from utils.ifdata_cache.manager import CacheManager


ITAU_CATALOG = {
    "ITAU PRUDENCIAL": "ITAU - PRUDENCIAL",
    "ITAU UNIBANCO": "ITAU - PRUDENCIAL",
}


def _itau_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Instituição": [
                "Itau Unibanco",
                "Itau Unibanco",
                "Itau Unibanco",
                "ITAU - PRUDENCIAL",
                "ITAU - PRUDENCIAL",
            ],
            "Período": ["1/2025", "2/2025", "3/2025", "4/2025", "1/2026"],
            "CodInst": [None, None, None, "C0080099", "C0080099"],
            "Total Geral": [100.0, 110.0, 120.0, 130.0, 140.0],
        }
    )


def test_canonical_history_unifies_itau_and_exposes_all_quarters():
    raw = pd.concat(
        [
            _itau_history(),
            pd.DataFrame(
                {
                    "Instituição": ["COOPERATIVA DE CRÉDITO DE ITAÚNA"],
                    "Período": ["1/2025"],
                    "CodInst": ["999"],
                    "Total Geral": [5.0],
                }
            ),
        ],
        ignore_index=True,
    )

    out = canonicalize_institution_history(raw, catalog_map=ITAU_CATALOG)
    itau = out[out["Instituição"].eq("ITAU - PRUDENCIAL")]

    assert len(out) == len(raw)
    assert sorted(itau["Período"].tolist()) == [
        "1/2025",
        "1/2026",
        "2/2025",
        "3/2025",
        "4/2025",
    ]
    assert set(itau["InstituiçãoRaw"]) == {"Itau Unibanco", "ITAU - PRUDENCIAL"}
    assert "COOPERATIVA DE CRÉDITO DE ITAÚNA" in set(out["Instituição"])
    assert not out.duplicated(["Instituição", "Período"]).any()


def test_canonical_history_resolves_collision_deterministically_and_reports_it():
    raw = pd.DataFrame(
        {
            "Instituição": ["Itau Unibanco", "ITAU - PRUDENCIAL"],
            "Período": ["4/2025", "4/2025"],
            "CodInst": [None, "C0080099"],
            "Total Geral": [100.0, 200.0],
            "C1": [90.0, 180.0],
        }
    )

    out = canonicalize_institution_history(raw, catalog_map=ITAU_CATALOG)

    assert len(out) == 1
    assert out.iloc[0]["Instituição"] == "ITAU - PRUDENCIAL"
    assert out.iloc[0]["InstituiçãoRaw"] == "ITAU - PRUDENCIAL"
    assert out.iloc[0]["Total Geral"] == 200.0
    assert out.attrs["institution_identity_collision_count"] == 1
    assert out.attrs["institution_identity_collision_keys"] == [
        ("ITAU - PRUDENCIAL", "4/2025")
    ]


def test_carteira_loader_replaces_old_release_with_pinned_curated_asset(monkeypatch, tmp_path):
    old_data = _itau_history().query("`Período` != '1/2026'").copy()
    old_path = tmp_path / "dados.parquet"
    old_path.write_bytes(b"old-v2-asset")

    class FakeCache:
        arquivo_dados = old_path

        def existe(self):
            return True

        def carregar_local(self):
            return CacheResult(
                sucesso=True,
                mensagem="old local",
                dados=old_data,
                metadata={"periodos": old_data["Período"].tolist()},
                fonte="cache_local",
            )

        def salvar_local(self, dados, fonte="desconhecida", info_extra=None):
            return CacheResult(
                sucesso=True,
                mensagem="saved",
                dados=dados,
                metadata={"periodos": dados["Período"].tolist()},
                fonte=fonte,
            )

    class FakeManager:
        cache = FakeCache()

        def get_cache(self, cache_name):
            assert cache_name == "carteira_instrumentos"
            return self.cache

    calls = []

    def fake_download(cache_name, release_base_url, *, expected_sha256=""):
        calls.append((cache_name, release_base_url, expected_sha256))
        current = _itau_history()
        return CacheResult(
            sucesso=True,
            mensagem="curated",
            dados=current,
            metadata={"sha256": expected_sha256},
            fonte="github_releases_fallback",
        )

    monkeypatch.setattr(app1, "get_cache_manager", lambda: FakeManager())
    monkeypatch.setattr(app1, "_baixar_cache_release_base_cache", fake_download)
    monkeypatch.setattr(
        app1,
        "canonicalize_institution_history",
        lambda frame, base_dir=None: canonicalize_institution_history(frame, catalog_map=ITAU_CATALOG),
    )
    manifest = {
        "expected_periods": {"quarterly": "1/2026"},
        "caches": {
            "carteira_instrumentos": {
                "max_period": "1/2026",
                "max_period_ref": "202603",
                "period_count": 5,
                "sha256": "abc123",
            }
        },
    }

    out, status = app1._load_carteira_4966_data_impl(manifest)

    assert calls == [
        (
            "carteira_instrumentos",
            app1._CARTEIRA_4966_RELEASE_BASE_URL,
            "abc123",
        )
    ]
    assert status["valid"] is True
    assert status["integrity_verified"] is True
    assert sorted(out.loc[out["Instituição"].eq("ITAU - PRUDENCIAL"), "Período"]) == [
        "1/2025",
        "1/2026",
        "2/2025",
        "3/2025",
        "4/2025",
    ]


def test_carteira_release_token_changes_with_manifest_digest():
    manifest_a = {
        "generated_at_utc": "2026-07-10T00:00:00Z",
        "caches": {
            "carteira_instrumentos": {
                "sha256": "sha-a",
                "max_period_ref": "202603",
                "period_count": 5,
            }
        },
    }
    manifest_b = {
        **manifest_a,
        "caches": {
            "carteira_instrumentos": {
                **manifest_a["caches"]["carteira_instrumentos"],
                "sha256": "sha-b",
            }
        },
    }

    assert app1._carteira_4966_release_token(manifest_a) != app1._carteira_4966_release_token(manifest_b)


def test_cached_loader_uses_the_manifest_that_created_its_release_token(monkeypatch):
    manifest = {
        "generated_at_utc": "2026-07-14T00:00:00Z",
        "caches": {"carteira_instrumentos": {"sha256": "pinned-digest"}},
    }
    captured = []

    def unexpected_manifest_fetch(*args, **kwargs):
        raise AssertionError("the cached loader must not fetch the manifest again")

    def fake_load(received_manifest):
        captured.append(received_manifest)
        return "loaded", {"valid": True}

    monkeypatch.setattr(app1, "_carregar_manifest_release_cache", unexpected_manifest_fetch)
    monkeypatch.setattr(app1, "_load_carteira_4966_data_impl", fake_load)
    app1.load_carteira_4966_data.clear()
    try:
        result = app1.load_carteira_4966_data(
            app1._carteira_4966_release_token(manifest),
            json.dumps(manifest, sort_keys=True),
        )
    finally:
        app1.load_carteira_4966_data.clear()

    assert result == ("loaded", {"valid": True})
    assert captured == [manifest]


def test_curated_download_rejects_asset_with_wrong_digest(monkeypatch):
    class FakeResponse:
        status_code = 200
        content = b"corrupted-parquet"

    monkeypatch.setattr(app1.requests, "get", lambda *args, **kwargs: FakeResponse())

    result = app1._baixar_cache_release_base_cache(
        "carteira_instrumentos",
        app1._CARTEIRA_4966_RELEASE_BASE_URL,
        expected_sha256="not-the-received-digest",
    )

    assert result.sucesso is False
    assert "integridade inválida" in result.mensagem


def test_carteira_loader_keeps_valid_local_cache_when_it_is_newer_than_release(
    monkeypatch,
    tmp_path,
):
    local_data = pd.concat(
        [
            _itau_history(),
            pd.DataFrame(
                {
                    "Instituição": ["ITAU - PRUDENCIAL"],
                    "Período": ["2/2026"],
                    "CodInst": ["C0080099"],
                    "Total Geral": [150.0],
                }
            ),
        ],
        ignore_index=True,
    )
    local_path = tmp_path / "dados.parquet"
    local_path.write_bytes(b"new-local-api-cache")

    class FakeCache:
        arquivo_dados = local_path

        def existe(self):
            return True

        def carregar_local(self):
            return CacheResult(
                sucesso=True,
                mensagem="new local",
                dados=local_data,
                metadata={"periodos": local_data["Período"].tolist()},
                fonte="api",
            )

    class FakeManager:
        cache = FakeCache()

        def get_cache(self, cache_name):
            assert cache_name == "carteira_instrumentos"
            return self.cache

    def unexpected_download(*args, **kwargs):
        raise AssertionError("download should not run")

    monkeypatch.setattr(app1, "get_cache_manager", lambda: FakeManager())
    monkeypatch.setattr(
        app1,
        "_baixar_cache_release_base_cache",
        unexpected_download,
    )
    monkeypatch.setattr(
        app1,
        "canonicalize_institution_history",
        lambda frame, base_dir=None: canonicalize_institution_history(frame, catalog_map=ITAU_CATALOG),
    )
    manifest = {
        "expected_periods": {"quarterly": "1/2026"},
        "caches": {
            "carteira_instrumentos": {
                "max_period": "1/2026",
                "max_period_ref": "202603",
                "period_count": 5,
                "sha256": "release-digest",
            }
        },
    }

    out, status = app1._load_carteira_4966_data_impl(manifest)

    assert status["valid"] is True
    assert status["local_ref"] == "202606"
    assert status["integrity_verified"] is False
    assert "mais recente" in status["warning"]
    assert "2/2026" in set(out["Período"])


def test_manifest_outage_does_not_accept_an_incomplete_local_cache(monkeypatch, tmp_path):
    incomplete_data = _itau_history().query("`Período` == '4/2025'").copy()
    local_path = tmp_path / "dados.parquet"
    local_path.write_bytes(b"incomplete-local-cache")

    class FakeCache:
        arquivo_dados = local_path

        def existe(self):
            return True

        def carregar_local(self):
            return CacheResult(
                sucesso=True,
                mensagem="incomplete local",
                dados=incomplete_data,
                metadata={"periodos": incomplete_data["Período"].tolist()},
                fonte="cache_local",
            )

    class FakeManager:
        def get_cache(self, cache_name):
            assert cache_name == "carteira_instrumentos"
            return FakeCache()

    monkeypatch.setattr(app1, "get_cache_manager", lambda: FakeManager())
    monkeypatch.setattr(
        app1,
        "_baixar_cache_release_base_cache",
        lambda *args, **kwargs: CacheResult(False, "release unavailable", fonte="nenhum"),
    )

    out, status = app1._load_carteira_4966_data_impl({"_erro": "manifest timeout"})

    assert out is None
    assert status["valid"] is False
    assert status["missing_required_periods"] == ["202503", "202506", "202509", "202603"]


def test_newer_local_cache_with_a_historical_gap_is_rejected(monkeypatch, tmp_path):
    gapped_data = pd.concat(
        [
            _itau_history().query("`Período` != '1/2025'"),
            pd.DataFrame(
                {
                    "Instituição": ["ITAU - PRUDENCIAL"],
                    "Período": ["2/2026"],
                    "CodInst": ["C0080099"],
                    "Total Geral": [150.0],
                }
            ),
        ],
        ignore_index=True,
    )
    local_path = tmp_path / "dados.parquet"
    local_path.write_bytes(b"newer-but-gapped-cache")

    class FakeCache:
        arquivo_dados = local_path

        def existe(self):
            return True

        def carregar_local(self):
            return CacheResult(
                sucesso=True,
                mensagem="gapped local",
                dados=gapped_data,
                metadata={"periodos": gapped_data["Período"].tolist()},
                fonte="api",
            )

    class FakeManager:
        def get_cache(self, cache_name):
            assert cache_name == "carteira_instrumentos"
            return FakeCache()

    manifest = {
        "caches": {
            "carteira_instrumentos": {
                "max_period_ref": "202603",
                "period_count": 5,
                "sha256": "release-digest",
            }
        }
    }
    monkeypatch.setattr(app1, "get_cache_manager", lambda: FakeManager())
    monkeypatch.setattr(
        app1,
        "_baixar_cache_release_base_cache",
        lambda *args, **kwargs: CacheResult(False, "release unavailable", fonte="nenhum"),
    )

    out, status = app1._load_carteira_4966_data_impl(manifest)

    assert out is None
    assert status["valid"] is False
    assert status["local_ref"] == "202606"
    assert status["local_period_count"] == 5
    assert status["missing_required_periods"] == ["202503"]


def test_cache_manager_canonicalizes_carteira_before_persisting(monkeypatch, tmp_path):
    captured = {}

    class FakeCache:
        config = SimpleNamespace(nome="carteira_instrumentos")

        def salvar_local(self, dados, fonte="desconhecida", info_extra=None):
            captured["dados"] = dados.copy()
            return CacheResult(True, "saved", dados=dados, fonte=fonte)

    def fake_canonicalize(frame, *, base_dir=None, **kwargs):
        captured["base_dir"] = base_dir
        out = frame.copy()
        out["Instituição"] = "NOME CANÔNICO"
        return out

    monkeypatch.setattr(
        "utils.ifdata_cache.institutions.canonicalize_institution_history",
        fake_canonicalize,
    )
    manager = object.__new__(CacheManager)
    manager.base_dir = tmp_path

    manager._salvar_parcial(
        cache=FakeCache(),
        dados_novos=[_itau_history().iloc[:1]],
        dados_existentes=None,
        modo="overwrite",
        info="test",
    )

    assert captured["base_dir"] == tmp_path
    assert captured["dados"]["Instituição"].tolist() == ["NOME CANÔNICO"]
