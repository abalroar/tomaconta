from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from utils.atualizar_base_ui import (
    execution_options, fetch_remote_cache_status, invalid_date_range,
    record_adapter_result, remote_status, resumable_run, run_quarterly_update,
)
from utils.ifdata_cache.update_state import UpdateBusyError, UpdateRunStore


class FakeManager:
    def __init__(self, base_dir, results):
        self.base_dir = base_dir
        self.results = list(results)
        self.calls = []

    def extrair_periodos_com_salvamento(self, **kwargs):
        self.calls.append(kwargs)
        metadata = self.results.pop(0)
        if kwargs.get('callback_progresso'):
            kwargs['callback_progresso'](0, len(kwargs['periodos']), kwargs['periodos'][0])
        if kwargs.get('callback_checkpoint') and metadata.get('persisted_periods'):
            kwargs['callback_checkpoint'](metadata)
        return SimpleNamespace(sucesso=metadata.get('success', True), mensagem='Resultado de teste', metadata=metadata)


def test_new_cache_never_inherits_other_execution(tmp_path):
    store = UpdateRunStore(tmp_path)
    previous = store.create('principal', ['202603', '202606'])
    store.record_result(previous, {'persisted_periods': ['202603']})
    current = store.create('capital', ['202603', '202606'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603', '202606']}])
    _, receipt = run_quarterly_update(manager, store, current)
    assert manager.calls[0]['periodos'] == ['202603', '202606']
    assert receipt['status'] == 'saved'
    assert not resumable_run(previous, 'capital')


def test_resume_uses_frozen_plan_and_only_confirmed_periods(tmp_path):
    store = UpdateRunStore(tmp_path)
    original = store.create('principal', ['202603', '202606'], options={'intervalo_save': 2})
    manager = FakeManager(tmp_path, [
        {'persisted_periods': ['202603'], 'failed_periods': {'202606': 'timeout'}},
        {'persisted_periods': ['202606']},
    ])
    _, partial = run_quarterly_update(manager, store, original)
    assert partial['status'] == 'partial'
    assert partial['pending_periods'] == ['202606']
    assert resumable_run(partial, 'principal')
    plan = execution_options(partial)
    assert plan['periods'] == ['202603', '202606']
    assert plan['options']['intervalo_save'] == 2
    _, complete = run_quarterly_update(manager, store, partial)
    assert manager.calls[1]['periodos'] == ['202606']
    assert complete['failed_periods'] == {}
    assert complete['status'] == 'saved'


def test_rebuild_discards_history_only_in_initial_batch(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603', '202606'], 'rebuild', options={'batch_size': 1})
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603']}, {'persisted_periods': ['202606']}])
    _, first = run_quarterly_update(manager, store, run)
    _, second = run_quarterly_update(manager, store, first)
    assert [c['modo'] for c in manager.calls] == ['rebuild', 'incremental']
    assert second['status'] == 'saved'


def test_no_materialization_when_only_extracting(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603']}])
    _, receipt = run_quarterly_update(manager, store, run, materialize=lambda _: pytest.fail('unexpected derivation'))
    assert receipt['status'] == 'saved'


def test_partial_result_never_publishes(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603', '202606'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603'], 'failed_periods': {'202606': 'timeout'}}])
    _, receipt = run_quarterly_update(manager, store, run, publish=lambda *_: pytest.fail('partial publication'))
    assert receipt['status'] == 'partial'


def test_publication_stage_follows_persistence_and_keeps_retry_state(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603']}])

    def materialize(_):
        assert store.load(run['run_id'])['status'] == 'validating'
        return [{'status': 'ok'}]

    def publish(record, details):
        assert store.load(run['run_id'])['status'] == 'publishing'
        assert record['pending_periods'] == []
        return False, 'Falha remota', {}

    _, receipt = run_quarterly_update(manager, store, run, materialize=materialize, publish=publish)
    assert receipt['status'] == 'publish_failed'
    assert receipt['persisted_periods'] == ['202603']
    assert receipt['publication']['message'] == 'Falha remota'


def test_checkpoint_error_is_not_converted_to_success(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603'], 'checkpoint_error': 'disco indisponível'}])
    _, receipt = run_quarterly_update(manager, store, run, publish=lambda *_: pytest.fail('unsafe publish'))
    assert receipt['status'] == 'failed'
    assert receipt['error'] == 'disco indisponível'


def test_contender_cannot_overwrite_successful_run(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603'])
    started, release = threading.Event(), threading.Event()
    failures = []

    class BlockingManager(FakeManager):
        def extrair_periodos_com_salvamento(self, **kwargs):
            started.set()
            assert release.wait(5)
            return super().extrair_periodos_com_salvamento(**kwargs)

    first = BlockingManager(tmp_path, [{'persisted_periods': ['202603']}])
    second = FakeManager(tmp_path, [{'persisted_periods': ['202603']}])

    def execute():
        try:
            run_quarterly_update(first, store, run)
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    assert started.wait(5)
    try:
        with pytest.raises(UpdateBusyError):
            run_quarterly_update(second, store, run)
    finally:
        release.set()
        thread.join(5)
    assert not failures
    assert not second.calls
    assert store.load(run['run_id'])['status'] == 'saved'


def test_materialization_exception_is_recorded_while_lock_held(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('principal', ['202603'])
    manager = FakeManager(tmp_path, [{'persisted_periods': ['202603']}])

    def fail(_):
        raise RuntimeError('derivação falhou')

    with pytest.raises(RuntimeError, match='derivação falhou'):
        run_quarterly_update(manager, store, run, materialize=fail, publish=lambda *_: None)
    receipt = store.load(run['run_id'])
    assert receipt['status'] == 'publish_failed'
    assert receipt['persisted_periods'] == ['202603']


def test_special_adapter_keeps_native_partial_receipt(tmp_path):
    store = UpdateRunStore(tmp_path)
    run = store.create('taxas_juros_historico', [], options={'start': '2026-01-01'})
    result = SimpleNamespace(sucesso=True, mensagem='Há mais janelas', metadata={'remaining_windows': 3, 'finalized': False})
    receipt = record_adapter_result(store, run, result, finalized=False)
    assert receipt['status'] == 'partial'
    assert receipt['summary']['remaining_windows'] == 3
    assert not resumable_run(receipt, 'taxas_juros_historico')


def test_invalid_special_dates_are_detected_before_dispatch():
    assert invalid_date_range(date(2026, 6, 1), date(2026, 3, 1))
    assert not invalid_date_range(date(2026, 3, 1), date(2026, 3, 1))


def test_remote_status_does_not_claim_old_remote_is_current():
    assert remote_status({'existe': True, 'sha256': 'new'}, {'existe': True, 'sha256': 'old'}) == 'Versão local diferente'
    assert remote_status({'existe': True}, {'existe': True}) == 'Disponível no release (versão não verificada)'
    assert remote_status({'existe': True}, {'verification_error': 'timeout'}) == 'Verificação indisponível'


def test_remote_catalog_queries_distinct_effective_releases_once():
    calls = []
    names = ['principal', 'taxas_juros', 'taxas_juros_historico', 'mercado_credito_sgs', 'spb_meios_pagamento']
    destinations = [(name, 'owner/repo', 'v1', name) for name in names]
    destinations.append(('scr_data', 'owner/repo', 'scr', 'scr_data'))

    def request(url, **_):
        calls.append(url)
        assets = [{'name': f'{name}_dados.parquet', 'size': 100} for name in names + ['scr_data']]
        return SimpleNamespace(status_code=200, json=lambda: {'assets': assets})

    status = fetch_remote_cache_status(destinations, request)
    assert len(calls) == 2
    assert all(status['caches'][name]['existe'] for name in names + ['scr_data'])
    assert status['caches']['scr_data']['tag'] == 'scr'


def test_remote_read_failure_is_unknown_not_absent():
    status = fetch_remote_cache_status([('principal', 'owner/repo', 'v1', 'principal')],
        lambda *a, **k: SimpleNamespace(status_code=503))
    assert status['caches']['principal']['verification_error']
    assert remote_status({'existe': True}, status['caches']['principal']) == 'Verificação indisponível'


def test_receipt_and_backup_survive_rerun():
    AppTest = pytest.importorskip('streamlit.testing.v1').AppTest
    source = (Path(__file__).resolve().parents[1] / 'app1.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_render_comprovante_atualizacao')
    function = ast.get_source_segment(source, node)
    script = '''import streamlit as st
import json
from utils.atualizar_base_ui import STATUS_LABELS
class Manager:
    def get_dados_para_download(self, name):
        return {"label": "CSV", "data": b"a,b\\n1,2", "ext": ".csv", "mime": "text/csv"}
record = {"run_id": "abc", "cache_type": "principal", "status": "saved", "mode": "incremental", "periods": ["202603"], "persisted_periods": ["202603"], "pending_periods": [], "updated_at": "agora"}
''' + function + '\n_render_comprovante_atualizacao(record, Manager())\n'
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert 'Salva localmente' in app.info[0].value
    assert len(app.get('download_button')) == 1
    app.button[0].click().run()
    assert not app.exception
    assert len(app.get('download_button')) == 2
    app.run()
    assert len(app.get('download_button')) == 2


def _admin_app_script(base_dir):
    """Exercise the actual route with fake read dependencies, never the app bootstrap."""
    import textwrap
    source = (Path(__file__).resolve().parents[1] / 'app1.py').read_text()
    start = source.index('elif menu == "Atualizar Base":')
    end = source.index('elif menu == "Glossário":', start)
    route = textwrap.dedent(source[start:end].split('\n', 1)[1])
    render_node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_render_comprovante_atualizacao')
    render = ast.get_source_segment(source, render_node)
    setup = '''import streamlit as st
import pandas as pd
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta
from utils.ifdata_cache.update_state import *
from utils.ifdata_cache.update_catalog import *
from utils.ifdata_cache import filter_supported_periods, describe_support_window
from utils.atualizar_base_ui import *
SENHA_ADMIN = "test"
st.session_state.setdefault("senha_admin_atualizacao_nova", "test")
class FakeCache:
    def __init__(self, name):
        self.config = SimpleNamespace(nome=name)
        self.arquivo_dados = Path(BASE_DIR) / (name + '.parquet')
        self.arquivo_dados_pickle = Path(BASE_DIR) / (name + '.pkl')
    def dataset_paths(self):
        return {"nucleo": self.arquivo_dados}
class FakeManager:
    base_dir = Path(BASE_DIR)
    def listar_caches(self):
        return list(QUARTERLY_CACHES) + ['bloprudencial', 'taxas_juros', 'taxas_juros_historico', 'spb_meios_pagamento', 'mercado_credito_sgs']
    def get_cache(self, name):
        return FakeCache(name)
    def info(self, name):
        return {"existe": False, "periodos": []}
st.session_state.setdefault('cache_manager', FakeManager())
_get_sgs_credit_cache = lambda manager: None
_release_config_app = lambda: SimpleNamespace(repo='owner/repo', tag='test', repo_source='test', tag_source='test')
build_runtime_manifest = lambda *a, **k: {"caches": {}, "gates": {}}
verificar_caches_github = lambda destinations: {"caches": {}, "release_existe": True, "releases": {}}
_ordenar_opcoes_cache_atualizacao = lambda keys, _: keys
_status_cache_atualizacao = remote_status
_intervalo_periodos_cache = lambda info: ('-', '-')
_versao_local_cache = lambda info: '-'
_render_runbook_atualizar_base = lambda **kwargs: None
_resumo_publicacao_consistente = lambda name: 'Resumo de teste'
_normalizar_periodo_cache = lambda value: '202603'
_prox_periodo_api = lambda value: ''
_carregar_checkpoint_atualizacao = lambda: {}
_obter_token_github = lambda: ('test-token', 'test')
def _validar_token_release_github(*args, **kwargs):
    st.session_state['token_checks'] = st.session_state.get('token_checks', 0) + 1
    return True, 'Acesso de teste'
def _diagnostico_mapeamento_instituicoes(*args):
    raise AssertionError('Diagnóstico não deve executar durante edição do formulário')
'''
    return 'BASE_DIR = ' + repr(str(base_dir)) + '\n' + setup + '\n' + render + '\n' + route


def test_actual_route_keeps_token_checks_explicit_and_special_controls_valid(tmp_path):
    AppTest = pytest.importorskip('streamlit.testing.v1').AppTest
    app = AppTest.from_string(_admin_app_script(tmp_path)).run()
    assert not app.exception
    assert app.session_state.filtered_state.get('token_checks', 0) == 0
    assert app.checkbox(key='publicar_auto').value is False
    assert app.checkbox(key='modo_bg_unificado')
    app.selectbox(key='cache_selecionado').set_value('mercado_credito_sgs').run()
    assert not app.exception
    assert app.session_state.filtered_state.get('token_checks', 0) == 0
    assert not [item for item in app.checkbox if item.key == 'modo_bg_unificado']
    app.date_input(key='sgs_credit_data_inicio_extracao').set_value(date(2026, 6, 1))
    app.date_input(key='sgs_credit_data_fim_extracao').set_value(date(2026, 3, 1))
    app.run()
    assert not app.exception
    assert app.button(key='btn_extrair_unificado').disabled
    app.button(key='validate_update_token').click().run()
    assert not app.exception
    assert app.session_state.filtered_state['token_checks'] == 1


def test_all_fifteen_source_forms_render_without_triggering_diagnostics(tmp_path):
    AppTest = pytest.importorskip('streamlit.testing.v1').AppTest
    app = AppTest.from_string(_admin_app_script(tmp_path)).run()
    names = list(app.selectbox(key='cache_selecionado').options)
    assert len(names) == 15
    from utils.ifdata_cache.update_catalog import QUARTERLY_CACHES
    for name in list(QUARTERLY_CACHES) + ['bloprudencial', 'taxas_juros', 'taxas_juros_historico', 'spb_meios_pagamento', 'mercado_credito_sgs']:
        app.selectbox(key='cache_selecionado').set_value(name).run()
        assert not app.exception, name
        assert app.session_state.filtered_state.get('token_checks', 0) == 0
        assert bool([item for item in app.checkbox if item.key == 'modo_bg_unificado']) == (name in QUARTERLY_CACHES)


def test_actual_resume_uses_original_window_even_with_invalid_new_form(tmp_path):
    AppTest = pytest.importorskip('streamlit.testing.v1').AppTest
    store = UpdateRunStore(tmp_path)
    record = store.create('principal', ['202603', '202606'], options={'intervalo_save': 1, 'publicar_auto': False})
    store.record_result(record, {'persisted_periods': ['202603'], 'failed_periods': {'202606': 'timeout'}})
    script = _admin_app_script(tmp_path)
    implementation = '''    def extrair_periodos_com_salvamento(self, **kwargs):
        st.session_state['executed_periods'] = kwargs['periodos']
        metadata = {'persisted_periods': kwargs['periodos']}
        kwargs['callback_checkpoint'](metadata)
        return SimpleNamespace(sucesso=True, mensagem='Salvo no teste', metadata=metadata)
'''
    script = script.replace('    def info(self, name):', implementation + '    def info(self, name):')
    # The cached remote reader exposes clear() in production.
    script = script.replace('_ordenar_opcoes_cache_atualizacao =', 'verificar_caches_github.clear = lambda: None\n_ordenar_opcoes_cache_atualizacao =')
    app = AppTest.from_string(script).run()
    app.selectbox(key='ano_i_unificado').set_value(2028).run()
    assert app.button(key='btn_extrair_unificado').disabled
    app.button(key='retomar_unificado').click().run()
    assert not app.exception
    assert app.session_state.filtered_state['executed_periods'] == ['202606']
    assert store.load(record['run_id'])['status'] == 'saved'


def test_remote_individual_asset_cannot_make_consolidated_cache_available():
    destinations = [('principal', 'owner/repo', 'v1', 'principal'), ('principal_individual', 'owner/repo', 'v1', 'principal_individual')]
    response = SimpleNamespace(status_code=200, json=lambda: {'assets': [{'name': 'principal_individual_dados.parquet', 'size': 10}]})
    status = fetch_remote_cache_status(destinations, lambda *a, **k: response)
    assert not status['caches']['principal']['existe']
    assert status['caches']['principal_individual']['existe']
