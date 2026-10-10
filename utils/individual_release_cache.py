"""Confere os bytes dos caches individuais contra o release publicado."""
from __future__ import annotations

from collections.abc import Mapping
from copy import copy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import pandas as pd
import requests

from .ifdata_cache.release_config import add_release_cache_buster
from .ifdata_cache.update_state import mutation_lock


INDIVIDUAL_CACHES = {"principal_individual", "derived_metrics_individual"}


def _file_sha256(path: Path) -> str | None:
    try:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _release_descriptor(cache, info: Mapping) -> tuple[str, str, int | None]:
    name = str(info.get("cache") or cache.config.nome)
    if name not in INDIVIDUAL_CACHES or name != cache.config.nome:
        raise ValueError("Manifesto não corresponde ao cache individual solicitado.")
    if info.get("exists") is False:
        raise ValueError(f"{name}: release sem fonte publicada.")
    asset = f"{name}_dados.parquet"
    descriptor = info
    files = info.get("files")
    if isinstance(files, Mapping):
        candidate = files.get("parquet") or files.get(asset) or files.get("dados.parquet")
        if isinstance(candidate, Mapping):
            descriptor = candidate
    elif isinstance(files, list):
        matches = [item for item in files if isinstance(item, Mapping)
                   and (item.get("asset_name") or item.get("name")) == asset]
        if len(matches) == 1:
            descriptor = matches[0]
    expected = str(descriptor.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"{name}: SHA-256 do parquet ausente ou inválido no manifesto.")
    declared_asset = descriptor.get("asset_name") or descriptor.get("name")
    if declared_asset and declared_asset != asset:
        raise ValueError(f"{name}: nome do asset diverge do cache solicitado.")
    raw_size = descriptor.get("size_bytes", descriptor.get("size"))
    try:
        size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: tamanho inválido no manifesto.") from exc
    if size is not None and size <= 0:
        raise ValueError(f"{name}: tamanho inválido no manifesto.")
    return asset, expected, size


def ensure_individual_release_cache(cache, info: Mapping, release_base_url: str) -> Path:
    """Retorna a fonte cuja assinatura corresponde ao manifesto do release.

    Quantidade de linhas e última competência iguais não comprovam que o cache
    contém a revisão publicada. A comparação usa SHA-256 dos bytes do parquet.
    Falhas de rede, assinatura, leitura ou validação deixam a fonte anterior
    intacta e propagam erro; o consumidor deve bloquear esse recorte.
    """
    with mutation_lock(cache.base_dir, owner={"cache_type": cache.config.nome}):
        cache._recover_local_transaction()
        return _ensure_individual_release_cache_locked(cache, info, release_base_url)


def _ensure_individual_release_cache_locked(cache, info: Mapping, release_base_url: str) -> Path:
    if not isinstance(info, Mapping):
        raise ValueError("Manifesto do cache individual ausente.")
    asset, expected, expected_size = _release_descriptor(cache, info)
    current = Path(cache.read_data_file)
    if _file_sha256(current) == expected:
        return current

    url = add_release_cache_buster(f"{str(release_base_url).rstrip('/')}/{asset}", expected)
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    raw = response.content
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"{cache.config.nome}: SHA-256 recebido diverge do manifesto; fonte anterior preservada.")
    if expected_size is not None and len(raw) != expected_size:
        raise ValueError(f"{cache.config.nome}: tamanho recebido diverge do manifesto; fonte anterior preservada.")
    try:
        frame = pd.read_parquet(BytesIO(raw))
    except Exception as exc:
        raise ValueError(f"{cache.config.nome}: parquet do release ilegível; fonte anterior preservada.") from exc
    if info.get("record_count") is not None and len(frame) != int(info["record_count"]):
        raise ValueError(f"{cache.config.nome}: quantidade de registros diverge do manifesto.")

    # O serializer pode mudar a assinatura de um parquet sem mudar seus dados.
    # Salva metadata/validação em staging e publica os bytes originais do asset.
    target = Path(cache.arquivo_dados_runtime)
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="individual-release-", dir=target.parent) as directory:
        staged = copy(cache)
        staged.cache_dir = Path(directory)
        result = staged.salvar_local(frame, fonte="github_releases_verified",
            info_extra={"release_asset_sha256": expected, "release_asset_url": url})
        if not result.sucesso:
            raise ValueError(f"{cache.config.nome}: cache do release inválido: {result.mensagem}")
        metadata = json.loads(staged.arquivo_metadata_runtime.read_text(encoding="utf-8"))
        # A validação em staging usa o serializer local; a promoção conserva
        # os bytes assinados e gera a integridade correspondente ao asset original.
        metadata.pop("integridade", None)
        metadata["sha256"] = expected
        metadata["colunas"] = list(frame.columns)
        metadata["total_registros"] = len(frame)
        publication_id = info.get("publication_id")
        if publication_id:
            metadata["publication_id"] = str(publication_id)
        # O asset conferido substitui a revisão bundled que está instalada.
        # A identidade dessa base vem do bundle local, e a cobertura precisa
        # permanecer completa para que a precedência selecione o novo runtime.
        bundled_publication = cache._publication_metadata()
        if bundled_publication:
            if not set(metadata.get("periodos", [])).issuperset(bundled_publication.get("periodos", [])):
                raise ValueError(f"{cache.config.nome}: release não cobre os períodos da base publicada; fonte anterior preservada.")
            metadata["baseline_publication_id"] = bundled_publication["publication_id"]
        candidate = Path(directory) / "release-original.parquet"
        candidate.write_bytes(raw)
        promoted = cache.salvar_arquivo_local(candidate, metadata)
        if not promoted.sucesso:
            raise ValueError(f"{cache.config.nome}: cache do release não foi ativado: {promoted.mensagem}")

    verified = Path(cache.read_data_file)
    if _file_sha256(verified) != expected:
        raise ValueError(f"{cache.config.nome}: precedência local não selecionou o parquet validado.")
    return verified
