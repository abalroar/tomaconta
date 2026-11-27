"""Concessões ajustadas publicadas nas tabelas 2 a 5 e no SGS."""
import json
from pathlib import Path

import pandas as pd

from utils.sgs_credit_registry import bcb_series


ARQUIVO = Path(__file__).resolve().parents[1] / "data/bundled/mercado_credito_sgs/concessoes_ajustadas_tabelas.json"
MODALIDADES_SGS = ("concessoes_sa_pj_capital_giro", "concessoes_sa_pf_veiculos", "concessoes_sa_pf_cartao_vista")


def concessoes_das_tabelas(wide: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Conserva a edição integral do anexo e completa meses fora dela com observações SGS."""
    arquivo = Path(wide.attrs.get("arquivo_concessoes_bc", ARQUIVO))
    aliases = {s.code: s.alias for s in bcb_series() if 24439 <= s.code <= 24447}
    colunas = [aliases[codigo] for codigo in sorted(aliases)]
    # O SGS expressa o fluxo em R$ milhões. O anexo o expressa em R$ bilhões.
    sgs = wide.reindex(columns=colunas).div(1000)
    sgs = sgs.groupby(pd.DatetimeIndex(sgs.index).to_period("M")).last()
    fonte_sgs = {"source": "BC · SGS", "source_footer": "BC · SGS", "preservar_lacunas": True}
    if not arquivo.is_file():
        sgs.index = sgs.index.to_timestamp()
        return sgs.dropna(how="all"), fonte_sgs
    ficha = json.loads(arquivo.read_text(encoding="utf-8"))
    tabela = pd.DataFrame(ficha["dados"], columns=["data", *(aliases[c] for c in ficha["codigos_sgs"])]).set_index("data")
    tabela.index = pd.PeriodIndex(tabela.index, freq="M")
    if not sgs.empty:
        tabela = tabela.loc[sgs.index.min():sgs.index.max()]
    else:
        tabela = tabela.iloc[:0]
    tabela = tabela.reindex(tabela.index.union(sgs.index))
    usa_tabela = tabela.notna().any().any()
    usa_sgs = (tabela.isna() & sgs.notna()).any().any()
    quadro = tabela.combine_first(sgs).dropna(how="all").astype(float)
    quadro.index = quadro.index.to_timestamp()
    data = pd.Timestamp(ficha["publicado_em"]).strftime("%d/%m/%Y")
    if not usa_tabela:
        return quadro, fonte_sgs
    rotulo = f"BC · tabelas 2 a 5 de {data}"
    complemento = " · SGS nos meses fora do anexo" if usa_sgs else ""
    return quadro, {
        "source": rotulo + complemento, "source_provider": "BC/TabelasCredito",
        "source_footer": f"[{rotulo}]({ficha['fonte']})" + complemento,
        "source_note": "O BC ajusta cada série separadamente. A soma das aberturas pode diferir do total publicado.",
        "preservar_lacunas": True,
    }
