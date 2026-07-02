"""
relatorios_completos.py - Caches para relatórios que extraem todas as variáveis

Este módulo implementa caches para os relatórios que extraem TODAS as variáveis:
- Relatório 2: Ativo
- Relatório 3: Passivo
- Relatório 4: Demonstração de Resultado (DRE)
- Relatório 11: Carteira de crédito ativa PF - modalidade e prazo
- Relatório 13: Carteira de crédito ativa PJ - modalidade e prazo
- Relatório 16: Carteira de crédito ativa - Instrumentos Financeiros Res. 4.966 (C1-C5)

Todos usam a mesma lógica: extrair TODAS as variáveis do relatório da API.

IMPORTANTE: Este módulo usa o extrator autônomo (extractor.py) que produz dados
no formato exato que os gráficos esperam:
- Coluna "Instituição" (não "NomeInstituicao")
- Coluna "Período" no formato "1/2024" (trimestre/ano)
"""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .release_config import get_release_config

logger = logging.getLogger("ifdata_cache")


# =============================================================================
# CLASSE BASE PARA RELATORIOS COMPLETOS
# =============================================================================
class RelatorioCompletoCache(BaseCache):
    """Cache base para relatórios que extraem todas as variáveis.

    Produz dados com:
    - Coluna "Instituição" (nome da instituição)
    - Coluna "Período" no formato "1/2024" (trimestre/ano)
    - Todas as variáveis do relatório
    """

    def __init__(
        self,
        config: CacheConfig,
        base_dir: Path,
        relatorio_num: int,
        tipo_instituicao: int = 1,
        manter_codinst: bool = True,
    ):
        release_config = get_release_config()
        runtime_config = replace(config, github_url_base=release_config.release_base_url)
        super().__init__(runtime_config, base_dir)
        self.relatorio_num = relatorio_num
        self.tipo_instituicao = tipo_instituicao
        self.manter_codinst = manter_codinst
        self.release_repo = release_config.repo
        self.release_tag = release_config.tag
        release_base = release_config.release_base_url

        # URLs em ordem de prioridade:
        # 1. Parquet do repositório raw (configurável)
        self.github_raw_url = f"https://raw.githubusercontent.com/{release_config.raw_repo}/main/data/cache/{self.config.nome}/dados.parquet"
        # 2. Parquet dos releases (prod por padrão)
        self.github_release_parquet_url = f"{release_base}/{self.config.nome}_dados.parquet"
        # 3. Pickle dos releases (compat legado)
        self.github_release_url = f"{release_base}/{self.config.nome}_cache.pkl"
        self.repo_raw_enabled = False

    def baixar_remoto(self) -> CacheResult:
        """Baixa dados do GitHub (tenta repositório primeiro, depois releases)."""
        self._log("info", f"Tentando baixar do GitHub (repo={self.release_repo}, tag={self.release_tag})...")

        # 1. Tentar parquet do repositório
        if self.repo_raw_enabled:
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
            mensagem=f"Cache {self.config.nome} não encontrado no GitHub (tentou repositório e releases)",
            fonte="nenhum"
        )

    def _baixar_parquet_repo(self) -> CacheResult:
        """Baixa parquet do repositório GitHub."""
        try:
            self._log("info", f"Tentando parquet do repositório: {self.github_raw_url}")
            response = requests.get(self.github_raw_url, timeout=120)

            if response.status_code == 404:
                self._log("warning", f"Parquet {self.config.nome} não encontrado no repositório")
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
            response = requests.get(
                self.github_release_parquet_url,
                timeout=120,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )

            if response.status_code == 404:
                self._log("warning", f"Parquet {self.config.nome} não encontrado nos releases")
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
            response = requests.get(
                self.github_release_url,
                timeout=120,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )

            if response.status_code == 404:
                self._log("warning", f"Cache {self.config.nome} não encontrado nos releases (404)")
                return CacheResult(sucesso=False, mensagem="Cache não existe nos releases", fonte="nenhum")

            response.raise_for_status()

            import pickle
            import io

            dados_dict = pickle.load(io.BytesIO(response.content))

            # Converter para DataFrame único
            if isinstance(dados_dict, dict):
                dfs = []
                for periodo, df in dados_dict.items():
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        # Verificar coluna de período (pode ser "Periodo" ou "Período")
                        if "Período" not in df.columns and "Periodo" not in df.columns:
                            df = df.copy()
                            df["Período"] = str(periodo)
                        elif "Periodo" in df.columns and "Período" not in df.columns:
                            df = df.copy()
                            df["Período"] = df["Periodo"]
                        dfs.append(df)

                if dfs:
                    df_final = pd.concat(dfs, ignore_index=True)
                else:
                    return CacheResult(sucesso=False, mensagem="Arquivo do GitHub vazio", fonte="nenhum")
            elif isinstance(dados_dict, pd.DataFrame):
                df_final = dados_dict
            else:
                return CacheResult(sucesso=False, mensagem=f"Formato inesperado: {type(dados_dict)}", fonte="nenhum")

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

    def extrair_periodo(
        self,
        periodo: str,
        dict_aliases: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> CacheResult:
        """Extrai dados de um período da API do BCB.

        Usa o extrator autônomo para extrair TODAS as variáveis do relatório.
        Produz dados no formato exato que os gráficos esperam.

        Args:
            periodo: Período no formato YYYYMM (ex: "202312")
            dict_aliases: parâmetro legado sem efeito

        Returns:
            CacheResult com DataFrame ou erro
        """
        self._log("info", f"Extraindo período {periodo}...")

        try:
            # Usar extrator autônomo
            from .extractor import extrair_relatorio_completo

            df = extrair_relatorio_completo(
                periodo,
                self.relatorio_num,
                tipo_instituicao=self.tipo_instituicao,
                manter_codinst=self.manter_codinst,
            )

            if df is None or df.empty:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Sem dados para {periodo}",
                    fonte="nenhum"
                )

            # Contar variáveis (excluindo Instituição e Período)
            cols_info = ["Instituição", "Período"]
            n_variaveis = len([c for c in df.columns if c not in cols_info])

            self._log("info", f"Período {periodo}: {len(df)} instituições, {n_variaveis} variáveis")

            return CacheResult(
                sucesso=True,
                mensagem=f"Extraído {periodo}: {len(df)} registros",
                dados=df,
                metadata={
                    "periodo": periodo,
                    "relatorio": self.relatorio_num,
                    "n_instituicoes": len(df),
                    "n_variaveis": n_variaveis
                },
                fonte="api"
            )

        except Exception as e:
            self._log("error", f"Erro em {periodo}: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro: {e}",
                fonte="nenhum"
            )

    # =========================================================================
    # COMPATIBILIDADE COM SISTEMA ANTIGO
    # =========================================================================

    def carregar_formato_antigo(self) -> Optional[dict]:
        """Carrega e retorna no formato antigo {periodo: DataFrame}.

        O período é no formato de exibição ("1/2024").
        """
        resultado = self.carregar()
        if not resultado.sucesso or resultado.dados is None:
            return None

        df = resultado.dados

        # Verificar coluna de período (pode ser "Período" ou "Periodo")
        col_periodo = None
        if "Período" in df.columns:
            col_periodo = "Período"
        elif "Periodo" in df.columns:
            col_periodo = "Periodo"
        else:
            return None

        dados_dict = {}
        for periodo in df[col_periodo].unique():
            dados_dict[str(periodo)] = df[df[col_periodo] == periodo].copy()

        return dados_dict

    def salvar_formato_antigo(
        self,
        dados_dict: dict,
        fonte: str = "api",
        info_extra: Optional[dict] = None
    ) -> CacheResult:
        """Salva a partir do formato antigo {periodo: DataFrame}."""
        if not dados_dict:
            return CacheResult(
                sucesso=False,
                mensagem="Dicionário vazio",
                fonte="nenhum"
            )

        dfs = []
        for periodo, df in dados_dict.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                df_copy = df.copy()
                if "Período" not in df_copy.columns:
                    df_copy["Período"] = str(periodo)
                dfs.append(df_copy)

        if not dfs:
            return CacheResult(
                sucesso=False,
                mensagem="Nenhum DataFrame válido",
                fonte="nenhum"
            )

        df_final = pd.concat(dfs, ignore_index=True)
        return self.salvar_local(df_final, fonte=fonte, info_extra=info_extra)


# =============================================================================
# CONFIGURACOES ESPECÍFICAS DE CADA RELATORIO
# =============================================================================

# Relatório 2: Ativo
ATIVO_CONFIG = CacheConfig(
    nome="ativo",
    descricao="Composição detalhada do Ativo (Relatório 2)",
    subdir="ativo",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],  # Formato de exibição com acento
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=2,
)

# Relatório 3: Passivo
PASSIVO_CONFIG = CacheConfig(
    nome="passivo",
    descricao="Composição detalhada do Passivo (Relatório 3)",
    subdir="passivo",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=3,
)

# Relatório 4: DRE
DRE_CONFIG = CacheConfig(
    nome="dre",
    descricao="Demonstração de Resultado do Exercício (Relatório 4)",
    subdir="dre",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=4,
)

DRE_INDIVIDUAL_CONFIG = CacheConfig(
    nome="dre_individual",
    descricao="Demonstração de Resultado do Exercício - instituições individuais (Relatório 4)",
    subdir="dre_individual",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=4,
)

# Relatório 11: Carteira PF
CARTEIRA_PF_CONFIG = CacheConfig(
    nome="carteira_pf",
    descricao="Carteira de crédito ativa PF - modalidade e prazo (Relatório 11)",
    subdir="carteira_pf",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=11,
)

# Relatório 13: Carteira PJ
CARTEIRA_PJ_CONFIG = CacheConfig(
    nome="carteira_pj",
    descricao="Carteira de crédito ativa PJ - modalidade e prazo (Relatório 13)",
    subdir="carteira_pj",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=13,
)

# Relatório 16: Carteira por Instrumentos Financeiros - Res. 4.966 (C1-C5)
CARTEIRA_INSTRUMENTOS_CONFIG = CacheConfig(
    nome="carteira_instrumentos",
    descricao="Carteira de crédito ativa - Instrumentos Financeiros Res. 4.966 (Relatório 16)",
    subdir="carteira_instrumentos",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=168.0,
    colunas_obrigatorias=["Período"],
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=16,
)


# =============================================================================
# CLASSES DE CACHE ESPECIFICAS
# =============================================================================

class AtivoCache(RelatorioCompletoCache):
    """Cache de dados de Ativo (Relatório 2)."""

    def __init__(self, base_dir: Path):
        super().__init__(ATIVO_CONFIG, base_dir, relatorio_num=2)


class PassivoCache(RelatorioCompletoCache):
    """Cache de dados de Passivo (Relatório 3)."""

    def __init__(self, base_dir: Path):
        super().__init__(PASSIVO_CONFIG, base_dir, relatorio_num=3)


class DRECache(RelatorioCompletoCache):
    """Cache de Demonstração de Resultado (Relatório 4)."""

    def __init__(self, base_dir: Path):
        super().__init__(DRE_CONFIG, base_dir, relatorio_num=4)


class DREIndividualCache(RelatorioCompletoCache):
    """Cache de DRE para instituições individuais (Relatório 4)."""

    def __init__(self, base_dir: Path):
        super().__init__(
            DRE_INDIVIDUAL_CONFIG,
            base_dir,
            relatorio_num=4,
            tipo_instituicao=2,
            manter_codinst=True,
        )


class CarteiraPFCache(RelatorioCompletoCache):
    """Cache de Carteira de Crédito PF (Relatório 11)."""

    def __init__(self, base_dir: Path):
        super().__init__(CARTEIRA_PF_CONFIG, base_dir, relatorio_num=11)


class CarteiraPJCache(RelatorioCompletoCache):
    """Cache de Carteira de Crédito PJ (Relatório 13)."""

    def __init__(self, base_dir: Path):
        super().__init__(CARTEIRA_PJ_CONFIG, base_dir, relatorio_num=13)


class CarteiraInstrumentosCache(RelatorioCompletoCache):
    """Cache de Carteira de Crédito - Instrumentos Financeiros Res. 4.966 (Relatório 16)."""

    def __init__(self, base_dir: Path):
        super().__init__(CARTEIRA_INSTRUMENTOS_CONFIG, base_dir, relatorio_num=16)


# =============================================================================
# FUNCOES DE CONVENIENCIA
# =============================================================================

def listar_relatorios_completos() -> List[Dict]:
    """Lista todos os relatórios completos disponíveis."""
    return [
        {"numero": 2, "nome": "ativo", "descricao": "Composição do Ativo"},
        {"numero": 3, "nome": "passivo", "descricao": "Composição do Passivo"},
        {"numero": 4, "nome": "dre", "descricao": "Demonstração de Resultado"},
        {"numero": 11, "nome": "carteira_pf", "descricao": "Carteira de Crédito PF"},
        {"numero": 13, "nome": "carteira_pj", "descricao": "Carteira de Crédito PJ"},
        {"numero": 16, "nome": "carteira_instrumentos", "descricao": "Carteira - Instrumentos 4.966"},
    ]
