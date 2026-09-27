"""Soja CBOT (ZS=F) desde el endpoint chart de Yahoo Finance.

Solo soja: el factor bushels/tonelada es específico del producto.

ZS=F es una serie *continua* del contrato más cercano: en cada roll salta de
un vencimiento al siguiente, así que sirve como referencia internacional de
nivel, NO para calcular resultados de una cobertura con un contrato puntual.
Unidad: centavos de dólar por bushel (Yahoo informa currency "USX").
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import requests

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 1 tonelada métrica de soja = 36,7437 bushels (bushel de soja = 60 lb).
BUSHELS_SOJA_POR_TN = 36.7437


class CbotError(ValueError):
    """La respuesta de Yahoo no tiene el formato esperado."""


def parsear_chart(payload: dict) -> pd.DataFrame:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise CbotError(f"Yahoo devolvió error: {chart['error']}")
    resultado = (chart.get("result") or [None])[0]
    if resultado is None:
        raise CbotError("Respuesta sin resultados.")
    moneda = resultado.get("meta", {}).get("currency")
    if moneda != "USX":
        raise CbotError(f"Moneda inesperada {moneda!r}; se esperaba USX (centavos de USD).")
    tiempos = resultado.get("timestamp") or []
    cierres = resultado["indicators"]["quote"][0]["close"]
    if len(tiempos) != len(cierres):
        raise CbotError(f"{len(tiempos)} timestamps para {len(cierres)} cierres.")
    for ts, cierre in zip(tiempos, cierres):
        if not isinstance(ts, int):
            raise CbotError(f"Timestamp inválido: {ts!r}")
        if cierre is not None and (not isinstance(cierre, (int, float)) or not math.isfinite(cierre) or cierre <= 0):
            raise CbotError(f"Cierre inválido en ts={ts}: {cierre!r}")
    # Yahoo marca cada barra diaria con un instante en la zona que informa en
    # meta.exchangeTimezoneName (para ZS=F es America/New_York: medianoche,
    # o 09:30 en algunos días). Convertir con otra zona corre la fecha un día.
    zona = resultado.get("meta", {}).get("exchangeTimezoneName")
    if not zona:
        raise CbotError("Respuesta sin exchangeTimezoneName: no se puede fechar cada barra.")
    fechas = pd.to_datetime(pd.Series(tiempos, dtype="int64"), unit="s", utc=True).dt.tz_convert(zona).dt.date
    # Un cierre nulo queda como faltante marcado, igual que "S/C" en pizarra.
    cierre = pd.Series([float("nan") if c is None else float(c) for c in cierres])
    serie = pd.DataFrame(
        {"fecha": fechas.values, "usd_por_tn": cierre.values / 100 * BUSHELS_SOJA_POR_TN, "sin_dato": cierre.isna().values}
    )
    repetidas = serie[serie["fecha"].duplicated(keep=False)]
    if not repetidas.empty:
        raise CbotError(f"Fechas repetidas: {sorted(set(repetidas['fecha']))[:5]}")
    return serie.reset_index(drop=True)


def descargar(desde: dt.date, hasta: dt.date) -> pd.DataFrame:
    p1 = int(dt.datetime.combine(desde, dt.time(), dt.timezone.utc).timestamp())
    p2 = int(dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp())
    resp = requests.get(
        URL.format(simbolo="ZS=F"),
        params={"period1": p1, "period2": p2, "interval": "1d"},
        headers=_HEADERS,
        timeout=60,
    )
    resp.raise_for_status()
    return parsear_chart(resp.json())
