"""Catálogo canônico de instituições sem dependência de alias local."""

from __future__ import annotations

import csv
import copy
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import requests

from utils.ifdata_extractor import parece_codigo_instituicao, resolver_nome_instituicao


CONGLOMERADOS_API_URL = "https://www3.bcb.gov.br/informes/rest/conglomerados"
PLACEHOLDER_IF_PATTERN = re.compile(r"^\[IF\s+([A-Za-z0-9]+)\]$", re.IGNORECASE)

_GENERIC_TOKENS = {
    "A",
    "ANONIMA",
    "BANCO",
    "BANK",
    "BCO",
    "BM",
    "CONGLOMERADO",
    "D",
    "DA",
    "DAS",
    "DE",
    "DO",
    "DOS",
    "FINANCEIRA",
    "GRUPO",
    "HOLDING",
    "INSTITUICAO",
    "MULTIPLO",
    "OF",
    "PAGAMENTO",
    "PRUDENCIAL",
    "S",
    "SA",
    "SOCIEDADE",
}


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


def _significant_institution_tokens(nome: str | None) -> Tuple[str, ...]:
    """Retorna tokens significativos para canonicalização nominal auditável."""
    texto = normalize_institution_name(nome)
    if not texto:
        return ()

    texto = re.sub(r"\bBCO\b", "BANCO", texto)
    texto = re.sub(r"\bS A\b", "SA", texto)
    tokens = [token for token in texto.split() if token and token not in _GENERIC_TOKENS]
    return tuple(tokens)


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

    dados = _load_conglomerados_bloprudencial_fallback(root)
    if dados:
        return dados

    return _load_conglomerados_api()


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

    tokens_brutos = _significant_institution_tokens(bruto)
    if tokens_brutos:
        tokens_set = set(tokens_brutos)
        candidatos_subconjunto = {
            nome_canonico
            for chave_catalogo, nome_canonico in catalog.items()
            if tokens_set.issubset(set(_significant_institution_tokens(chave_catalogo)))
        }
        if len(candidatos_subconjunto) == 1:
            return next(iter(candidatos_subconjunto))

    return bruto


def canonicalize_institution_series(
    nomes: Iterable[str],
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> List[str]:
    """Resolve uma sequência de nomes para nomes canônicos."""
    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    return [canonicalize_institution_name(nome, catalog_map=catalog, base_dir=base_dir) for nome in nomes]


def is_placeholder_institution_name(nome: str | None) -> bool:
    texto = str(nome or "").strip()
    if not texto:
        return False
    return bool(PLACEHOLDER_IF_PATTERN.fullmatch(texto))


def build_code_to_name_map(
    *frames: pd.DataFrame | None,
    code_columns: Iterable[str] = ("CodInst", "COD_INST", "cod_inst", "CODINST"),
    name_columns: Iterable[str] = ("Instituição", "NomeInstituicao", "NomeInstituição", "NOME_INSTITUICAO"),
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    code_cols = list(code_columns)
    name_cols = list(name_columns)

    for frame in frames:
        if frame is None or frame.empty:
            continue
        code_col = next((col for col in code_cols if col in frame.columns), None)
        name_col = next((col for col in name_cols if col in frame.columns), None)
        if not code_col or not name_col:
            continue
        base = frame[[code_col, name_col]].dropna(subset=[code_col]).copy()
        if base.empty:
            continue
        for _, row in base.iterrows():
            code_val = row.get(code_col)
            name_val = str(row.get(name_col) or "").strip()
            if not name_val:
                continue
            if is_placeholder_institution_name(name_val) or parece_codigo_instituicao(name_val):
                continue
            try:
                code_key = str(int(float(code_val)))
            except Exception:
                code_key = str(code_val).strip()
            if code_key and code_key not in mapping:
                mapping[code_key] = name_val
    return mapping


def canonicalize_institution_dataframe(
    df: pd.DataFrame | None,
    *,
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
    name_column: str = "Instituição",
    extra_frames: Iterable[pd.DataFrame | None] = (),
) -> pd.DataFrame:
    if df is None or df.empty or name_column not in df.columns:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    out = df.copy()
    code_to_name = build_code_to_name_map(out, *list(extra_frames))
    code_columns = [col for col in ("CodInst", "COD_INST", "cod_inst", "CODINST") if col in out.columns]

    def _resolve_name(row: pd.Series) -> str:
        raw_name = str(row.get(name_column) or "").strip()
        code_key = ""
        for code_col in code_columns:
            code_val = row.get(code_col)
            if pd.isna(code_val):
                continue
            try:
                code_key = str(int(float(code_val)))
            except Exception:
                code_key = str(code_val).strip()
            if code_key:
                break

        nome_base = raw_name
        if (is_placeholder_institution_name(raw_name) or parece_codigo_instituicao(raw_name)) and code_key:
            nome_base = code_to_name.get(code_key) or resolver_nome_instituicao(code_key, raw_name)

        return canonicalize_institution_name(nome_base, catalog_map=catalog, base_dir=base_dir)

    out[name_column] = out.apply(_resolve_name, axis=1)
    return out
