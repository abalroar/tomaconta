"""Estimativa de esforço por commits, com atualização automática não bloqueante.

O snapshot distribuído acompanha o código. Atualizações em execução são locais,
atômicas e só substituem o último resultado após consultar todo o histórico.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
from typing import Callable
from zoneinfo import ZoneInfo

import requests

SCHEMA_VERSION = 2
CACHE_TTL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(minutes=15)
TZ_BR = ZoneInfo("America/Sao_Paulo")
MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
DEFAULT_CONFIG = {
    "repositorios": ["abalroar/tomaconta-dev", "abalroar/tomaconta", "abalroar/ficadeolho"],
    "limiar_sessao_min": 90,
    "overhead_sessao_min": 20,
    "incluir_merges": False,
}


class DevelopmentHoursError(RuntimeError):
    """Falha de consulta com mensagem segura para a interface."""


def parse_datetime(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def normalize_config(value: dict | None = None) -> dict:
    config = {**DEFAULT_CONFIG, **(value or {})}
    repos = config["repositorios"]
    if not isinstance(repos, list) or not repos or any(
        not isinstance(repo, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) for repo in repos
    ):
        raise ValueError("Repositórios da estimativa inválidos.")
    for key, low, high in (("limiar_sessao_min", 15, 480), ("overhead_sessao_min", 0, 120)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError(f"Parâmetro {key} inválido.")
    if type(config["incluir_merges"]) is not bool:
        raise ValueError("Parâmetro incluir_merges inválido.")
    return {key: list(repos) if key == "repositorios" else config[key] for key in DEFAULT_CONFIG}


def load_config(path: Path) -> dict:
    return normalize_config(read_json(path))


def _is_merge(item: dict) -> bool:
    parents = item.get("parents")
    if isinstance(parents, list):
        return len(parents) > 1
    message = str(item.get("commit", {}).get("message", "")).strip().lower()
    return message.startswith(("merge pull request", "merge branch", "merge remote-tracking branch"))


def fetch_history(config: dict, token: str | None = None, *, client=None) -> tuple[list[dict], list[dict]]:
    """Resolve aliases e pagina cada repositório canônico em uma revisão fixa."""
    config = normalize_config(config)
    owned_client = client is None
    client = client or requests.Session()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_json(path, params=None):
        try:
            response = client.get(f"https://api.github.com/{path}", headers=headers, params=params, timeout=20)
            if response.status_code == 401 and "Authorization" in headers:
                headers.pop("Authorization")
                response = client.get(f"https://api.github.com/{path}", headers=headers, params=params, timeout=20)
            if response.status_code != 200:
                detail = "limite de API ou permissão" if response.status_code in (403, 429) else "consulta indisponível"
                raise DevelopmentHoursError(f"GitHub: {detail} (HTTP {response.status_code}).")
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DevelopmentHoursError("A consulta ao GitHub não foi concluída.") from exc

    commits, sources = [], {}
    try:
        for requested in config["repositorios"]:
            metadata = get_json(f"repos/{requested}")
            if not isinstance(metadata, dict) or not metadata.get("full_name") or not metadata.get("default_branch"):
                raise DevelopmentHoursError("GitHub retornou identificação de repositório incompleta.")
            canonical = metadata["full_name"]
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", canonical):
                raise DevelopmentHoursError("GitHub retornou identificação de repositório inválida.")
            if canonical.casefold() in sources:
                sources[canonical.casefold()]["nomes_consultados"].append(requested)
                continue
            source = {
                "repositorio": canonical, "nomes_consultados": [requested],
                "branch": metadata["default_branch"], "head_sha": None,
                "commits_consultados": 0, "merges_excluidos": 0, "commits_considerados": 0,
            }
            sources[canonical.casefold()] = source
            revision = metadata["default_branch"]
            page = 1
            while True:
                batch = get_json(f"repos/{canonical}/commits", {"per_page": 100, "page": page, "sha": revision})
                if not isinstance(batch, list):
                    raise DevelopmentHoursError("GitHub retornou um histórico de commits incompleto.")
                if page == 1 and batch:
                    revision = batch[0].get("sha")
                    if not revision:
                        raise DevelopmentHoursError("GitHub retornou commit sem revisão.")
                    source["head_sha"] = revision
                for item in batch:
                    if not isinstance(item, dict):
                        raise DevelopmentHoursError("GitHub retornou commit inválido.")
                    source["commits_consultados"] += 1
                    if not config["incluir_merges"] and _is_merge(item):
                        source["merges_excluidos"] += 1
                        continue
                    raw = item.get("commit") or {}
                    date = parse_datetime((raw.get("author") or {}).get("date"))
                    if not item.get("sha") or date is None or not isinstance(raw.get("message"), str):
                        raise DevelopmentHoursError("GitHub retornou commit sem data ou identificação.")
                    commits.append({"repo": canonical, "sha": item["sha"], "mensagem": raw["message"], "data": date})
                    source["commits_considerados"] += 1
                if len(batch) < 100:
                    break
                page += 1
        return commits, list(sources.values())
    finally:
        if owned_client:
            client.close()


def calculate_estimate(commits: list[dict], config: dict, *, sources=None, now=None) -> dict:
    """Linha do tempo única; sessões separadas por intervalo superior ao limiar."""
    config = normalize_config(config)
    unique, seen_sha, seen_content = [], set(), set()
    for commit in commits:
        date = commit.get("data")
        if not isinstance(date, datetime) or date.tzinfo is None or not commit.get("sha"):
            raise ValueError("Commit sem data com fuso ou identificação.")
        fingerprint = (date.astimezone(timezone.utc).isoformat(timespec="seconds"), str(commit.get("mensagem", "")).strip().lower())
        if commit["sha"] in seen_sha or fingerprint in seen_content:
            continue
        seen_sha.add(commit["sha"])
        seen_content.add(fingerprint)
        unique.append(commit)
    unique.sort(key=lambda commit: commit["data"])
    sessions = []
    threshold = timedelta(minutes=config["limiar_sessao_min"])
    for commit in unique:
        if not sessions or commit["data"] - sessions[-1][-1]["data"] > threshold:
            sessions.append([])
        sessions[-1].append(commit)
    weekly, monthly = {}, {}
    distribution = {"< 30 min": 0, "30-60 min": 0, "1-2 h": 0, "2-4 h": 0, "> 4 h": 0}
    base = 0.0
    for session in sessions:
        start, end = session[0]["data"], session[-1]["data"]
        hours = (end - start).total_seconds() / 3600
        base += hours
        minutes = hours * 60
        bucket = "< 30 min" if minutes < 30 else "30-60 min" if minutes < 60 else "1-2 h" if minutes < 120 else "2-4 h" if minutes <= 240 else "> 4 h"
        distribution[bucket] += 1
        day = start.astimezone(TZ_BR).date()
        week = day - timedelta(days=day.weekday())
        item = weekly.setdefault(week, {"sessoes": 0, "horas_commits": 0.0})
        item["sessoes"] += 1
        item["horas_commits"] += hours
    for commit in unique:
        month = commit["data"].astimezone(TZ_BR).strftime("%Y-%m")
        monthly[month] = monthly.get(month, 0) + 1
    weekly_rows = []
    if unique:
        day = unique[-1]["data"].astimezone(TZ_BR).date()
        last_week = day - timedelta(days=day.weekday())
        week = min(weekly)
        while week <= last_week:
            item = weekly.get(week, {"sessoes": 0, "horas_commits": 0.0})
            overhead = item["sessoes"] * config["overhead_sessao_min"] / 60
            weekly_rows.append({
                "semana_inicio": week.isoformat(), "label_semana": f"{week.day:02d}/{MONTHS[week.month - 1]}",
                "sessoes": item["sessoes"], "horas_commits": round(item["horas_commits"], 2),
                "horas_overhead": round(overhead, 2), "total_horas": round(item["horas_commits"] + overhead, 2),
            })
            week += timedelta(days=7)
    overhead = len(sessions) * config["overhead_sessao_min"] / 60
    total = base + overhead
    return {
        "schema_version": SCHEMA_VERSION, "calculado_em": (now or datetime.now(timezone.utc)).isoformat(),
        "horas_base_commits": round(base, 2), "horas_overhead": round(overhead, 2), "total_horas": round(total, 2),
        "faixa_estimativa_horas": {"min": round(base, 2), "central": round(total, 2), "max": round(base + len(sessions) * max(60, config["overhead_sessao_min"]) / 60, 2)},
        "total_sessoes": len(sessions), "sessao_media_horas": round(total / len(sessions), 2) if sessions else 0.0,
        "total_commits": len(unique), "commits_duplicados": len(commits) - len(unique),
        "primeiro_commit": unique[0]["data"].isoformat() if unique else None,
        "ultimo_commit": unique[-1]["data"].isoformat() if unique else None,
        "repositorios": config["repositorios"], "fontes": sources or [],
        "parametros": {key: config[key] for key in ("limiar_sessao_min", "overhead_sessao_min", "incluir_merges")},
        "distribuicao_sessoes": distribution, "commits_por_mes": dict(sorted(monthly.items())), "esforco_semanal": weekly_rows,
    }


def fetch_estimate(config: dict, token=None) -> dict:
    commits, sources = fetch_history(config, token)
    return calculate_estimate(commits, config, sources=sources)


def valid_snapshot(value) -> bool:
    if not isinstance(value, dict) or parse_datetime(value.get("calculado_em")) is None:
        return False
    for key in ("horas_base_commits", "horas_overhead", "total_horas", "total_sessoes", "total_commits", "sessao_media_horas"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            return False
    return abs(value["total_horas"] - value["horas_base_commits"] - value["horas_overhead"]) < .03


def needs_refresh(snapshot: dict | None, config: dict, now=None) -> bool:
    if not valid_snapshot(snapshot) or snapshot.get("schema_version") != SCHEMA_VERSION:
        return True
    parameters = {key: config[key] for key in ("limiar_sessao_min", "overhead_sessao_min", "incluir_merges")}
    age = (now or datetime.now(timezone.utc)) - parse_datetime(snapshot["calculado_em"])
    return age >= CACHE_TTL or age < timedelta(0) or snapshot.get("parametros") != parameters or snapshot.get("repositorios") != config["repositorios"]


def write_snapshot(path: Path, snapshot: dict) -> None:
    if not valid_snapshot(snapshot):
        raise ValueError("Estimativa incompleta ou inválida.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(snapshot, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class EstimateStatus:
    snapshot: dict | None
    refreshing: bool = False
    error: str | None = None
    stale: bool = False


class EstimateCache:
    """Compartilha um refresh entre sessões e preserva o último cálculo íntegro."""

    def __init__(self, bundled_path: Path, runtime_path: Path, *, fetcher: Callable = fetch_estimate):
        self.bundled_path, self.runtime_path = Path(bundled_path), Path(runtime_path)
        self.fetcher = fetcher
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dev-hours")
        self._future: Future | None = None
        self._config_key: str | None = None
        self._error: str | None = None
        self._failed_at: datetime | None = None

    def _refresh(self, config, token):
        snapshot = self.fetcher(config, token)
        if needs_refresh(snapshot, config):
            raise DevelopmentHoursError("O resultado da consulta está incompleto ou desatualizado.")
        write_snapshot(self.runtime_path, snapshot)
        return snapshot

    def status(self, config: dict, token=None, *, now=None) -> EstimateStatus:
        config = normalize_config(config)
        now = now or datetime.now(timezone.utc)
        key = json.dumps(config, sort_keys=True)
        with self._lock:
            if self._future is not None and self._future.done():
                try:
                    self._future.result()
                    self._error, self._failed_at = None, None
                except Exception as exc:
                    self._error = str(exc) if isinstance(exc, DevelopmentHoursError) else "A atualização automática não foi concluída."
                    self._failed_at = now
                self._future = None
            candidates = [read_json(self.runtime_path), read_json(self.bundled_path)]
            candidates = [item for item in candidates if valid_snapshot(item)]
            matching = [item for item in candidates if item.get("repositorios") == config["repositorios"] and item.get("parametros") == {k: config[k] for k in ("limiar_sessao_min", "overhead_sessao_min", "incluir_merges")}]
            snapshot = max(matching or candidates, key=lambda item: parse_datetime(item["calculado_em"]), default=None)
            stale = needs_refresh(snapshot, config, now)
            if key != self._config_key:
                self._error, self._failed_at = None, None
                self._config_key = key
            retry_due = self._failed_at is None or now - self._failed_at >= RETRY_INTERVAL
            if stale and self._future is None and retry_due:
                self._error = None
                self._future = self._executor.submit(self._refresh, config, token)
            return EstimateStatus(snapshot, self._future is not None, self._error, stale)

    def close(self):
        self._executor.shutdown(wait=True)
