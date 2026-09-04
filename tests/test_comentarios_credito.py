"""Leitura dos dados: o card de texto de cada página de Estatísticas Crédito BC."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from utils.comentarios_credito import (
    CHAVES,
    aplicar,
    carregar,
    caminho_padrao,
    com_texto,
    comentario,
    desatualizado,
    serializar,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_arquivo_esta_versionado_e_cobre_todas_as_paginas():
    """O texto é artefato versionado, como o parquet que ele comenta."""
    caminho = caminho_padrao()
    assert caminho.exists(), "data/comentarios_credito_bc.json ausente"
    documento = carregar()
    assert set(documento["paginas"]) == set(CHAVES)


@pytest.mark.parametrize("chave", CHAVES)
def test_cada_pagina_tem_um_ou_dois_paragrafos_com_fonte_e_data_base(chave):
    texto = comentario(chave)
    assert texto is not None
    assert 1 <= len(texto.paragrafos) <= 2, "um ou dois parágrafos por página"
    assert texto.fontes, "todo card declara de onde veio"
    assert len(texto.data_base) == 7 and texto.data_base[4] == "-"


def test_edicao_da_sessao_entra_no_json_baixado():
    """O download é o que torna a edição pública; precisa carregar o que foi escrito."""
    documento = carregar()
    base = comentario("concessoes", documento=documento)
    editado = com_texto(base, "Texto novo.", ("Fonte nova",))
    resultado = aplicar(documento, {"concessoes": editado}, atualizado_em="2026-09-04")

    assert resultado["paginas"]["concessoes"]["texto"] == "Texto novo."
    assert resultado["paginas"]["concessoes"]["fontes"] == ["Fonte nova"]
    assert resultado["atualizado_em"] == "2026-09-04"
    # As outras páginas seguem intactas.
    assert resultado["paginas"]["taxas"] == documento["paginas"]["taxas"]
    # E o arquivo em disco não foi tocado: no Streamlit Cloud a gravação seria
    # perdida no restart, o que daria falsa impressão de persistência.
    assert carregar()["paginas"]["concessoes"]["texto"] == base.texto


def test_json_baixado_volta_a_carregar_no_mesmo_formato():
    documento = carregar()
    bytes_json = serializar(documento)
    assert bytes_json.endswith(b"\n")
    assert json.loads(bytes_json.decode("utf-8")) == documento


def test_texto_e_marcado_como_desatualizado_quando_o_cache_avanca():
    texto = comentario("concessoes")
    assert desatualizado(texto, "2026-08") is True
    assert desatualizado(texto, "2026-07") is False
    assert desatualizado(texto, None) is False


def test_arquivo_ausente_nao_quebra(tmp_path):
    assert carregar(tmp_path) == {"versao": 1, "paginas": {}}
    assert comentario("concessoes", base_dir=tmp_path) is None


def _chamadas_de_leitura(fonte: str) -> list[tuple[str, int]]:
    """(chave, número de argumentos) de cada chamada a ``_leitura``."""
    return [
        (no.args[0].value, len(no.args))
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id == "_leitura"
        and no.args
        and isinstance(no.args[0], ast.Constant)
    ]


def test_toda_pagina_da_secao_chama_o_card():
    """Uma chamada por página, e nenhuma no Glossário.

    O Glossário é metodologia, não dado: não tem leitura de tendência a fazer.
    """
    fonte = (PROJECT_ROOT / "tabs" / "mercado_credito.py").read_text(encoding="utf-8")
    chamadas = {chave for chave, _ in _chamadas_de_leitura(fonte)}
    assert chamadas == set(CHAVES) - {"npl_faixa_renda"}
    corpo_glossario = fonte[fonte.index("def _render_glossary("):fonte.index("@st.cache_data")]
    assert "_leitura(" not in corpo_glossario

    view = (PROJECT_ROOT / "tabs" / "scr_inadimplencia_view.py").read_text(encoding="utf-8")
    assert 'render_comentario("npl_faixa_renda"' in view


def test_data_base_da_situacao_usa_as_series_da_propria_pagina():
    """Comprometimento fecha antes do resto do cache e não é desatualizado por isso."""
    fonte = (PROJECT_ROOT / "tabs" / "mercado_credito.py").read_text(encoding="utf-8")
    argumentos = dict(_chamadas_de_leitura(fonte))
    assert argumentos["situacao"] == 3, (
        "o card de Situação dos Agentes precisa receber as séries da página"
    )
