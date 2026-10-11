"""Serviço portátil: fila durável, workspace isolado e promoção de uma revisão.

O servidor recebe intenções autorizadas. Um processo worker separado executa
os extratores existentes; somente o ponteiro oficial torna os dados visíveis.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from .base import CacheResult
from .durable_jobs import DurableJobQueue, validate_job_spec
from .manager import CacheManager
from .official_store import LocalRevisionStore, RevisionConflict, RevisionNotFound, writable_cache_context
from .update_access import PermissionDenied, validate_action
from .update_service import finalize_saved_run, run_quarterly_update
from .update_state import UpdateRunStore, mutation_lock


SPECIAL_CACHES = frozenset({
    "cosif_4010", "taxas_juros", "taxas_juros_historico", "spb_meios_pagamento",
    "mercado_credito_sgs", "scr_data",
})


class LocalOnlySourcesManager:
    """Reutiliza os builders com fontes fixas do workspace, sem fallback remoto."""
    def __init__(self, manager):
        self.manager = manager

    def __getattr__(self, name):
        return getattr(self.manager, name)

    def carregar(self, tipo, forcar_remoto=False):
        if forcar_remoto:
            return CacheResult(False, "Fallback remoto bloqueado na revisão portátil")
        cache = self.manager.get_cache(tipo)
        return cache.carregar_local() if cache is not None else CacheResult(False, "Fonte não configurada")


def assert_adapter_complete(result):
    """Exige a conclusão do resultado novo antes de certificar o pacote nativo."""
    metadata = getattr(result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Metadata do adaptador inválida")
    sections = [metadata, metadata.get("extra") or {}, metadata.get("info_extra") or {}]
    if not getattr(result, "sucesso", False):
        raise ValueError(getattr(result, "mensagem", None) or "Adaptador incompleto")
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Metadata do adaptador inválida")
        if (section.get("finalized") is False or section.get("partial") is True
                or section.get("truncado") is True
                or section.get("status") in {"partial", "failed", "erro"}
                or any(section.get(key) for key in (
                    "remaining_windows", "failures", "failed_windows", "falhas", "erros",
                    "pendentes", "periodos_pendentes", "periodos_falhos",
                    "pending_periods", "failed_periods", "persistence_error", "checkpoint_error", "callback_error"))):
            raise ValueError("Adaptador ainda possui unidades pendentes ou falhas; base oficial preservada")


def validate_official_publication(manager, selected, details):
    """Aplica os gates existentes sem consultar o manifesto remoto do GitHub."""
    from .diagnostics import build_runtime_manifest
    from .release_ops import (
        _publication_scope, _materialization_targets,
        _assert_complete_update, _assert_required_native_assets, validate_cache_quality,
        get_publishable_bundle, DERIVED_TARGET_SPECS,
    )
    promised, sources = _publication_scope([selected])
    scope = list(dict.fromkeys([*promised, *sources]))
    for name in scope:
        _assert_complete_update(manager.base_dir, name)
        _assert_required_native_assets(manager, name)
    runtime = build_runtime_manifest(manager, cache_names=scope, include_hashes=True)
    quality = validate_cache_quality(manager, scope)
    _, problems = get_publishable_bundle([selected], materialization_details=details,
                                         manifest_payload={**runtime, "quality_checks": quality})
    problems.extend(f"{name}: {check.get('message')}" for name, check in quality.items() if not check.get("success"))
    detail_map = {str(item.get("cache")): item for item in details or []}
    for target in _materialization_targets([selected]):
        detail = detail_map.get(target) or {}
        if detail.get("status") != "ok":
            problems.append(f"{target}: materialização incompleta")
        key = DERIVED_TARGET_SPECS[target]["gate"] if target in DERIVED_TARGET_SPECS else "snapshot_peers"
        gate = (runtime.get("gates") or {}).get(key)
        if not gate or not gate.get("success"):
            problems.append(f"{target}: cobertura das fontes e consumidores não está alinhada")
        for source in detail.get("sources") or []:
            if source.get("status") != "ok":
                problems.append(f"{target}: fonte inválida {source.get('cache')}")
    if problems:
        raise ValueError("Publicação incompleta: " + "; ".join(dict.fromkeys(problems)))
    return scope


class _CacheReadGeneration:
    """Fixa o par e os auxiliares no diretório da mesma geração de leitura."""

    def __init__(self, cache):
        self.original = cache
        self.arquivo_dados, self.arquivo_metadata = cache.coherent_read_paths()
        self.cache_dir = self.arquivo_dados.parent
        self.arquivo_dados_pickle = self.cache_dir / cache.arquivo_dados_pickle.name

    def __getattr__(self, name):
        return getattr(self.original, name)

    def _path(self, path):
        path = Path(path)
        for root in (self.original.cache_dir, self.original.bundled_dir):
            if path.is_relative_to(root):
                return self.cache_dir / path.relative_to(root)
        raise ValueError("Asset nativo está fora do diretório do cache")

    @property
    def manifest_path(self):
        return self._path(self.original.manifest_path)

    def dimension_paths(self):
        return {key: self._path(path) for key, path in self.original.dimension_paths().items()}

    def dataset_paths(self):
        return {key: self._path(path) for key, path in self.original.dataset_paths().items()}

    def annual_path(self, year):
        return self._path(self.original.annual_path(year))

    def extra_release_assets(self):
        name = self.config.nome
        if name not in {"taxas_juros_historico", "scr_data", "spb_meios_pagamento"}:
            method = getattr(self.original, "extra_release_assets", None)
            return [(self._path(path), asset) for path, asset in method()] if callable(method) else []
        paths = [self.manifest_path]
        if name == "spb_meios_pagamento":
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            datasets = self.dataset_paths()
            paths.extend(datasets[key] for key in manifest["datasets"])
        else:
            paths.extend(self.dimension_paths().values())
            if name == "scr_data":
                metadata = json.loads(self.arquivo_metadata.read_text(encoding="utf-8"))
                for section in (metadata, metadata.get("extra"), metadata.get("info_extra")):
                    if isinstance(section, dict):
                        paths.extend(self.annual_path(year) for year in section.get("anos_materializados", []))
        return [(path, f"{name}_{path.name}") for path in dict.fromkeys(paths)
                if path != self.arquivo_dados]


def _job_list_summary(job):
    """Mantém o histórico pequeno; listas e diagnósticos completos ficam no GET."""
    spec = job["spec"]
    periods = spec.get("periods") or []
    run = job.get("run") or {}
    result = job.get("result") or {}
    if run:
        if run.get("periods") == ["materialization"]:
            confirmed = "materialization" in (run.get("persisted_periods") or [])
            persisted, pending = (len(periods), 0) if confirmed else (0, len(periods))
        else:
            persisted_set = set(run.get("persisted_periods") or [])
            pending_set = set(run.get("pending_periods") or [])
            persisted = sum(period in persisted_set for period in periods)
            pending = sum(period in pending_set for period in periods)
            if run.get("status") == "failed" and not pending:
                pending = len(periods)
    elif "pending_periods" in result:
        pending_set = set(result["pending_periods"])
        pending = sum(period in pending_set for period in periods)
        persisted = len(periods) - pending
    else:
        persisted, pending = (len(periods), 0) if job["status"] == "succeeded" else (0, len(periods))

    def brief(value):
        return str(value)[:256] if value is not None else None

    summary = {key: job.get(key) for key in (
        "job_id", "execution_run_id", "subject", "status", "created_at", "updated_at", "lease_expires_at",
    )}
    summary.update({"summary": True, "error": brief(job.get("error")),
        "spec": {"cache_type": spec["cache_type"], "mode": spec["mode"]},
        "result": {key: result[key] for key in ("revision_id", "parent_revision", "activated", "run_id") if key in result},
        "run": {"status": run.get("status"), "current_period": run.get("current_period"),
                "error": brief(run.get("error")),
                "publication": {"message": brief((run.get("publication") or {}).get("message"))},
                "total_periods": len(periods), "persisted_count": persisted, "pending_count": pending},
    })
    return summary


def _assert_job_revision(snapshot, job):
    metadata = snapshot.manifest.get("metadata")
    if (not isinstance(metadata, Mapping)
            or metadata.get("job_id") != job["job_id"]
            or metadata.get("run_id") != job["execution_run_id"]
            or metadata.get("subject") != job["subject"]):
        raise ValueError("A identidade da revisão preparada diverge deste job")


def collect_official_artifacts(manager, *, changed=(), validate_quality=True):
    """Coleciona todos os caches presentes, sem download nem atualização implícita.

    Dados, metadata e arquivos nativos pertencem à mesma revisão global.
    Comprovantes, staging temporário e credenciais ficam fora da publicação.
    """
    import pyarrow.parquet as pq
    from .release_ops import (
        _assert_complete_metadata, _assert_complete_update, _assert_required_native_assets,
        release_assets_for_cache, validate_cache_quality,
    )

    artifacts = {}
    names = []
    for name in changed:
        cache = manager.get_cache(name)
        if cache is None or not cache.existe_leitura():
            raise ValueError(f"Cache obrigatório ausente na revisão: {name}")
    for name in manager.listar_caches():
        original = manager.get_cache(name)
        if not original.existe_leitura():
            continue
        cache = _CacheReadGeneration(original)
        generation_manager = SimpleNamespace(get_cache=lambda _: cache)
        names.append(name)
        _assert_complete_metadata(cache.arquivo_metadata, name)
        if name in changed:
            _assert_complete_update(manager.base_dir, name)
        _assert_required_native_assets(generation_manager, name)
        data, metadata_path = cache.arquivo_dados, cache.arquivo_metadata
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert_adapter_complete(SimpleNamespace(sucesso=True, metadata=metadata))
        if name in {"taxas_juros_historico", "scr_data", "spb_meios_pagamento"}:
            native_manifest = json.loads(cache.manifest_path.read_text(encoding="utf-8"))
            assert_adapter_complete(SimpleNamespace(sucesso=True, metadata=native_manifest))
        if data.suffix != ".parquet":
            raise ValueError(f"{name}: converta o cache legado para parquet antes de importar")
        parquet = pq.ParquetFile(data)
        columns = parquet.schema_arrow.names
        required = set(cache.config.colunas_obrigatorias)
        if required - set(columns):
            raise ValueError(f"{name}: colunas obrigatórias ausentes")
        if "total_registros" in metadata and metadata["total_registros"] != parquet.metadata.num_rows:
            raise ValueError(f"{name}: quantidade de registros diverge da metadata")
        if "colunas" in metadata and metadata["colunas"] != columns:
            raise ValueError(f"{name}: colunas divergem da metadata")
        for path, _ in release_assets_for_cache(generation_manager, name):
            # Bundled e runtime convergem para o mesmo caminho lógico portátil.
            relative = path.relative_to(cache.bundled_dir if path.is_relative_to(cache.bundled_dir) else cache.cache_dir)
            logical = (Path("data/cache") / cache.config.subdir / relative).as_posix()
            if logical in artifacts and artifacts[logical] != path:
                raise ValueError("Dois arquivos declararam o mesmo caminho oficial")
            artifacts[logical] = path
        marker = data.parent / cache._integrity_file.name
        if marker.is_file():
            artifacts[(Path("data/cache") / cache.config.subdir / marker.name).as_posix()] = marker
    if not artifacts:
        raise ValueError("Nenhum cache completo disponível para a revisão")
    if validate_quality:
        checks = validate_cache_quality(manager, list(changed) or names)
        failures = [f"{name}: {check.get('message')}" for name, check in checks.items() if not check.get("success")]
        if failures:
            raise ValueError("Qualidade insuficiente: " + "; ".join(failures))
    root = Path(manager.base_dir)
    for path in [root / "conglomerados.csv", *root.glob("*BLOPRUDENCIAL*.CSV")]:
        if path.is_file():
            artifacts[path.name] = path
    # Cadastros de identidade já persistidos; nenhuma consulta durante a coleta.
    for folder in (root / "data/bundled/institution_registry", root / "data/cache/institution_registry"):
        for path in sorted(folder.glob("*.json")):
            artifacts[f"data/cache/institution_registry/{path.name}"] = path
    return artifacts


def bootstrap_official_store(source_dir, store, *, actor=None, validate_quality=True):
    """Importação inicial explícita da geração legada, validada antes da ativação."""
    if store.current() is not None:
        raise RevisionConflict("O armazenamento já possui uma revisão; importação inicial recusada")
    source_dir = Path(source_dir).resolve()
    with mutation_lock(source_dir, owner={"label": "importação inicial"}), writable_cache_context():
        manager = CacheManager(source_dir)
        artifacts = collect_official_artifacts(manager, validate_quality=validate_quality)
        snapshot = store.stage(artifacts, parent_revision=None, metadata={"action": "legacy_import"})
        return store.activate(snapshot.revision_id, expected_parent=None, actor=actor)


class UpdateBackend:
    """Autoriza operações com a identidade verificada pelo servidor HTTP/SSO."""

    def __init__(self, data_dir, store, *, queue=None):
        self.base_dir = Path(data_dir).resolve()
        self.store = store
        self.queue = queue or DurableJobQueue(self.base_dir)

    def _owned(self, job_id, principal):
        job = self.queue.get(job_id)
        if not job:
            raise KeyError("Atualização inexistente")
        if job["subject"] != principal.subject:
            raise PermissionDenied("Atualização pertence a outro usuário")
        return job

    def _present(self, job, *, summary=False):
        workspace = self.base_dir / "jobs" / job["job_id"] / "workspace"
        if workspace.exists():
            receipt = UpdateRunStore(workspace).load(job["execution_run_id"])
            if receipt:
                job = {**job, "run": receipt}
        result = job.get("result") or {}
        if job.get("status") == "succeeded" and result.get("revision_id") and not result.get("activated"):
            if self.store.find_publication(job["job_id"]) is not None:
                job = {**job, "result": {**result, "activated": True}}
        return _job_list_summary(job) if summary else job

    def submit(self, spec, principal, idempotency_key):
        validate_action(principal, "update")
        spec = validate_job_spec(spec)
        if spec.get("publish", True):
            validate_action(principal, "publish")
        # Publicações com fontes alteradas exigem consumidores recalculados.
        if spec.get("materialize", True) is not True:
            raise ValueError("A atualização portátil exige recalcular as dependências")
        kind = spec.get("cache_type")
        options = spec.get("options") or {}
        if kind in {"taxas_juros", "taxas_juros_historico", "mercado_credito_sgs"} and not all(options.get(key) for key in ("start", "end")):
            raise ValueError("Informe uma janela de datas completa para congelar o plano")
        if kind == "scr_data" and not options.get("years"):
            raise ValueError("Informe os anos do SCR.data para congelar o plano")
        if kind == "scr_data":
            years = sorted(options["years"])
            if years != list(range(years[0], years[-1] + 1)):
                raise ValueError("O adaptador do SCR.data exige um intervalo de anos contíguo")
        if kind == "spb_meios_pagamento":
            from .spb_meios_pagamento import DATASETS
            if set(options.get("datasets") or []) - {item.key for item in DATASETS}:
                raise ValueError("Dataset SPB desconhecido")
        return self.queue.submit(spec, subject=principal.subject, idempotency_key=idempotency_key)

    def get(self, job_id, principal):
        validate_action(principal, "read")
        return self._present(self._owned(job_id, principal))

    def list(self, principal):
        validate_action(principal, "read")
        return [self._present(job, summary=True) for job in self.queue.list(subject=principal.subject)]

    def retry(self, job_id, principal):
        validate_action(principal, "update")
        job = self._owned(job_id, principal)
        if job["spec"].get("publish", True):
            validate_action(principal, "publish")
        return self.queue.retry(job_id, subject=principal.subject)

    def cancel(self, job_id, principal):
        validate_action(principal, "update")
        self._owned(job_id, principal)
        return self.queue.cancel(job_id, subject=principal.subject)

    def publish(self, job_id, principal):
        validate_action(principal, "publish")
        job = self._owned(job_id, principal)
        if job["status"] != "succeeded" or not job.get("result", {}).get("revision_id"):
            raise ValueError("A atualização ainda não possui uma revisão validada")
        result = job["result"]
        with mutation_lock(self.base_dir, owner={"label": "promover revisão"}):
            _assert_job_revision(self.store.get_revision(result["revision_id"]), job)
            snapshot = self.store.activate(result["revision_id"], expected_parent=result.get("parent_revision"),
                                           actor={"subject": principal.subject, "job_id": job_id})
        return {"revision_id": snapshot.revision_id, "activated": True}

    def current(self, principal):
        validate_action(principal, "read")
        snapshot = self.store.current()
        return {"revision_id": snapshot.revision_id if snapshot else None}

    def restore(self, revision_id, expected_parent, principal):
        validate_action(principal, "restore")
        with mutation_lock(self.base_dir, owner={"label": "restaurar revisão"}):
            snapshot = self.store.rollback(revision_id, expected_parent=expected_parent,
                                           actor={"subject": principal.subject})
        return {"revision_id": snapshot.revision_id, "restored": True}


class UpdateJobExecutor:
    """Retoma o workspace do job e promove apenas um conjunto completo.

    manager_factory/materializer/collector são pontos de injeção usados pelos
    testes e por instalações que acrescentem fontes, mantendo este protocolo.
    """

    def __init__(self, backend, *, manager_factory=CacheManager, materializer=None, collector=None):
        self.backend = backend
        self.queue = backend.queue
        self.store = backend.store
        self.manager_factory = manager_factory
        self.materializer = materializer
        self.collector = collector or collect_official_artifacts

    def _fence(self, job):
        self.queue.ensure_claim(job["job_id"], job["lease_owner"], job["claim_token"])

    def _context(self, job, values):
        return self.queue.update_context(job["job_id"], job["lease_owner"], job["claim_token"], values)

    def __call__(self, job):
        from .release_ops import materialize_for_publication
        job_id = job["job_id"]
        self._fence(job)
        published = self.store.find_publication(job_id)
        if published is not None:
            _assert_job_revision(published, job)
            return {"status": "succeeded", "result": {"revision_id": published.revision_id,
                    "parent_revision": published.parent_revision, "activated": True, "reconciled": True}}
        context = self.queue.get(job_id).get("context") or {}
        workspace = self.backend.base_dir / "jobs" / job_id / "workspace"
        if "parent_revision" not in context:
            snapshot = self.store.current()
            if snapshot is None:
                raise ValueError("Importe uma revisão inicial validada antes de executar atualizações")
            context = {**context, "parent_revision": snapshot.revision_id, "revision_id": job_id}
            self._context(job, context)
        try:
            candidate = self.store.get_revision(context["revision_id"])
        except RevisionNotFound:
            candidate = None
        if candidate is not None:
            _assert_job_revision(candidate, job)
            if candidate.parent_revision != context["parent_revision"]:
                raise ValueError("A revisão preparada diverge do plano deste job")
            self._fence(job)
            activated = bool(job["spec"].get("publish", True))
            if activated:
                self.store.activate(candidate.revision_id, expected_parent=context["parent_revision"],
                                    actor={"subject": job["subject"], "job_id": job_id})
            return {"status": "succeeded", "result": {"revision_id": candidate.revision_id,
                    "parent_revision": candidate.parent_revision, "activated": activated, "reconciled": True}}
        if not workspace.exists():
            self.store.materialize_workspace(context["parent_revision"], workspace)
        manager = self.manager_factory(workspace)
        spec = job["spec"]
        kind = spec["cache_type"]
        run_store = UpdateRunStore(workspace)
        units = ["materialization"] if kind in SPECIAL_CACHES else spec["periods"]
        record = run_store.create(kind, units, spec["mode"], spec["options"], run_id=job["execution_run_id"])
        details = []

        def materialize(selected):
            nonlocal details
            if self.materializer is None:
                from .release_ops import _materialization_targets, _sources_for_target
                sources = set()
                for target in _materialization_targets([selected]):
                    sources.update(_sources_for_target(target))
                # Toda dependência vem da revisão importada ou do workspace.
                # A ausência não autoriza substituir uma fonte pelo GitHub.
                for source in sources:
                    source_cache = manager.get_cache(source)
                    if source_cache is None or not source_cache.existe_leitura():
                        raise ValueError(f"Fonte obrigatória ausente na revisão: {source}")
                    local = source_cache.carregar_local()
                    if not local.sucesso:
                        raise ValueError(f"Fonte obrigatória ilegível: {source}")
            operation = self.materializer or (lambda mgr, name: materialize_for_publication(
                mgr, cache_names=[name], base_dir=workspace, force=True, save_bundled=False))
            details = operation(LocalOnlySourcesManager(manager), selected)
            return details

        # Extrair e finalizar são fases separadas: cada retomada usa o comprovante.
        if record["status"] in {"saved", "validating", "publishing", "publish_failed", "published"}:
            _, record = finalize_saved_run(manager, run_store, record, materialize=materialize)
        elif kind in SPECIAL_CACHES:
            record = run_store.finish(record, "extracting", error=None)
            result = self._special_update(manager, spec)
            if not result.sucesso:
                record = run_store.finish(record, "failed", error=result.mensagem)
                return {"status": "failed", "error": result.mensagem, "result": {"run_id": record["run_id"]}}
            assert_adapter_complete(result)
            # Os adaptadores usam seu grão nativo; o pacote inteiro é a confirmação.
            from .release_ops import _assert_complete_metadata, _assert_required_native_assets
            _assert_complete_metadata(manager.get_cache(kind).arquivo_metadata, kind)
            _assert_required_native_assets(manager, kind)
            receipt = {"status": "saved", "finalized": True, "requested_periods": units,
                       "extracted_periods": units, "persisted_periods": units,
                       "pending_periods": [], "failed_periods": {}}
            from .update_state import write_cache_update_result
            write_cache_update_result(workspace, kind, receipt)
            record = run_store.record_result(record, receipt)
            record = run_store.finish(record, "saved", error=None)
            _, record = finalize_saved_run(manager, run_store, record, materialize=materialize)
        else:
            # Lotes internos permanecem no worker; o analista acompanha um job.
            while record["status"] in {"prepared", "extracting", "partial", "failed"}:
                self._fence(job)
                before = tuple(record["persisted_periods"])
                extraction_options = ({"force_refresh": spec["options"].get("force_refresh", spec["mode"] != "incremental")}
                                      if kind == "bloprudencial" else {})
                result, record = run_quarterly_update(manager, run_store, record, materialize=materialize,
                                                     extraction_options=extraction_options)
                if record["status"] == "partial" and tuple(record["persisted_periods"]) != before and not record["failed_periods"]:
                    continue
                if record["status"] not in {"saved", "published"}:
                    return {"status": "partial" if record["persisted_periods"] else "failed",
                            "error": record.get("error") or result.mensagem,
                            "result": {"run_id": record["run_id"], "pending_periods": record["pending_periods"]}}
                break
        if record["status"] not in {"saved", "published"}:
            return {"status": "failed", "error": record.get("error") or "Validação incompleta"}
        self._fence(job)
        changed = validate_official_publication(manager, kind, details)
        artifacts = self.collector(manager, changed=changed)
        snapshot = self.store.stage(artifacts, parent_revision=context["parent_revision"],
            revision_id=context["revision_id"], metadata={"job_id": job_id, "run_id": record["run_id"],
                                                         "subject": job["subject"], "changed_caches": changed})
        self._fence(job)
        activated = bool(spec.get("publish", True))
        if activated:
            self.store.activate(snapshot.revision_id, expected_parent=context["parent_revision"],
                                actor={"subject": job["subject"], "job_id": job_id})
        return {"status": "succeeded", "result": {"revision_id": snapshot.revision_id,
                "parent_revision": context["parent_revision"], "activated": activated,
                "run_id": record["run_id"], "materialization": details}}

    @staticmethod
    def _special_update(manager, spec):
        cache = manager.get_cache(spec["cache_type"])
        options = spec["options"]
        overwrite = spec["mode"] in {"overwrite", "rebuild"}
        kind = spec["cache_type"]
        if kind == "cosif_4010":
            from scripts.ingest_cosif_4010 import ingest
            return ingest(cache, spec["periods"], refresh=overwrite)
        if kind == "taxas_juros":
            from .update_service import extract_taxas_window
            return extract_taxas_window(cache, options["start"], options["end"])
        if kind == "scr_data":
            from .scr_data import PRIMEIRO_ANO
            years = options.get("years")
            return cache.materialize_history(ano_inicial=min(years) if years else PRIMEIRO_ANO,
                    ano_final=max(years) if years else None, overwrite=overwrite)
        if kind == "taxas_juros_historico":
            previous_completed = -1
            while True:
                result = cache.materialize_history(data_inicio=options.get("start"), data_fim=options.get("end"),
                    overwrite=overwrite, max_windows_per_run=options.get("max_windows"),
                    reprocess_tail_windows=options.get("reprocess_tail", 20))
                if not result.sucesso or (result.metadata or {}).get("finalized") is not False:
                    return result
                checkpoint = json.loads(cache.checkpoint_path.read_text(encoding="utf-8"))
                completed = len(checkpoint.get("completed_windows", []))
                if completed <= previous_completed:
                    return CacheResult(False, "O lote histórico não avançou; base oficial preservada")
                previous_completed = completed
        keys = ("datasets",) if kind == "spb_meios_pagamento" else ("start", "end")
        kwargs = {key: options[key] for key in keys if key in options}
        return cache.materialize_history(overwrite=overwrite, **kwargs)
