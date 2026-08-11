"""
base.py - Classes base para o sistema de cache

Define a interface comum para todos os tipos de cache.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        """Carrega dados do cache local (runtime ou bundled; parquet ou pickle)."""
        if not self.existe_leitura():
            return CacheResult(
                sucesso=False,
                mensagem="Cache local nao existe",
                fonte="nenhum"
            )

        try:
            # Determinar formato e carregar dados
            if self.arquivo_dados.exists():
                # Tentar parquet
                try:
                    df = pd.read_parquet(self.arquivo_dados)
                    formato = "parquet"
                except ImportError:
                    # pyarrow não disponível mas arquivo existe
                    if self.arquivo_dados_pickle.exists():
                        import pickle
                        with open(self.arquivo_dados_pickle, 'rb') as f:
                            df = pickle.load(f)
                        formato = "pickle"
                    else:
                        raise ImportError("pyarrow não disponível e não há fallback pickle")
            elif self.arquivo_dados_pickle.exists():
                # Usar pickle
                import pickle
                with open(self.arquivo_dados_pickle, 'rb') as f:
                    df = pickle.load(f)
                formato = "pickle"
            else:
                return CacheResult(
                    sucesso=False,
                    mensagem="Arquivo de dados não encontrado",
                    fonte="nenhum"
                )

            # Carregar metadata (ou gerar se estiver ausente)
            if self.arquivo_metadata.exists():
                with open(self.arquivo_metadata, "r") as f:
                    metadata = json.load(f)
            else:
                metadata = {
                    "timestamp_salvamento": datetime.fromtimestamp(
                        self.arquivo_dados.stat().st_mtime
                        if self.arquivo_dados.exists()
                        else self.arquivo_dados_pickle.stat().st_mtime
                    ).isoformat(),
                    "fonte": "cache_local",
                    "total_registros": len(df),
                    "colunas": list(df.columns),
                    "formato": formato,
                }

                col_periodo = None
                if "Período" in df.columns:
                    col_periodo = "Período"
                elif "Periodo" in df.columns:
                    col_periodo = "Periodo"

                if col_periodo:
                    periodos = sorted(df[col_periodo].unique().tolist())
                    metadata["periodos"] = [str(p) for p in periodos]
                    metadata["total_periodos"] = len(periodos)

                self._log("warning", "Metadata ausente; gerada automaticamente")
                # Só persiste quando há parquet de runtime: o artefato bundled é
                # somente-leitura e não deve ganhar metadata órfã ao lado.
                if self.arquivo_dados_runtime.exists():
                    try:
                        self._garantir_diretorio()
                        with open(self.arquivo_metadata_runtime, "w") as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                    except Exception as e:
                        self._log("warning", f"Falha ao gravar metadata gerada: {e}")

            # Validar dados
            valido, msg = self._validar_dados(df)
            if not valido:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Cache corrompido: {msg}",
                    fonte="nenhum"
                )

            self._log("info", f"Cache local carregado: {len(df)} registros")

            return CacheResult(
                sucesso=True,
                mensagem=f"Carregado do cache local: {len(df)} registros",
                dados=df,
                metadata=metadata,
                fonte="cache_local"
            )

        except Exception as e:
            self._log("error", f"Erro ao carregar cache local: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao carregar: {e}",
                fonte="nenhum"
            )

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
        if runtime.exists():
            return runtime
        bundled = self.bundled_dir / self.config.arquivo_dados
        if bundled.exists():
            return bundled
        return runtime

    @property
    def arquivo_metadata(self) -> Path:
        """Metadata efetivo para leitura, pareado com `arquivo_dados`."""
        if self.arquivo_dados_runtime.exists():
            return self.arquivo_metadata_runtime
        bundled = self.bundled_dir / self.config.arquivo_metadata
        if bundled.exists():
            return bundled
        return self.arquivo_metadata_runtime

    @property
    def arquivo_dados_pickle(self) -> Path:
        """Caminho do arquivo de dados em formato pickle (fallback)."""
        return self.cache_dir / self.config.arquivo_dados.replace('.parquet', '.pkl')

    def salvar_local(
        self,
        dados: pd.DataFrame,
        fonte: str = "desconhecida",
        info_extra: Optional[Dict] = None
    ) -> CacheResult:
        """Salva dados no cache local.

        Tenta salvar em parquet primeiro. Se falhar (pyarrow não disponível),
        usa pickle como fallback.
        """
        # Validar dados
        valido, msg = self._validar_dados(dados)
        if not valido:
            return CacheResult(
                sucesso=False,
                mensagem=f"Dados invalidos: {msg}",
                fonte="nenhum"
            )

        try:
            self._garantir_diretorio()

            # Tentar salvar em parquet primeiro
            formato_usado = "parquet"
            arquivo_salvo = self.arquivo_dados_runtime
            try:
                dados.to_parquet(self.arquivo_dados_runtime, index=False)
            except ImportError as e:
                # pyarrow/fastparquet não disponível - usar pickle como fallback
                self._log("warning", f"Parquet não disponível ({e}), usando pickle como fallback")
                import pickle
                arquivo_salvo = self.arquivo_dados_pickle
                with open(arquivo_salvo, 'wb') as f:
                    pickle.dump(dados, f)
                formato_usado = "pickle"

            # Criar metadata
            metadata = {
                "timestamp_salvamento": datetime.now().isoformat(),
                "fonte": fonte,
                "total_registros": len(dados),
                "colunas": list(dados.columns),
                "formato": formato_usado,
            }

            # Adicionar periodos se disponivel (verificar ambas as grafias)
            col_periodo = None
            if "Período" in dados.columns:
                col_periodo = "Período"
            elif "Periodo" in dados.columns:
                col_periodo = "Periodo"

            if col_periodo:
                periodos = sorted(dados[col_periodo].unique().tolist())
                metadata["periodos"] = [str(p) for p in periodos]
                metadata["total_periodos"] = len(periodos)

            # Adicionar info extra
            if info_extra:
                metadata["extra"] = info_extra

            # Salvar metadata (sempre no runtime, pareado com o parquet gravado)
            with open(self.arquivo_metadata_runtime, "w") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Verificar que foi salvo corretamente
            if not arquivo_salvo.exists():
                raise IOError("Arquivo de dados nao foi criado")

            tamanho = arquivo_salvo.stat().st_size
            self._log("info", f"Cache salvo ({formato_usado}): {len(dados)} registros, {tamanho:,} bytes")

            return CacheResult(
                sucesso=True,
                mensagem=f"Salvo com sucesso ({formato_usado}): {len(dados)} registros",
                dados=dados,
                metadata=metadata,
                fonte="cache_local"
            )

        except Exception as e:
            self._log("error", f"Erro ao salvar cache: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao salvar: {e}",
                fonte="nenhum"
            )

    def limpar_local(self) -> CacheResult:
        """Remove arquivos de cache local (parquet e pickle)."""
        removidos = []

        try:
            # Limpeza atinge apenas o cache de runtime; o bundled é imutável.
            if self.arquivo_dados_runtime.exists():
                self.arquivo_dados_runtime.unlink()
                removidos.append(self.config.arquivo_dados)

            if self.arquivo_dados_pickle.exists():
                self.arquivo_dados_pickle.unlink()
                removidos.append(str(self.arquivo_dados_pickle.name))

            if self.arquivo_metadata_runtime.exists():
                self.arquivo_metadata_runtime.unlink()
                removidos.append(self.config.arquivo_metadata)

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
        info = {
            "nome": self.config.nome,
            "descricao": self.config.descricao,
            "existe": self.existe(),
            "diretorio": str(self.cache_dir),
            "arquivo_dados": str(self.arquivo_dados),
        }

        if self.existe():
            try:
                with open(self.arquivo_metadata, "r") as f:
                    metadata = json.load(f)

                info.update({
                    "tamanho_bytes": self.arquivo_dados.stat().st_size,
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
            self.salvar_local(resultado.dados, fonte=resultado.fonte)
            return resultado

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
