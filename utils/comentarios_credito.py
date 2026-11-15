"""Leitura dos dados: o texto que acompanha cada página de Estatísticas Crédito BC.

O texto mora em ``data/comentarios_credito_bc.json``, versionado no repositório
ao lado dos artefatos de dado que ele comenta. O disco do Streamlit Cloud é
efêmero: o que for gravado em arquivo durante uma sessão desaparece no próximo
restart. Por isso a edição na tela vale para a sessão de quem editou e o card
entrega o JSON atualizado para virar commit — que é o que torna a alteração
pública e deixa cada versão do texto no histórico, ao lado da versão dos dados.

Este módulo não importa Streamlit: a renderização fica em
``tabs/comentario_credito.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping


ARQUIVO = "comentarios_credito_bc.json"

# Chave de cada página da seção. O Glossário fica de fora: é metodologia, não
# dado, e não tem leitura de tendência a fazer.
CHAVES = (
    "concessoes",
    "credito_estoque",
    "credito_tomador",
    "credito_produto",
    "credito_empresa",
    "credito_controle",
    "situacao",
    "npl_pre_inad",
    "npl_cobertura",
    "npl_faixa_renda",
    "taxas",
)


@dataclass(frozen=True)
class Comentario:
    chave: str
    titulo: str
    texto: str
    fontes: tuple[str, ...]
    data_base: str

    @property
    def paragrafos(self) -> list[str]:
        return [bloco.strip() for bloco in self.texto.split("\n\n") if bloco.strip()]

    @property
    def vazio(self) -> bool:
        return not self.texto.strip()


def caminho_padrao(base_dir: Path | None = None) -> Path:
    raiz = base_dir or Path(__file__).resolve().parent.parent
    return raiz / "data" / ARQUIVO


def carregar(base_dir: Path | None = None) -> dict:
    """Documento completo. Devolve estrutura vazia se o arquivo não existir."""
    caminho = caminho_padrao(base_dir)
    if not caminho.exists():
        return {"versao": 1, "paginas": {}}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"versao": 1, "paginas": {}}


def comentario(
    chave: str,
    *,
    documento: Mapping | None = None,
    base_dir: Path | None = None,
) -> Comentario | None:
    """Comentário de uma página, ou ``None`` quando não há texto escrito."""
    doc = documento if documento is not None else carregar(base_dir)
    bruto = (doc.get("paginas") or {}).get(chave)
    if not isinstance(bruto, Mapping):
        return None
    return Comentario(
        chave=chave,
        titulo=str(bruto.get("titulo") or chave),
        texto=str(bruto.get("texto") or ""),
        fontes=tuple(str(item) for item in (bruto.get("fontes") or [])),
        data_base=str(bruto.get("data_base") or doc.get("data_base") or ""),
    )


def com_texto(base: Comentario, texto: str, fontes: tuple[str, ...] | None = None) -> Comentario:
    return replace(base, texto=texto, fontes=fontes if fontes is not None else base.fontes)


def aplicar(
    documento: Mapping,
    edicoes: Mapping[str, Comentario],
    *,
    atualizado_em: str | None = None,
) -> dict:
    """Documento com as edições da sessão aplicadas, pronto para virar commit."""
    resultado = json.loads(json.dumps(documento, ensure_ascii=False))
    paginas = resultado.setdefault("paginas", {})
    for chave, editado in edicoes.items():
        pagina = paginas.setdefault(chave, {})
        pagina["titulo"] = editado.titulo
        pagina["texto"] = editado.texto
        pagina["fontes"] = list(editado.fontes)
        pagina["data_base"] = editado.data_base
    if atualizado_em:
        resultado["atualizado_em"] = atualizado_em
    return resultado


def serializar(documento: Mapping) -> bytes:
    """Bytes do JSON no mesmo formato do arquivo versionado."""
    return (json.dumps(documento, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def desatualizado(comentario_: Comentario, data_base_cache: str | None) -> bool:
    """Indica que o cache avançou e o texto ficou para trás.

    Compara competências ``YYYY-MM``. Sem uma das duas, não afirma nada.
    """
    if not comentario_.data_base or not data_base_cache:
        return False
    return str(data_base_cache)[:7] > str(comentario_.data_base)[:7]
