"""Catálogo canônico de instituições sem dependência de alias local."""

from __future__ import annotations

import csv
import copy
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List

import requests


CONGLOMERADOS_API_URL = "https://www3.bcb.gov.br/informes/rest/conglomerados"


def normalize_institution_name(nome: str | None) -> str:
    """Normaliza nome oficial para chave estável de matching."""
    if nome is None:
        return ""

    texto = str(nome).strip().upper()
    texto = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )
    texto = re.sub(r"[^A-Z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _project_root(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir.resolve()
    return Path(__file__).resolve().parents[2]


def _parse_conglomerados_csv_text(texto: str) -> List[dict]:
    blocos = re.split(r"(?=Conglomerado)", texto, flags=re.IGNORECASE)
    resultados: List[dict] = []
    for bloco in blocos:
        bloco_limpo = " ".join(bloco.split())
        if not bloco_limpo:
            continue

        cod_match = re.search(r"CDIGO\D*(\d{4,8})", bloco_limpo, flags=re.IGNORECASE)
        nome_match = re.search(r"NOME\s*(.*?)\s*TIPO", bloco_limpo, flags=re.IGNORECASE)
        if not cod_match:
            continue

        codigo = int(cod_match.group(1))
        nome = nome_match.group(1).strip(" -") if nome_match else "SEM NOME"
        participacoes = []

        for part in re.finditer(
            r"CNPJ\D*([0-9]{8,14})\s*(.*?)\s*(LIDER|PARTICIPANTE)",
            bloco_limpo,
            flags=re.IGNORECASE,
        ):
            cnpj = part.group(1).zfill(14)
            nome_inst = re.sub(r"\s+", " ", part.group(2)).strip(" -")
            condicao = normalize_institution_name(part.group(3))
            participacoes.append({"cnpj": cnpj, "nome": nome_inst, "condicao": condicao})

        resultados.append({"codigo": codigo, "nome": nome, "participacoes": participacoes})
    return resultados


def _load_conglomerados_local_csv(base_dir: Path) -> List[dict]:
    caminho = base_dir / "conglomerados.csv"
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8", errors="ignore")
    return _parse_conglomerados_csv_text(texto)


def _load_conglomerados_api() -> List[dict]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
    }
    for metodo in ("GET", "POST"):
        try:
            resposta = requests.request(metodo, CONGLOMERADOS_API_URL, timeout=40, headers=headers)
            if resposta.status_code in {400, 405}:
                continue
            resposta.raise_for_status()
            payload = json.loads(resposta.text)
            dados_api = payload.get("content", []) if isinstance(payload, dict) else payload
            if isinstance(dados_api, list) and dados_api:
                return dados_api
        except Exception:
            continue
    return []


def _load_conglomerados_bloprudencial_fallback(base_dir: Path) -> List[dict]:
    candidatos = sorted(base_dir.glob("*BLOPRUDENCIAL*.CSV"), reverse=True)
    if not candidatos:
        return []

    conglomerados: Dict[str, dict] = {}
    for caminho in candidatos:
        try:
            with caminho.open("r", encoding="latin1", errors="ignore", newline="") as fp:
                leitor = csv.reader(fp, delimiter=";")
                for partes in leitor:
                    if len(partes) < 7:
                        continue
                    linha = ";".join(partes)
                    if not linha or linha.startswith("Balancete") or linha.startswith("Data de geracao") or linha.startswith("Fonte:"):
                        continue
                    if linha.startswith("#"):
                        continue

                    cnpj = re.sub(r"\D", "", partes[2]).zfill(14)
                    nome_inst = partes[4].strip()
                    cod_congl = partes[5].strip()
                    nome_congl = partes[6].strip()
                    if not cod_congl or not nome_congl:
                        continue

                    codigo = re.sub(r"\D", "", cod_congl)
                    if not codigo:
                        continue

                    item = conglomerados.setdefault(
                        codigo,
                        {
                            "codigo": int(codigo),
                            "nome": nome_congl,
                            "participacoes": [],
                        },
                    )
                    if cnpj and nome_inst:
                        registro = {"cnpj": cnpj, "nome": nome_inst, "condicao": "PARTICIPANTE"}
                        if registro not in item["participacoes"]:
                            item["participacoes"].append(registro)
        except Exception:
            continue

    resultado = sorted(conglomerados.values(), key=lambda x: x.get("codigo", 0))
    for item in resultado:
        if item.get("participacoes"):
            item["participacoes"][0]["condicao"] = "LIDER"
    return resultado


def load_conglomerados_catalog(base_dir: Path | None = None) -> List[dict]:
    """Carrega catálogo oficial de conglomerados."""
    root = _project_root(base_dir)
    return copy.deepcopy(_load_conglomerados_catalog_cached(str(root)))


@lru_cache(maxsize=8)
def _load_conglomerados_catalog_cached(root_str: str) -> List[dict]:
    root = Path(root_str)
    dados = _load_conglomerados_local_csv(root)
    if dados:
        return dados

    dados = _load_conglomerados_api()
    if dados:
        return dados

    return _load_conglomerados_bloprudencial_fallback(root)


def build_institution_to_conglomerate_map(base_dir: Path | None = None) -> Dict[str, str]:
    """Mapa nome normalizado -> nome canônico do conglomerado."""
    root = _project_root(base_dir)
    return dict(_build_institution_to_conglomerate_map_cached(str(root)))


@lru_cache(maxsize=8)
def _build_institution_to_conglomerate_map_cached(root_str: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in _load_conglomerados_catalog_cached(root_str):
        nome_conglomerado = str(item.get("nome", "")).strip()
        if not nome_conglomerado:
            continue
        chave_congl = normalize_institution_name(nome_conglomerado)
        if chave_congl:
            mapping[chave_congl] = nome_conglomerado

        for participacao in item.get("participacoes", []) or []:
            nome_participante = str(participacao.get("nome", "")).strip()
            chave_participante = normalize_institution_name(nome_participante)
            if chave_participante and chave_participante not in mapping:
                mapping[chave_participante] = nome_conglomerado
    return mapping


def canonicalize_institution_name(
    nome: str | None,
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    """Resolve um nome de instituição para o nome oficial do conglomerado."""
    if nome is None:
        return ""

    bruto = str(nome).strip()
    if not bruto:
        return ""

    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    chave = normalize_institution_name(bruto)
    resolved = catalog.get(chave)
    if resolved:
        return resolved

    # Variações oficiais podem omitir sufixos como "HOLDING S.A.".
    # Aceitamos apenas correspondência única para manter rastreabilidade.
    candidatos = {
        nome_canonico
        for chave_catalogo, nome_canonico in catalog.items()
        if chave and (chave in chave_catalogo or chave_catalogo in chave)
    }
    if len(candidatos) == 1:
        return next(iter(candidatos))

    tokens = [token for token in chave.split() if len(token) >= 3]
    if tokens:
        candidatos_tokens = {
            nome_canonico
            for chave_catalogo, nome_canonico in catalog.items()
            if all(token in chave_catalogo for token in tokens)
        }
        if len(candidatos_tokens) == 1:
            return next(iter(candidatos_tokens))

    return bruto


def canonicalize_institution_series(
    nomes: Iterable[str],
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> List[str]:
    """Resolve uma sequência de nomes para nomes canônicos."""
    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    return [canonicalize_institution_name(nome, catalog_map=catalog, base_dir=base_dir) for nome in nomes]
