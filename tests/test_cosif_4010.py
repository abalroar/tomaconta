from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import pandas as pd
import pytest

from scripts.ingest_cosif_4010 import ingest
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.cosif_4010 import (
    Cosif4010Cache, KEY_COLUMNS, LOADER_VERSION, SOURCE_COLUMNS,
    fgc_reference_frame, read_source_zip, validate_frame,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'data/bundled/cosif_4010'


def sample(period='202606', saldo=0.0):
    row = dict.fromkeys(SOURCE_COLUMNS, '')
    row.update(DATA_BASE=period, DOCUMENTO='4010', CNPJ='00000001',
               NOME_INSTITUICAO='Banco individual', NOME_CONGL='Grupo prudencial',
               CONTA='3822000003', NOME_CONTA='ATIVO DE REFERÊNCIA (AR)', SALDO=saldo)
    row.update({'Período': period, 'GRUPO_FONTE': 'Bancos', 'ARQUIVO_FONTE': period+'BANCOS.csv.zip'})
    return pd.DataFrame([row])


def test_parser_preserves_identifiers_zero_missing_and_document_scope(tmp_path):
    rows = []
    for cnpj, doc, amount in [('00000000', '4010', '1.234,56'), ('00000001', '4010', '0,00'),
                              ('00000002', '4010', ''), ('00000000', '4016', '999,00')]:
        data = sample().iloc[0].to_dict()
        data.update(CNPJ=cnpj, DOCUMENTO=doc, SALDO=amount)
        rows.append(';'.join(str(data[col]) for col in SOURCE_COLUMNS))
    raw = 'Balancete\nData de geracao: 2026-08-31\nFonte: BCB\n#'+';'.join(SOURCE_COLUMNS)+'\n'+'\n'.join(rows)
    path = tmp_path/'202606BANCOS.csv.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('202606BANCOS.CSV', raw.encode('latin1'))
    data, audit = read_source_zip(path, '202606', 'Bancos')
    assert data.CNPJ.tolist() == ['00000000', '00000001', '00000002']
    assert data.SALDO.iloc[:2].tolist() == [1234.56, 0]
    assert pd.isna(data.SALDO.iloc[2])
    assert audit['documentos_na_fonte'] == {'4010': 3, '4016': 1}
    with pytest.raises(ValueError, match='competência'):
        read_source_zip(path, '202607', 'Bancos')


def test_duplicate_keys_and_other_documents_are_rejected():
    with pytest.raises(ValueError, match='duplicada'):
        validate_frame(pd.concat([sample(), sample()]))
    with pytest.raises(ValueError, match='outro documento'):
        validate_frame(sample().assign(DOCUMENTO='4016'))


def test_bundle_is_complete_and_source_coverage_is_auditable():
    metadata = json.loads((BUNDLE/'metadata.json').read_text())
    assert hashlib.sha256((BUNDLE/'dados.parquet').read_bytes()).hexdigest() == metadata['sha256']
    data = pd.read_parquet(BUNDLE/'dados.parquet')
    validate_frame(data)
    assert len(data) == 345835
    assert data.CNPJ.nunique() == 1752
    assert set(data.DATA_BASE) == {'202606'}
    assert '00000000' in set(data.CNPJ)
    sources = metadata['extra']['fontes_por_periodo']['202606']
    assert sum(source['registros_4010'] for source in sources) == len(data)
    assert len(sources) == 5
    assert not data.duplicated(KEY_COLUMNS).any()


def test_fgc_keeps_all_names_and_does_not_infer_cr():
    data = fgc_reference_frame(Cosif4010Cache(ROOT), ('202606',))
    assert len(data) == 1752
    assert data['AR'].notna().sum() == 270
    assert data['VR'].notna().sum() == 107
    assert data['CR'].isna().all()
    original = data.set_index('CNPJ').loc['92894922']
    assert original['AR'] == pytest.approx(34_798_346_860.47)
    assert pd.isna(original['VR'])
    assert data['VR - controle'].notna().sum() != 0


def test_stale_runtime_cannot_shadow_deployed_bundle(tmp_path, monkeypatch):
    cache = Cosif4010Cache(tmp_path)
    assert cache.salvar_local(sample('202603')).sucesso
    cache.bundled_dir.mkdir(parents=True)
    for name in ('dados.parquet', 'metadata.json'):
        shutil.copy2(BUNDLE/name, cache.bundled_dir/name)
    monkeypatch.setattr('requests.get', lambda *a, **k: pytest.fail('bundle deve funcionar offline'))
    assert cache.available_periods() == ['202606']
    assert cache.arquivo_dados.parent == cache.bundled_dir
    assert len(cache.load_slice(('202606',), contas=('3822000003',))) == 270


def test_new_ingestion_preserves_history_and_follows_current_bundle(tmp_path, monkeypatch):
    cache = Cosif4010Cache(tmp_path)
    assert cache.salvar_local(sample()).sucesso
    cache.bundled_dir.mkdir(parents=True)
    for source, name in [(cache.arquivo_dados_runtime,'dados.parquet'), (cache.arquivo_metadata_runtime,'metadata.json')]:
        shutil.copy2(source, cache.bundled_dir/name)
    monkeypatch.setattr(cache, 'extrair_periodo', lambda p, **kw: CacheResult(True, 'OK', sample(p, 10), {'fontes': []}))
    ingest(cache, ['202607'])
    assert cache.available_periods() == ['202606','202607']
    assert cache.arquivo_dados == cache.arquivo_dados_runtime
    before = cache.arquivo_dados.read_bytes()
    monkeypatch.setattr(cache, 'extrair_periodo', lambda p, **kw: CacheResult(False, 'grupo indisponível'))
    with pytest.raises(RuntimeError, match='grupo indisponível'):
        ingest(cache, ['202608'])
    assert cache.arquivo_dados.read_bytes() == before


def test_cold_download_uses_published_tag_and_rejects_wrong_hash(tmp_path, monkeypatch):
    monkeypatch.setenv('TOMACONTA_RELEASE_TAG','v2.0-cache')
    cache = Cosif4010Cache(tmp_path)
    metadata = json.loads((BUNDLE/'metadata.json').read_text())
    urls = []
    class Response:
        def __init__(self, data): self.content = data
        def raise_for_status(self): pass
        def json(self): return metadata
    def get(url, **kwargs):
        urls.append(url)
        return Response((BUNDLE/'dados.parquet').read_bytes() if '.parquet' in url else b'')
    monkeypatch.setattr('requests.get',get)
    assert cache.available_periods() == ['202606']
    assert all('/v1.1-cache/' in url for url in urls)
    assert cache.arquivo_dados.exists()
    assert len(cache.load_slice(('202606',),contas=('9822500002',))) == 107
    metadata['sha256'] = '0'*64
    result = cache.baixar_remoto()
    assert not result.sucesso
    assert 'SHA-256' in result.mensagem


def test_manifest_patch_preserves_other_caches_and_their_periods():
    from utils.ifdata_cache.cosif_4010 import merge_release_manifest
    old = {'caches': {'principal': {'sha256':'original','max_period':'202603'}},
           'expected_periods': {'quarterly':'202603'}, 'gates':{'snapshot':'original'}}
    merged = merge_release_manifest(old, Cosif4010Cache(ROOT))
    assert merged['caches']['principal'] == old['caches']['principal']
    assert merged['expected_periods'] == old['expected_periods']
    assert merged['gates'] == old['gates']
    assert merged['caches']['cosif_4010']['max_period_ref'] == '202606'
    assert 'cosif_4010' not in old['caches']
