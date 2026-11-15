from pathlib import Path
from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest
import requests

from utils import dre_bcb_source as source


def _raw(period='202606', kind=1):
    return pd.DataFrame({'CodInst': ['C0080099' if kind == 1 else '60701190'],
                         'Instituição': ['ITAU - PRUDENCIAL' if kind == 1 else 'ITAU UNIBANCO S.A.'],
                         'Período': [f'{int(period[4:]) // 3}/{period[:4]}'],
                         'Lucro Líquido (z) = (w) + (x) + (y)': [24_670_305_939.7],
                         'Ativo Total': [2_846_418_000_000.0],
                         'Ausente': [None], 'Zero': [0.0]})


def _provenance():
    return {'api': 'BCB oficial', 'source_urls': ['https://www3.bcb.gov.br/ifdata/rest/arquivos']}


def test_money_unit_boundary_keeps_missing_and_zero():
    from tabs.dre_ifdata_schema import load_mapping_config, build_mapping_candidates, calculate_dre
    frame = source.normalize_reais(_raw(), 'BCB')
    assert frame.iloc[0]['Lucro Líquido (z) = (w) + (x) + (y)'] == pytest.approx(24_670_305.9397)
    assert pd.isna(frame.iloc[0]['Ausente'])
    assert frame.iloc[0]['Zero'] == 0
    with pytest.raises(ValueError, match='duplicada'):
        source.normalize_reais(frame, 'BCB')
    config = load_mapping_config()
    dre, _, _ = calculate_dre(frame.iloc[0], build_mapping_candidates(frame, config), config)
    net = dre[dre['nome_canônico'].eq('net_income')].iloc[0]
    assert net['valor_r_mm'] == pytest.approx(24_670.3059397)


def test_olinda_failure_uses_official_api_and_saves_validated_query(tmp_path, monkeypatch):
    monkeypatch.setattr(source, '_query_olinda', lambda *a: (_ for _ in ()).throw(requests.HTTPError('500')))
    monkeypatch.setattr(source, '_query_web', lambda *a: (_raw(), _provenance()))
    frame, meta = source.consult_dre('202606', 1, tmp_path)
    assert meta['fallback'] is False
    assert meta['api'] == 'BCB oficial'
    assert frame['Instituição'].tolist() == ['ITAU - PRUDENCIAL']
    monkeypatch.setattr(source, '_query_web', lambda *a: pytest.fail('fresh persisted consultation should be reused'))
    again, second = source.consult_dre('202606', 1, tmp_path)
    pd.testing.assert_frame_equal(frame, again)
    assert second['queried_at_utc'] == meta['queried_at_utc']


def test_refresh_bypasses_valid_saved_consultation(tmp_path, monkeypatch):
    calls = []
    def query(period, kind):
        calls.append((period, kind))
        return _raw(period, kind), _provenance()
    monkeypatch.setattr(source, '_query_olinda', query)
    source.consult_dre('202606', 1, tmp_path)
    source.consult_dre('202606', 1, tmp_path, refresh=True)
    assert calls == [('202606', 1), ('202606', 1)]


def test_expired_saved_query_is_reconsulted(tmp_path, monkeypatch):
    monkeypatch.setattr(source, '_query_olinda', lambda *a: (_raw(), _provenance()))
    source.consult_dre('202606', 1, tmp_path)
    _, manifest = source._paths('202606', 1, tmp_path)
    meta = json.loads(manifest.read_text())
    meta['queried_at_utc'] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    manifest.write_text(json.dumps(meta))
    calls = []
    monkeypatch.setattr(source, '_query_olinda', lambda *a: (calls.append(a) or _raw(), _provenance()))
    source.consult_dre('202606', 1, tmp_path)
    assert len(calls) == 1


def _fail_queries(monkeypatch):
    def fail(*a):
        raise requests.ConnectionError('BC indisponível')
    monkeypatch.setattr(source, '_query_olinda', fail)
    monkeypatch.setattr(source, '_query_web', fail)


def test_unavailable_apis_recovers_same_period_and_perimeter_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(source, '_query_olinda', lambda *a: (_raw(), _provenance()))
    first, first_meta = source.consult_dre('202606', 1, tmp_path)
    _fail_queries(monkeypatch)
    frame, meta = source.consult_dre('202606', 1, tmp_path, refresh=True)
    assert meta['fallback'] is True
    assert meta['queried_at_utc'] == first_meta['queried_at_utc']
    pd.testing.assert_frame_equal(first, frame)
    monkeypatch.setattr(source, '_published_raw', lambda *a: (pd.DataFrame(), {}))
    for period, kind in [('202603', 1), ('202606', 3)]:
        with pytest.raises(ValueError, match='não há DRE validada'):
            source.consult_dre(period, kind, tmp_path)


def test_published_recovery_never_substitutes_another_period(tmp_path, monkeypatch):
    _fail_queries(monkeypatch)
    monkeypatch.setattr(source, '_published_raw', lambda *a: (_raw('202603'), {'published_file': 'published-dre'}))
    with pytest.raises(ValueError, match='não há DRE validada'):
        source.consult_dre('202606', 1, tmp_path)
    frame, meta = source.consult_dre('202603', 1, tmp_path)
    assert meta['fallback'] is True
    assert meta['queried_at_utc'] is None
    assert frame['Período'].tolist() == ['1/2026']
    assert frame.iloc[0]['Ativo Total'] == pytest.approx(2_846_418_000)


def test_corrupt_saved_query_not_served(tmp_path, monkeypatch):
    monkeypatch.setattr(source, '_query_olinda', lambda *a: (_raw(), _provenance()))
    source.consult_dre('202606', 1, tmp_path)
    parquet, _ = source._paths('202606', 1, tmp_path)
    parquet.write_bytes(b'corrupt')
    _fail_queries(monkeypatch)
    monkeypatch.setattr(source, '_published_raw', lambda *a: (pd.DataFrame(), {}))
    with pytest.raises(ValueError, match='não há DRE validada'):
        source.consult_dre('202606', 1, tmp_path)


def _long():
    return pd.DataFrame({'CodInst': ['C0080099', '60701190', '60701190'], 'NomeColuna': ['Valor\n (a)', 'Valor\n (a)', 'Outra'],
                         'Saldo': [None, 0, 1000], 'AnoMes': ['202606'] * 3, 'TipoInstituicao': [1] * 3})


def _registry():
    return pd.DataFrame({'CodInst': ['C0080099', '60701190'], 'NomeInstituicao': ['ITAU - PRUDENCIAL', 'TESTE']})


def test_wide_keeps_missing_cells_and_exact_names_without_aggregation():
    frame = source._wide_values(_long(), _registry(), '202606', 1)
    assert pd.isna(frame.set_index('CodInst').loc['C0080099', 'Valor (a)'])
    assert frame.set_index('CodInst').loc['60701190', 'Valor (a)'] == 0
    assert frame.set_index('CodInst').loc['C0080099', 'Instituição'] == 'ITAU - PRUDENCIAL'


@pytest.mark.parametrize('change,error', [('AnoMes', 'Competência'), ('TipoInstituicao', 'Perímetro')])
def test_wide_rejects_mixed_period_or_perimeter(change, error):
    data = _long()
    data.loc[0, change] = '202603' if change == 'AnoMes' else 3
    with pytest.raises(ValueError, match=error):
        source._wide_values(data, _registry(), '202606', 1)


def test_conflicting_cells_never_sum():
    data = _long()
    conflict = data.iloc[[1]].assign(Saldo=42)
    with pytest.raises(ValueError, match='conflitantes'):
        source._wide_values(pd.concat([data, conflict]), _registry(), '202606', 1)


def test_missing_official_name_never_becomes_id():
    with pytest.raises(ValueError, match='não cobre'):
        source._wide_values(_long(), _registry().iloc[:1], '202606', 1)


def test_available_periods_uses_official_report_and_perimeter(tmp_path, monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return [
                {'dt': 202606, 'files': [{'trel': {'n': 'Demonstração de Resultado', 's': [{'id': 1009}]}}]},
                {'dt': 202609, 'files': [{'trel': {'n': 'Resumo', 's': [{'id': 1009}]}}]},
                {'dt': 202603, 'files': [{'trel': {'n': 'Demonstração de Resultado', 's': [{'id': 1006}]}}]},
            ]
    monkeypatch.setattr(source.requests, 'get', lambda *a, **k: Response())
    monkeypatch.setattr(source, '_published_raw', lambda *a: (pd.DataFrame(), {}))
    assert source.available_periods(1, tmp_path) == ['202606']
    assert source.available_periods(3, tmp_path) == ['202603']


def test_dre_ui_starts_with_analysis_and_refreshes_api(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import tabs.dre_ifdata_schema as ui
    calls = []
    monkeypatch.setattr(ui, '_dre_bcb_periods', lambda *a: ['202606'])
    def query(period, kind, root, refresh_token):
        calls.append((period, kind, refresh_token))
        frame = source.normalize_reais(_raw(period, kind), 'BCB')
        return frame, {**_provenance(), 'fallback': False, 'queried_at_utc': datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(ui, '_dre_bcb_consult', query)
    monkeypatch.setattr(ui, '_dre_bcb_history', lambda *a: pd.DataFrame())
    at = AppTest.from_string('from tabs.dre_ifdata_schema import render_streamlit_app\nrender_streamlit_app()').run(timeout=15)
    assert not at.exception
    assert len(at.get('file_uploader')) == 0
    assert [tab.label for tab in at.tabs] == ['DRE', 'Gráficos', 'Validações']
    assert 'Rubrica' in at.dataframe[0].value
    assert 'N/D' in at.dataframe[0].value['Valor (R$ milhões)'].tolist()
    assert all(label not in at.dataframe[0].value for label in ['colunas_origem', 'formula_usada'])
    at.button(key='dre_bcb_refresh').click().run(timeout=15)
    assert not at.exception
    assert calls[-1][:2] == ('202606', 1)
    assert calls[-1][2]
    at.selectbox(key='dre_bcb_kind').select(3).run(timeout=15)
    assert not at.exception
    assert calls[-1][1] == 3
    control = at.selectbox(key='dre_bcb_institution_3')
    assert control.format_func(control.value) == 'ITAU UNIBANCO S.A.'


def test_institution_selection_survives_period_change(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import tabs.dre_ifdata_schema as ui
    monkeypatch.setattr(ui, '_dre_bcb_periods', lambda *a: ['202606', '202603'])
    def query(period, kind, root, refresh):
        raw = _raw(period, kind)
        other = raw.copy()
        other['CodInst'], other['Instituição'] = 'C0000001', 'BANCO B'
        frame = source.normalize_reais(pd.concat([raw, other], ignore_index=True), 'BCB')
        return frame, {**_provenance(), 'fallback': False, 'queried_at_utc': None}
    monkeypatch.setattr(ui, '_dre_bcb_consult', query)
    monkeypatch.setattr(ui, '_dre_bcb_history', lambda *a: pd.DataFrame())
    at = AppTest.from_string('from tabs.dre_ifdata_schema import render_streamlit_app\nrender_streamlit_app()').run(timeout=15)
    at.selectbox(key='dre_bcb_institution_1').select('C0000001').run(timeout=15)
    at.selectbox(key='dre_bcb_period_1').select('202603').run(timeout=15)
    assert not at.exception
    assert at.selectbox(key='dre_bcb_institution_1').value == 'C0000001'


def test_individual_default_uses_exact_identity_not_name_substring(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import tabs.dre_ifdata_schema as ui
    monkeypatch.setattr(ui, '_dre_bcb_periods', lambda *a: ['202606'])
    def query(period, kind, root, refresh):
        raw = _raw(period, kind)
        other = raw.copy()
        other['CodInst'], other['Instituição'] = '60394079', 'BANCO ITAUBANK S.A.'
        frame = source.normalize_reais(pd.concat([raw, other], ignore_index=True), 'BCB')
        return frame, {**_provenance(), 'fallback': False, 'queried_at_utc': None}
    monkeypatch.setattr(ui, '_dre_bcb_consult', query)
    monkeypatch.setattr(ui, '_dre_bcb_history', lambda *a: pd.DataFrame())
    at = AppTest.from_string('from tabs.dre_ifdata_schema import render_streamlit_app\nrender_streamlit_app()').run(timeout=15)
    at.selectbox(key='dre_bcb_kind').select(3).run(timeout=15)
    assert not at.exception
    assert at.selectbox(key='dre_bcb_institution_3').value == '60701190'
