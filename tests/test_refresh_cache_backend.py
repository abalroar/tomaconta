from argparse import Namespace

import pytest

from tools import refresh_cache_backend


def _args(**overrides):
    values = {
        "snapshot_label": "teste",
        "reason": "teste",
        "dry_run": True,
        "ano_inicial": 2025,
        "mes_inicial": "03",
        "ano_final": 2026,
        "mes_final": "03",
        "mensal_inicio": "202503",
        "mensal_fim": "202603",
        "batch_size": 6,
        "retry_max": 0,
        "retry_delay": 0,
        "intervalo": 4,
        "publish": True,
        "publish_only": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_publish_only_dry_run_announces_runtime_reuse(tmp_path, capsys):
    (tmp_path / "data" / "cache").mkdir(parents=True)

    result = refresh_cache_backend._run_refresh(_args(), tmp_path)

    output = capsys.readouterr().out
    assert result == 0
    assert "[REUSE] principal:" in output
    assert "[REFRESH] principal:" not in output


def test_release_assets_require_runtime_files(tmp_path):
    class FakeCache:
        arquivo_dados_runtime = tmp_path / "cache" / "dados.parquet"
        arquivo_dados_pickle = tmp_path / "cache" / "dados.pkl"
        arquivo_metadata_runtime = tmp_path / "cache" / "metadata.json"

    class FakeManager:
        @staticmethod
        def get_cache(cache_name):
            return FakeCache()

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "dados.parquet").write_bytes(b"stale")

    with pytest.raises(FileNotFoundError, match="runtime ausente"):
        refresh_cache_backend._release_assets_for_cache(FakeManager(), "principal")


def test_parser_accepts_publish_only():
    args = refresh_cache_backend.build_parser().parse_args(["--publish-only", "--dry-run"])

    assert args.publish_only is True


def test_publish_manifest_is_scoped_to_assets_managed_by_cli(monkeypatch):
    captured = {}

    def fake_build_runtime_manifest(manager, **kwargs):
        captured.update(kwargs)
        return {"caches": {}, "gates": {}}

    monkeypatch.setattr(refresh_cache_backend, "build_runtime_manifest", fake_build_runtime_manifest)

    result = refresh_cache_backend._build_publish_runtime_manifest(
        object(),
        release_config=object(),
        expected_periods={"quarterly": "202603"},
    )

    assert result == {"caches": {}, "gates": {}}
    assert captured["cache_names"] == refresh_cache_backend.PUBLISH_CACHE_NAMES
    assert "taxas_juros_historico" not in captured["cache_names"]
    assert captured["include_hashes"] is True
