"""Precios de ajuste de futuros y opciones agrícolas de A3 Mercados (ex Matba-Rofex).

Fuente: API pública que usa el sitio https://cem.matbarofex.com.ar/
    https://apicem.matbarofex.com.ar/api/v2/closing-prices
Sin login. Verificado el 2026-09-27: hay datos desde enero de 2020; para
fechas anteriores la API devuelve cero filas (en todos los productos de soja).

Consultas de varios años con paginado profundo fallan (HTTP 424 en la página
143 al pedir 2020-2026 de opciones): `descargar_serie` baja año por año.

Producto "SOJ Dolar MATba": futuros SOJ.ROS (USD/tn, entrega Rosario) y sus
opciones (prima en USD/tn, con strike y tipo Call/Put).
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pandas as pd
import requests

URL = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"
PAGE_SIZE = 1000
PRIMERA_FECHA_DISPONIBLE = dt.date(2020, 1, 1)

_TIPOS = {"FUT", "OPT"}


class A3Error(ValueError):
    """La respuesta de A3 no tiene el formato esperado o trae datos inválidos."""


def parsear_pagina(payload: dict, tipo: str) -> pd.DataFrame:
    """Convierte una página de la API en filas [fecha, simbolo, ..., ajuste]."""
    filas = payload.get("data")
    if filas is None:
        raise A3Error(f"Respuesta sin 'data': claves {sorted(payload)}")
    registros = []
    for fila in filas:
        ajuste = fila.get("settlement")
        # Una prima de 0 es válida (opción muy fuera del dinero); negativa o no finita, no.
        if not isinstance(ajuste, (int, float)) or not math.isfinite(ajuste) or ajuste < 0:
            raise A3Error(f"Precio de ajuste inválido en {fila.get('symbol')} {fila.get('dateTime')}: {ajuste!r}")
        tipo_opcion = fila.get("optionType")
        if tipo == "FUT" and tipo_opcion is not None:
            raise A3Error(f"Se pidieron futuros y llegó una opción: {fila.get('symbol')}")
        if not fila.get("symbol"):
            raise A3Error(f"Fila sin símbolo el {fila.get('dateTime')}")
        if tipo == "FUT" and ajuste == 0:
            raise A3Error(f"Futuro con ajuste 0: {fila.get('symbol')} {fila.get('dateTime')}")
        if tipo == "OPT":
            strike = fila.get("strikePrice")
            if tipo_opcion not in ("Call", "Put") or not isinstance(strike, (int, float)) or not math.isfinite(strike) or strike <= 0:
                raise A3Error(f"Opción sin tipo o strike válido: {fila.get('symbol')}")
            if not fila.get("underlying"):
                raise A3Error(f"Opción sin subyacente: {fila.get('symbol')}")
        registros.append(
            {
                "fecha": dt.date.fromisoformat(fila["dateTime"][:10]),
                "simbolo": fila["symbol"],
                "subyacente": fila.get("underlying") if tipo == "OPT" else fila["symbol"],
                "tipo": tipo_opcion or "Futuro",
                "strike": fila.get("strikePrice"),
                "ajuste": float(ajuste),
                "volumen": fila.get("volume"),
                "interes_abierto": fila.get("openInterest"),
            }
        )
    return pd.DataFrame(
        registros,
        columns=["fecha", "simbolo", "subyacente", "tipo", "strike", "ajuste", "volumen", "interes_abierto"],
    )


def descargar(
    desde: dt.date,
    hasta: dt.date,
    tipo: str,
    producto: str = "SOJ Dolar MATba",
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga todas las páginas de futuros (`FUT`) u opciones (`OPT`) del rango."""
    if tipo not in _TIPOS:
        raise ValueError(f"tipo debe ser uno de {sorted(_TIPOS)}")
    if desde < PRIMERA_FECHA_DISPONIBLE:
        raise ValueError(
            f"A3 no tiene datos antes de {PRIMERA_FECHA_DISPONIBLE}; pedir desde {desde} "
            "daría una serie incompleta sin avisar."
        )
    http = session or requests.Session()
    partes = []
    pagina = 1
    while True:
        resp = http.get(
            URL,
            params={
                "version": "v2",
                "product": producto,
                "type": tipo,
                "from": desde.isoformat(),
                "to": hasta.isoformat(),
                "pageSize": PAGE_SIZE,
                "page": pagina,
            },
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        partes.append(parsear_pagina(payload, tipo))
        total = payload.get("totalEntries")
        if total is None:
            raise A3Error("Respuesta sin 'totalEntries': no se puede saber si faltan páginas.")
        if pagina * PAGE_SIZE >= total:
            break
        pagina += 1

    serie = pd.concat(partes, ignore_index=True)
    if len(serie) != total:
        raise A3Error(f"Se esperaban {total} filas y llegaron {len(serie)}.")
    if serie.duplicated(["fecha", "simbolo"]).any():
        raise A3Error("Filas repetidas (misma fecha y símbolo).")
    return serie.sort_values(["fecha", "simbolo"]).reset_index(drop=True)


_COLUMNAS = ["fecha", "simbolo", "subyacente", "tipo", "strike", "ajuste", "volumen", "interes_abierto"]


def descargar_serie(
    desde_anio: int,
    hasta_anio: int,
    tipo: str,
    cache_dir: Path,
    producto: str = "SOJ Dolar MATba",
    hoy: dt.date | None = None,
) -> pd.DataFrame:
    """Serie multi-año bajada de a un año, cacheando en CSV solo años cerrados.

    Igual que en pizarra: el año en curso nunca se escribe a disco, así un
    archivo parcial no puede quedar tomado como completo.
    """
    hoy = hoy or dt.date.today()
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = producto.replace(" ", "_")
    partes = []
    with requests.Session() as session:
        for anio in range(desde_anio, hasta_anio + 1):
            archivo = cache_dir / f"a3_{slug}_{tipo}_{anio}.csv"
            if anio < hoy.year and archivo.exists():
                parte = pd.read_csv(archivo)
                # Conversión explícita: con un CSV vacío (año sin datos) pandas
                # no infiere dtype de fecha y `.dt` fallaría.
                parte["fecha"] = pd.to_datetime(parte["fecha"], format="%Y-%m-%d", errors="raise").dt.date
            else:
                parte = descargar(dt.date(anio, 1, 1), min(dt.date(anio, 12, 31), hoy), tipo, producto, session)
                if anio < hoy.year:
                    parte.to_csv(archivo, index=False)
            partes.append(parte[_COLUMNAS])
    serie = pd.concat(partes, ignore_index=True)
    if serie.duplicated(["fecha", "simbolo"]).any():
        raise A3Error("Filas repetidas entre años distintos.")
    return serie
