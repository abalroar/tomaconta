"""Busca rankeada para seletores de instituições financeiras."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable, Sequence


GENERIC_TOKENS = {
    "A",
    "AGENCIA",
    "BANCO",
    "BCO",
    "BM",
    "BRASIL",
    "C",
    "CC",
    "CCTVM",
    "CFI",
    "COMERCIAL",
    "CONGLOMERADO",
    "COOPERATIVA",
    "CRED",
    "CREDITO",
    "CTVM",
    "D",
    "DA",
    "DAS",
    "DE",
    "DESENVOLVIMENTO",
    "DO",
    "DOS",
    "DTVM",
    "E",
    "ECONOMIA",
    "FINANCEIRA",
    "FINANCIAMENTO",
    "HOLDING",
    "INSTITUICAO",
    "INVESTIMENTO",
    "IP",
    "LTDA",
    "MULTIPLO",
    "MUTUO",
    "PAGAMENTO",
    "PAGAMENTOS",
    "PRUDENCIAL",
    "S",
    "SA",
    "SC",
    "SCD",
    "SCFI",
    "SCMEPP",
    "SOCIEDADE",
}

DEFAULT_ALIAS_TARGETS = {
    "ITAU": {"ITAU PRUDENCIAL", "ITAU UNIBANCO"},
    "ITAÚ": {"ITAU PRUDENCIAL", "ITAU UNIBANCO"},
    "ITAU UNIBANCO": {"ITAU PRUDENCIAL", "ITAU UNIBANCO"},
    "ITAÚ UNIBANCO": {"ITAU PRUDENCIAL", "ITAU UNIBANCO"},
    "VOLVO": {"VOLVO PRUDENCIAL", "VOLVO"},
    "CRESSOL": {"CRESOL", "CRESSOL"},
    "CRESOL": {"CRESOL", "CRESSOL"},
}


@dataclass(frozen=True)
class InstitutionSearchEntry:
    value: str
    normalized: str
    core: str
    tokens: tuple[str, ...]
    core_tokens: tuple[str, ...]


def normalize_search_text(value: object) -> str:
    """Normaliza texto para busca sem acentos, caixa ou pontuação."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(part for part in normalize_search_text(text).split() if part)


def _core_tokens(tokens: Sequence[str]) -> tuple[str, ...]:
    core = tuple(token for token in tokens if token not in GENERIC_TOKENS)
    return core or tuple(tokens)


def build_institution_search_index(options: Iterable[object]) -> tuple[InstitutionSearchEntry, ...]:
    """Monta índice leve e estável a partir da lista canônica de opções."""
    entries: list[InstitutionSearchEntry] = []
    seen: set[str] = set()
    for option in options:
        if option is None:
            continue
        value = str(option).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized = normalize_search_text(value)
        tokens = _tokens(value)
        core_tokens = _core_tokens(tokens)
        entries.append(
            InstitutionSearchEntry(
                value=value,
                normalized=normalized,
                core=" ".join(core_tokens),
                tokens=tokens,
                core_tokens=core_tokens,
            )
        )
    return tuple(entries)


def _word_boundary_contains(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    pattern = r"(^|\s)" + re.escape(needle) + r"($|\s)"
    return bool(re.search(pattern, haystack))


def _token_similarity(query_token: str, candidate_token: str) -> float:
    if not query_token or not candidate_token:
        return 0.0
    return SequenceMatcher(None, query_token, candidate_token).ratio()


def _best_token_similarity(query_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    scores = []
    for query_token in query_tokens:
        scores.append(max(_token_similarity(query_token, candidate_token) for candidate_token in candidate_tokens))
    return min(scores) if scores else 0.0


def _alias_score(query: str, entry: InstitutionSearchEntry) -> int | None:
    targets = DEFAULT_ALIAS_TARGETS.get(query)
    if not targets:
        return None
    if entry.normalized in targets or entry.core in targets:
        return -100
    if any(target in entry.normalized for target in targets):
        return -50
    return None


def _score_entry(query: str, query_tokens: Sequence[str], entry: InstitutionSearchEntry) -> int | None:
    alias_score = _alias_score(query, entry)
    if alias_score is not None:
        return alias_score

    if query == entry.normalized or query == entry.core:
        return 0

    query_core_tokens = _core_tokens(query_tokens)
    query_core = " ".join(query_core_tokens)
    if query_core and query_core == entry.core:
        return 10

    token_set = set(entry.core_tokens)
    if query_core_tokens and set(query_core_tokens).issubset(token_set):
        extra = max(0, len(entry.core_tokens) - len(query_core_tokens))
        first_bonus = -20 if entry.core_tokens[: len(query_core_tokens)] == tuple(query_core_tokens) else 0
        return 80 + extra * 8 + first_bonus

    if query and entry.core.startswith(query):
        return 160 + max(0, len(entry.core) - len(query))

    if query and _word_boundary_contains(entry.normalized, query):
        return 220 + len(entry.normalized)

    if query_core_tokens:
        prefix_matches = []
        for query_token in query_core_tokens:
            token_match = any(
                candidate_token.startswith(query_token)
                and (
                    len(query_token) >= 5
                    or candidate_token == query_token
                    or _token_similarity(query_token, candidate_token) >= 0.88
                )
                for candidate_token in entry.core_tokens
            )
            prefix_matches.append(token_match)
        if all(prefix_matches):
            return 300 + len(entry.core)

    if len(query) >= 5 and query in entry.core:
        return 420 + len(entry.core)

    if len(query) >= 5 and query_core_tokens:
        similarity = _best_token_similarity(query_core_tokens, entry.core_tokens)
        if similarity >= 0.84:
            return 520 + int((1.0 - similarity) * 100) + len(entry.core_tokens) * 4

    return None


def search_institutions(
    options: Iterable[object],
    query: object,
    *,
    limit: int = 12,
) -> list[str]:
    """Retorna opções ordenadas por relevância, evitando matches genéricos."""
    normalized_query = normalize_search_text(query)
    if not normalized_query:
        return []
    query_tokens = _tokens(normalized_query)
    entries = build_institution_search_index(options)
    scored: list[tuple[int, int, str]] = []
    for idx, entry in enumerate(entries):
        score = _score_entry(normalized_query, query_tokens, entry)
        if score is not None:
            scored.append((score, idx, entry.value))
    if normalized_query in DEFAULT_ALIAS_TARGETS and any(score < 0 for score, _, _ in scored):
        scored = [item for item in scored if item[0] < 0]
    scored.sort(key=lambda item: (item[0], item[1], item[2].lower()))
    return [value for _, _, value in scored[: max(1, int(limit))]]
