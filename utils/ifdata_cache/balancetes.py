"""
balancetes.py - Cache para dados de balancetes do Banco Central

Este módulo implementa cache para demonstrações contábeis COSIF (4060, 4066)
obtidas via API REST do Banco Central.

Endpoints utilizados:
- https://www3.bcb.gov.br/informes/rest/balanco
- https://www3.bcb.gov.br/informes/rest/balanco/arquivosCosif
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from io import BytesIO

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult

logger = logging.getLogger("ifdata_cache")


# =============================================================================
# CONFIGURAÇÃO DO CACHE DE BALANCETES
# =============================================================================
BALANCETES_CONFIG = CacheConfig(
    nome="balancetes",
    descricao="Demonstrações Contábeis - Balancetes COSIF (4060, 4066)",
    subdir="balancetes",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base="https://github.com/abalroar/tomaconta/releases/download/v1.0-cache",
    max_idade_horas=168.0,  # 7 dias
    colunas_obrigatorias=["Período", "CNPJ"],
    api_url="https://www3.bcb.gov.br/informes/rest/balanco",
    relatorio_tipo=None,  # API diferente do IFData
)


# =============================================================================
# CLASSE DE CACHE PARA BALANCETES
# =============================================================================
class BalancetesCache(BaseCache):
    """Cache para demonstrações contábeis - Balancetes COSIF (4060, 4066).

    Busca dados de TODAS as instituições financeiras usando a API REST do BCB.
    Suporta documentos COSIF:
    - 4060: Balancete Analítico
    - 4066: Balancete Sintético

    Produz dados com:
    - Coluna "Instituição" (nome da instituição)
    - Coluna "CNPJ" (CNPJ da instituição)
    - Coluna "Período" (formato YYYYMM)
    - Coluna "Documento" (código COSIF: 4060 ou 4066)
    - Todas as colunas do arquivo CSV do BCB
    """

    def __init__(self, base_dir: Path):
        super().__init__(BALANCETES_CONFIG, base_dir)

        # URLs remotas para fallback
        release_repo = "abalroar/tomaconta"
        raw_repo = "abalroar/tomaconta-dev"
        release_base = f"https://github.com/{release_repo}/releases/download/v1.0-cache"

        self.github_raw_url = f"https://raw.githubusercontent.com/{raw_repo}/main/data/cache/balancetes/dados.parquet"
        self.github_release_parquet_url = f"{release_base}/balancetes_dados.parquet"
        self.github_release_url = f"{release_base}/balancetes_cache.pkl"

        # Configurações da API BCB
        self.api_base_url = "https://www3.bcb.gov.br/informes/rest/balanco"
        self.timeout = 120
        self.max_retries = 3
        self.backoff_factor = 2.0
        self.rate_limit_delay = 1.5

    def baixar_remoto(self) -> CacheResult:
        """Baixa dados do GitHub (tenta repositório primeiro, depois releases)."""
        self._log("info", "Tentando baixar do GitHub...")

        # 1. Tentar parquet do repositório
        resultado = self._baixar_parquet_repo()
        if resultado.sucesso:
            return resultado

        # 2. Fallback: tentar parquet dos releases
        resultado = self._baixar_parquet_release()
        if resultado.sucesso:
            return resultado

        # 3. Fallback: tentar pickle dos releases
        resultado = self._baixar_pickle_releases()
        if resultado.sucesso:
            return resultado

        return CacheResult(
            sucesso=False,
            mensagem="Cache balancetes não encontrado no GitHub",
            fonte="nenhum"
        )

    def _baixar_parquet_repo(self) -> CacheResult:
        """Baixa parquet do repositório GitHub."""
        try:
            self._log("info", f"Tentando parquet do repositório: {self.github_raw_url}")
            response = requests.get(self.github_raw_url, timeout=120)

            if response.status_code == 404:
                self._log("warning", "Parquet balancetes não encontrado no repositório")
                return CacheResult(sucesso=False, mensagem="Parquet não existe no repositório", fonte="nenhum")

            response.raise_for_status()

            import io
            try:
                df = pd.read_parquet(io.BytesIO(response.content))
                self._log("info", f"Baixado parquet do repositório: {len(df)} registros")
                return CacheResult(
                    sucesso=True,
                    mensagem=f"Baixado do repositório: {len(df)} registros",
                    dados=df,
                    fonte="github_repo"
                )
            except ImportError:
                self._log("warning", "pyarrow não disponível para ler parquet")
                return CacheResult(sucesso=False, mensagem="pyarrow não disponível", fonte="nenhum")

        except requests.RequestException as e:
            self._log("error", f"Erro ao baixar do repositório: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")
        except Exception as e:
            self._log("error", f"Erro: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")

    def _baixar_parquet_release(self) -> CacheResult:
        """Baixa parquet do GitHub Releases."""
        try:
            self._log("info", f"Tentando parquet dos releases: {self.github_release_parquet_url}")
            response = requests.get(self.github_release_parquet_url, timeout=120)

            if response.status_code == 404:
                self._log("warning", "Parquet balancetes não encontrado nos releases")
                return CacheResult(sucesso=False, mensagem="Parquet não existe nos releases", fonte="nenhum")

            response.raise_for_status()

            import io
            try:
                df = pd.read_parquet(io.BytesIO(response.content))
                self._log("info", f"Baixado parquet dos releases: {len(df)} registros")
                return CacheResult(
                    sucesso=True,
                    mensagem=f"Baixado dos releases: {len(df)} registros",
                    dados=df,
                    fonte="github_releases"
                )
            except ImportError:
                self._log("warning", "pyarrow não disponível para ler parquet")
                return CacheResult(sucesso=False, mensagem="pyarrow não disponível", fonte="nenhum")

        except requests.RequestException as e:
            self._log("error", f"Erro de rede: {e}")
            return CacheResult(sucesso=False, mensagem=f"Erro de rede: {e}", fonte="nenhum")
        except Exception as e:
            self._log("error", f"Erro: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")

    def _baixar_pickle_releases(self) -> CacheResult:
        """Baixa pickle do GitHub Releases."""
        try:
            self._log("info", f"Tentando pickle dos releases: {self.github_release_url}")
            response = requests.get(self.github_release_url, timeout=120)

            if response.status_code == 404:
                self._log("warning", "Cache balancetes não encontrado nos releases (404)")
                return CacheResult(sucesso=False, mensagem="Cache não existe nos releases", fonte="nenhum")

            response.raise_for_status()

            import pickle
            import io

            dados = pickle.load(io.BytesIO(response.content))

            if isinstance(dados, pd.DataFrame):
                df_final = dados
            elif isinstance(dados, dict):
                dfs = []
                for k, v in dados.items():
                    if isinstance(v, pd.DataFrame) and not v.empty:
                        dfs.append(v)
                if dfs:
                    df_final = pd.concat(dfs, ignore_index=True)
                else:
                    return CacheResult(sucesso=False, mensagem="Arquivo do GitHub vazio", fonte="nenhum")
            else:
                return CacheResult(sucesso=False, mensagem=f"Formato inesperado: {type(dados)}", fonte="nenhum")

            self._log("info", f"Baixado pickle dos releases: {len(df_final)} registros")

            return CacheResult(
                sucesso=True,
                mensagem=f"Baixado dos releases: {len(df_final)} registros",
                dados=df_final,
                fonte="github_releases"
            )

        except requests.RequestException as e:
            self._log("error", f"Erro de rede: {e}")
            return CacheResult(sucesso=False, mensagem=f"Erro de rede: {e}", fonte="nenhum")
        except Exception as e:
            self._log("error", f"Erro ao processar: {e}")
            return CacheResult(sucesso=False, mensagem=f"Erro: {e}", fonte="nenhum")

    def _buscar_periodos_disponiveis_bcb(
        self,
        cnpj: str,
        documento: str = "4060",
        ano_inicial: int = 2015,
        ano_final: Optional[int] = None
    ) -> List[str]:
        """Busca períodos disponíveis para um CNPJ na API BCB.

        Args:
            cnpj: CNPJ da instituição (8 dígitos)
            documento: Código do documento COSIF (4060 ou 4066)
            ano_inicial: Ano inicial para busca
            ano_final: Ano final para busca (None = ano atual)

        Returns:
            Lista de períodos no formato YYYYMM
        """
        import datetime
        if ano_final is None:
            ano_final = datetime.datetime.now().year

        periodos_encontrados = []

        # Buscar trimestralmente (Mar, Jun, Set, Dez)
        for ano in range(ano_inicial, ano_final + 1):
            for mes in ["03", "06", "09", "12"]:
                ano_mes = f"{ano}{mes}"

                try:
                    # Montar URL de consulta
                    url = f"{self.api_base_url}/arquivos"
                    params = {
                        "cnpj": cnpj.zfill(8),
                        "anoMes": int(ano_mes),
                        "periodo": 1  # Mensal
                    }

                    response = requests.get(url, params=params, timeout=self.timeout)

                    if response.status_code == 200:
                        try:
                            data = response.json()
                            # Verificar se há arquivos disponíveis
                            if data and len(data) > 0:
                                periodos_encontrados.append(ano_mes)
                        except json.JSONDecodeError:
                            pass

                    # Rate limiting
                    time.sleep(self.rate_limit_delay)

                except Exception as e:
                    self._log("debug", f"Erro ao verificar {ano_mes} para CNPJ {cnpj}: {e}")
                    continue

        return sorted(periodos_encontrados)

    def _baixar_balancete_bcb(
        self,
        cnpj: str,
        periodo: str,
        documento: str = "4060"
    ) -> Optional[pd.DataFrame]:
        """Baixa balancete de uma instituição para um período específico.

        Args:
            cnpj: CNPJ da instituição (8 dígitos)
            periodo: Período no formato YYYYMM
            documento: Código do documento COSIF (4060 ou 4066)

        Returns:
            DataFrame com os dados do balancete ou None
        """
        try:
            # Montar URL de consulta para listar arquivos
            url_lista = f"{self.api_base_url}/arquivos"
            params = {
                "cnpj": cnpj.zfill(8),
                "anoMes": int(periodo),
                "periodo": 1  # Mensal
            }

            response = requests.get(url_lista, params=params, timeout=self.timeout)
            response.raise_for_status()

            arquivos = response.json()

            if not arquivos or len(arquivos) == 0:
                self._log("debug", f"Nenhum arquivo encontrado para CNPJ {cnpj} em {periodo}")
                return None

            # Buscar arquivo do documento específico
            arquivo_alvo = None
            for arquivo in arquivos:
                nome = arquivo.get("nomeArquivo", "")
                if documento in nome:
                    arquivo_alvo = arquivo
                    break

            if not arquivo_alvo:
                self._log("debug", f"Documento {documento} não encontrado para CNPJ {cnpj} em {periodo}")
                return None

            # Baixar arquivo
            url_download = f"{self.api_base_url}/download/{arquivo_alvo['nomeArquivo']}"
            response = requests.get(url_download, timeout=self.timeout)
            response.raise_for_status()

            # Tentar ler CSV com diferentes encodings
            content = response.content
            encodings = ["utf-8", "latin1", "cp1252", "iso-8859-1"]

            for encoding in encodings:
                try:
                    df = pd.read_csv(
                        BytesIO(content),
                        sep=None,
                        engine="python",
                        encoding=encoding
                    )

                    if not df.empty:
                        # Adicionar metadados
                        df["Período"] = periodo
                        df["CNPJ"] = cnpj
                        df["Documento"] = documento
                        return df

                except Exception:
                    continue

            self._log("warning", f"Falha ao decodificar CSV para CNPJ {cnpj} em {periodo}")
            return None

        except Exception as e:
            self._log("error", f"Erro ao baixar balancete CNPJ {cnpj} em {periodo}: {e}")
            return None

    def extrair_periodo(
        self,
        periodo: str,
        dict_aliases: Optional[Dict[str, str]] = None,
        instituicoes_cnpj: Optional[Dict[str, str]] = None,
        documentos: Optional[List[str]] = None,
        **kwargs
    ) -> CacheResult:
        """Extrai balancetes de todas as instituições para um período.

        Args:
            periodo: Período no formato YYYYMM (ex: "202312")
            dict_aliases: Dicionário de aliases (não usado aqui)
            instituicoes_cnpj: Mapeamento {nome_instituição: cnpj}
            documentos: Lista de documentos COSIF a buscar (default: ["4060"])

        Returns:
            CacheResult com DataFrame ou erro
        """
        self._log("info", f"Extraindo balancetes para período {periodo}...")

        if not instituicoes_cnpj:
            return CacheResult(
                sucesso=False,
                mensagem="Nenhuma instituição com CNPJ fornecida",
                fonte="nenhum"
            )

        if documentos is None:
            documentos = ["4060"]

        todos_dfs = []
        total_instituicoes = len(instituicoes_cnpj)
        contador = 0

        for nome_inst, cnpj in instituicoes_cnpj.items():
            contador += 1
            self._log("info", f"[{contador}/{total_instituicoes}] Buscando {nome_inst} (CNPJ: {cnpj})...")

            for documento in documentos:
                df = self._baixar_balancete_bcb(cnpj, periodo, documento)

                if df is not None and not df.empty:
                    df["Instituição"] = nome_inst
                    todos_dfs.append(df)

                # Rate limiting entre requisições
                time.sleep(self.rate_limit_delay)

        if not todos_dfs:
            return CacheResult(
                sucesso=False,
                mensagem=f"Nenhum balancete encontrado para período {periodo}",
                fonte="nenhum"
            )

        df_final = pd.concat(todos_dfs, ignore_index=True)

        self._log("info", f"Período {periodo}: {len(df_final)} registros de {len(todos_dfs)} balancetes")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraído {periodo}: {len(df_final)} registros",
            dados=df_final,
            metadata={
                "periodo": periodo,
                "n_registros": len(df_final),
                "n_balancetes": len(todos_dfs),
                "documentos": documentos
            },
            fonte="api"
        )

    def extrair_todos_periodos(
        self,
        periodos: List[str],
        instituicoes_cnpj: Dict[str, str],
        documentos: Optional[List[str]] = None,
        callback_progresso: Optional[callable] = None
    ) -> CacheResult:
        """Extrai balancetes de todas as instituições para múltiplos períodos.

        Args:
            periodos: Lista de períodos no formato YYYYMM
            instituicoes_cnpj: Mapeamento {nome_instituição: cnpj}
            documentos: Lista de documentos COSIF a buscar (default: ["4060"])
            callback_progresso: Função callback(periodo, df) para reportar progresso

        Returns:
            CacheResult com DataFrame consolidado
        """
        self._log("info", f"Extraindo balancetes para {len(periodos)} períodos...")

        todos_dfs = []

        for i, periodo in enumerate(periodos):
            self._log("info", f"Processando período {periodo} ({i+1}/{len(periodos)})...")

            resultado = self.extrair_periodo(
                periodo,
                instituicoes_cnpj=instituicoes_cnpj,
                documentos=documentos
            )

            if resultado.sucesso and resultado.dados is not None:
                todos_dfs.append(resultado.dados)

                if callback_progresso:
                    callback_progresso(periodo, resultado.dados)

            # Salvar incrementalmente a cada 4 períodos
            if (i + 1) % 4 == 0 and todos_dfs:
                df_temp = pd.concat(todos_dfs, ignore_index=True)
                self.salvar_local(df_temp, fonte="api")
                self._log("info", f"Salvamento incremental: {len(df_temp)} registros")

        if not todos_dfs:
            return CacheResult(
                sucesso=False,
                mensagem="Nenhum balancete encontrado para os períodos especificados",
                fonte="nenhum"
            )

        df_final = pd.concat(todos_dfs, ignore_index=True)

        # Salvar resultado final
        resultado_salvar = self.salvar_local(df_final, fonte="api")

        if resultado_salvar.sucesso:
            self._log("info", f"Extração completa: {len(df_final)} registros salvos")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraídos {len(periodos)} períodos: {len(df_final)} registros",
            dados=df_final,
            metadata={
                "n_periodos": len(periodos),
                "n_registros": len(df_final),
                "documentos": documentos
            },
            fonte="api"
        )
