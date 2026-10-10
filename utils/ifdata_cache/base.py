"""
base.py - Classes base para o sistema de cache

Define a interface comum para todos os tipos de cache.
"""

import hashlib
import json
import logging
import os
import pickle
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pandas as pd

logger = logging.getLogger("ifdata_cache")


@dataclass
class CacheConfig:
    """Configuracao de um tipo de cache."""

    # Identificador unico do cache
    nome: str

    # Descricao para logs e UI
    descricao: str

    # Diretorio relativo para armazenamento (dentro de data/cache/)
    subdir: str

    # Nome do arquivo de dados
    arquivo_dados: str = "data.parquet"

    # Nome do arquivo de metadados
    arquivo_metadata: str = "metadata.json"

    # URL base para download do GitHub (None = sem suporte remoto)
    github_url_base: Optional[str] = None

    # Tempo maximo de cache em horas (None = sem expiracao)
    max_idade_horas: Optional[float] = 168.0  # 7 dias

    # Colunas obrigatorias para validacao
    colunas_obrigatorias: List[str] = field(default_factory=lambda: ["Periodo", "CodInst"])

    # Mapeamento de campos para extracao (nome_api -> nome_exibicao)
    campos_mapeamento: Dict[str, str] = field(default_factory=dict)

    # URL da API para extracao (None = sem suporte a extracao direta)
    api_url: Optional[str] = None

    # Tipo de relatorio IFData (1-5)
    relatorio_tipo: Optional[int] = None


@dataclass
class CacheResult:
    """Resultado de uma operacao de cache."""

    sucesso: bool
    mensagem: str
    dados: Optional[pd.DataFrame] = None
    metadata: Optional[Dict[str, Any]] = None
    fonte: str = "nenhum"  # cache_local, github, api, nenhum

    def __repr__(self):
        status = "OK" if self.sucesso else "ERRO"
        n_registros = len(self.dados) if self.dados is not None else 0
        return f"CacheResult({status}, fonte={self.fonte}, registros={n_registros})"


class BaseCache(ABC):
    """Classe base abstrata para implementacoes de cache."""

    def __init__(self, config: CacheConfig, base_dir: Path):
        """
        Args:
            config: Configuracao do cache
            base_dir: Diretorio base do projeto (onde fica data/)
        """
        self.config = config
        self.base_dir = base_dir
        self.cache_dir = base_dir / "data" / "cache" / config.subdir

        # Prefixo para logs
        self._log_prefix = f"[CACHE:{config.nome.upper()}]"

    def _log(self, nivel: str, msg: str):
        """Log com prefixo padronizado."""
        getattr(logger, nivel)(f"{self._log_prefix} {msg}")

    def _garantir_diretorio(self):
        """Cria diretorio de cache se nao existir."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _transaction_file(self) -> Path:
        return self.cache_dir / f".{self.config.arquivo_dados}.transaction.json"

    @property
    def _integrity_file(self) -> Path:
        return self.cache_dir / f".{self.config.arquivo_dados}.integrity.json"

    @property
    def _previous_generation_file(self) -> Path:
        return self.cache_dir / f".{self.config.arquivo_dados}.previous.json"

    def _runtime_paths(self) -> List[Path]:
        return list(dict.fromkeys([
            self.arquivo_dados_runtime, self.arquivo_dados_pickle,
            self.arquivo_metadata_runtime, self._integrity_file, self._previous_generation_file,
        ]))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sync_file(path: Path):
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    @staticmethod
    def _sync_directory(path: Path):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_json_atomic(self, path: Path, payload: Dict):
        """Grava JSON sem expor um arquivo truncado aos leitores."""
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _transaction_snapshot(self, contents: bytes) -> Tuple[Path, Dict[str, Path]]:
        """Valida o diário e seu snapshot antes de ler ou restaurar arquivos."""
        journal = json.loads(contents)
        name = journal.get("directory", "")
        prefix = f".{self.config.arquivo_dados}.transaction-"
        if (journal.get("version") != 1 or not isinstance(name, str)
                or not name.startswith(prefix) or Path(name).name != name):
            raise ValueError("Diário de persistência inválido")
        transaction = self.cache_dir / name
        previous = transaction / "previous"
        entries = journal.get("previous")
        expected_names = {path.name for path in self._runtime_paths()}
        if (not isinstance(entries, dict) or set(entries) != expected_names
                or transaction.is_symlink() or previous.is_symlink()):
            raise ValueError("Snapshot de persistência inválido")
        paths = {}
        for filename, entry in entries.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("exists"), bool):
                raise ValueError("Entrada de recuperação inválida")
            path = previous / filename
            if entry["exists"]:
                if path.is_symlink() or not path.is_file() or self._sha256(path) != entry.get("sha256"):
                    raise ValueError("Snapshot de recuperação ausente ou corrompido")
            elif path.exists():
                raise ValueError("Arquivo inesperado no snapshot de recuperação")
            paths[filename] = path
        return transaction, paths

    def _recover_local_transaction(self):
        """Restaura a geração anterior após interrupção, mantendo o diário até o fim.

        A cópia de recuperação permanece imutável: uma segunda interrupção durante
        o rollback pode repetir a operação na próxima leitura.
        """
        if not self._transaction_file.exists():
            return
        contents = self._transaction_file.read_bytes()
        transaction, paths = self._transaction_snapshot(contents)
        for target in self._runtime_paths():
            source = paths[target.name]
            if source.exists():
                temporary = self.cache_dir / f".{target.name}.restore-{uuid4().hex}"
                try:
                    shutil.copy2(source, temporary)
                    self._sync_file(temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
        self._sync_directory(self.cache_dir)
        self._transaction_file.unlink()
        self._sync_directory(self.cache_dir)
        shutil.rmtree(transaction, ignore_errors=True)
        self._log("warning", "Persistência interrompida: geração anterior restaurada")

    def _read_paths(self, runtime_paths: Optional[Dict[str, Path]] = None) -> Tuple[Path, Path, Path]:
        """Resolve o par de leitura, inclusive o snapshot anterior de uma promoção."""
        if runtime_paths is None:
            data = self.arquivo_dados
            if not data.exists() and self.arquivo_dados_pickle.exists():
                return self.arquivo_dados_pickle, self.arquivo_metadata_runtime, self.arquivo_dados_pickle
            return data, self.arquivo_metadata, self.arquivo_dados_pickle
        paths = runtime_paths or {path.name: path for path in self._runtime_paths()}
        runtime = paths[self.arquivo_dados_runtime.name]
        runtime_pickle = paths[self.arquivo_dados_pickle.name]
        runtime_metadata = paths[self.arquivo_metadata_runtime.name]
        bundled = self.bundled_dir / self.config.arquivo_dados
        bundled_metadata = self.bundled_dir / self.config.arquivo_metadata
        publication = self._publication_metadata()
        prefer_bundle = False
        if publication:
            try:
                metadata = json.loads(runtime_metadata.read_text(encoding="utf-8"))
                current = publication["publication_id"] in (
                    metadata.get("publication_id"), metadata.get("baseline_publication_id"),
                ) and set(metadata.get("periodos", [])).issuperset(publication.get("periodos", []))
                prefer_bundle = not (runtime.exists() and current)
            except (OSError, ValueError):
                prefer_bundle = True
        if prefer_bundle or (not runtime.exists() and bundled.exists()):
            return bundled, bundled_metadata, runtime_pickle
        if runtime.exists():
            return runtime, runtime_metadata, runtime_pickle
        return runtime_pickle, runtime_metadata, runtime_pickle

    def coherent_read_paths(self) -> Tuple[Path, Path]:
        """Resolve arquivos para leitores de slices, com recuperação ou snapshot anterior."""
        from .update_state import UpdateBusyError, mutation_lock
        try:
            with mutation_lock(self.base_dir):
                self._recover_local_transaction()
                data, metadata, _ = self._read_paths()
                self._validate_file_identity(data, metadata)
                return data, metadata
        except UpdateBusyError:
            if self._transaction_file.exists():
                _, snapshot = self._transaction_snapshot(self._transaction_file.read_bytes())
                data, metadata, _ = self._read_paths(snapshot)
                self._validate_file_identity(data, metadata)
                return data, metadata
            data, metadata, _ = self._read_paths()
            self._validate_file_identity(data, metadata)
            return data, metadata

    def _validate_file_identity(self, data_path: Path, metadata_path: Path):
        marker = data_path.parent / self._integrity_file.name
        if not metadata_path.exists():
            if marker.exists():
                raise ValueError("Metadata da geração persistida está ausente")
            return
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        integrity = metadata.get("integridade")
        if integrity:
            if (integrity.get("arquivo_dados") != data_path.name
                    or integrity.get("sha256") != self._sha256(data_path)
                    or integrity.get("tamanho_bytes") != data_path.stat().st_size):
                raise ValueError("Arquivos da geração persistida estão corrompidos ou divergentes")
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != integrity:
            raise ValueError("Identidade da geração diverge da metadata")

    @staticmethod
    def _read_data_file(path: Path, formato: str) -> Tuple[pd.DataFrame, str, int]:
        # A leitura e o checksum usam o mesmo descritor: um rename concorrente
        # não pode associar o DataFrame antigo ao hash do arquivo novo.
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            handle.seek(0)
            data = pickle.load(handle) if formato == "pickle" else pd.read_parquet(handle)
            after = os.fstat(handle.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Arquivo alterado durante a leitura")
            return data, digest.hexdigest(), before.st_size

    def _validate_pair(
        self, data: pd.DataFrame, metadata: Dict, path: Path, integrity_path: Optional[Path],
        data_checksum: Optional[str] = None, data_size: Optional[int] = None,
    ):
        valid, message = self._validar_dados(data)
        if not valid:
            raise ValueError(f"Cache corrompido: {message}")
        if not isinstance(metadata, dict):
            raise ValueError("Metadata deve ser um objeto JSON")
        if "total_registros" in metadata and metadata["total_registros"] != len(data):
            raise ValueError("Quantidade de registros diverge da metadata")
        if "colunas" in metadata and metadata["colunas"] != list(data.columns):
            raise ValueError("Colunas divergem da metadata")
        integrity = metadata.get("integridade")
        if integrity is not None:
            if (not isinstance(integrity, dict) or integrity.get("versao") != 1
                    or integrity.get("arquivo_dados") != path.name
                    or integrity.get("sha256") != (data_checksum or self._sha256(path))
                    or integrity.get("tamanho_bytes") != (data_size if data_size is not None else path.stat().st_size)):
                raise ValueError("Dados e metadata pertencem a gerações diferentes ou estão corrompidos")
        if integrity_path is not None and integrity_path.exists():
            marker = json.loads(integrity_path.read_text(encoding="utf-8"))
            if not integrity or marker != integrity:
                raise ValueError("Identidade da geração diverge da metadata")

    # =========================================================================
    # OPERACOES DE CACHE LOCAL
    # =========================================================================

    def existe(self) -> bool:
        """Verifica se o cache de runtime existe (parquet ou pickle).

        Não considera o artefato bundled de propósito: `limpar_local`, `cache_valido`
        e os fluxos de extração raciocinam sobre o cache gravável. Para saber se há
        dado legível de qualquer origem, use `existe_leitura`.
        """
        tem_parquet = self.arquivo_dados_runtime.exists()
        tem_pickle = self.arquivo_dados_pickle.exists()
        return tem_parquet or tem_pickle

    def existe_leitura(self) -> bool:
        """Indica se há dado legível, seja no runtime ou no artefato bundled."""
        return self.existe() or self.arquivo_dados.exists()

    def carregar_local(self) -> CacheResult:
        """Carrega uma geração coerente e recupera persistências interrompidas.

        Durante extrações longas, o leitor pode usar a última geração concluída
        sem disputar a trava administrativa. O diário e a identidade são
        conferidos antes e depois da leitura.
        """
        from .update_state import UpdateBusyError, mutation_lock
        try:
            try:
                with mutation_lock(self.base_dir):
                    self._recover_local_transaction()
                    return self._load_coherent_local()
            except UpdateBusyError:
                # Um processo ativo pode estar consultando a API, sem promover
                # arquivos. Nesse intervalo a geração anterior continua legível.
                return self._load_coherent_local()
        except Exception as e:
            self._log("error", f"Erro ao carregar cache local: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao carregar: {e}",
                fonte="nenhum"
            )

    def _load_coherent_local(self) -> CacheResult:
        last_error = None
        for _ in range(3):
            try:
                journal_before = self._transaction_file.read_bytes() if self._transaction_file.exists() else None
                snapshot = None
                if journal_before is not None:
                    _, snapshot = self._transaction_snapshot(journal_before)
                data_path, metadata_path, pickle_path = self._read_paths(snapshot)
                runtime_paths = snapshot or {path.name: path for path in self._runtime_paths()}
                if not data_path.exists():
                    return CacheResult(False, "Cache local nao existe", fonte="nenhum")
                formato = "pickle" if data_path.suffix == ".pkl" else "parquet"
                metadata_before = metadata_path.read_bytes() if metadata_path.exists() else None
                try:
                    data, data_checksum, data_size = self._read_data_file(data_path, formato)
                except ImportError:
                    if not pickle_path.exists():
                        raise ImportError("pyarrow não disponível e não há fallback pickle")
                    data_path = pickle_path
                    metadata_path = runtime_paths[self.arquivo_metadata_runtime.name]
                    formato = "pickle"
                    metadata_before = metadata_path.read_bytes() if metadata_path.exists() else None
                    data, data_checksum, data_size = self._read_data_file(data_path, formato)
                runtime_read = data_path in (
                    runtime_paths[self.arquivo_dados_runtime.name],
                    runtime_paths[self.arquivo_dados_pickle.name],
                )
                integrity_path = runtime_paths[self._integrity_file.name] if runtime_read else None
                integrity_before = integrity_path.read_bytes() if integrity_path and integrity_path.exists() else None
                if metadata_before is not None:
                    metadata = json.loads(metadata_before)
                elif integrity_before is not None:
                    raise ValueError("Metadata da geração persistida está ausente")
                else:
                    # Compatibilidade com dados anteriores ao contrato de
                    # integridade. A leitura não escreve metadata provisória.
                    metadata = self._build_local_metadata(data, "cache_local", formato)
                    metadata["timestamp_salvamento"] = datetime.fromtimestamp(data_path.stat().st_mtime).isoformat()
                    self._log("warning", "Metadata legada ausente; gerada em memória")
                self._validate_pair(data, metadata, data_path, integrity_path, data_checksum, data_size)
                metadata_after = metadata_path.read_bytes() if metadata_path.exists() else None
                integrity_after = integrity_path.read_bytes() if integrity_path and integrity_path.exists() else None
                journal_after = self._transaction_file.read_bytes() if self._transaction_file.exists() else None
                if (metadata_after != metadata_before or integrity_after != integrity_before
                        or journal_after != journal_before):
                    raise ValueError("A geração mudou durante a leitura; repetindo")
                self._log("info", f"Cache local carregado: {len(data)} registros")
                return CacheResult(
                    True, f"Carregado do cache local: {len(data)} registros",
                    dados=data, metadata=metadata, fonte="cache_local",
                )
            except (OSError, ValueError) as exc:
                last_error = exc
        raise last_error

    @property
    def bundled_dir(self) -> Path:
        """Artefato versionado somente-leitura.

        O runtime nunca escreve aqui: downloads e extrações vão para `cache_dir`
        (efêmero e ignorado no git), de modo que uma execução do app não possa
        degradar o dado publicado no repositório.
        """
        return self.base_dir / "data" / "bundled" / self.config.subdir

    @property
    def arquivo_dados_runtime(self) -> Path:
        """Caminho gravável do parquet (sempre em data/cache/)."""
        return self.cache_dir / self.config.arquivo_dados

    @property
    def arquivo_metadata_runtime(self) -> Path:
        """Caminho gravável do metadata (sempre em data/cache/)."""
        return self.cache_dir / self.config.arquivo_metadata

    @property
    def arquivo_dados(self) -> Path:
        """Parquet efetivo para leitura: runtime quando existir, senão o bundled."""
        runtime = self.arquivo_dados_runtime
        if self._prefer_publication_bundle():
            return self.bundled_dir / self.config.arquivo_dados
        if runtime.exists():
            return runtime
        bundled = self.bundled_dir / self.config.arquivo_dados
        if bundled.exists():
            return bundled
        return runtime

    @property
    def arquivo_metadata(self) -> Path:
        """Metadata efetivo para leitura, pareado com `arquivo_dados`."""
        if self._prefer_publication_bundle():
            return self.bundled_dir / self.config.arquivo_metadata
        if self.arquivo_dados_runtime.exists() or (
                self.arquivo_dados_pickle.exists()
                and not (self.bundled_dir / self.config.arquivo_dados).exists()):
            return self.arquivo_metadata_runtime
        bundled = self.bundled_dir / self.config.arquivo_metadata
        if bundled.exists():
            return bundled
        return self.arquivo_metadata_runtime

    def _publication_metadata(self) -> dict:
        """Contrato opt-in de um conjunto publicado junto com o código."""
        if not (self.bundled_dir / self.config.arquivo_dados).exists():
            return {}
        path = self.bundled_dir / self.config.arquivo_metadata
        try:
            metadata = json.loads(path.read_text())
            return metadata if metadata.get("publication_id") else {}
        except (OSError, ValueError):
            return {}

    def _prefer_publication_bundle(self) -> bool:
        bundled = self._publication_metadata()
        if not bundled:
            return False
        try:
            runtime = json.loads(self.arquivo_metadata_runtime.read_text())
            current = bundled["publication_id"] in (
                runtime.get("publication_id"), runtime.get("baseline_publication_id"),
            ) and set(runtime.get("periodos", [])).issuperset(bundled.get("periodos", []))
            return not (self.arquivo_dados_runtime.exists() and current)
        except (OSError, ValueError):
            return True

    @property
    def arquivo_dados_pickle(self) -> Path:
        """Caminho do arquivo de dados em formato pickle (fallback)."""
        return self.cache_dir / self.config.arquivo_dados.replace('.parquet', '.pkl')

    def _build_local_metadata(self, dados: pd.DataFrame, fonte: str, formato: str, info_extra: Optional[Dict] = None) -> Dict:
        metadata = {
            "timestamp_salvamento": datetime.now().isoformat(),
            "fonte": fonte,
            "total_registros": len(dados),
            "colunas": list(dados.columns),
            "formato": formato,
        }
        column = next((name for name in ("Período", "Periodo") if name in dados.columns), None)
        if column:
            periods = sorted(dados[column].unique().tolist())
            metadata["periodos"] = [str(period) for period in periods]
            metadata["total_periodos"] = len(periods)
        if info_extra:
            metadata["extra"] = info_extra
        return metadata

    def _promote_staged_pair(
        self, transaction: Path, staged_data: Optional[Path], metadata: Optional[Dict], formato: str,
        extras: Optional[Dict[Path, Path]] = None,
    ):
        """Promove o mesmo contrato para DataFrames e materialização em streaming."""
        target = self.arquivo_dados_pickle if formato == "pickle" else self.arquivo_dados_runtime
        staged_metadata = transaction / self.arquivo_metadata_runtime.name
        staged_integrity = transaction / self._integrity_file.name
        older = None
        if self._previous_generation_file.exists():
            older = json.loads(self._previous_generation_file.read_text(encoding="utf-8")).get("directory")
        previous = transaction / "previous"
        previous.mkdir()
        snapshots = {}
        for path in self._runtime_paths():
            entry = {"exists": path.exists()}
            if entry["exists"]:
                snapshot = previous / path.name
                shutil.copy2(path, snapshot)
                self._sync_file(snapshot)
                entry["sha256"] = self._sha256(snapshot)
            snapshots[path.name] = entry
        self._sync_directory(previous)
        self._sync_directory(transaction)
        journal = {"version": 1, "directory": transaction.name, "previous": snapshots}
        self._write_json_atomic(self._transaction_file, journal)
        try:
            extra_checksums = {target: self._sha256(source) for target, source in (extras or {}).items()}
            for extra_target, extra_source in (extras or {}).items():
                os.replace(extra_source, extra_target)
                self._sync_directory(extra_target.parent)
            if staged_data is not None:
                os.replace(staged_data, target)
                os.replace(staged_metadata, self.arquivo_metadata_runtime)
                os.replace(staged_integrity, self._integrity_file)
                other = self.arquivo_dados_runtime if formato == "pickle" else self.arquivo_dados_pickle
                if other != target:
                    other.unlink(missing_ok=True)
            self._sync_directory(self.cache_dir)
            if staged_data is not None:
                saved_metadata = json.loads(self.arquivo_metadata_runtime.read_text(encoding="utf-8"))
                integrity = saved_metadata.get("integridade", {})
                if (integrity != metadata["integridade"]
                        or integrity.get("sha256") != self._sha256(target)
                        or integrity != json.loads(self._integrity_file.read_text(encoding="utf-8"))):
                    raise ValueError("Geração promovida diverge do candidato validado")
            if any(self._sha256(path) != checksum for path, checksum in extra_checksums.items()):
                raise ValueError("Artefato auxiliar promovido diverge do candidato")
            self._write_json_atomic(self._previous_generation_file, {"directory": transaction.name})
            self._transaction_file.unlink()
            self._sync_directory(self.cache_dir)
        except Exception:
            if not self._transaction_file.exists():
                try:
                    self._write_json_atomic(self._transaction_file, journal)
                except Exception:
                    if not self._transaction_file.exists():
                        raise
            self._recover_local_transaction()
            raise
        # Um leitor que recebeu um caminho do snapshot durante a promoção pode
        # abri-lo após o commit. Mantém-se uma geração anterior até o próximo save.
        if isinstance(older, str) and older != transaction.name and Path(older).name == older:
            if older.startswith(f".{self.config.arquivo_dados}.transaction-"):
                shutil.rmtree(self.cache_dir / older, ignore_errors=True)

    def salvar_arquivo_local(
        self, candidato: Path, metadata: Dict, arquivos_extras: Optional[Dict[Path, Path]] = None,
    ) -> CacheResult:
        """Valida um parquet já produzido sem carregar o histórico inteiro em RAM.

        Materializadores especializados mantêm seus schemas e cálculos. Todas
        as páginas do parquet são decodificadas em lotes antes da promoção.
        """
        from .update_state import mutation_lock
        transaction = None
        promotion_started = False
        try:
            with mutation_lock(self.base_dir):
                self._garantir_diretorio()
                self._recover_local_transaction()
                transaction = Path(tempfile.mkdtemp(
                    prefix=f".{self.config.arquivo_dados}.transaction-", dir=self.cache_dir,
                ))
                staged_data = transaction / self.arquivo_dados_runtime.name
                shutil.copy2(candidato, staged_data)
                self._sync_file(staged_data)
                import pyarrow.parquet as pq
                parquet = pq.ParquetFile(staged_data)
                columns = parquet.schema_arrow.names
                rows = sum(batch.num_rows for batch in parquet.iter_batches(batch_size=50_000))
                if not rows or rows != parquet.metadata.num_rows:
                    raise ValueError("Parquet candidato vazio ou incompleto")
                for column in self.config.colunas_obrigatorias:
                    equivalent = {"Período": "Periodo", "Periodo": "Período"}.get(column)
                    if column not in columns and equivalent not in columns:
                        raise ValueError(f"Coluna obrigatória ausente: {column}")
                metadata = dict(metadata)
                if "total_registros" in metadata and metadata["total_registros"] != rows:
                    raise ValueError("Quantidade de registros diverge da metadata")
                if "colunas" in metadata and metadata["colunas"] != columns:
                    raise ValueError("Colunas divergem da metadata")
                metadata.setdefault("total_registros", rows)
                checksum = self._sha256(staged_data)
                remote_integrity = metadata.get("integridade")
                if remote_integrity and remote_integrity.get("sha256") != checksum:
                    raise ValueError("Checksum do parquet difere da metadata recebida")
                if metadata.get("sha256") and metadata["sha256"] != checksum:
                    raise ValueError("Checksum do parquet difere da publicação recebida")
                metadata["integridade"] = {
                    "versao": 1, "geracao": uuid4().hex,
                    "arquivo_dados": self.arquivo_dados_runtime.name,
                    "sha256": checksum, "tamanho_bytes": staged_data.stat().st_size,
                }
                self._write_json_atomic(transaction / self.arquivo_metadata_runtime.name, metadata)
                self._write_json_atomic(transaction / self._integrity_file.name, metadata["integridade"])
                extras = {}
                allowed = {path for path in self._runtime_paths()} - {
                    self.arquivo_dados_runtime, self.arquivo_dados_pickle,
                    self.arquivo_metadata_runtime, self._integrity_file, self._previous_generation_file,
                }
                for target, source in (arquivos_extras or {}).items():
                    if target not in allowed or not target.resolve().is_relative_to(self.cache_dir.resolve()):
                        raise ValueError("Artefato auxiliar fora do contrato de runtime")
                    staged = transaction / target.name
                    shutil.copy2(source, staged)
                    self._sync_file(staged)
                    if target.suffix == ".parquet":
                        for _ in pq.ParquetFile(staged).iter_batches(batch_size=50_000):
                            pass
                    elif target.suffix == ".json":
                        json.loads(staged.read_text(encoding="utf-8"))
                    extras[target] = staged
                promotion_started = True
                self._promote_staged_pair(transaction, staged_data, metadata, "parquet", extras)
                transaction = None
                return CacheResult(True, f"Parquet validado e salvo: {rows} registros", metadata=metadata, fonte="cache_local")
        except Exception as exc:
            if transaction is not None and not promotion_started and not self._transaction_file.exists():
                shutil.rmtree(transaction, ignore_errors=True)
            self._log("error", f"Erro ao salvar parquet materializado: {exc}")
            return CacheResult(False, f"Erro ao salvar parquet materializado: {exc}", fonte="nenhum")

    def baixar_arquivos_local(self, urls: Dict[Path, str], *, timeout: int = 120, headers: Optional[Dict] = None) -> CacheResult:
        """Baixa todos os artefatos obrigatórios antes de substituir o runtime."""
        from .update_state import mutation_lock
        import requests
        try:
            with mutation_lock(self.base_dir):
                self._garantir_diretorio()
                allowed = set(self._runtime_paths())
                if not set(urls).issubset(allowed) or not {
                    self.arquivo_dados_runtime, self.arquivo_metadata_runtime,
                }.issubset(urls):
                    raise ValueError("Pacote remoto fora do contrato de runtime")
                with tempfile.TemporaryDirectory(prefix="download-candidate-", dir=self.cache_dir) as directory:
                    candidates = {}
                    for target, url in urls.items():
                        response = requests.get(url, timeout=timeout, headers=headers or {})
                        if response.status_code != 200:
                            raise ValueError(f"Artefato obrigatório {target.name} indisponível (HTTP {response.status_code})")
                        candidate = Path(directory) / target.name
                        candidate.write_bytes(response.content)
                        candidates[target] = candidate
                    metadata = json.loads(candidates[self.arquivo_metadata_runtime].read_text(encoding="utf-8"))
                    extras = {target: source for target, source in candidates.items()
                              if target not in {self.arquivo_dados_runtime, self.arquivo_metadata_runtime}}
                    saved = self.salvar_arquivo_local(candidates[self.arquivo_dados_runtime], metadata, extras)
                    if saved.sucesso:
                        saved.fonte = "github_releases"
                    return saved
        except Exception as exc:
            return CacheResult(False, f"Download não ativado; base anterior preservada: {exc}", fonte="nenhum")

    def salvar_arquivos_auxiliares(self, candidatos: Dict[Path, Path]) -> CacheResult:
        """Promove um subconjunto auxiliar sem exigir um fato principal já existente."""
        from .update_state import mutation_lock
        transaction = None
        try:
            with mutation_lock(self.base_dir):
                self._garantir_diretorio()
                self._recover_local_transaction()
                transaction = Path(tempfile.mkdtemp(prefix=f".{self.config.arquivo_dados}.transaction-", dir=self.cache_dir))
                protected = {self.arquivo_dados_runtime, self.arquivo_dados_pickle,
                             self.arquivo_metadata_runtime, self._integrity_file, self._previous_generation_file}
                allowed = set(self._runtime_paths()) - protected
                extras = {}
                for target, source in candidatos.items():
                    if target not in allowed:
                        raise ValueError("Artefato auxiliar fora do contrato de runtime")
                    staged = transaction / target.name
                    shutil.copy2(source, staged)
                    if target.suffix == ".parquet":
                        import pyarrow.parquet as pq
                        for _ in pq.ParquetFile(staged).iter_batches(batch_size=50_000):
                            pass
                    elif target.suffix == ".json":
                        json.loads(staged.read_text(encoding="utf-8"))
                    self._sync_file(staged)
                    extras[target] = staged
                self._promote_staged_pair(transaction, None, None, "parquet", extras)
                return CacheResult(True, "Artefatos auxiliares validados e salvos", fonte="cache_local")
        except Exception as exc:
            if transaction is not None and not self._transaction_file.exists():
                # Após uma falha de rollback a geração anterior permanece no
                # snapshot; candidatos pré-promoção podem ser descartados.
                if not (transaction / "previous").exists():
                    shutil.rmtree(transaction, ignore_errors=True)
            return CacheResult(False, f"Artefatos auxiliares não ativados: {exc}", fonte="nenhum")

    def salvar_local(
        self,
        dados: pd.DataFrame,
        fonte: str = "desconhecida",
        info_extra: Optional[Dict] = None,
        metadata_extra: Optional[Dict] = None,
    ) -> CacheResult:
        """Valida e promove dados/metadata juntos, com rollback recuperável.

        Os nomes públicos dos arquivos permanecem iguais. A geração anterior
        fica disponível até o candidato ser relido e a promoção ser concluída.
        Sem suporte a parquet, o candidato usa o fallback pickle existente.
        """
        # Validar dados
        valido, msg = self._validar_dados(dados)
        if not valido:
            return CacheResult(
                sucesso=False,
                mensagem=f"Dados invalidos: {msg}",
                fonte="nenhum"
            )

        from .institution_registry import INSTITUTION_NAMED_CACHE_NAMES, validate_institution_names
        if self.config.nome in INSTITUTION_NAMED_CACHE_NAMES:
            valido, msg = validate_institution_names(dados)
            if not valido:
                return CacheResult(sucesso=False, mensagem=msg, fonte="nenhum")

        from .update_state import mutation_lock
        transaction = None
        promotion_started = False
        try:
            with mutation_lock(self.base_dir):
                self._garantir_diretorio()
                self._recover_local_transaction()
                transaction = Path(tempfile.mkdtemp(
                    prefix=f".{self.config.arquivo_dados}.transaction-", dir=self.cache_dir,
                ))
                staged_data = transaction / self.arquivo_dados_runtime.name
                formato_usado = "parquet"
                arquivo_salvo = self.arquivo_dados_runtime
                try:
                    dados.to_parquet(staged_data, index=False)
                except ImportError as exc:
                    self._log("warning", f"Parquet não disponível ({exc}), usando pickle como fallback")
                    staged_data.unlink(missing_ok=True)
                    formato_usado = "pickle"
                    arquivo_salvo = self.arquivo_dados_pickle
                    staged_data = transaction / arquivo_salvo.name
                    with staged_data.open("xb") as handle:
                        pickle.dump(dados, handle)
                self._sync_file(staged_data)
                metadata = {**(metadata_extra or {}), **self._build_local_metadata(dados, fonte, formato_usado, info_extra)}
                publication = self._publication_metadata()
                if publication and fonte in {"api", "bcb_cosif", "ifdata_web", "materialized", "derivado", "BCData/SGS"}:
                    metadata["baseline_publication_id"] = publication["publication_id"]
                metadata["integridade"] = {
                    "versao": 1,
                    "geracao": uuid4().hex,
                    "arquivo_dados": arquivo_salvo.name,
                    "sha256": self._sha256(staged_data),
                    "tamanho_bytes": staged_data.stat().st_size,
                }
                if metadata_extra is not None and "sha256" in metadata_extra:
                    metadata["sha256"] = metadata["integridade"]["sha256"]
                staged_metadata = transaction / self.arquivo_metadata_runtime.name
                staged_integrity = transaction / self._integrity_file.name
                self._write_json_atomic(staged_metadata, metadata)
                self._write_json_atomic(staged_integrity, metadata["integridade"])
                reread, checksum, size = self._read_data_file(staged_data, formato_usado)
                reread_metadata = json.loads(staged_metadata.read_text(encoding="utf-8"))
                self._validate_pair(reread, reread_metadata, staged_data, staged_integrity, checksum, size)
                pd.testing.assert_frame_equal(
                    dados.reset_index(drop=True), reread.reset_index(drop=True),
                    check_dtype=False, check_categorical=False, check_exact=True,
                )

                promotion_started = True
                self._promote_staged_pair(transaction, staged_data, metadata, formato_usado)
                transaction = None
                self._log("info", f"Cache salvo ({formato_usado}): {len(dados)} registros, {metadata['integridade']['tamanho_bytes']:,} bytes")
                return CacheResult(
                    True, f"Salvo com sucesso ({formato_usado}): {len(dados)} registros",
                    dados=dados, metadata=metadata, fonte="cache_local",
                )
        except Exception as e:
            # O diário pode ter sido gravado antes de uma falha de fsync. Nesse
            # caso o snapshot precisa sobreviver para recuperação posterior.
            if transaction is not None and not promotion_started and not self._transaction_file.exists():
                shutil.rmtree(transaction, ignore_errors=True)
            self._log("error", f"Erro ao salvar cache: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao salvar: {e}",
                fonte="nenhum"
            )

    def limpar_local(self) -> CacheResult:
        """Remove arquivos de cache local (parquet e pickle)."""
        removidos = []
        from .update_state import mutation_lock
        try:
            with mutation_lock(self.base_dir):
                self._recover_local_transaction()
                # Limpeza atinge apenas o runtime; o bundled é imutável.
                for path in self._runtime_paths():
                    if path.exists():
                        path.unlink()
                        if path not in {self._integrity_file, self._previous_generation_file}:
                            removidos.append(path.name)
                for directory in self.cache_dir.glob(f".{self.config.arquivo_dados}.transaction-*"):
                    if directory.is_dir() and not directory.is_symlink():
                        shutil.rmtree(directory)
                if self.cache_dir.exists():
                    self._sync_directory(self.cache_dir)

            if removidos:
                self._log("info", f"Cache limpo: {', '.join(removidos)}")
                return CacheResult(
                    sucesso=True,
                    mensagem=f"Removidos: {', '.join(removidos)}",
                    fonte="nenhum"
                )
            else:
                return CacheResult(
                    sucesso=True,
                    mensagem="Cache ja estava vazio",
                    fonte="nenhum"
                )

        except Exception as e:
            self._log("error", f"Erro ao limpar cache: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao limpar: {e}",
                fonte="nenhum"
            )

    def get_info(self) -> Dict[str, Any]:
        """Retorna informacoes sobre o cache."""
        from .update_state import UpdateBusyError, mutation_lock
        try:
            with mutation_lock(self.base_dir):
                self._recover_local_transaction()
                return self._get_coherent_info()
        except UpdateBusyError:
            return self._get_coherent_info()
        except Exception as exc:
            return {"nome": self.config.nome, "descricao": self.config.descricao,
                    "existe": self.existe(), "diretorio": str(self.cache_dir), "erro_metadata": str(exc)}

    def _get_coherent_info(self) -> Dict[str, Any]:
        info = {
            "nome": self.config.nome,
            "descricao": self.config.descricao,
            "existe": self.existe(),
            "diretorio": str(self.cache_dir),
            "arquivo_dados": str(self.arquivo_dados),
        }

        if self.existe_leitura():
            try:
                journal_before = self._transaction_file.read_bytes() if self._transaction_file.exists() else None
                snapshot = self._transaction_snapshot(journal_before)[1] if journal_before is not None else None
                data_path, metadata_path, _ = self._read_paths(snapshot)
                paths = snapshot or {path.name: path for path in self._runtime_paths()}
                runtime_read = data_path in (paths[self.arquivo_dados_runtime.name], paths[self.arquivo_dados_pickle.name])
                marker_path = paths[self._integrity_file.name] if runtime_read else None
                if not metadata_path.exists() and not (marker_path and marker_path.exists()):
                    info["metadata_ausente"] = True
                    return info
                metadata_before = metadata_path.read_bytes()
                metadata = json.loads(metadata_before)
                if not data_path.exists():
                    info["existe"] = False
                    return info
                integrity = metadata.get("integridade")
                if integrity and (integrity.get("sha256") != self._sha256(data_path)
                                  or integrity.get("tamanho_bytes") != data_path.stat().st_size):
                    raise ValueError("Dados e metadata pertencem a gerações diferentes")
                if marker_path and marker_path.exists() and json.loads(marker_path.read_bytes()) != integrity:
                    raise ValueError("Identidade da geração diverge da metadata")
                journal_after = self._transaction_file.read_bytes() if self._transaction_file.exists() else None
                if metadata_path.read_bytes() != metadata_before or journal_after != journal_before:
                    raise ValueError("A geração mudou durante a leitura da metadata")

                info.update({
                    "arquivo_dados": str(data_path),
                    "tamanho_bytes": data_path.stat().st_size,
                    "timestamp_salvamento": metadata.get("timestamp_salvamento"),
                    "fonte": metadata.get("fonte"),
                    "total_registros": metadata.get("total_registros"),
                    "total_periodos": metadata.get("total_periodos"),
                    "periodos": metadata.get("periodos"),
                })

                # Calcular idade do cache
                if metadata.get("timestamp_salvamento"):
                    ts = datetime.fromisoformat(metadata["timestamp_salvamento"])
                    idade = datetime.now() - ts
                    info["idade_horas"] = idade.total_seconds() / 3600

            except Exception as e:
                info["erro_metadata"] = str(e)

        return info

    def cache_valido(self) -> Tuple[bool, str]:
        """Verifica se cache existe e nao expirou."""
        if not self.existe():
            return False, "Cache nao existe"

        info = self.get_info()

        if "erro_metadata" in info:
            return False, f"Cache inválido: {info['erro_metadata']}"

        # Verificar expiracao
        if self.config.max_idade_horas and "idade_horas" in info:
            if info["idade_horas"] > self.config.max_idade_horas:
                return False, f"Cache expirado (idade: {info['idade_horas']:.1f}h)"

        return True, "Cache valido"

    # =========================================================================
    # VALIDACAO
    # =========================================================================

    def _validar_dados(self, dados: Any) -> Tuple[bool, str]:
        """Valida dados antes de salvar/apos carregar."""
        if dados is None:
            return False, "Dados sao None"

        if not isinstance(dados, pd.DataFrame):
            return False, f"Esperado DataFrame, recebido {type(dados)}"

        if dados.empty:
            return False, "DataFrame vazio"

        # Verificar colunas obrigatorias (aceita variantes comuns)
        colunas_disponiveis = set(dados.columns)
        equivalentes = {
            "Período": "Periodo",
            "Periodo": "Período",
        }
        for col in self.config.colunas_obrigatorias:
            if col not in colunas_disponiveis:
                equivalente = equivalentes.get(col)
                if equivalente and equivalente in colunas_disponiveis:
                    continue
                return False, f"Coluna obrigatoria ausente: {col}"

        return True, "OK"

    # =========================================================================
    # METODOS ABSTRATOS (implementados pelas subclasses)
    # =========================================================================

    @abstractmethod
    def baixar_remoto(self) -> CacheResult:
        """Baixa dados de fonte remota (GitHub/API)."""
        pass

    @abstractmethod
    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        """Extrai dados de um periodo especifico da API."""
        pass

    # =========================================================================
    # METODO PRINCIPAL DE CARREGAMENTO
    # =========================================================================

    def carregar(self, forcar_remoto: bool = False) -> CacheResult:
        """Carrega dados usando a melhor fonte disponivel.

        Ordem de prioridade:
        1. Cache local (se valido e nao forcar_remoto)
        2. Download remoto (GitHub)
        3. Falha

        Args:
            forcar_remoto: Se True, ignora cache local

        Returns:
            CacheResult com dados ou erro
        """
        # Tentar cache local primeiro
        if not forcar_remoto:
            if self._publication_metadata():
                resultado = self.carregar_local()
                if resultado.sucesso:
                    return resultado
            valido, msg = self.cache_valido()
            if valido:
                resultado = self.carregar_local()
                if resultado.sucesso:
                    self._log("info", f"Usando cache local: {msg}")
                    return resultado

        # Tentar baixar do remoto
        self._log("info", "Tentando baixar de fonte remota...")
        resultado = self.baixar_remoto()

        if resultado.sucesso:
            # Salvar localmente
            salvo = self.salvar_local(resultado.dados, fonte=resultado.fonte)
            if salvo.sucesso:
                return resultado
            self._log("warning", f"Fonte remota rejeitada: {salvo.mensagem}")

        # Tentar cache local mesmo expirado como fallback
        # Inclui o artefato bundled: sem rede, ele é a última linha de defesa.
        if self.existe_leitura():
            self._log("warning", "Usando cache local expirado como fallback")
            resultado = self.carregar_local()
            if resultado.sucesso:
                resultado.fonte = "cache_local_expirado"
                return resultado

        return CacheResult(
            sucesso=False,
            mensagem="Nenhuma fonte de dados disponivel",
            fonte="nenhum"
        )
