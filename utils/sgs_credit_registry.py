"""Registro central das séries do módulo Mercado de Crédito.

Os nomes oficiais foram conferidos no Portal de Dados Abertos do BCB. Códigos
que aparecem apenas nas fotografias e ainda não têm correspondência inequívoca
ficam em ``UNRESOLVED_SGS_CODES`` e não alimentam gráficos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Literal, Mapping


ProviderName = Literal["bcb_sgs", "external"]
ValidationStatus = Literal["official_metadata", "user_confirmed", "pending"]


@dataclass(frozen=True)
class SeriesSpec:
    alias: str
    code: int | None
    label: str
    official_name: str
    unit: str
    frequency: str = "monthly"
    provider: ProviderName = "bcb_sgs"
    validation: ValidationStatus = "official_metadata"
    discontinued_after: str | None = None
    note: str | None = None

    @property
    def metadata_url(self) -> str | None:
        if self.provider != "bcb_sgs" or self.code is None:
            return None
        return (
            "https://www3.bcb.gov.br/sgspub/consultarmetadados/"
            "consultarMetadadosSeries.do?method=consultarMetadadosSeriesInternet"
            f"&hdOidSerieSelecionada={self.code}"
        )


def _s(
    alias: str,
    code: int,
    label: str,
    official_name: str,
    unit: str,
    **kwargs,
) -> SeriesSpec:
    return SeriesSpec(alias, code, label, official_name, unit, **kwargs)


_SERIES = [
    # Séries auxiliares.
    _s("ipca_mensal", 433, "IPCA", "IPCA - Variação mensal", "pct_month", validation="user_confirmed"),
    _s("selic_aa", 4189, "Selic", "Taxa de juros - Selic acumulada no mês anualizada base 252", "pct_year"),
    _s("cdi_aa", 4392, "CDI", "Taxa CDI", "pct_year", validation="user_confirmed"),
    _s("desocupacao", 24369, "Taxa de desocupação", "Taxa de desocupação", "pct", validation="user_confirmed"),
    # Saldo agregado e por tomador.
    _s("saldo_pj_total", 20540, "PJ total", "Saldo da carteira de crédito - Pessoas jurídicas - Total", "brl_million"),
    _s("saldo_pf_total", 20541, "PF total", "Saldo da carteira de crédito - Pessoas físicas - Total", "brl_million"),
    _s("saldo_livre_total", 20542, "Recursos livres", "Saldo da carteira de crédito com recursos livres - Total", "brl_million"),
    _s("saldo_livre_pj", 20543, "PJ livre", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Total", "brl_million"),
    _s("saldo_livre_pj_duplicatas", 20544, "Desconto de duplicatas/recebíveis", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Desconto de duplicatas e recebíveis", "brl_million"),
    _s("saldo_livre_pj_capital_giro", 20550, "Capital de giro", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Capital de giro total", "brl_million"),
    _s("saldo_livre_pj_conta_garantida", 20551, "Conta garantida", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Conta garantida", "brl_million"),
    _s("saldo_livre_pj_aquisicao_bens", 20555, "Aquisição de bens", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Aquisição de bens total", "brl_million"),
    _s("saldo_livre_pj_acc", 20565, "ACC", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Adiantamento sobre contratos de câmbio (ACC)", "brl_million"),
    _s("saldo_livre_pj_exportacao", 20567, "Financiamento à exportação", "Saldo da carteira de crédito com recursos livres - Pessoas jurídicas - Financiamento a exportações", "brl_million"),
    _s("saldo_livre_pf", 20570, "PF livre", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Total", "brl_million"),
    _s("saldo_livre_pf_cheque", 20573, "Cheque especial", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Cheque especial", "brl_million"),
    _s("saldo_livre_pf_pessoal_nao_consignado", 20574, "Crédito pessoal não consignado", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "brl_million"),
    _s("saldo_livre_pf_consignado_privado", 20576, "Consignado privado", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado para trabalhadores do setor privado", "brl_million"),
    _s("saldo_livre_pf_consignado_publico", 20577, "Consignado público", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado para trabalhadores do setor público", "brl_million"),
    _s("saldo_livre_pf_consignado_inss", 20578, "Consignado INSS", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado para aposentados e pensionistas do INSS", "brl_million"),
    _s("saldo_livre_pf_consignado", 20579, "Consignado", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "brl_million"),
    _s("saldo_livre_pf_veiculos", 20581, "Veículos", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Aquisição de veículos", "brl_million"),
    _s("saldo_livre_pf_cartao_rotativo", 20587, "Cartão rotativo", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito rotativo", "brl_million"),
    _s("saldo_livre_pf_cartao_parcelado", 20588, "Cartão parcelado", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito parcelado", "brl_million"),
    _s("saldo_livre_pf_cartao_vista", 20589, "Cartão à vista", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito à vista", "brl_million"),
    _s("saldo_livre_pf_cartao_total", 20590, "Cartão de crédito", "Saldo da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito total", "brl_million"),
    _s("saldo_direcionado_total", 20593, "Recursos direcionados", "Saldo da carteira de crédito com recursos direcionados - Total", "brl_million"),
    _s("saldo_direcionado_pj", 20594, "PJ direcionado", "Saldo da carteira de crédito com recursos direcionados - Pessoas jurídicas - Total", "brl_million"),
    _s("saldo_direcionado_pj_rural", 20597, "Rural PJ", "Saldo da carteira de crédito com recursos direcionados - Pessoas jurídicas - Crédito rural total", "brl_million"),
    _s("saldo_direcionado_pj_imobiliario", 20600, "Imobiliário PJ", "Saldo da carteira de crédito com recursos direcionados - Pessoas jurídicas - Financiamento imobiliário total", "brl_million"),
    _s("saldo_direcionado_pj_bndes", 20604, "BNDES PJ", "Saldo da carteira de crédito com recursos direcionados - Pessoas jurídicas - Financiamento com recursos do BNDES total", "brl_million"),
    _s("saldo_direcionado_pj_outros", 20605, "Outros direcionados PJ", "Saldo da carteira de crédito com recursos direcionados - Pessoas jurídicas - Outros créditos direcionados", "brl_million"),
    _s("saldo_direcionado_pf", 20606, "PF direcionado", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Total", "brl_million"),
    _s("saldo_direcionado_pf_rural", 20609, "Rural PF", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Crédito rural total", "brl_million"),
    _s("saldo_direcionado_pf_imobiliario", 20612, "Imobiliário PF", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário total", "brl_million"),
    _s("saldo_direcionado_pf_bndes", 20616, "BNDES PF", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Financiamento com recursos do BNDES total", "brl_million"),
    _s("saldo_direcionado_pf_microcredito", 20620, "Microcrédito", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Microcrédito total", "brl_million"),
    _s("saldo_direcionado_pf_outros", 20621, "Outros direcionados PF", "Saldo da carteira de crédito com recursos direcionados - Pessoas físicas - Outros créditos direcionados", "brl_million"),
    # Crédito ampliado.
    _s("credito_ampliado_total", 28183, "Crédito ampliado", "Saldo de crédito ampliado ao setor não financeiro - Total", "brl_million"),
    _s("credito_ampliado_emprestimos", 28184, "Empréstimos", "Saldo de empréstimos e financiamentos ao setor não financeiro - total", "brl_million"),
    _s("credito_ampliado_titulos", 28188, "Títulos de dívida", "Saldo de títulos de dívida - Total", "brl_million"),
    _s("credito_ampliado_divida_externa", 28192, "Dívida externa", "Saldo de dívida externa - Total", "brl_million"),
    # Porte e controle.
    _s("saldo_controle_publico", 2007, "SF público", "Saldos das operações de crédito das instituições financeiras sob controle público - Total", "brl_million"),
    _s("saldo_controle_privado_nacional", 12106, "SF privado nacional", "Saldos das operações de crédito das instituições financeiras sob controle privado nacional - Total", "brl_million"),
    _s("saldo_controle_estrangeiro", 12150, "SF privado estrangeiro", "Saldos das operações de crédito das instituições financeiras sob controle estrangeiro - Total", "brl_million"),
    _s("saldo_pj_mpme", 27701, "Pequenas e médias", "Saldo das operações de crédito por porte da empresa - Micro, Pequena e Média (MPMe)", "brl_million"),
    _s("saldo_pj_grande", 27702, "Grandes", "Saldo das operações de crédito por porte da empresa - Grande", "brl_million"),
    # Concessões.
    _s("concessoes_total", 20631, "Concessões totais", "Concessões de crédito - Total", "brl_million"),
    _s("concessoes_livre_pj", 20635, "PJ livre", "Concessões de crédito com recursos livres - Pessoas jurídicas - Total", "brl_million"),
    _s("concessoes_livre_pj_capital_giro", 20642, "Capital de giro", "Concessões de crédito com recursos livres - Pessoas jurídicas - Capital de giro total", "brl_million"),
    _s("concessoes_livre_pf", 20662, "PF livre", "Concessões de crédito com recursos livres - Pessoas físicas - Total", "brl_million"),
    _s("concessoes_livre_pf_nao_consignado", 20666, "Crédito pessoal não consignado", "Concessões de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "brl_million"),
    _s("concessoes_livre_pf_consignado", 20671, "Consignado", "Concessões de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "brl_million"),
    _s("concessoes_livre_pf_veiculos", 20673, "Veículos", "Concessões de crédito com recursos livres - Pessoas físicas - Aquisição de veículos", "brl_million"),
    _s("concessoes_livre_pf_cartao", 20682, "Cartão de crédito", "Concessões de crédito com recursos livres - Pessoas físicas - Cartão de crédito total", "brl_million"),
    _s("concessoes_direcionado_pj", 20686, "PJ direcionado", "Concessões de crédito com recursos direcionados - Pessoas jurídicas - Total", "brl_million"),
    _s("concessoes_direcionado_pf", 20698, "PF direcionado", "Concessões de crédito com recursos direcionados - Pessoas físicas - Total", "brl_million"),
    _s("concessoes_direcionado_pf_imobiliario", 20704, "Crédito imobiliário", "Concessões de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário total", "brl_million"),
    _s("concessoes_sa_pj", 24440, "PJ total", "Concessões de crédito sazonalmente ajustadas - Pessoas jurídicas - Total", "brl_million"),
    _s("concessoes_sa_pf", 24441, "PF total", "Concessões de crédito sazonalmente ajustadas - Pessoas físicas - Total", "brl_million"),
    _s("concessoes_sa_livre_pj", 24443, "PJ livre", "Concessões de crédito com recursos livres sazonalmente ajustadas - Pessoas jurídicas - Total", "brl_million"),
    _s("concessoes_sa_livre_pf", 24444, "PF livre", "Concessões de crédito com recursos livres sazonalmente ajustadas - Pessoas físicas - Total", "brl_million"),
    _s("concessoes_sa_direcionado_pj", 24446, "PJ direcionado", "Concessões de crédito com recursos direcionados sazonalmente ajustadas - Pessoas jurídicas - Total", "brl_million"),
    _s("concessoes_sa_direcionado_pf", 24447, "PF direcionado", "Concessões de crédito com recursos direcionados sazonalmente ajustadas - Pessoas físicas - Total", "brl_million"),
    _s("concessoes_sa_pj_capital_giro", 28169, "Capital de giro", "Concessões de crédito com recursos livres sazonalmente ajustadas - Pessoas jurídicas - Capital de giro total", "brl_million"),
    _s("concessoes_sa_pf_veiculos", 28170, "Veículos", "Concessões de crédito com recursos livres sazonalmente ajustadas - Pessoas físicas - Aquisição de veículos", "brl_million"),
    _s("concessoes_sa_pf_cartao_vista", 28171, "Cartão à vista", "Concessões de crédito com recursos livres sazonalmente ajustadas - Pessoas físicas - Cartão de crédito à vista", "brl_million"),
    # Prazo médio das novas operações.
    _s("prazo_livre_pj", 20856, "Prazo médio", "Prazo médio das concessões de crédito com recursos livres - Pessoas jurídicas - Total", "months"),
    _s("prazo_livre_pf_nao_consignado", 20879, "Prazo médio", "Prazo médio das concessões de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "months"),
    _s("prazo_livre_pf_consignado", 20884, "Prazo médio", "Prazo médio das concessões de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "months"),
    _s("prazo_livre_pf_veiculos", 20886, "Prazo médio", "Prazo médio das concessões de crédito com recursos livres - Pessoas físicas - Aquisição de veículos", "months"),
    _s("prazo_livre_pf_cartao_parcelado", 20892, "Prazo médio", "Prazo médio das concessões de crédito com recursos livres - Pessoas físicas - Cartão de crédito parcelado", "months"),
    _s("prazo_direcionado_pj", 20896, "Prazo médio", "Prazo médio das concessões de crédito com recursos direcionados - Pessoas jurídicas - Total", "months"),
    _s("prazo_direcionado_pf_imobiliario", 20914, "Prazo médio", "Prazo médio das concessões de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário total", "months"),
    # Pré-inadimplência e inadimplência.
    _s("pre_inad_total", 21003, "Pré-inad total", "Percentual da carteira de crédito com atraso entre 15 e 90 dias - Total", "pct"),
    _s("pre_inad_livre_total", 21006, "Pré-inad total", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Total", "pct"),
    _s("pre_inad_livre_pj", 21007, "PJ pré-inad", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas jurídicas - Total", "pct"),
    _s("pre_inad_livre_pj_duplicatas", 21008, "Desconto de recebíveis", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas jurídicas - Desconto de duplicatas e recebíveis", "pct"),
    _s("pre_inad_livre_pj_capital_giro", 21014, "Capital de giro", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas jurídicas - Capital de giro total", "pct"),
    _s("pre_inad_livre_pj_conta_garantida", 21015, "Conta garantida", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas jurídicas - Conta garantida", "pct"),
    _s("pre_inad_livre_pf", 21033, "PF pré-inad", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Total", "pct"),
    _s("pre_inad_livre_pf_cheque", 21034, "Cheque especial", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Cheque especial", "pct"),
    _s("pre_inad_livre_pf_nao_consignado", 21035, "Crédito pessoal não consignado", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Crédito pessoal não consignado", "pct"),
    _s("pre_inad_livre_pf_consignado", 21040, "Consignado", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Crédito pessoal consignado total", "pct"),
    _s("pre_inad_livre_pf_veiculos", 21042, "Veículos", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Aquisição de veículos", "pct"),
    _s("pre_inad_livre_pf_cartao_rotativo", 21048, "Cartão rotativo", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Cartão de crédito rotativo", "pct"),
    _s("pre_inad_livre_pf_cartao_parcelado", 21049, "Cartão parcelado", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Cartão de crédito parcelado", "pct"),
    _s("pre_inad_livre_pf_cartao_total", 21050, "Cartão total", "Percentual da carteira de crédito com recursos livres com atraso entre 15 e 90 dias - Pessoas físicas - Cartão de crédito total", "pct"),
    _s("pre_inad_direcionado_pf_imobiliario", 21072, "Imobiliário", "Percentual da carteira de crédito com recursos direcionados com atraso entre 15 e 90 dias - Pessoas físicas - Financiamento imobiliário total", "pct"),
    _s("inad_total", 21082, "Inad total", "Inadimplência da carteira de crédito - Total", "pct"),
    _s("inad_livre_total", 21085, "Inad total", "Inadimplência da carteira de crédito com recursos livres - Total", "pct"),
    _s("inad_livre_pj", 21086, "PJ inad", "Inadimplência da carteira de crédito com recursos livres - Pessoas jurídicas - Total", "pct"),
    _s("inad_livre_pj_duplicatas", 21087, "Desconto de recebíveis", "Inadimplência da carteira de crédito com recursos livres - Pessoas jurídicas - Desconto de duplicatas e recebíveis", "pct"),
    _s("inad_livre_pj_capital_giro", 21093, "Capital de giro", "Inadimplência da carteira de crédito com recursos livres - Pessoas jurídicas - Capital de giro total", "pct"),
    _s("inad_livre_pj_conta_garantida", 21094, "Conta garantida", "Inadimplência da carteira de crédito com recursos livres - Pessoas jurídicas - Conta garantida", "pct"),
    _s("inad_livre_pf", 21112, "PF inad", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Total", "pct"),
    _s("inad_livre_pf_cheque", 21113, "Cheque especial", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Cheque especial", "pct"),
    _s("inad_livre_pf_nao_consignado", 21114, "Crédito pessoal não consignado", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "pct"),
    _s("inad_livre_pf_consignado", 21119, "Consignado", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "pct"),
    _s("inad_livre_pf_veiculos", 21121, "Veículos", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Aquisição de veículos", "pct"),
    _s("inad_livre_pf_cartao_rotativo", 21127, "Cartão rotativo", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito rotativo", "pct"),
    _s("inad_livre_pf_cartao_parcelado", 21128, "Cartão parcelado", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito parcelado", "pct"),
    _s("inad_livre_pf_cartao_total", 21129, "Cartão total", "Inadimplência da carteira de crédito com recursos livres - Pessoas físicas - Cartão de crédito total", "pct"),
    _s("inad_direcionado_pf_imobiliario", 21151, "Imobiliário", "Inadimplência da carteira de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário total", "pct"),
    # Provisão e inadimplência por controle, para cobertura derivada.
    _s("provisao_sfn", 13645, "SFN", "Percentual do total de provisões em relação à carteira de crédito do Sistema Financeiro Nacional", "pct"),
    _s("provisao_publico", 13666, "Bancos públicos", "Percentual do total de provisões em relação à carteira de crédito das instituições financeiras sob controle público", "pct"),
    _s("inad_publico", 13667, "Bancos públicos", "Inadimplência da carteira de crédito das instituições financeiras sob controle público - Total", "pct"),
    _s("provisao_privado_nacional", 13672, "Privado nacional", "Percentual do total de provisões em relação à carteira de crédito das instituições financeiras sob controle privado nacional", "pct"),
    _s("inad_privado_nacional", 13673, "Privado nacional", "Inadimplência da carteira de crédito das instituições financeiras sob controle privado nacional - Total", "pct"),
    _s("provisao_estrangeiro", 13678, "Privado estrangeiro", "Percentual do total de provisões em relação à carteira de crédito das instituições financeiras sob controle estrangeiro", "pct"),
    _s("inad_estrangeiro", 13679, "Privado estrangeiro", "Inadimplência da carteira de crédito das instituições financeiras sob controle estrangeiro - Total", "pct"),
    # Taxas e spreads.
    _s("taxa_pj_livre", 20718, "Taxa PJ livre", "Taxa média de juros das operações de crédito com recursos livres - Pessoas jurídicas - Total", "pct_year"),
    _s("taxa_pj_duplicatas", 20719, "Desconto de duplicatas", "Taxa média de juros das operações de crédito com recursos livres - Pessoas jurídicas - Desconto de duplicatas e recebíveis", "pct_year"),
    _s("taxa_pj_capital_giro", 20725, "Capital de giro", "Taxa média de juros das operações de crédito com recursos livres - Pessoas jurídicas - Capital de giro total", "pct_year"),
    _s("taxa_pj_conta_garantida", 20726, "Conta garantida", "Taxa média de juros das operações de crédito com recursos livres - Pessoas jurídicas - Conta garantida", "pct_year"),
    _s("taxa_pf_livre", 20740, "Taxa PF livre", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Total", "pct_year"),
    _s("taxa_pf_cheque", 20741, "Cheque especial", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cheque especial", "pct_year"),
    _s("taxa_pf_nao_consignado", 20742, "Crédito pessoal não consignado", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "pct_year"),
    _s("taxa_pf_consignado", 20747, "Consignado", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "pct_year"),
    _s("taxa_pf_veiculos", 20749, "Veículos", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Aquisição de veículos", "pct_year"),
    _s("taxa_pf_imobiliario", 20774, "Imobiliário", "Taxa média de juros das operações de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário total", "pct_year"),
    _s("taxa_pf_cartao_rotativo", 22022, "Cartão rotativo", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cartão de crédito rotativo", "pct_year"),
    _s("taxa_pf_cartao_parcelado", 22023, "Cartão parcelado", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cartão de crédito parcelado", "pct_year"),
    _s("taxa_pf_cartao_total", 22024, "Cartão total", "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cartão de crédito total", "pct_year"),
    _s("spread_pj_livre", 20787, "Spread PJ", "Spread médio das operações de crédito com recursos livres - Pessoas jurídicas - Total", "pp"),
    _s("spread_pf_livre", 20809, "Spread PF", "Spread médio das operações de crédito com recursos livres - Pessoas físicas - Total", "pp"),
    # Situação das famílias.
    _s("comprometimento_juros", 29033, "Juros", "Comprometimento de renda das famílias com juros da dívida com o Sistema Financeiro Nacional - Com ajuste sazonal (RNDBF)", "pct"),
    _s("comprometimento_servico_ex_habitacional", 29035, "Serviço da dívida ex-habitacional", "Comprometimento de renda das famílias com o serviço da dívida com o Sistema Financeiro Nacional exceto crédito habitacional - Com ajuste sazonal (RNDBF)", "pct"),
    _s("comprometimento_amortizacao", 29036, "Amortização", "Comprometimento de renda das famílias com amortização da dívida com o Sistema Financeiro Nacional - Com ajuste sazonal (RNDBF)", "pct"),
    _s("endividamento_renda", 29037, "Endividamento", "Endividamento das famílias com o Sistema Financeiro Nacional em relação à renda acumulada dos últimos doze meses (RNDBF)", "pct"),
]


SGS_SERIES: Dict[str, SeriesSpec] = {spec.alias: spec for spec in _SERIES}
SGS_SERIES_BY_CODE: Dict[int, SeriesSpec] = {
    spec.code: spec for spec in _SERIES if spec.code is not None
}

# Inventário fotografado ainda pendente de associação inequívoca a um card.
UNRESOLVED_SGS_CODES = frozenset(
    {
        1619, 20576, 20577, 20578, 20636, 20643, 20647, 20657, 20659,
        20663, 20668, 20669, 20670, 20679, 20680, 20744, 20745, 20746,
        20756, 20757, 20768, 20852, 20857, 20863, 20866, 20873, 20875,
        20878, 20881, 20882, 20883, 20899, 20902, 20906, 20908, 20911,
        20918, 20922, 21004, 21005, 21037, 21038, 21039, 21053, 21054,
        21066, 21083, 21084, 21116, 21117, 21118, 21132, 21133, 21145,
        21400, 27705, 27706, 27707, 28185, 28186, 28187, 28189, 28190,
        28191, 28193, 28194, 28195,
    }
)


def get_series(alias: str) -> SeriesSpec:
    try:
        return SGS_SERIES[alias]
    except KeyError as exc:
        raise KeyError(f"Série SGS não registrada: {alias}") from exc


def series_for_aliases(aliases: Iterable[str]) -> Mapping[str, SeriesSpec]:
    return {alias: get_series(alias) for alias in aliases}


def bcb_series() -> tuple[SeriesSpec, ...]:
    return tuple(
        spec for spec in SGS_SERIES.values()
        if spec.provider == "bcb_sgs" and spec.code is not None and spec.validation != "pending"
    )
