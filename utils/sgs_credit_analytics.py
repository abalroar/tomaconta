"""Transformações e figuras do módulo Mercado de Crédito SGS.

Este módulo é o único lugar que decide como um gráfico da seção
"Estatísticas Crédito BC" se pinta: paleta, espessura de linha, tamanho e cor
de rótulo, geometria da área de plotagem e régua do eixo temporal. As abas
apenas montam os dados e pedem a figura.

Três regras de leitura que o módulo garante:

* **Cor identifica no máximo cinco séries.** Da sexta em diante a cor repete
  com traço tracejado, que é um canal independente da cor. Toda cor de linha
  tem no mínimo 3:1 de contraste sobre o papel branco e ΔE >= 27 das outras,
  então nenhuma dupla é confundível.
* **Rótulo de dado tem um tamanho só e nunca deita.** A biblioteca não recebe
  permissão para encolher nem girar texto para caber: fatia que não couber com
  o rótulo em ``TAMANHO_ROTULO_PX`` simplesmente não recebe rótulo, e o valor
  continua no tooltip.
* **Rótulo sempre legível.** Dentro da barra, a cor do texto é preto ou branco
  declarado por cor de preenchimento, nunca a escolha automática da biblioteca
  nem a cor da própria série.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .sgs_credit_registry import SGS_SERIES, get_series


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
# Família fechada: laranja-vivo, laranja claro, laranja escuro, cinzas, preto.
ITAU_ORANGE = "#EC7000"
ITAU_ORANGE_LIGHT = "#F7B267"
ITAU_ORANGE_DARK = "#A34700"
ITAU_BLACK = "#141414"
ITAU_DARK_GRAY = "#4F4F4F"
# 4,61:1 com rótulo branco. #7A7A7A, o valor anterior, caía exatamente na
# faixa em que nem preto nem branco alcançam 4,5:1 sobre ele (4,29:1 nos
# dois) — só serve como preenchimento um cinza fora dessa faixa.
ITAU_MID_GRAY = "#757575"
ITAU_LIGHT_GRAY = "#CFCFCF"

COR_GRADE = "#E6E6E6"
COR_EIXO_ZERO = "#B8B1AB"
COR_PAPEL = "#FFFFFF"
COR_TEXTO_FRACO = "#6F6F6F"

# Linhas sobre papel branco: contraste >= 3:1 no branco e ΔE >= 27,3 entre si,
# medido em CIELAB. Cinco é o teto — acima disso nenhuma paleta de uma única
# família cromática separa as cores, então a sexta série em diante repete a cor
# com traço tracejado.
PALETA_LINHA = (
    ITAU_ORANGE,        # 3,05:1 no branco
    ITAU_BLACK,         # 18,42:1
    "#8F3E00",          # 7,35:1  laranja escuro
    ITAU_DARK_GRAY,     # 8,19:1
    "#949494",          # 3,03:1
)

# Preenchimentos de barra empilhada. Aqui o texto vai DENTRO da fatia, então o
# requisito é outro: cada cor carrega a cor de rótulo que passa 4,5:1 sobre
# ela. ΔE mínimo de 27,3 entre as seis, zero pares confundíveis.
PALETA_PREENCHIMENTO = (
    ITAU_ORANGE,
    ITAU_BLACK,
    ITAU_ORANGE_LIGHT,
    ITAU_MID_GRAY,
    ITAU_ORANGE_DARK,
    ITAU_LIGHT_GRAY,
)

# Preto ou branco, o que passa 4,5:1 sobre o preenchimento. Nunca deduzido.
COR_ROTULO_SOBRE = {
    ITAU_ORANGE: ITAU_BLACK,          # 6,04:1
    ITAU_BLACK: "#FFFFFF",            # 18,42:1
    ITAU_ORANGE_LIGHT: ITAU_BLACK,    # 10,11:1
    ITAU_MID_GRAY: "#FFFFFF",         # 4,61:1
    ITAU_ORANGE_DARK: "#FFFFFF",      # 6,07:1
    ITAU_LIGHT_GRAY: ITAU_BLACK,      # 11,82:1
    "#8F3E00": "#FFFFFF",             # 7,35:1
    ITAU_DARK_GRAY: "#FFFFFF",        # 8,19:1
    "#949494": ITAU_BLACK,            # 6,24:1 (branco daria 3,03:1)
}

# Mantido para compatibilidade com o exportador, que usa a paleta como fallback
# quando um trace chega sem cor explícita.
ITAU_PALETTE = PALETA_LINHA

# Acima deste número de séries a cor repete e o tracejado entra.
MAXIMO_CORES_LINHA = len(PALETA_LINHA)

# ---------------------------------------------------------------------------
# Tipografia e geometria
# ---------------------------------------------------------------------------
# Uma régua só para a seção inteira (era 13 px em uma aba e 14 px na outra).
TAMANHO_FONTE_BASE = 13
TAMANHO_FONTE_EIXO = 12
TAMANHO_ROTULO_PX = 12
# Barra larga comporta um rótulo maior: nos cards de Concessões, com barra de
# largura total, 13 px continua cabendo e lê melhor de longe.
TAMANHO_ROTULO_BARRA_PX = 13
TAMANHO_LEGENDA = 12

# Espessura como segundo canal de hierarquia: grossa é a série em foco.
LARGURA_LINHA_FOCO = 3.0
LARGURA_LINHA_AGREGADO = 2.4
LARGURA_LINHA_CONTEXTO = 1.8

# Cards de largura total, um por linha.
ALTURA_PADRAO = 470
# Card de meia largura: dois por linha. A leitura de séries próximas melhora
# quando o gráfico não se estica pela tela inteira e a sensibilidade vertical
# se perde.
ALTURA_COMPACTA = 430
MARGEM_ESQUERDA = 64
# Card sem rótulo no fim da linha: à direita sobra só o respiro da borda. O
# valor antigo, 108, era do tempo em que a margem servia para tudo.
MARGEM_DIREITA_LEGENDA = 76
MARGEM_DIREITA_ROTULO_DIRETO = 210
MARGEM_DIREITA_ROTULO_DIRETO_COMPACTA = 168
# Com eixo secundário, a régua da direita precisa de espaço próprio: sem ele
# ela é desenhada por cima dos dados, já que autoexpand fica desligado.
LARGURA_EIXO_SECUNDARIO = 44
MARGEM_TOPO = 48
MARGEM_BASE_COM_LEGENDA = 92
MARGEM_BASE_SEM_LEGENDA = 56

# Altura ocupada por um rótulo de fim de linha, com folga.
ALTURA_ROTULO_PX = 16.0
FOLGA_ROTULO_PX = 3.0

MESES_ABREV_PT = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)


# Orçamento de caracteres para o nome da série no rótulo de meia largura.
LIMITE_NOME_COMPACTO = 22


def encurtar_rotulo(nome: str, limite: int = LIMITE_NOME_COMPACTO) -> str:
    """Corta o nome no limite de palavras que cabe no card de meia largura.

    O nome completo continua no tooltip; o rótulo só precisa ser suficiente
    para dizer qual linha é qual entre as do próprio card.
    """
    texto = str(nome).strip()
    if len(texto) <= limite:
        return texto
    palavras = texto.split()
    curto = ""
    for palavra in palavras:
        candidato = f"{curto} {palavra}".strip()
        if len(candidato) > limite:
            break
        curto = candidato
    return curto or texto[:limite].rstrip()


def cor_de_linha(posicao: int) -> str:
    """Cor da série ``posicao`` (base zero) num gráfico de linhas."""
    return PALETA_LINHA[posicao % len(PALETA_LINHA)]


def tracejado_de_linha(posicao: int) -> str | None:
    """``dash`` da série: a cor repete a partir da sexta, o traço distingue."""
    return "dash" if posicao >= MAXIMO_CORES_LINHA else None


def cor_de_preenchimento(posicao: int) -> str:
    """Cor da fatia ``posicao`` (base zero) numa barra empilhada."""
    return PALETA_PREENCHIMENTO[posicao % len(PALETA_PREENCHIMENTO)]


def cor_do_rotulo(preenchimento: str) -> str:
    """Preto ou branco sobre ``preenchimento``, declarado e não deduzido."""
    return COR_ROTULO_SOBRE.get(preenchimento, ITAU_BLACK)


def normalized_long(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"data", "serie", "valor"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Colunas ausentes: {', '.join(sorted(missing))}")
    result = frame.copy()
    result["data"] = pd.to_datetime(result["data"], errors="coerce")
    result["valor"] = pd.to_numeric(result["valor"], errors="coerce")
    return (
        result.dropna(subset=["data", "serie", "valor"])
        .drop_duplicates(["data", "serie"], keep="last")
        .sort_values(["data", "serie"])
        .reset_index(drop=True)
    )


def to_wide(frame: pd.DataFrame, aliases: Sequence[str] | None = None) -> pd.DataFrame:
    long = normalized_long(frame)
    if aliases is not None:
        unknown = set(aliases).difference(SGS_SERIES)
        if unknown:
            raise KeyError(f"Séries fora do registry: {', '.join(sorted(unknown))}")
        long = long[long["serie"].isin(aliases)]
    if long.empty:
        return pd.DataFrame()
    return long.pivot(index="data", columns="serie", values="valor").sort_index()


def build_ipca_index(ipca_monthly_pct: pd.Series, base: float = 100.0) -> pd.Series:
    """Constrói o índice encadeado usado para deflacionar os estoques."""
    inflation = pd.to_numeric(ipca_monthly_pct, errors="coerce")
    valid = inflation.dropna()
    result = pd.Series(index=inflation.index, dtype="float64", name="ipca_index")
    if valid.empty:
        return result
    result.loc[valid.index] = base * (1.0 + valid / 100.0).cumprod()
    return result


def real_yoy(nominal: pd.Series, ipca_index: pd.Series) -> pd.Series:
    """Variação real em 12 meses: (X/IPCA)/(X[-12]/IPCA[-12]) - 1."""
    aligned = pd.concat(
        [pd.to_numeric(nominal, errors="coerce"), pd.to_numeric(ipca_index, errors="coerce")],
        axis=1,
    )
    aligned.columns = ["nominal", "deflator"]
    real_level = aligned["nominal"] / aligned["deflator"]
    return (real_level / real_level.shift(12) - 1.0) * 100.0


def yoy_pp(values: pd.Series) -> pd.Series:
    """Diferença em pontos percentuais contra o mesmo mês do ano anterior."""
    return pd.to_numeric(values, errors="coerce").diff(12)


def sum_columns(wide: pd.DataFrame, aliases: Sequence[str], *, min_count: int | None = None) -> pd.Series:
    missing = set(aliases).difference(wide.columns)
    if missing:
        return pd.Series(index=wide.index, dtype="float64")
    required_count = len(aliases) if min_count is None else min_count
    return wide[list(aliases)].sum(axis=1, min_count=required_count)


def shares(wide: pd.DataFrame, aliases: Sequence[str], total: pd.Series | None = None) -> pd.DataFrame:
    available = [alias for alias in aliases if alias in wide.columns]
    if not available:
        return pd.DataFrame(index=wide.index)
    values = wide[available]
    denominator = total if total is not None else values.sum(axis=1, min_count=len(available))
    denominator = pd.to_numeric(denominator, errors="coerce").replace(0, np.nan)
    return values.div(denominator, axis=0) * 100.0


def derive_credit_totals(wide: pd.DataFrame) -> pd.DataFrame:
    result = wide.copy()
    component_aliases = [
        "saldo_livre_pj", "saldo_livre_pf", "saldo_direcionado_pj", "saldo_direcionado_pf"
    ]
    result["saldo_sfn_total_derivado"] = sum_columns(result, component_aliases)
    result["saldo_pj_total_derivado"] = sum_columns(
        result, ["saldo_livre_pj", "saldo_direcionado_pj"]
    )
    result["saldo_pf_total_derivado"] = sum_columns(
        result, ["saldo_livre_pf", "saldo_direcionado_pf"]
    )
    return result


def coverage_ratio(provision_pct: pd.Series, delinquency_pct: pd.Series) -> pd.Series:
    delinquency = pd.to_numeric(delinquency_pct, errors="coerce").replace(0, np.nan)
    return pd.to_numeric(provision_pct, errors="coerce") / delinquency * 100.0


def ultima_competencia(values: pd.Series) -> pd.Timestamp | None:
    """Última data com valor efetivo — a competência real daquela série."""
    valid = pd.to_numeric(values, errors="coerce").dropna()
    if valid.empty:
        return None
    return pd.Timestamp(valid.index[-1])


def formatar_numero(valor: float, casas: int = 1, sufixo: str = "") -> str:
    """Número no padrão brasileiro: ponto separa milhar, vírgula separa decimal."""
    texto = f"{float(valor):,.{casas}f}"
    # Troca os dois separadores de uma vez, sem passar por um estado ambíguo.
    texto = texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{texto}{sufixo}"


def _last_text(values: pd.Series, decimals: int = 1, suffix: str = "") -> list[str | None]:
    text: list[str | None] = [None] * len(values)
    valid_positions = np.flatnonzero(values.notna().to_numpy())
    if len(valid_positions):
        value = float(values.iloc[valid_positions[-1]])
        text[valid_positions[-1]] = formatar_numero(value, decimals, suffix)
    return text


def _all_text(values: pd.Series, decimals: int = 1, suffix: str = "") -> list[str | None]:
    """Rótulo em todo período com dado.

    Só vale a pena onde a barra é larga: a trava de tamanho uniforme continua
    valendo, então o período que não comportar o rótulo fica sem ele em vez de
    receber um texto encolhido.
    """
    return [
        None if pd.isna(valor) else formatar_numero(valor, decimals, suffix)
        for valor in values
    ]


def _meia_categoria(datas: Sequence[pd.Timestamp]) -> pd.Timedelta:
    """Metade do intervalo típico entre observações — meia largura de barra."""
    if len(datas) < 2:
        return pd.Timedelta(days=15)
    ordenadas = pd.DatetimeIndex(sorted(set(datas)))
    if len(ordenadas) < 2:
        return pd.Timedelta(days=15)
    return pd.to_timedelta(pd.Series(ordenadas).diff().dropna().median()) / 2


def _source_aliases(wide: pd.DataFrame, aliases: Sequence[str]) -> list[str]:
    """Resolve as séries SGS de origem para a ficha de informação do gráfico."""
    candidates = [*wide.attrs.get("source_aliases", []), *aliases]
    return list(dict.fromkeys(alias for alias in candidates if alias in SGS_SERIES))


# ---------------------------------------------------------------------------
# Geometria da área de plotagem
# ---------------------------------------------------------------------------
def _altura_area_plotagem(fig: go.Figure) -> float:
    """Altura real, em pixels, da área onde os dados são desenhados.

    As margens são explícitas e ``autoexpand`` fica desligado justamente para
    que esta conta seja exata. A versão anterior assumia 285 px fixos enquanto
    a área real era 323 px, e era essa diferença que empilhava dois rótulos no
    mesmo pixel.
    """
    altura = float(fig.layout.height or ALTURA_PADRAO)
    margem = fig.layout.margin
    topo = float(margem.t) if margem.t is not None else MARGEM_TOPO
    base = float(margem.b) if margem.b is not None else MARGEM_BASE_COM_LEGENDA
    return max(altura - topo - base, 1.0)


def _valores_do_eixo(fig: go.Figure, yref: str) -> list[float]:
    valores: list[float] = []
    for trace in fig.data:
        if (getattr(trace, "yaxis", None) or "y") != yref:
            continue
        if getattr(trace, "y", None) is None:
            continue
        numeric = pd.to_numeric(pd.Series(trace.y), errors="coerce").dropna()
        valores.extend(float(valor) for valor in numeric)
    return valores


def _passo_redondo(bruto: float) -> float:
    """Degrau de grade em número redondo, logo acima de ``bruto``."""
    if not np.isfinite(bruto) or bruto <= 0:
        return 1.0
    expoente = 10 ** np.floor(np.log10(bruto))
    for multiplo in (1, 2, 2.5, 5, 10):
        if bruto <= multiplo * expoente:
            return float(multiplo * expoente)
    return float(10 * expoente)


# Fração da altura que o dado precisa ocupar para o zero valer a pena. Abaixo
# dela o eixo enquadra o dado.
OCUPACAO_MINIMA_COM_ZERO = 0.5
# Folga acima e abaixo do dado quando o eixo o enquadra, em fração da amplitude.
FOLGA_ENQUADRAMENTO = 0.08


def escala_de_eixo(
    valores: Sequence[float], *, ancorar_zero: bool | None = None
) -> tuple[float, float]:
    """Piso e teto do eixo, em degraus redondos, recalculados a cada leitura.

    O zero entra em três situações: a série o cruza, o dado ocupa ao menos
    metade da altura com ele dentro, ou quem chama declara que ele é a
    referência — barra, que codifica o valor no comprimento, e eixo secundário
    ancorado de propósito. Fora disso o eixo enquadra o dado: uma inadimplência
    entre 3,6% e 5,8% desenhada de 0 a 6 vira uma linha quase reta no alto de
    um gráfico vazio, e o movimento — que é o que a página mostra — some.

    Como a conta parte dos próprios valores, o eixo acompanha o dado: quando a
    série anda, o piso e o teto andam junto, sem número fixo no código.
    """
    finitos = [
        float(valor) for valor in valores
        if valor is not None and np.isfinite(float(valor))
    ]
    if not finitos:
        return (0.0, 1.0)
    menor, maior = min(finitos), max(finitos)
    if maior == menor:
        maior = menor + (abs(menor) or 1.0) * 0.1
    if ancorar_zero is None:
        if menor <= 0 <= maior:
            ancorar_zero = True
        else:
            # Distância do dado até o zero, medida pela ponta mais próxima.
            distancia = min(abs(menor), abs(maior))
            ocupacao = (maior - menor) / (distancia + maior - menor)
            ancorar_zero = ocupacao >= OCUPACAO_MINIMA_COM_ZERO
    if ancorar_zero:
        menor, maior = min(menor, 0.0), max(maior, 0.0)
    else:
        folga = (maior - menor) * FOLGA_ENQUADRAMENTO
        menor, maior = menor - folga, maior + folga
    passo = _passo_redondo((maior - menor) / 7)
    piso = float(np.floor(menor / passo) * passo)
    teto = float(np.ceil(maior / passo) * passo)
    if teto <= piso:
        teto = piso + passo
    return (round(piso, 10), round(teto, 10))


def _faixa_do_eixo(
    fig: go.Figure, yref: str, *, base_zero: bool = False
) -> tuple[float, float]:
    """Faixa explícita do eixo, para que pixel por unidade seja conhecido."""
    valores = _valores_do_eixo(fig, yref)
    if not valores:
        return (0.0, 1.0)
    return escala_de_eixo(valores, ancorar_zero=True if base_zero else None)


def _espalhar_em_pixels(
    alvos: Sequence[float], intervalo: float, limite: float
) -> list[float]:
    """Separa posições verticais em pixels sem perder a ordem das séries.

    Toda a conta acontece em pixels de tela — nunca misturando régua de dado
    com régua de pixel, que era a origem da sobreposição.
    """
    total = len(alvos)
    if total == 0:
        return []
    if total == 1:
        return [float(alvos[0])]

    ordem = sorted(range(total), key=lambda indice: alvos[indice])
    posicoes = [float(valor) for valor in alvos]
    for anterior, atual in zip(ordem, ordem[1:]):
        posicoes[atual] = max(float(alvos[atual]), posicoes[anterior] + intervalo)

    deslocamento = (sum(posicoes) / total) - (sum(alvos) / total)
    posicoes = [posicao - deslocamento for posicao in posicoes]

    espaco_util = limite - intervalo
    altura_ocupada = posicoes[ordem[-1]] - posicoes[ordem[0]]
    if altura_ocupada > espaco_util:
        # Não cabe nem com o intervalo mínimo: distribui por igual, o que ainda
        # preserva a ordem e mantém a maior distância possível entre rótulos.
        passo = espaco_util / (total - 1)
        for posicao_na_ordem, indice in enumerate(ordem):
            posicoes[indice] = intervalo / 2 + posicao_na_ordem * passo
        return posicoes

    topo = posicoes[ordem[0]]
    if topo < intervalo / 2:
        ajuste = intervalo / 2 - topo
        posicoes = [posicao + ajuste for posicao in posicoes]
    fundo = posicoes[ordem[-1]]
    if fundo > limite - intervalo / 2:
        ajuste = fundo - (limite - intervalo / 2)
        posicoes = [posicao - ajuste for posicao in posicoes]
    return posicoes


# Combo volume + prazo: as barras ficam na metade de baixo e a linha na parte
# de cima, as duas ancoradas em zero. Ancorar o prazo em zero é o que dá
# sensibilidade proporcional — um prazo que varia 1 mês em 47 (Veículos) fica
# visualmente plano e um que varia 11 meses em 27 (PJ livre) fica visível. Com
# escala automática, os dois preenchiam a altura inteira do card por igual.
FOLGA_EIXO_BARRA = 1.85
FOLGA_EIXO_LINHA = 1.15


# Largura média de um caractere do rótulo, em pixels, no corpo padrão. Serve
# para dimensionar a faixa da direita — e não para desenhar nada.
LARGURA_CARACTERE_PX = 6.6
# Piso da margem direita: o gráfico nunca encosta na borda do card.
MARGEM_DIREITA_MINIMA = 24


def _ajustar_margem_direita(fig: go.Figure, achatados, recuo: int) -> None:
    """Encolhe a margem da direita até o tamanho do maior rótulo de fim.

    A margem era fixa e dimensionada para o pior caso. Num card cujo rótulo é
    "29,3" ela reservava mais de cem pixels de papel em branco, e o desenho
    parava bem antes da borda do card. Só encolhe: quem precisa de mais que o
    padrão continua com o padrão.
    """
    maior = max(
        (
            len(linha)
            for (ponto, _) in achatados
            for linha in str(ponto[2]).split("<br>")
        ),
        default=0,
    )
    if not maior:
        return
    margem = fig.layout.margin
    atual = float(margem.r) if margem.r is not None else MARGEM_DIREITA_LEGENDA
    necessario = recuo + maior * LARGURA_CARACTERE_PX + 12
    fig.update_layout(margin_r=max(MARGEM_DIREITA_MINIMA, min(atual, necessario)))


def posicionar_rotulos_finais(
    fig: go.Figure,
    grupos: Sequence[tuple[Sequence[tuple[pd.Timestamp, float, str, str]], str, tuple[float, float] | None]],
) -> None:
    """Rótulos de fim de linha de todos os eixos, espalhados em uma só passada.

    Um gráfico com eixo secundário tem dois conjuntos de rótulos sobre a mesma
    área. Espalhar cada conjunto por si deixava o rótulo do eixo da direita em
    cima dos da esquerda, porque nenhum dos dois enxergava o outro.
    """
    grupos = [(list(pontos), yref, faixa) for pontos, yref, faixa in grupos if pontos]
    if not grupos:
        return
    altura_area = _altura_area_plotagem(fig)

    escalas: dict[str, tuple[float, float]] = {}
    for pontos, yref, faixa in grupos:
        menor, maior = faixa or _faixa_do_eixo(fig, yref)
        if maior - menor <= 0:
            return
        eixo = "yaxis" if yref == "y" else f"yaxis{yref[1:]}"
        fig.update_layout({eixo: {"range": [menor, maior], "autorange": False}})
        escalas[yref] = (menor, maior)

    def tela(valor: float, yref: str) -> float:
        menor, maior = escalas[yref]
        return (maior - float(valor)) * altura_area / (maior - menor)

    achatados = [
        (ponto, yref) for pontos, yref, _ in grupos for ponto in pontos
    ]
    recuo_rotulo = LARGURA_EIXO_SECUNDARIO + 6 if "y2" in escalas else 34
    _ajustar_margem_direita(fig, achatados, recuo_rotulo)
    linhas_por_rotulo = max(
        (str(ponto[2]).count("<br>") + 1 for ponto, _ in achatados), default=1
    )
    alvos = [tela(ponto[1], yref) for ponto, yref in achatados]
    finais = _espalhar_em_pixels(
        alvos, ALTURA_ROTULO_PX * linhas_por_rotulo + FOLGA_ROTULO_PX, altura_area
    )

    for ((ultimo_x, bruto_y, texto, cor), yref), tela_final in zip(achatados, finais):
        fig.add_annotation(
            x=ultimo_x,
            y=bruto_y,
            xref="x",
            yref=yref,
            text=texto,
            showarrow=True,
            arrowhead=0,
            arrowwidth=1,
            arrowcolor=cor,
            ax=recuo_rotulo,
            ay=int(round(tela_final - tela(bruto_y, yref))),
            xanchor="left",
            align="left",
            font={"color": cor, "size": TAMANHO_ROTULO_PX},
            bgcolor="rgba(255,255,255,0.86)",
            borderpad=1,
        )

    datas = _valid_trace_dates(fig)
    if datas:
        folga = _meia_categoria(datas) if _tem_barra(fig) else pd.Timedelta(0)
        fig.update_xaxes(
            range=[min(datas) - folga, max(datas) + max(folga, pd.Timedelta(days=30))]
        )


def _add_last_line_labels(
    fig: go.Figure,
    endpoints: Sequence[tuple[pd.Timestamp, float, str, str]],
    *,
    yref: str = "y",
    base_zero: bool = False,
    plot_height: float | None = None,
    faixa: tuple[float, float] | None = None,
) -> None:
    """Rótulos coloridos no fim de cada linha, sem sobreposição.

    ``plot_height`` existe apenas para chamadas antigas; quando não vem, a
    altura é lida da própria figura, que é o comportamento correto.
    """
    if not endpoints:
        return

    altura_area = float(plot_height) if plot_height else _altura_area_plotagem(fig)
    menor, maior = faixa or _faixa_do_eixo(fig, yref, base_zero=base_zero)
    eixo = "yaxis" if yref == "y" else f"yaxis{yref[1:]}"
    fig.update_layout({eixo: {"range": [menor, maior], "autorange": False}})

    amplitude = maior - menor
    if amplitude <= 0:
        return
    pixels_por_unidade = altura_area / amplitude

    def tela(valor: float) -> float:
        return (maior - float(valor)) * pixels_por_unidade

    # Rótulo de duas linhas ocupa o dobro da altura; o espaçamento mínimo
    # acompanha, senão o nome de uma série encosta no valor da vizinha.
    linhas_por_rotulo = max(
        (str(ponto[2]).count("<br>") + 1 for ponto in endpoints), default=1
    )
    alvos = [tela(ponto[1]) for ponto in endpoints]
    finais = _espalhar_em_pixels(
        alvos,
        ALTURA_ROTULO_PX * linhas_por_rotulo + FOLGA_ROTULO_PX,
        altura_area,
    )
    recuo_rotulo = LARGURA_EIXO_SECUNDARIO + 6 if yref == "y2" else 34
    _ajustar_margem_direita(fig, [(ponto, yref) for ponto in endpoints], recuo_rotulo)

    for (ultimo_x, bruto_y, texto, cor), tela_final in zip(endpoints, finais):
        fig.add_annotation(
            x=ultimo_x,
            y=bruto_y,
            xref="x",
            yref=yref,
            text=texto,
            showarrow=True,
            arrowhead=0,
            arrowwidth=1,
            arrowcolor=cor,
            ax=recuo_rotulo,
            ay=int(round(tela_final - tela(bruto_y))),
            xanchor="left",
            align="left",
            font={"color": cor, "size": TAMANHO_ROTULO_PX},
            bgcolor="rgba(255,255,255,0.86)",
            borderpad=1,
        )

    datas = _valid_trace_dates(fig)
    if datas:
        # Meia categoria de folga de cada lado. Sem ela, a faixa começava
        # exatamente no centro da primeira barra e o Plotly desenhava só a
        # metade direita dela — o gráfico "consertava" sozinho ao dar duplo
        # clique porque isso restaura o autorange.
        folga = _meia_categoria(datas) if _tem_barra(fig) else pd.Timedelta(0)
        fig.update_xaxes(
            range=[
                min(datas) - folga,
                max(datas) + max(folga, pd.Timedelta(days=30)),
            ]
        )


def formatar_competencia(value: object) -> str:
    """Formata uma data mensal como ``Jan/26``."""
    data = pd.Timestamp(value)
    return f"{MESES_ABREV_PT[data.month - 1]}/{str(data.year)[-2:]}"


def passo_eixo_mensal(total_meses: int) -> int:
    """Escolhe um intervalo legível para os rótulos do eixo mensal."""
    if total_meses <= 14:
        return 1
    if total_meses <= 26:
        return 2
    if total_meses <= 42:
        return 3
    if total_meses <= 84:
        return 6
    return 12


def eixo_datas_adaptativo(index: Sequence[object]) -> tuple[list[pd.Timestamp], list[str]]:
    """Marca meses em passo adaptativo e sempre inclui a última observação."""
    datas = pd.DatetimeIndex(pd.to_datetime(list(index), errors="coerce")).dropna()
    if datas.empty:
        return [], []
    tabela = pd.DataFrame({"data": datas})
    tabela["mes"] = tabela["data"].dt.to_period("M")
    # Algumas fontes têm dias de fechamento diferentes entre instituições.
    # Uma única marca por competência evita repetir, por exemplo, ``dez.25``.
    por_mes = tabela.groupby("mes", observed=True)["data"].max().sort_index()
    meses = list(por_mes.index)
    passo = passo_eixo_mensal(len(meses))
    meses_selecionados = meses[::passo]
    ultimo_mes = meses[-1]
    if meses_selecionados[-1] != ultimo_mes:
        meses_selecionados.append(ultimo_mes)
    selecionadas = [pd.Timestamp(por_mes.loc[mes]) for mes in meses_selecionados]
    rotulos = [formatar_competencia(data) for data in selecionadas]
    return selecionadas, rotulos


def eixo_datas_semestral(index: Sequence[object]) -> tuple[list[pd.Timestamp], list[str]]:
    """Compatibilidade: usa a nova régua adaptativa."""
    return eixo_datas_adaptativo(index)


def _tem_barra(fig: go.Figure) -> bool:
    return any(str(getattr(trace, "type", "")) == "bar" for trace in fig.data)


def _valid_trace_dates(fig: go.Figure) -> list[pd.Timestamp]:
    """Datas que têm valor efetivamente desenhado em ao menos um trace.

    Nem todo gráfico da seção tem tempo no eixo X: o de participação por UF
    tem siglas. O que não converte para data é ignorado, e a figura recebe a
    régua automática do eixo.
    """
    datas: list[pd.Timestamp] = []
    for trace in fig.data:
        trace_x = getattr(trace, "x", None)
        trace_y = getattr(trace, "y", None)
        if trace_x is None or trace_y is None:
            continue
        with warnings.catch_warnings():
            # Eixo de siglas cai inteiro em NaT; o aviso de formato não
            # acrescenta nada e polui o log a cada render.
            warnings.simplefilter("ignore", UserWarning)
            convertidas = pd.to_datetime(pd.Series(list(trace_x)), errors="coerce")
        for data, value_y in zip(convertidas, trace_y):
            numero = pd.to_numeric(value_y, errors="coerce")
            if pd.notna(data) and pd.notna(numero):
                datas.append(pd.Timestamp(data))
    return datas


def aplicar_estilo(
    fig: go.Figure,
    *,
    title: str,
    y_title: str,
    height: int = ALTURA_PADRAO,
    legenda: bool = True,
    rotulo_direto: bool = False,
    compacto: bool = False,
    tamanho_rotulo: int = TAMANHO_ROTULO_PX,
    eixo_secundario: bool = False,
) -> go.Figure:
    """Estilo único de toda a seção: tipografia, grade, margens e régua do eixo.

    Antes existiam duas funções concorrentes — uma para os cards do SGS e outra
    para os do SCR — com fontes, margens e posição de legenda diferentes. Esta
    é a única.
    """
    meta = dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}
    meta["chart_title"] = str(title)

    if rotulo_direto:
        margem_direita = (
            MARGEM_DIREITA_ROTULO_DIRETO_COMPACTA if compacto
            else MARGEM_DIREITA_ROTULO_DIRETO
        )
    else:
        margem_direita = MARGEM_DIREITA_LEGENDA
    if eixo_secundario:
        margem_direita += LARGURA_EIXO_SECUNDARIO
    margem_base = MARGEM_BASE_COM_LEGENDA if legenda else MARGEM_BASE_SEM_LEGENDA

    fig.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        height=height,
        # autoexpand desligado de propósito: com ele a biblioteca cresce as
        # margens por conta própria e a altura real da área de plotagem deixa
        # de ser conhecida, que é o que a conta dos rótulos precisa saber.
        margin={
            "l": MARGEM_ESQUERDA,
            "r": margem_direita,
            "t": MARGEM_TOPO,
            "b": margem_base,
            "autoexpand": False,
        },
        paper_bgcolor=COR_PAPEL,
        plot_bgcolor=COR_PAPEL,
        hovermode="x unified",
        showlegend=legenda,
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.14,
            "x": 0,
            "font": {"size": TAMANHO_LEGENDA},
        },
        font={"family": "Arial", "color": ITAU_BLACK, "size": TAMANHO_FONTE_BASE},
        yaxis_title=y_title,
        # Trava de tamanho de texto: rótulo que não couber em 12 px é escondido
        # em vez de encolhido. Sem isto a biblioteca desenhava o mesmo rótulo
        # entre 0,2 px e 14 px na mesma barra.
        uniformtext={"mode": "hide", "minsize": tamanho_rotulo},
        separators=",.",
        meta=meta,
    )

    datas = _valid_trace_dates(fig)
    tickvals, ticktext = eixo_datas_adaptativo(datas)
    tickangle = (
        -35
        if any(
            (right - left).days <= 45
            for left, right in zip(tickvals, tickvals[1:])
        )
        else 0
    )
    fig.update_xaxes(
        showgrid=False,
        tickmode="array" if tickvals else "auto",
        tickvals=tickvals or None,
        ticktext=ticktext or None,
        tickangle=tickangle,
        tickfont={"size": TAMANHO_FONTE_EIXO},
    )
    fig.update_yaxes(
        gridcolor=COR_GRADE,
        zerolinecolor=COR_EIXO_ZERO,
        tickfont={"size": TAMANHO_FONTE_EIXO},
        # Com separators=",." acima, o agrupamento do d3 vira ponto de milhar e
        # vírgula decimal: 7372 sai como 7.372.
        tickformat=",",
    )
    return fig


# Nome antigo, mantido porque outras abas importam.
_base_layout = aplicar_estilo


def line_figure(
    wide: pd.DataFrame,
    aliases: Sequence[str],
    *,
    title: str,
    y_title: str,
    labels: Mapping[str, str] | None = None,
    decimals: int = 1,
    suffix: str = "",
    destaques: Sequence[str] | None = None,
    height: int | None = None,
    compacto: bool = False,
    secundarios: Sequence[str] | None = None,
    y_title_secundario: str = "",
) -> go.Figure:
    """Gráfico de linhas com hierarquia de espessura e rótulo no fim da linha.

    ``destaques`` marca as séries que recebem a espessura de foco. Sem ele,
    séries com "total"/"derivado" no alias entram como agregado tracejado e o
    resto fica na espessura de contexto.
    """
    presentes = [alias for alias in aliases if alias in wide.columns]
    # Acima de cinco séries a legenda separada obriga o olho a ir e voltar
    # comparando cores parecidas; o nome vai para a ponta da linha. Em card de
    # meia largura vale a partir da terceira, porque a legenda horizontal já
    # quebra em duas linhas.
    limite_rotulo_direto = 2 if compacto else MAXIMO_CORES_LINHA
    rotulo_direto = len(presentes) > limite_rotulo_direto
    if height is None:
        height = ALTURA_COMPACTA if compacto else ALTURA_PADRAO
    marcados = set(destaques or ())

    # Séries de outra ordem de grandeza vão para o eixo da direita. Sem isso,
    # endividamento a 49,8% da renda achata comprometimento e serviço da dívida,
    # que rodam entre 5% e 29%, na base do gráfico.
    no_secundario = {alias for alias in (secundarios or ()) if alias in presentes}
    if no_secundario:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
    else:
        fig = go.Figure()
    endpoints: list[tuple[pd.Timestamp, float, str, str]] = []
    endpoints_secundario: list[tuple[pd.Timestamp, float, str, str]] = []
    for index, alias in enumerate(presentes):
        values = pd.to_numeric(wide[alias], errors="coerce")
        label = (labels or {}).get(alias) or (
            get_series(alias).label if alias in SGS_SERIES else alias
        )
        color = cor_de_linha(index)
        dash = tracejado_de_linha(index)
        agregado = ("total" in alias) or ("derivado" in alias)
        if alias in marcados:
            width = LARGURA_LINHA_FOCO
        elif agregado:
            width = LARGURA_LINHA_AGREGADO
            dash = dash or "dash"
        elif not marcados and index == 0:
            width = LARGURA_LINHA_FOCO
        else:
            width = LARGURA_LINHA_CONTEXTO
        secundario = alias in no_secundario
        traco = go.Scatter(
            x=wide.index,
            y=values,
            name=f"{label} (dir.)" if secundario else label,
            mode="lines",
            cliponaxis=False,
            connectgaps=False,
            line={"color": color, "width": width, "dash": dash or "solid"},
            meta={
                "series_alias": alias,
                "eixo": "secundario" if secundario else "primario",
                "rotulo_limpo": label,
            },
            hovertemplate="%{y:.2f}" + (suffix or "") + "<extra>%{fullData.name}</extra>",
        )
        if no_secundario:
            fig.add_trace(traco, secondary_y=secundario)
        else:
            fig.add_trace(traco)
        valid = values.dropna()
        if not valid.empty:
            value = float(valid.iloc[-1])
            numero = formatar_numero(value, decimals, suffix)
            if not rotulo_direto:
                texto = numero
            elif compacto:
                # Meia largura não comporta nome e valor na mesma linha sem
                # cortar o nome no meio: eles empilham.
                texto = f"{encurtar_rotulo(label)}<br>{numero}"
            else:
                texto = f"{label}  {numero}"
            destino = endpoints_secundario if secundario else endpoints
            destino.append((pd.Timestamp(valid.index[-1]), value, texto, color))

    fig.update_layout(meta={"source_aliases": _source_aliases(wide, aliases)})
    aplicar_estilo(
        fig,
        title=title,
        y_title=y_title,
        height=height,
        legenda=not rotulo_direto,
        rotulo_direto=rotulo_direto,
        compacto=compacto,
        eixo_secundario=bool(no_secundario),
    )
    faixa_secundaria = None
    if no_secundario:
        topo = max(
            float(pd.to_numeric(wide[alias], errors="coerce").max())
            for alias in no_secundario
        )
        if topo > 0:
            # Mesma regra do combo volume + prazo: eixo secundário ancorado em
            # zero. O leitor vê o nível pela altura da linha na escala e a
            # variação pelo tamanho do movimento, os dois proporcionais.
            faixa_secundaria = (0.0, topo * FOLGA_EIXO_LINHA)
        fig.update_yaxes(title_text=y_title, secondary_y=False)
        cor_secundaria = next(
            (
                cor_de_linha(posicao)
                for posicao, alias in enumerate(presentes)
                if alias in no_secundario
            ),
            ITAU_BLACK,
        )
        fig.update_yaxes(
            # Em meia largura o título do eixo da direita não cabe ao lado dos
            # próprios números. O "(dir.)" no nome da série faz esse trabalho.
            title_text="" if compacto else (y_title_secundario or y_title),
            secondary_y=True,
            showgrid=False,
            range=list(faixa_secundaria) if faixa_secundaria else None,
            # Régua na cor da série que ela mede, como nos cards de volume e prazo.
            color=cor_secundaria,
            tickfont={"color": cor_secundaria, "size": TAMANHO_FONTE_EIXO},
        )
        fig.update_layout(meta={
            **(fig.layout.meta if isinstance(fig.layout.meta, dict) else {}),
            "titulo_eixo_primario": y_title,
            "titulo_eixo_secundario": y_title_secundario or y_title,
            "tipo_grafico": "line",
        })
    # Depois do estilo: a conta dos rótulos precisa da geometria já definida.
    posicionar_rotulos_finais(
        fig,
        [
            (endpoints, "y", None),
            (endpoints_secundario, "y2", faixa_secundaria),
        ],
    )
    return fig


def stacked_figure(
    wide: pd.DataFrame,
    aliases: Sequence[str],
    *,
    title: str,
    y_title: str,
    labels: Mapping[str, str] | None = None,
    scale: float = 1.0,
    total: pd.Series | None = None,
    percent: bool = False,
    height: int = ALTURA_PADRAO,
    rotular_todos: bool = True,
    tamanho_rotulo: int = TAMANHO_ROTULO_PX,
) -> go.Figure:
    """Barras empilhadas com rótulo de tamanho único e contraste garantido.

    O rótulo entra em todo período por padrão. A trava de tamanho uniforme
    continua valendo, então a fatia que não comportar o rótulo em
    ``tamanho_rotulo`` fica sem ele, e o valor segue no tooltip.
    """
    rotulos = _all_text if rotular_todos else _last_text
    fig = go.Figure()
    presentes = [alias for alias in aliases if alias in wide.columns]
    for index, alias in enumerate(presentes):
        values = pd.to_numeric(wide[alias], errors="coerce") * scale
        label = (labels or {}).get(alias) or (
            get_series(alias).label if alias in SGS_SERIES else alias
        )
        preenchimento = cor_de_preenchimento(index)
        fig.add_trace(
            go.Bar(
                x=wide.index,
                y=values,
                name=label,
                marker_color=preenchimento,
                text=rotulos(values, 1, "%" if percent else ""),
                textposition="inside",
                # Horizontal sempre. Girar o texto para caber é o que produzia
                # um rótulo deitado ao lado de nove em pé na mesma barra.
                textangle=0,
                insidetextanchor="middle",
                insidetextfont={
                    "size": tamanho_rotulo,
                    "color": cor_do_rotulo(preenchimento),
                    "family": "Arial",
                },
                textfont={"size": tamanho_rotulo, "family": "Arial"},
                constraintext="inside",
                meta={"series_alias": alias},
                hovertemplate="%{y:.1f}" + ("%" if percent else "")
                + "<extra>%{fullData.name}</extra>",
            )
        )

    fig.update_layout(barmode="stack")
    total_alias = getattr(total, "name", None) if total is not None else None
    source_candidates = [*aliases, *([total_alias] if total_alias else [])]
    fig.update_layout(meta={"source_aliases": _source_aliases(wide, source_candidates)})
    aplicar_estilo(
        fig, title=title, y_title=y_title, height=height, legenda=True,
        tamanho_rotulo=tamanho_rotulo,
    )

    if total is not None:
        # Anotação, não série. Como série invisível de texto, o total fazia o
        # exportador ler "barra + ponto" e trocar o empilhado por linhas.
        total_values = pd.to_numeric(total, errors="coerce") * scale
        valid = total_values.dropna()
        if not valid.empty:
            valor = float(valid.iloc[-1])
            fig.add_annotation(
                x=pd.Timestamp(valid.index[-1]),
                y=valor,
                text=formatar_numero(valor, 1, "%" if percent else ""),
                showarrow=False,
                yshift=11,
                xanchor="center",
                font={
                    "size": tamanho_rotulo,
                    "color": ITAU_BLACK,
                    "family": "Arial",
                },
                bgcolor="rgba(255,255,255,0.86)",
                borderpad=1,
            )
            # Folga só para o rótulo do total caber acima da barra mais alta.
            fig.update_yaxes(range=[0, max(valor, float(valid.max())) * 1.08])
    return fig


def bar_line_figure(
    wide: pd.DataFrame,
    *,
    bar_alias: str,
    line_alias: str,
    title: str,
    bar_title: str = "R$ bi",
    line_title: str = "meses",
    height: int = ALTURA_PADRAO,
    rotular_todos: bool = True,
    tamanho_rotulo: int = TAMANHO_ROTULO_BARRA_PX,
) -> go.Figure:
    """Volume em coluna no eixo esquerdo, prazo em linha no eixo direito.

    O eixo direito, a linha e o nome dela na legenda saem em laranja: é o que
    diz ao leitor, sem precisar de nota, que "meses" se lê à direita.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    rotulos = _all_text if rotular_todos else _last_text
    if bar_alias in wide.columns:
        bar = pd.to_numeric(wide[bar_alias], errors="coerce") / 1000.0
        fig.add_trace(
            go.Bar(
                x=wide.index,
                y=bar,
                name=get_series(bar_alias).label,
                marker_color=ITAU_LIGHT_GRAY,
                text=rotulos(bar, 1),
                textposition="outside",
                textangle=0,
                textfont={
                    "size": tamanho_rotulo,
                    "color": ITAU_BLACK,
                    "family": "Arial",
                },
                cliponaxis=False,
                meta={"series_alias": bar_alias, "eixo": "primario"},
                hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
            ),
            secondary_y=False,
        )
    if line_alias in wide.columns:
        line = pd.to_numeric(wide[line_alias], errors="coerce")
        rotulo_linha = get_series(line_alias).label
        fig.add_trace(
            go.Scatter(
                x=wide.index,
                y=line,
                # O Plotly aceita HTML no nome da série: é assim que o item da
                # legenda sai na cor da linha, junto do eixo que ele mede.
                name=f"<span style='color:{ITAU_ORANGE}'>{rotulo_linha}</span>",
                mode="lines",
                line={"color": ITAU_ORANGE, "width": LARGURA_LINHA_FOCO},
                cliponaxis=False,
                connectgaps=False,
                meta={
                    "series_alias": line_alias,
                    "eixo": "secundario",
                    # O exportador usa este nome limpo: a marcação HTML só faz
                    # sentido no navegador.
                    "rotulo_limpo": rotulo_linha,
                },
                hovertemplate="%{y:.1f}<extra>" + rotulo_linha + "</extra>",
            ),
            secondary_y=True,
        )

    fig.update_layout(
        meta={
            "source_aliases": _source_aliases(wide, [bar_alias, line_alias]),
            # O exportador precisa saber que este card tem dois eixos, com
            # unidades e formatos diferentes, para não achatar os dois em um.
            "eixo_secundario": get_series(line_alias).label
            if line_alias in SGS_SERIES
            else line_alias,
            "titulo_eixo_primario": bar_title,
            "titulo_eixo_secundario": line_title,
            "formato_primario": "0.0",
            "formato_secundario": "0.0",
            "tipo_grafico": "column_line",
            "cor_eixo_secundario": ITAU_ORANGE,
        }
    )
    aplicar_estilo(
        fig, title=title, y_title=bar_title, height=height, legenda=True,
        tamanho_rotulo=tamanho_rotulo, eixo_secundario=True,
    )

    faixa_barra = None
    if bar_alias in wide.columns:
        topo_barra = pd.to_numeric(wide[bar_alias], errors="coerce").dropna().max()
        if pd.notna(topo_barra) and float(topo_barra) > 0:
            faixa_barra = (0.0, float(topo_barra) / 1000.0 * FOLGA_EIXO_BARRA)
    fig.update_yaxes(
        title_text=bar_title,
        secondary_y=False,
        range=list(faixa_barra) if faixa_barra else None,
        rangemode="tozero",
    )

    faixa_linha = None
    if line_alias in wide.columns:
        topo_linha = pd.to_numeric(wide[line_alias], errors="coerce").dropna().max()
        if pd.notna(topo_linha) and float(topo_linha) > 0:
            faixa_linha = (0.0, float(topo_linha) * FOLGA_EIXO_LINHA)
    fig.update_yaxes(
        title_text=line_title,
        secondary_y=True,
        showgrid=False,
        color=ITAU_ORANGE,
        tickfont={"color": ITAU_ORANGE, "size": TAMANHO_FONTE_EIXO},
        title_font={"color": ITAU_ORANGE},
        range=list(faixa_linha) if faixa_linha else None,
    )

    if line_alias in wide.columns:
        valid = pd.to_numeric(wide[line_alias], errors="coerce").dropna()
        if not valid.empty:
            value = float(valid.iloc[-1])
            _add_last_line_labels(
                fig,
                [(
                    pd.Timestamp(valid.index[-1]),
                    value,
                    formatar_numero(value, 1),
                    ITAU_ORANGE,
                )],
                yref="y2",
                faixa=faixa_linha,
            )
    return fig
