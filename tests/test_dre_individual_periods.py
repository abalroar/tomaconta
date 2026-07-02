from types import SimpleNamespace

import pandas as pd

import app1
from tabs.dre_ifdata_schema import _bar_from_canonicals, _waterfall_figure


def test_dre_individual_period_catalog_defaults_to_dec_previous_and_mar_latest():
    df_periods = pd.DataFrame(
        {
            "Periodo": ["1/2025", "2/2025", "3/2025", "4/2025", "1/2026"],
            "ano": [2025, 2025, 2025, 2025, 2026],
            "mes": [3, 6, 9, 12, 3],
        }
    )

    catalog = app1._periodos_catalogo_dre_individual(df_periods)

    assert catalog["Periodo"].tolist() == ["1/2025", "2/2025", "3/2025", "4/2025", "1/2026"]
    assert app1._default_periodos_dre_individual(catalog) == ["4/2025", "1/2026"]


def test_dre_individual_cache_status_marks_local_cache_behind_release_as_stale():
    result = SimpleNamespace(
        dados=pd.DataFrame({"Período": ["1/2025", "2/2025", "3/2025"]}),
        metadata={"periodos": ["1/2025", "2/2025", "3/2025"]},
        fonte="cache_local",
    )
    manifest = {"caches": {"dre_individual": {"max_period": "1/2026"}}}

    status = app1._cache_period_status_from_result("dre_individual", result, manifest)

    assert status["local_ref"] == "202509"
    assert status["release_ref"] == "202603"
    assert status["stale"] is True


def test_dre_individual_manifest_uses_latest_reference_across_remote_and_bundled():
    remote_manifest = {
        "expected_periods": {"quarterly": "4/2025"},
        "caches": {"dre_individual": {"max_period": "4/2025"}},
    }
    bundled_manifest = {
        "expected_periods": {"quarterly": "1/2026"},
        "caches": {"dre_individual": {"max_period": "1/2026"}},
    }

    assert app1._periodo_maximo_manifest_cache(remote_manifest, "dre_individual") == "202512"
    assert (
        app1._periodo_maximo_manifest_cache(
            [remote_manifest, bundled_manifest],
            "dre_individual",
        )
        == "202603"
    )


def test_dre_individual_cache_loader_forces_remote_when_bundled_manifest_is_newer():
    class FakeManager:
        def __init__(self):
            self.calls = []

        def carregar(self, cache_name, forcar_remoto=False):
            self.calls.append((cache_name, forcar_remoto))
            if forcar_remoto:
                return SimpleNamespace(
                    sucesso=True,
                    dados=pd.DataFrame({"Período": ["1/2026"]}),
                    metadata={"periodos": ["1/2026"]},
                    fonte="github_releases",
                )
            return SimpleNamespace(
                sucesso=True,
                dados=pd.DataFrame({"Período": ["4/2025"]}),
                metadata={"periodos": ["4/2025"]},
                fonte="cache_local",
            )

    remote_manifest = {
        "expected_periods": {"quarterly": "4/2025"},
        "caches": {"dre_individual": {"max_period": "4/2025"}},
    }
    bundled_manifest = {
        "expected_periods": {"quarterly": "1/2026"},
        "caches": {"dre_individual": {"max_period": "1/2026"}},
    }

    result, status = app1._carregar_cache_com_freshness(
        FakeManager(),
        "dre_individual",
        [remote_manifest, bundled_manifest],
    )

    assert result.fonte == "github_releases"
    assert status["local_ref"] == "202603"
    assert status["release_ref"] == "202603"
    assert status["stale"] is False
    assert status["remote_forced"] is True


def test_dre_individual_cache_loader_uses_canonical_fallback_when_configured_release_stays_stale(monkeypatch):
    class FakeCache:
        def __init__(self):
            self.saved_sources = []

        def salvar_local(self, dados, fonte="desconhecida", info_extra=None):
            self.saved_sources.append(fonte)
            return SimpleNamespace(
                sucesso=True,
                dados=dados,
                metadata={"periodos": dados["Período"].astype(str).tolist()},
                fonte="cache_local",
            )

    class FakeManager:
        def __init__(self):
            self.calls = []
            self.cache = FakeCache()

        def carregar(self, cache_name, forcar_remoto=False):
            self.calls.append((cache_name, forcar_remoto))
            return SimpleNamespace(
                sucesso=True,
                dados=pd.DataFrame({"Período": ["4/2025"]}),
                metadata={"periodos": ["4/2025"]},
                fonte="github_releases" if forcar_remoto else "cache_local",
            )

        def get_cache(self, cache_name):
            return self.cache

    remote_manifest = {
        "release": {"release_base_url": "https://github.com/example/old/releases/download/v1"},
        "expected_periods": {"quarterly": "4/2025"},
        "caches": {"dre_individual": {"max_period": "4/2025"}},
    }
    bundled_manifest = {
        "release": {"release_base_url": "https://github.com/abalroar/tomaconta/releases/download/v1.0-cache"},
        "expected_periods": {"quarterly": "1/2026"},
        "caches": {"dre_individual": {"max_period": "1/2026"}},
    }

    def fake_download(cache_name, release_base_url):
        if release_base_url.endswith("/v1.0-cache"):
            return SimpleNamespace(
                sucesso=True,
                dados=pd.DataFrame({"Período": ["1/2026"]}),
                metadata=None,
                fonte=f"github_releases_fallback:{release_base_url}",
            )
        return SimpleNamespace(
            sucesso=False,
            dados=None,
            metadata=None,
            fonte="nenhum",
            mensagem="old release stale",
        )

    monkeypatch.setattr(app1, "_baixar_cache_release_base_cache", fake_download)
    manager = FakeManager()

    result, status = app1._carregar_cache_com_freshness(
        manager,
        "dre_individual",
        [remote_manifest, bundled_manifest],
    )

    assert manager.calls == [("dre_individual", False), ("dre_individual", True)]
    assert result.dados["Período"].tolist() == ["1/2026"]
    assert status["local_ref"] == "202603"
    assert status["release_ref"] == "202603"
    assert status["stale"] is False
    assert status["remote_forced"] is True
    assert status["fallback_release_base"].endswith("/v1.0-cache")
    assert manager.cache.saved_sources == [status["fonte"]]


def test_dre_individual_cache_loader_forces_remote_when_local_is_stale():
    class FakeManager:
        def __init__(self):
            self.calls = []

        def carregar(self, cache_name, forcar_remoto=False):
            self.calls.append((cache_name, forcar_remoto))
            if forcar_remoto:
                return SimpleNamespace(
                    sucesso=True,
                    dados=pd.DataFrame({"Período": ["1/2026"]}),
                    metadata={"periodos": ["1/2026"]},
                    fonte="github_releases",
                )
            return SimpleNamespace(
                sucesso=True,
                dados=pd.DataFrame({"Período": ["3/2025"]}),
                metadata={"periodos": ["3/2025"]},
                fonte="cache_local",
            )

    manager = FakeManager()
    manifest = {"caches": {"dre_individual": {"max_period": "1/2026"}}}

    result, status = app1._carregar_cache_com_freshness(manager, "dre_individual", manifest)

    assert manager.calls == [("dre_individual", False), ("dre_individual", True)]
    assert result.fonte == "github_releases"
    assert status["local_ref"] == "202603"
    assert status["stale"] is False
    assert status["remote_forced"] is True


def test_dre_schema_bar_chart_accepts_series_rows():
    fig = _bar_from_canonicals(
        {
            "net_income": pd.Series(
                {
                    "rubrica": "Lucro líquido",
                    "valor_r_mil": 125000,
                }
            )
        },
        ["net_income"],
        "Teste",
    )

    assert fig is not None
    assert list(fig.data[0].x) == ["Lucro líquido"]
    assert list(fig.data[0].y) == [125.0]


def test_dre_schema_waterfall_accepts_series_rows():
    fig = _waterfall_figure(
        {
            "intermediation_result": pd.Series({"valor_r_mil": 100000}),
            "income_tax_social_contribution": pd.Series({"valor_r_mil": -15000}),
            "net_income": pd.Series({"valor_r_mil": 85000}),
        }
    )

    assert fig is not None
    assert list(fig.data[0].x) == ["Intermediação", "IR/CS", "Lucro líquido"]
    assert list(fig.data[0].y) == [100.0, -15.0, 85.0]
