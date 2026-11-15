"""Catálogo e figuras do Mercado Imobiliário, preservando os conceitos do BCB."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .sgs_credit_analytics import line_figure, stacked_figure

SOURCE_URL = "https://www.bcb.gov.br/estatisticas/mercadoimobiliario"
METHODOLOGY_URL = "https://www.bcb.gov.br/content/estatisticas/mercadoimobiliario_docs/Metodologia.pdf"
CATALOG_VERSION = 1
LINE_LABELS = {"sfh": "SFH", "fgts": "FGTS", "livre": "Livre", "comercial": "Comercial", "home_equity": "Home Equity"}
INDEX_LABELS = {"tr": "TR", "prefixado": "Prefixado", "ipca": "IPCA", "cdi": "CDI", "outros": "Outros"}
RISK_LABELS = {"aa": "AA", "a": "A", "b": "B", "c": "C", "d_mais": "D ou mais"}
UFS = frozenset("ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to br na".split())


@dataclass(frozen=True)
class ChartSpec:
    key: str
    section: str
    title: str
    prefix: str
    labels: dict[str, str]
    unit: str
    scale: float = 1.0
    stacked: bool = False
    note: str = ""
    historical: bool = False


CHARTS: tuple[ChartSpec, ...] = tuple(
    spec
    for person in ("pf", "pj")
    for spec in (
        ChartSpec(f"contratacao_valor_{person}", f"Contratação · {person.upper()}", "Valor contratado", f"credito_contratacao_contratado_{person}_", LINE_LABELS, "R$ milhões", 1e-6, True,
                  "Valores contratados e liberados; exclui crédito a liberar e limites."),
        ChartSpec(f"contratacao_indexador_{person}", f"Contratação · {person.upper()}", "Indexadores", f"credito_contratacao_indexador_{person}_", INDEX_LABELS, "R$ milhões", 1e-6, True),
        ChartSpec(f"contratacao_taxa_{person}", f"Contratação · {person.upper()}", "Taxa", f"credito_contratacao_taxa_{person}_", LINE_LABELS, "% a.a.", note="Taxa anual ponderada pelo valor contratado, incluindo o componente pós-fixado."),
        *([ChartSpec("contratacao_ltv_pf", "Contratação · PF", "Loan to Value", "credito_contratacao_ltv_pf_", LINE_LABELS, "%", note="Mediana da relação entre o valor contratado e as garantias não fidejussórias.")] if person == "pf" else []),
    )
) + tuple(
    spec
    for person in ("pf", "pj")
    for spec in (
        ChartSpec(f"estoque_carteira_{person}", f"Estoque · {person.upper()}", "Carteira de crédito", f"credito_estoque_carteira_credito_{person}_", LINE_LABELS, "R$ bilhões", 1e-9, True,
                  "Somatório dos valores a vencer, vencidos e em prejuízo, conforme esta publicação do BCB."),
        ChartSpec(f"estoque_indexador_{person}", f"Estoque · {person.upper()}", "Indexadores", f"credito_estoque_indexador_{person}_", INDEX_LABELS, "R$ bilhões", 1e-9, True),
        ChartSpec(f"estoque_risco_{person}", f"Estoque · {person.upper()}", "Risco da operação", f"credito_estoque_risco_operacao_{person}_", RISK_LABELS, "%", stacked=True,
                  note="Classificação AA–D ou mais da Resolução 2.682. Última observação encontrada: dezembro/2024. Série histórica; não corresponde aos estágios da Resolução 4.966.", historical=True),
        ChartSpec(f"estoque_inadimplencia_{person}", f"Estoque · {person.upper()}", "Inadimplência", f"credito_estoque_inadimplencia_{person}_", LINE_LABELS, "%",
                  note="Percentual da carteira ativa das operações com alguma parcela vencida há mais de 90 dias; considera o saldo inteiro da operação."),
        ChartSpec(f"estoque_problematico_{person}", f"Estoque · {person.upper()}", "Ativos problemáticos", f"credito_estoque_ativo_problematico_{person}_", LINE_LABELS, "R$ bilhões", 1e-9,
                  note="Saldo monetário publicado pelo BCB. A classificação de risco sofreu mudança em 2025; evite interpretar a passagem de regime como variação econômica isolada."),
        *([ChartSpec("estoque_parcela_pf", "Estoque · PF", "Valor da próxima parcela", "credito_estoque_parcela_pf_", LINE_LABELS, "R$", note="Mediana do valor da próxima parcela. Disponível para PF.")] if person == "pf" else []),
    )
) + (
    ChartSpec("imoveis_tipo", "Imóveis", "Tipo de imóvel", "imoveis_tipo_", {"apartamento": "Apartamento", "casa": "Casa"}, "mil unidades", .001, True),
    ChartSpec("imoveis_dormitorio", "Imóveis", "Número de dormitórios", "imoveis_dormitorio_", {"1": "1", "2": "2", "3": "3", "4_mais": "4 ou mais"}, "mil unidades", .001, True),
    ChartSpec("imoveis_area", "Imóveis", "Área", "imoveis_area_", {"privativa": "Privativa", "total": "Total"}, "m²", note="Mediana das áreas privativa e total; não se soma nem se calcula média entre UFs."),
    ChartSpec("imoveis_implantacao", "Imóveis", "Tipo de implantação", "imoveis_implantacao_", {"condominio": "Condomínio", "isolado": "Isolado"}, "mil unidades", .001, True),
    ChartSpec("imoveis_valor", "Imóveis", "Valor do imóvel", "imoveis_valor_", {"avaliacao": "Avaliação", "compra": "Compra"}, "R$ mil", .001, note="Medianas dos valores de avaliação e compra. A composição dos imóveis registrados pode mudar entre meses."),
    ChartSpec("imoveis_garantia", "Imóveis", "Tipo de garantia", "imoveis_garantia_", {"alienacao_fiduciaria": "Alienação fiduciária", "hipoteca": "Hipoteca"}, "mil unidades", .001, True),
)
CHART_BY_KEY = {spec.key: spec for spec in CHARTS}
SECTIONS = tuple(dict.fromkeys(spec.section for spec in CHARTS))
FACT_COLUMNS = ["data", "info", "valor", "grafico", "categoria", "linha", "uf"]


def parse_info(info: str) -> dict | None:
    """Reconhece o código completo; underscores integram várias categorias."""
    for spec in CHARTS:
        if not info.startswith(spec.prefix):
            continue
        rest = info[len(spec.prefix):]
        category, sep, uf = rest.rpartition("_")
        uf = uf.lower()  # A fonte usa também NA para geografia não informada.
        if not sep or uf not in UFS:
            raise ValueError(f"Código geográfico não reconhecido: {info}")
        line = ""
        if spec.historical and category not in spec.labels:
            for candidate in LINE_LABELS:
                if category.startswith(candidate + "_"):
                    line, category = candidate, category[len(candidate) + 1:]
                    break
        if category not in spec.labels or ("_pj_" in spec.prefix and (category == "home_equity" or line == "home_equity")):
            raise ValueError(f"Série nova ou não reconhecida; revisar catálogo: {info}")
        return {"grafico": spec.key, "categoria": category, "linha": line, "uf": uf}
    return None


def normalize_records(records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        if not {"Data", "Info", "Valor"}.issubset(record):
            raise ValueError("Resposta Olinda sem Data, Info ou Valor")
        info = str(record["Info"])
        parsed = parse_info(info)
        if parsed is not None:
            rows.append({"data": record["Data"], "info": info, "valor": record["Valor"], **parsed})
    frame = pd.DataFrame(rows, columns=FACT_COLUMNS)
    frame["data"] = pd.to_datetime(frame["data"], errors="raise")
    frame["valor"] = pd.to_numeric(frame["valor"], errors="raise").astype("float64")
    valid = validate_frame(frame) if not frame.empty else {"success": True}
    if not valid["success"]:
        raise ValueError(valid["message"])
    return frame.sort_values(["data", "info"]).reset_index(drop=True)


def validate_frame(frame: pd.DataFrame) -> dict:
    if not set(FACT_COLUMNS).issubset(frame.columns):
        return {"success": False, "message": "Colunas do Mercado Imobiliário incompletas"}
    if frame[FACT_COLUMNS].isna().any().any() or frame.duplicated(["data", "info"]).any():
        return {"success": False, "message": "Valor ausente ou chave (Data, Info) duplicada"}
    if frame.empty:
        return {"success": False, "message": "Mercado Imobiliário sem observações"}
    if not pd.api.types.is_datetime64_any_dtype(frame["data"]) or not pd.api.types.is_numeric_dtype(frame["valor"]):
        return {"success": False, "message": "Data ou valor com tipo inválido"}
    if not frame["data"].dt.is_month_end.all():
        return {"success": False, "message": "Competência fora do fechamento mensal"}
    if not frame.empty:
        import numpy as np
        if not np.isfinite(frame["valor"]).all() or (frame["valor"] < 0).any():
            return {"success": False, "message": "Valor não finito ou negativo"}
        if frame["info"].str.startswith("contabil_").any() or not set(frame["grafico"]).issubset(CHART_BY_KEY):
            return {"success": False, "message": "Série fora do escopo aprovado"}
        try:
            parsed = {info: parse_info(info) for info in frame["info"].unique()}
            if any(value is None for value in parsed.values()):
                raise ValueError("Código fora do catálogo")
            for field in ("grafico", "categoria", "linha", "uf"):
                expected = frame["info"].map({info: dims[field] for info, dims in parsed.items()})
                if not frame[field].eq(expected).all():
                    raise ValueError(f"Classificação {field} divergente do código original")
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
    return {"success": True, "message": "Schema, chaves e valores conferidos"}


def figures_for_section(frame: pd.DataFrame, section: str, *, uf: str = "br", months: int | None = 12,
                        start=None, end=None) -> tuple[list, list[dict]]:
    """Cada gráfico termina na sua competência; intervalos explícitos são respeitados."""
    figures, coverage = [], []
    for spec in (item for item in CHARTS if item.section == section):
        selected = frame[(frame["grafico"] == spec.key) & (frame["uf"] == uf) & (frame["linha"] == "")]
        latest = selected["data"].max()
        if start is not None:
            selected = selected[selected["data"] >= pd.Timestamp(start)]
        if end is not None:
            selected = selected[selected["data"] <= pd.Timestamp(end)]
        if months and start is None and not selected.empty:
            selected = selected[selected["data"] >= selected["data"].max() - pd.DateOffset(months=months - 1)]
        if not selected.empty:
            wide = selected.pivot(index="data", columns="categoria", values="valor").sort_index() * spec.scale
            aliases = [category for category in spec.labels if category in wide]
            title = f"{spec.title} · {section.split(' · ')[-1]}" if section != "Imóveis" else spec.title
            builder = stacked_figure if spec.stacked else line_figure
            kwargs = {"percent": spec.unit == "%"} if spec.stacked else {"suffix": "%" if spec.unit.startswith("%") else "", "compacto": True}
            figure = builder(wide, aliases, title=title, y_title=spec.unit, labels=spec.labels, **kwargs)
            dates = selected["data"]
            period = f"{dates.min():%m/%Y} a {dates.max():%m/%Y}"
            note = spec.note + (" Histórico até dez/2024." if spec.historical else "")
            source = f"fonte: BCB · Olinda/MercadoImobiliario · {uf.upper()} · {period}"
            figure.update_layout(meta={**dict(figure.layout.meta or {}), "source": source,
                "source_provider": "Olinda/MercadoImobiliario", "source_codes": selected["info"].unique().tolist(),
                "source_note": note, "chart_key": spec.key, "value_format": "0.0%" if spec.unit.startswith("%") else "#,##0.0",
                "value_scale": .01 if spec.unit.startswith("%") else 1.0,
                "preservar_lacunas": True, "periodo": period})
            figures.append(figure)
        coverage.append({"Seção": f"Mercado Imobiliário · {section} · {spec.title}", "Situação": "Incluída" if not selected.empty else "Sem dados",
                         "Gráficos": int(not selected.empty), "De": selected["data"].min().strftime("%m/%Y") if not selected.empty else "N/D",
                         "Até": selected["data"].max().strftime("%m/%Y") if not selected.empty else "N/D", "erro": "",
                         "ultima_disponivel": latest.strftime("%Y-%m") if pd.notna(latest) else None})
    return figures, coverage
