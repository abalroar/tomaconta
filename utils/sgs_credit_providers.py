"""Provedores de séries para o módulo de mercado de crédito."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol

import pandas as pd
import requests

from .sgs_credit_registry import SeriesSpec


BCB_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SeriesProvider(Protocol):
    """Contrato mínimo para fontes BCB e fontes externas."""

    def fetch(self, spec: SeriesSpec, start: date, end: date) -> pd.DataFrame:
        """Retorna colunas ``data`` e ``valor`` para uma série."""


@dataclass
class BCBSGSProvider:
    session: requests.Session | None = None
    timeout: int = 60
    max_attempts: int = 4

    def fetch(self, spec: SeriesSpec, start: date, end: date) -> pd.DataFrame:
        if spec.code is None:
            raise ValueError(f"Série {spec.alias} sem código SGS")

        client = self.session or requests
        url = BCB_SGS_URL.format(code=spec.code)
        params = {
            "formato": "json",
            "dataInicial": start.strftime("%d/%m/%Y"),
            "dataFinal": end.strftime("%d/%m/%Y"),
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 5))
                    continue
                break

            if response.status_code in RETRYABLE_STATUS and attempt < self.max_attempts:
                time.sleep(min(2 ** (attempt - 1), 5))
                continue
            if response.status_code != 200:
                detail = response.text[:250].strip()
                raise RuntimeError(f"SGS {spec.code}: HTTP {response.status_code}: {detail}")

            try:
                payload = response.json()
            except ValueError as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 5))
                    continue
                break
            if not isinstance(payload, list):
                raise RuntimeError(f"SGS {spec.code}: payload inesperado ({type(payload).__name__})")
            frame = pd.DataFrame.from_records(payload)
            if frame.empty:
                return pd.DataFrame(columns=["data", "valor"])
            if not {"data", "valor"}.issubset(frame.columns):
                raise RuntimeError(f"SGS {spec.code}: colunas data/valor ausentes")
            frame = frame[["data", "valor"]].copy()
            frame["data"] = pd.to_datetime(frame["data"], format="%d/%m/%Y", errors="coerce")
            frame["valor"] = pd.to_numeric(
                frame["valor"].astype(str).str.replace(",", ".", regex=False),
                errors="coerce",
            )
            return frame.dropna(subset=["data", "valor"]).sort_values("data").reset_index(drop=True)

        raise RuntimeError(f"SGS {spec.code}: falha de rede após {self.max_attempts} tentativas: {last_error}")


def default_providers() -> Mapping[str, SeriesProvider]:
    return {"bcb_sgs": BCBSGSProvider()}
