"""
telegram_ura.py — URA interativa do toma.conta no Telegram.

Disponibiliza via teclado inline toda a documentação de "Como Usar",
módulos, indicadores e recursos da plataforma.

Uso:
    export TELEGRAM_BOT_TOKEN="seu_token_aqui"
    python telegram_ura.py

Dependência extra:
    pip install python-telegram-bot==20.7
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

TEXTO_BOAS_VINDAS = """
*toma.conta*
_análise de instituições financeiras brasileiras_

Consolida dados oficiais do Banco Central para análise comparativa de IFs, com foco em leitura rápida, filtros reproduzíveis e exportação.

Selecione uma opção no menu abaixo:
"""

TEXTO_COMO_USAR = """
*Como Usar — toma.conta*

*1. Selecione o módulo*
Escolha com foco no objetivo:
Rankings, Peers, Evolução, Scatter, DRE, Carteira 4.966, Taxas, Conselho ou Métrica Customizada.

*2. Defina período e instituições*
Ajuste o recorte comparativo com o período e a lista de bancos desejados.

*3. Aplique filtros e aliases*
Padronize nomes e cores para manter consistência visual entre análises.

*4. Consulte o Glossário*
Valide fórmulas e conceitos antes de concluir a análise.

*5. Exporte os resultados*
Baixe em Excel/CSV para compartilhar ou incluir em relatórios.
"""

TEXTO_MODULOS_ANALISE = """
*Módulos de Análise*

📊 *Snapshot*
Painel executivo por instituição. Design mobile-first para leitura rápida dos principais indicadores.

🏆 *Rankings*
Ordene qualquer indicador entre todas as IFs em um período. Exibe variação e comparação imediata.

📋 *Peers (Tabela)*
Compare múltiplos bancos em até 3 períodos com variação anual calculada automaticamente.

👥 *Conselho e Diretoria*
Consulta de composição de conselho e diretoria por conglomerado prudencial.

📈 *Evolução*
Séries temporais para identificar aceleração, desaceleração ou estabilidade em qualquer indicador.

🔵 *Scatter Plot*
Relação entre dois indicadores, com tamanho de bolha configurável por uma terceira variável.

📄 *DRE / DRE Individual*
Demonstração do Resultado nas visões Conglomerado Prudencial e Individual.

🗂️ *Carteira 4.966*
Qualidade da carteira de crédito por classe de risco (AA–H), foco em D–H.

💹 *Taxas de Juros por Produto*
Taxas médias por modalidade de crédito (PF e PJ) e evolução temporal.

⚙️ *Crie sua métrica!*
Construtor de indicadores personalizados a partir de variáveis brutas.

🏦 *Contribuições FGC/FGCoop*
Análise de contribuições ao FGC e FGCoop por período e instituição.
"""

TEXTO_MODULOS_UTILITARIOS = """
*Utilitários da Plataforma*

ℹ️ *Sobre*
Apresentação da plataforma, módulos disponíveis e stack tecnológica.

🔄 *Atualizar Base*
Interface para atualização incremental do cache local e publicação via GitHub Releases.

📚 *Glossário*
Documentação técnica completa: fórmulas, fontes e conceitos de todas as métricas.
"""

TEXTO_INDICADORES = """
*Indicadores e Métricas Disponíveis*

*Estrutura Patrimonial*
• Ativo Total
• Ativos Líquidos
• Carteira de Crédito Classificada e Líquida
• Títulos e Valores Mobiliários
• Depósitos e Captações / Core Funding
• Patrimônio Líquido
• Lucro Líquido Acumulado (YTD)

*Capital e Prudencial*
• Capital Principal (Tier 1 / CET1)
• Capital Complementar e Capital Nível II
• Patrimônio de Referência
• RWA Total, de Crédito, de Mercado e Operacional
• Índice de Capital Principal (CET1)
• Índice de Basileia
• Razão de Alavancagem

*Métricas Derivadas*
• ROE Acumulado Anualizado (%)
• Ativo / PL
• Crédito / PL (%)
• Crédito / Captações (%)
• Perda Esperada / Carteira
• PDD Total e Índices de Cobertura

*Outros Blocos*
• Carteira 4.966 por classe de risco (AA a H)
• Taxas de Juros por Produto (PF e PJ)
• Composição do Conselho e Diretoria
"""

TEXTO_RECURSOS = """
*Recursos Operacionais*

🔍 *Filtros inteligentes*
Seleção por lista customizada, recorte por período e universo configurável.

🏷️ *Nomenclatura personalizada*
Sistema de aliases: normalize nomes e defina cores por instituição.

📥 *Exportação*
Excel (multi-aba), CSV e PowerPoint nas visões tabulares e gráficas.

🏛️ *Dados oficiais*
Fontes exclusivamente oficiais do BCB: IF.data (Rel. 1–16), Relatório 5, COSIF/Cadoc 4060, BLOPRUDENCIAL.

🔧 *Modo diagnóstico*
Exibe uso de memória, tamanho do cache derivado e tempos de execução por tela.
"""

TEXTO_DADOS = """
*Fontes de Dados*

Todos os dados são oriundos de fontes oficiais do Banco Central do Brasil:

• *API Olinda / BCB* — dados cadastrais e indicadores gerais
• *IFData Rel. 1* — Principal (patrimônio, ativos)
• *IFData Rel. 2* — Composição do Ativo
• *IFData Rel. 3* — Composição do Passivo
• *IFData Rel. 4* — DRE
• *IFData Rel. 5* — Capital Regulatório e Prudencial
• *IFData Rel. 11* — Carteira de Crédito PF
• *IFData Rel. 13* — Carteira de Crédito PJ
• *IFData Rel. 16* — Carteira Instrumento (Res. 4.966)
• *Cadoc 4060* — Demonstrativo Contábil (COSIF)
• *BLOPRUDENCIAL* — Conselho e Diretoria
"""

TEXTO_STACK = """
*Stack Tecnológica*

• *Python 3.10+* — linguagem base
• *Streamlit 1.53* — interface web interativa
• *Pandas 2.3* — processamento e análise
• *NumPy 2.4* — computação numérica
• *Plotly 6.5* — visualizações interativas
• *Altair 6.0* — visualizações estatísticas
• *Matplotlib 3.10* — gráficos auxiliares
• *PyArrow ≥14* — arquivos Parquet (cache)
• *OpenPyXL / XlsxWriter* — Excel
• *python-pptx* — PowerPoint
• *Requests* — consumo de APIs
• *GitPython* — publicação do cache via Git
"""

TEXTO_SOBRE = """
*Sobre o toma.conta*

Ferramenta open-source para análise de instituições financeiras brasileiras.

Consolida dados oficiais do Banco Central do Brasil em uma única interface, permitindo:
• Comparar indicadores entre múltiplas IFs
• Acompanhar a evolução temporal de métricas
• Criar métricas personalizadas
• Exportar análises em Excel, CSV e PowerPoint

_Desenvolvido por Matheus Prates, CFA_
"""

# ---------------------------------------------------------------------------
# Teclados inline
# ---------------------------------------------------------------------------

def teclado_principal() -> InlineKeyboardMarkup:
    botoes = [
        [InlineKeyboardButton("📖 Como Usar", callback_data="como_usar")],
        [
            InlineKeyboardButton("📊 Módulos de Análise", callback_data="modulos_analise"),
            InlineKeyboardButton("🔧 Utilitários", callback_data="modulos_utilitarios"),
        ],
        [
            InlineKeyboardButton("📐 Indicadores", callback_data="indicadores"),
            InlineKeyboardButton("⚙️ Recursos", callback_data="recursos"),
        ],
        [
            InlineKeyboardButton("🏛️ Fontes de Dados", callback_data="dados"),
            InlineKeyboardButton("💻 Stack", callback_data="stack"),
        ],
        [InlineKeyboardButton("ℹ️ Sobre", callback_data="sobre")],
    ]
    return InlineKeyboardMarkup(botoes)


def teclado_voltar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]]
    )


# ---------------------------------------------------------------------------
# Handlers de comandos
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        TEXTO_BOAS_VINDAS,
        parse_mode="Markdown",
        reply_markup=teclado_principal(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        "*Comandos disponíveis*\n\n"
        "/start — Abre o menu principal da URA\n"
        "/help — Esta mensagem de ajuda\n"
        "/como\\_usar — Passo a passo de uso da plataforma\n"
        "/modulos — Lista de módulos de análise\n"
        "/indicadores — Indicadores e métricas disponíveis\n"
        "/stack — Stack tecnológica do projeto\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def cmd_como_usar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        TEXTO_COMO_USAR,
        parse_mode="Markdown",
        reply_markup=teclado_voltar(),
    )


async def cmd_modulos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        TEXTO_MODULOS_ANALISE,
        parse_mode="Markdown",
        reply_markup=teclado_voltar(),
    )


async def cmd_indicadores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        TEXTO_INDICADORES,
        parse_mode="Markdown",
        reply_markup=teclado_voltar(),
    )


async def cmd_stack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        TEXTO_STACK,
        parse_mode="Markdown",
        reply_markup=teclado_voltar(),
    )


# ---------------------------------------------------------------------------
# Handler de callbacks (botões inline)
# ---------------------------------------------------------------------------

ROTAS: dict[str, tuple[str, str]] = {
    "como_usar":          (TEXTO_COMO_USAR,           "Markdown"),
    "modulos_analise":    (TEXTO_MODULOS_ANALISE,     "Markdown"),
    "modulos_utilitarios":(TEXTO_MODULOS_UTILITARIOS, "Markdown"),
    "indicadores":        (TEXTO_INDICADORES,          "Markdown"),
    "recursos":           (TEXTO_RECURSOS,             "Markdown"),
    "dados":              (TEXTO_DADOS,                "Markdown"),
    "stack":              (TEXTO_STACK,                "Markdown"),
    "sobre":              (TEXTO_SOBRE,                "Markdown"),
}


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    dados = query.data

    if dados == "menu_principal":
        await query.edit_message_text(
            TEXTO_BOAS_VINDAS,
            parse_mode="Markdown",
            reply_markup=teclado_principal(),
        )
        return

    if dados in ROTAS:
        texto, parse_mode = ROTAS[dados]
        await query.edit_message_text(
            texto,
            parse_mode=parse_mode,
            reply_markup=teclado_voltar(),
        )
        return

    await query.edit_message_text("Opção não reconhecida.", reply_markup=teclado_principal())


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "Variável de ambiente TELEGRAM_BOT_TOKEN não definida.\n"
            "Execute: export TELEGRAM_BOT_TOKEN='seu_token_aqui'"
        )

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("como_usar", cmd_como_usar))
    app.add_handler(CommandHandler("modulos", cmd_modulos))
    app.add_handler(CommandHandler("indicadores", cmd_indicadores))
    app.add_handler(CommandHandler("stack", cmd_stack))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot iniciado. Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
