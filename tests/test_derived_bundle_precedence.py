import json
from pathlib import Path

import pandas as pd

from utils.ifdata_cache.derived_metrics import DerivedMetricsCache, load_derived_metrics_slice


def test_derived_metrics_reader_prefers_versioned_bundle_over_runtime(tmp_path: Path):
    cache = DerivedMetricsCache(tmp_path)
    runtime = pd.DataFrame(
        [{"Instituição": "A", "Período": "1/2026", "Métrica": "M", "Valor": 1.0, "Unidade": "%"}]
    )
    bundled = runtime.assign(Valor=2.0)
    assert cache.salvar_local(runtime, fonte="runtime").sucesso
    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    bundled.to_parquet(cache.bundled_data_file, index=False)
    cache.bundled_metadata_file.write_text(
        json.dumps({"periodos": ["1/2026"], "extra": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_derived_metrics_slice(cache, periodos=["1/2026"], metricas=["M"])

    assert loaded["Valor"].tolist() == [2.0]
    assert cache.read_data_file == cache.bundled_data_file
