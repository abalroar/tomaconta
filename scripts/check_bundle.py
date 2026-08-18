#!/usr/bin/env python3
"""Smoke check dos bundles críticos, release e branch publicada do Toma Conta."""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.ifdata_cache.artifact_identity import build_bundle_id, inspect_parquet_artifact
from utils.ifdata_cache.diagnostics import max_period_from_values
from utils.ifdata_cache.release_config import get_release_config


ARTIFACTS = {
    "critical_screens": {
        "path": REPO_ROOT / "data" / "bundled" / "critical_screens" / "dados.parquet",
        "metadata": REPO_ROOT / "data" / "bundled" / "critical_screens" / "metadata.json",
        "required_columns": {"Instituição", "Período", "InstituiçãoKey"},
    },
    "derived_metrics": {
        "path": REPO_ROOT / "data" / "bundled" / "derived_metrics" / "dados.parquet",
        "metadata": REPO_ROOT / "data" / "bundled" / "derived_metrics" / "metadata.json",
        "required_columns": {"Instituição", "Período", "Métrica", "Valor", "Unidade"},
    },
}

EXPECTED_METRICS = (
    "Custo de Crédito (%)",
    "Custo de Crédito / Receita de Crédito (%)",
    "Ativos Problemáticos / Carteira Total",
)
EXPECTED_MIN_COVERAGE = {
    "Custo de Crédito (%)": 1_000,
    "Custo de Crédito / Receita de Crédito (%)": 1_000,
    "Ativos Problemáticos / Carteira Total": 1_000,
}
MAX_ALLOWED_ABSOLUTE_DIFFERENCE = 0.001


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _deployment_check() -> tuple[bool, str]:
    head = _git("rev-parse", "HEAD")
    main = _git("rev-parse", "origin/main")
    if head.returncode or main.returncode:
        return False, "não foi possível resolver HEAD e origin/main"
    ancestor = _git("merge-base", "--is-ancestor", head.stdout.strip(), main.stdout.strip())
    if ancestor.returncode != 0:
        return False, f"HEAD {head.stdout.strip()[:8]} ainda não integra origin/main {main.stdout.strip()[:8]}"
    return True, f"HEAD {head.stdout.strip()[:8]} integra origin/main {main.stdout.strip()[:8]}"


def _release_hashes() -> dict[str, str]:
    release = get_release_config()
    hashes: dict[str, str] = {}
    for name in ARTIFACTS:
        url = f"{release.release_base_url}/{name}_dados.parquet"
        response = requests.get(
            url,
            timeout=120,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            params={"smoke": "content-hash"},
        )
        response.raise_for_status()
        hashes[name] = hashlib.sha256(response.content).hexdigest()
        pd.read_parquet(io.BytesIO(response.content), columns=["Período"])
    return hashes


def run_checks(*, check_release: bool = True, check_git: bool = True) -> tuple[list[str], list[str]]:
    passes: list[str] = []
    failures: list[str] = []
    identities: dict[str, dict[str, Any]] = {}

    for name, spec in ARTIFACTS.items():
        identity = inspect_parquet_artifact(spec["path"], metadata_path=spec["metadata"])
        identities[name] = identity
        if not identity["exists"]:
            failures.append(f"{name}: artefato ausente em {identity['path']}")
            continue
        missing = sorted(set(spec["required_columns"]) - set(identity["columns"]))
        if missing:
            failures.append(f"{name}: colunas obrigatórias ausentes: {', '.join(missing)}")
        else:
            passes.append(
                f"{name}: sha={identity['sha256'][:8]} linhas={identity['rows']} "
                f"colunas={len(identity['columns'])} max={identity['max_period']}"
            )

    if all(identity.get("exists") for identity in identities.values()):
        derived = pd.read_parquet(
            ARTIFACTS["derived_metrics"]["path"],
            columns=["Instituição", "Período", "Métrica", "Valor"],
        )
        metrics_present = set(derived["Métrica"].dropna().astype(str).unique())
        missing_metrics = sorted(set(EXPECTED_METRICS) - metrics_present)
        if missing_metrics:
            failures.append(f"derived_metrics: métricas ausentes: {', '.join(missing_metrics)}")

        latest_period = max_period_from_values(derived["Período"].dropna().astype(str).tolist())
        latest = derived[derived["Período"].astype(str).eq(str(latest_period))]
        coverage = latest.groupby("Métrica", observed=True)["Valor"].count().to_dict()
        for metric, minimum in EXPECTED_MIN_COVERAGE.items():
            valid = int(coverage.get(metric, 0))
            if valid < minimum:
                failures.append(f"{metric}: cobertura {valid} abaixo do mínimo {minimum} em {latest_period}")
            else:
                passes.append(f"{metric}: cobertura={valid} em {latest_period}")

        critical_columns = ["Instituição", "Período", *EXPECTED_METRICS]
        critical = pd.read_parquet(ARTIFACTS["critical_screens"]["path"], columns=critical_columns)
        pivot = (
            derived[derived["Métrica"].astype(str).isin(EXPECTED_METRICS)]
            .pivot_table(
                index=["Instituição", "Período"],
                columns="Métrica",
                values="Valor",
                aggfunc="first",
                observed=True,
            )
            .reset_index()
        )
        comparison = critical.merge(pivot, on=["Instituição", "Período"], suffixes=("_critical", "_derived"))
        for metric in EXPECTED_METRICS:
            difference = (
                pd.to_numeric(comparison[f"{metric}_critical"], errors="coerce")
                - pd.to_numeric(comparison[f"{metric}_derived"], errors="coerce")
            ).abs()
            max_difference = float(difference.max()) if difference.notna().any() else 0.0
            if max_difference > MAX_ALLOWED_ABSOLUTE_DIFFERENCE:
                failures.append(f"{metric}: diferença critical/derived={max_difference:.6f}")
            else:
                passes.append(f"{metric}: critical/derived max_diff={max_difference:.6f}")

        passes.append(f"bundle_id={build_bundle_id(identities)}")

    if check_release and all(identity.get("exists") for identity in identities.values()):
        try:
            release_hashes = _release_hashes()
        except Exception as exc:
            failures.append(f"release: falha ao baixar/validar assets: {exc}")
        else:
            for name, release_hash in release_hashes.items():
                local_hash = identities[name]["sha256"]
                if release_hash != local_hash:
                    failures.append(
                        f"{name}: release {release_hash[:8]} difere do bundle {str(local_hash)[:8]}"
                    )
                else:
                    passes.append(f"{name}: release=local sha={release_hash[:8]}")

    if check_git:
        ok, message = _deployment_check()
        (passes if ok else failures).append(f"deploy: {message}")
    return passes, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-release", action="store_true", help="não compara os assets do GitHub Release")
    parser.add_argument("--skip-git", action="store_true", help="não verifica se HEAD integra origin/main")
    args = parser.parse_args()

    passes, failures = run_checks(check_release=not args.skip_release, check_git=not args.skip_git)
    for message in passes:
        print(f"PASS | {message}")
    for message in failures:
        print(f"FAIL | {message}")
    print(f"RESULT | passes={len(passes)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
