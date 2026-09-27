"""Tipo de cambio mayorista BCRA (Comunicación A 3500), API pública v4.

Fuente: https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/5
(la v3 respondió 410 "deprecado" al verificarla el 2026-09-27).

OJO metodológico: la pizarra se pacta en pesos, pero el mercado físico la
convierte a dólares con el tipo de cambio BNA comprador, no con el A3500. Qué
tipo de cambio usar para pasar la pizarra a USD es una decisión pendiente
(ver README); este módulo solo trae la serie A3500, sin suponer que sirve para
eso.
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import requests

URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/5"
LIMITE = 1000


class FxError(ValueError):
    """La respuesta del BCRA no tiene el formato esperado."""


def parsear_respuesta(payload: dict) -> pd.DataFrame:
    if payload.get("status") != 200:
        raise FxError(f"Respuesta BCRA con status {payload.get('status')}: {payload.get('errorMessages')}")
    resultados = payload.get("results") or []
    if len(resultados) != 1 or resultados[0].get("idVariable") != 5:
        raise FxError("La respuesta no corresponde a la variable 5 (A3500).")
    detalle = resultados[0].get("detalle", [])
    fechas, valores = [], []
    for fila in detalle:
        valor = fila.get("valor")
        if not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
            raise FxError(f"Tipo de cambio inválido el {fila.get('fecha')}: {valor!r}")
        try:
            fechas.append(dt.date.fromisoformat(fila["fecha"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise FxError(f"Fecha inválida en la respuesta: {fila.get('fecha')!r}") from exc
        valores.append(float(valor))
    return pd.DataFrame({"fecha": fechas, "ars_por_usd": valores}, columns=["fecha", "ars_por_usd"])


def descargar_a3500(desde: dt.date, hasta: dt.date) -> pd.DataFrame:
    partes = []
    offset = 0
    total = None
    with requests.Session() as session:
        while total is None or offset < total:
            resp = session.get(
                URL,
                params={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "limit": LIMITE, "offset": offset},
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            parte = parsear_respuesta(payload)
            total_pagina = payload["metadata"]["resultset"]["count"]
            if total is not None and total_pagina != total:
                raise FxError(f"El total cambió entre páginas ({total} -> {total_pagina}).")
            total = total_pagina
            if parte.empty and offset < total:
                raise FxError(f"Página vacía en offset {offset} con {total} registros informados.")
            partes.append(parte)
            # Avanzamos por lo que efectivamente llegó: si el servidor capa el
            # tamaño de página por debajo de LIMITE, no salteamos registros.
            offset += len(parte)
    serie = pd.concat(partes, ignore_index=True)
    if len(serie) != total:
        raise FxError(f"Se esperaban {total} registros y llegaron {len(serie)}.")
    if serie["fecha"].duplicated().any():
        raise FxError("Fechas repetidas en la serie A3500.")
    return serie.sort_values("fecha").reset_index(drop=True)
