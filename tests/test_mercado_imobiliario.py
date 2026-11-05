"""Coleta retomável, conceitos, disponibilidade e PPTX da fonte imobiliária."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

import pandas as pd
from pptx import Presentation
import pytest

from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.durable_jobs import validate_job_spec
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.mercado_imobiliario import MercadoImobiliarioCache
from utils.ifdata_cache.update_backend import UpdateJobExecutor, assert_adapter_complete
from utils.mercado_imobiliario import CHARTS, SECTIONS, normalize_records, parse_info, figures_for_section, validate_frame
from utils.sgs_credit_pptx_export import exportar_deck_secoes_pptx, figura_para_painel
from tabs.mercado_imobiliario import deck_sections

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def published():
    return pd.read_parquet(ROOT / "data/bundled/mercado_imobiliario/dados.parquet")


def month_records(month):
    date = pd.Period(month, freq="M").end_time.strftime("%Y-%m-%d")
    return [{"Data": date, "Info": spec.prefix + next(iter(spec.labels)) + "_br", "Valor": 50.0}
            for spec in CHARTS if not spec.historical]


class Olinda:
    def __init__(self):
        self.calls, self.fail, self.deleted = [], set(), set()

    def __call__(self, url):
        query = {key: value[0] for key, value in parse_qs(urlparse(url).query).items()}
        if query.get("$orderby") == "Data desc":
            return {"value": [{"Data": "2026-02-28", "Info": "credito_contratacao_taxa_pf_sfh_br", "Valor": 10}]}
        month = re.search(r"Data eq '(\d{4}-\d{2})", query["$filter"])[1]
        self.calls.append(month)
        if month in self.fail:
            raise TimeoutError("queda simulada")
        rows = [r for r in month_records(month) if r["Info"] not in self.deleted]
        cursor = re.search(r"Info gt '([^']+)'", query["$filter"])
        if cursor:
            rows = [row for row in rows if row["Info"] > cursor[1]]
        return {"value": sorted(rows, key=lambda r: r["Info"])[:int(query["$top"]) ]}


def test_real_bundle_has_all_24_graphs_and_no_bndu(published):
    assert len(CHARTS) == 24 and published.grafico.nunique() == 24
    assert not published["info"].str.startswith("contabil_").any()
    assert validate_frame(published)["success"]
    assert published.data.min() == pd.Timestamp("2014-04-30")
    assert published.data.max() == pd.Timestamp("2026-08-31")
    for prefix, end in [("estoque_risco_", "2024-12-31"), ("imoveis_", "2026-07-31")]:
        assert published.loc[published.grafico.str.startswith(prefix), "data"].max() == pd.Timestamp(end)


def test_parser_preserves_compound_codes_and_unreported_geography():
    value = parse_info("credito_estoque_risco_operacao_pf_home_equity_d_mais_NA")
    assert value == {"grafico": "estoque_risco_pf", "categoria": "d_mais", "linha": "home_equity", "uf": "na"}
    assert parse_info("contabil_bndu_imobiliario_br") is None
    assert parse_info("credito_estoque_taxa_pj_sfh_br") is None
    with pytest.raises(ValueError, match="revisar catálogo"):
        parse_info("imoveis_tipo_novo_tipo_br")


def test_null_is_not_zero_and_duplicate_source_keys_are_rejected():
    row = {"Data": "2026-01-31", "Info": "imoveis_tipo_casa_br", "Valor": 0}
    assert normalize_records([row]).valor.iloc[0] == 0
    with pytest.raises(ValueError, match="ausente"):
        normalize_records([{**row, "Valor": None}])
    with pytest.raises(ValueError, match="duplicada"):
        normalize_records([row, row])


def test_keyset_pagination_confirms_every_row_without_skip(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    frame, receipt = cache.fetch_month("2026-01", page_size=3)
    assert len(frame) == 22 and not frame.duplicated(["data", "info"]).any()
    assert len(api.calls) == 8 and receipt["registros_fonte"] == 22


def test_ignored_cursor_cannot_be_certified_as_a_complete_month(tmp_path):
    cache = MercadoImobiliarioCache(tmp_path, request_json=lambda url: {"value": month_records("2026-01")[:2]})
    with pytest.raises(ValueError, match="repetida"):
        cache.fetch_month("2026-01", page_size=2)


def test_failure_preserves_pair_and_resume_only_fetches_pending_month(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    assert cache.salvar_local(normalize_records(month_records("2025-12"))).sucesso
    before = (cache.arquivo_dados.read_bytes(), cache.arquivo_metadata.read_bytes())
    api.fail.add("2026-02")
    first = cache.materialize_history(start="2026-01-01", end="2026-02-28", max_workers=1)
    assert not first.sucesso
    assert before == (cache.arquivo_dados.read_bytes(), cache.arquivo_metadata.read_bytes())
    with pytest.raises(ValueError, match="incompleta"):
        assert_adapter_complete(first)
    api.fail.clear()
    assert cache.materialize_history(start="2026-01-01", end="2026-02-28", max_workers=1).sucesso
    assert api.calls.count("2026-01") == 1 and api.calls.count("2026-02") == 2
    assert set(cache.carregar_local().dados.data.dt.strftime("%Y-%m")) == {"2025-12", "2026-01", "2026-02"}


def test_repeated_update_requeries_revisions_and_never_duplicates(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    for _ in range(2):
        assert cache.materialize_history(start="2026-01-01", end="2026-02-28").sucesso
    assert len(cache.carregar_local().dados) == 44 and api.calls.count("2026-01") == 2
    assert cache.default_start().isoformat() == "2025-03-01"


def test_month_replacement_removes_observations_retracted_by_source(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    frame = normalize_records(month_records("2026-01") + [{"Data": "2026-01-31", "Info": "imoveis_tipo_casa_br", "Valor": 10}])
    assert cache.salvar_local(frame).sucesso
    assert cache.materialize_history(start="2026-01-01", end="2026-01-31").sucesso
    assert "imoveis_tipo_casa_br" not in set(cache.carregar_local().dados["info"])


def test_missing_active_chart_blocks_promotion(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    assert cache.salvar_local(normalize_records(month_records("2025-12"))).sucesso
    before = sha256(cache.arquivo_dados.read_bytes()).hexdigest()
    api.deleted.add("credito_contratacao_taxa_pf_sfh_br")
    result = cache.materialize_history(start="2026-01-01", end="2026-02-28")
    assert not result.sucesso and "Cobertura incompleta" in result.mensagem
    assert sha256(cache.arquivo_dados.read_bytes()).hexdigest() == before


def test_historical_backfill_preserves_later_months_and_validates_selected_window(tmp_path):
    cache = MercadoImobiliarioCache(tmp_path, request_json=Olinda())
    assert cache.salvar_local(normalize_records(month_records("2026-02"))).sucesso
    result = cache.materialize_history(start="2026-01-01", end="2026-01-31")
    assert result.sucesso, result.mensagem
    assert set(cache.carregar_local().dados.data.dt.strftime("%Y-%m")) == {"2026-01", "2026-02"}


def test_end_date_never_includes_a_later_month_end(tmp_path):
    api = Olinda(); cache = MercadoImobiliarioCache(tmp_path, request_json=api)
    assert cache.materialize_history(start="2026-01-01", end="2026-02-10").sucesso
    assert api.calls == ["2026-01"]


def test_native_worker_contract_and_manager_registration(tmp_path):
    manager = CacheManager(tmp_path)
    assert isinstance(manager.get_cache("mercado_imobiliario"), MercadoImobiliarioCache)
    spec = validate_job_spec({"cache_type": "mercado_imobiliario", "periods": [], "mode": "rebuild",
        "options": {"start": "2014-04-01", "end": "2026-11-05"}, "materialize": True, "publish": False})
    calls = []
    cache = SimpleNamespace(materialize_history=lambda **kwargs: calls.append(kwargs) or CacheResult(True, "ok"))
    UpdateJobExecutor._special_update(SimpleNamespace(get_cache=lambda _: cache), spec)
    assert calls == [{"start": "2014-04-01", "end": "2026-11-05", "overwrite": True, "rebuild": True}]


def test_real_figures_keep_bcb_units_and_historical_cutoff(published):
    for section in SECTIONS:
        figures, checks = figures_for_section(published, section)
        assert all(item["Situação"] == "Incluída" for item in checks)
        for figure in figures:
            key = figure.layout.meta["chart_key"]
            panel = figura_para_painel(figure)
            assert "Olinda/MercadoImobiliario" in panel.fonte
            if key.startswith("estoque_risco"):
                assert max(panel.series.data_base) == "2024-12"
            if key == "contratacao_taxa_pj":
                assert panel.series[panel.series.serie == "SFH"].iloc[-1].valor == pytest.approx(.143)
            if key == "estoque_problematico_pf":
                assert figure.layout.yaxis.title.text == "R$ bilhões"
                tr = next(trace for trace in figure.data if trace.name == "FGTS")
                assert tr.y[-1] == pytest.approx(32.46348267284)
            if key == "imoveis_area":
                tr = next(trace for trace in figure.data if trace.name == "Privativa")
                assert tr.y[-1] == pytest.approx(58.95)


def test_partial_window_declares_historical_absence(published):
    sections, coverage = deck_sections(published, months=None, start="2026-01-01", end="2026-08-31")
    missing = [item for item in coverage if item["Situação"] != "Incluída"]
    assert len(missing) == 2 and all("Risco da operação" in item["Seção"] for item in missing)
    assert sum(len(section[2]) for section in sections) == 22


def test_section_pptx_has_24_native_charts_calibri_and_source_period(published):
    sections, coverage = deck_sections(published)
    blob, metadata = exportar_deck_secoes_pptx(sections, titulo_deck="Mercado Imobiliário")
    deck = Presentation(BytesIO(blob))
    assert metadata["paineis"] == 24 and all(item["Gráficos"] == 1 for item in coverage)
    charts = [shape.chart for slide in deck.slides for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 24 and all(chart.font.name == "Calibri" for chart in charts)
    sources = [shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame and shape.text.startswith("fonte: BCB · Olinda/")]
    assert len(sources) == 24 and all("BR" in text and " a " in text for text in sources)
    assert all(run.font.name == "Calibri" for slide in deck.slides for shape in slide.shapes if shape.has_text_frame for p in shape.text_frame.paragraphs for run in p.runs)
    assert not any(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes)
    with ZipFile(BytesIO(blob)) as archive:
        assert len([name for name in archive.namelist() if name.startswith("ppt/embeddings/")]) == 24
        texts = "".join(archive.read(name).decode() for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        assert "Olinda/MercadoImobiliario" in texts and "2024" in texts


def test_main_deck_signature_changes_with_imobiliario_revision(tmp_path):
    from tabs.mercado_credito import _assinatura_deck
    path = tmp_path / "metadata.json"; path.write_text('{"hash":"a"}')
    imob = SimpleNamespace(arquivo_metadata=path)
    manager = lambda: SimpleNamespace(get_cache=lambda name: imob if name == "mercado_imobiliario" else None)
    wide = pd.DataFrame({"x": [1]}, index=[pd.Timestamp("2026-08-31")])
    before = _assinatura_deck(wide, manager)
    path.write_text('{"hash":"b"}')
    assert _assinatura_deck(wide, manager) != before


def test_bundle_does_not_hide_a_successful_user_update(tmp_path):
    import json
    import shutil
    cache = MercadoImobiliarioCache(tmp_path, request_json=Olinda())
    assert cache.salvar_local(normalize_records(month_records("2025-12"))).sucesso
    cache.bundled_dir.mkdir(parents=True)
    shutil.copy2(cache.arquivo_dados, cache.bundled_dir / "dados.parquet")
    meta = json.loads(cache.arquivo_metadata.read_text()); meta["publication_id"] = "seed-1"
    meta["periodos"] = ["202512"]
    (cache.bundled_dir / "metadata.json").write_text(json.dumps(meta))
    assert cache.materialize_history(start="2026-01-01", end="2026-02-28").sucesso
    loaded = cache.carregar_local()
    assert loaded.metadata["baseline_publication_id"] == "seed-1"
    assert loaded.dados.data.max() == pd.Timestamp("2026-02-28")


def test_portable_worker_publishes_new_source_in_one_revision(tmp_path):
    from utils.ifdata_cache.durable_jobs import DurableJobQueue, run_worker
    from utils.ifdata_cache.official_store import LocalRevisionStore
    from utils.ifdata_cache.update_access import Principal
    from utils.ifdata_cache.update_backend import UpdateBackend, collect_official_artifacts

    class Manager(CacheManager):
        def _registrar_caches_padrao(self):
            self.registrar(MercadoImobiliarioCache(self.base_dir, request_json=Olinda()))

    initial_manager = Manager(tmp_path / "seed")
    cache = initial_manager.get_cache("mercado_imobiliario")
    assert cache.salvar_local(normalize_records(month_records("2025-12"))).sucesso
    store = LocalRevisionStore(tmp_path / "official")
    initial = store.stage(collect_official_artifacts(initial_manager))
    store.activate(initial.revision_id, expected_parent=None)
    base = tmp_path / "service"
    backend = UpdateBackend(base, store, queue=DurableJobQueue(base))
    analyst = Principal("teste", {"read", "update", "publish"})
    job = backend.submit({"cache_type": "mercado_imobiliario", "periods": [], "mode": "incremental",
        "options": {"start": "2026-01-01", "end": "2026-02-28"}, "materialize": True, "publish": True}, analyst, "request-1")
    executor = UpdateJobExecutor(backend, manager_factory=Manager, materializer=lambda *_: [])
    run_worker(backend.queue, executor, once=True)
    finished = backend.get(job["job_id"], analyst)
    assert finished["status"] == "succeeded", finished.get("error")
    assert finished["result"]["activated"] is True
    snapshot = store.current()
    frame = pd.read_parquet(snapshot.resolve("data/cache/mercado_imobiliario/dados.parquet"))
    assert frame.data.max() == pd.Timestamp("2026-02-28") and frame.data.min() == pd.Timestamp("2025-12-31")
    assert snapshot.revision_id != initial.revision_id
    assert pd.read_parquet(initial.resolve("data/cache/mercado_imobiliario/dados.parquet")).data.max() == pd.Timestamp("2025-12-31")


def test_classification_changes_cannot_pass_publication_validation(published):
    frame = published.iloc[:1].copy()
    frame.loc[frame.index[0], "uf"] = "sp"
    assert not validate_frame(frame)["success"]


def test_new_view_opens_without_sgs_and_reports_olinda_sources(monkeypatch, published):
    from streamlit.testing.v1 import AppTest
    from tabs import mercado_imobiliario as UI
    monkeypatch.setattr(UI, "load_frame", lambda _: (published, {}, ""))
    app = AppTest.from_string('''
import streamlit as st
from tabs.mercado_credito import render_mercado_credito
st.session_state['sgs_credit_main_section'] = 'Mercado Imobiliário'
render_mercado_credito(None)
''').run(timeout=20)
    assert not app.exception
    assert any(item.key == "imob_section" for item in app.get("button_group"))
    assert any("Olinda/MercadoImobiliario" in item.value for item in app.markdown)
