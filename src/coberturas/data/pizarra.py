"""Precios pizarra de la Cámara Arbitral de Cereales de Rosario (CAC-BCR).

Fuente: https://www.cac.bcr.com.ar/es/precios-de-pizarra/consultas
El sitio expone un export a Excel por GET, sin login ni captcha. Rangos largos
(varios años) devuelven HTTP 500, por eso se descarga un año por request.

Unidad: pesos argentinos por tonelada (ARS/tn), precio pizarra del día de
operación. Si el export trae un valor no numérico o una fecha repetida, se
corta con error: preferimos no calcular antes que aproximar en silencio.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import unicodedata
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://www.cac.bcr.com.ar"
# Id del nodo de consultas en el CMS del sitio; aparece en el link de export.
EXPORT_PATH = "/es/api/prices/987/export"

SIN_COTIZACION = "S/C"

PRODUCTOS = {"trigo": 8, "maiz": 3, "girasol": 9, "soja": 13, "sorgo": 6}

_HEADERS = {"User-Agent": "Mozilla/5.0 (CoberturasAgro research project)"}


class PizarraError(ValueError):
    """El export no tiene el formato esperado o trae datos inválidos."""


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.strip().lower()


def descargar_anio(producto: str, anio: int, session: requests.Session | None = None) -> bytes:
    """Descarga el export Excel de un producto para un año calendario."""
    if producto not in PRODUCTOS:
        raise ValueError(f"Producto desconocido: {producto!r}. Opciones: {sorted(PRODUCTOS)}")
    params = {
        "product": PRODUCTOS[producto],
        "type": "pizarra",
        "date_start": f"{anio}-01-01",
        "date_end": f"{anio}-12-31",
        "period": "day",
    }
    http = session or requests
    resp = http.get(BASE_URL + EXPORT_PATH, params=params, headers=_HEADERS, timeout=60)
    resp.raise_for_status()
    if "excel" not in resp.headers.get("Content-Type", ""):
        raise PizarraError(
            f"Respuesta inesperada para {producto} {anio}: Content-Type "
            f"{resp.headers.get('Content-Type')!r}"
        )
    return resp.content


def parsear_export(contenido: bytes, producto: str, anio: int | None = None) -> pd.DataFrame:
    """Convierte el Excel del export en un DataFrame [fecha, precio_ars_tn, sin_cotizacion].

    Layout observado (2024): fila con el nombre del producto, fila de encabezado
    "Fecha de operación" | "Precio", y luego una fila por día. Si se pasa
    `anio`, toda fecha fuera de ese año es un error (el export se pide por año).
    """
    crudo = pd.read_excel(io.BytesIO(contenido), header=None, dtype=object)

    fila_header = None
    for i, valor in crudo[0].items():
        if isinstance(valor, str) and _normalizar(valor).startswith("fecha"):
            fila_header = i
            break
    if fila_header is None:
        raise PizarraError("No se encontró la fila de encabezado 'Fecha de operación'.")
    if _normalizar(str(crudo.iat[fila_header, 1])) != "precio":
        raise PizarraError(f"Encabezado inesperado en columna de precio: {crudo.iat[fila_header, 1]!r}")

    nombres_producto = [
        _normalizar(v) for v in crudo.loc[: fila_header - 1, 0] if isinstance(v, str)
    ]
    if _normalizar(producto) not in nombres_producto:
        raise PizarraError(
            f"El export no corresponde a {producto!r} (encontrado: {nombres_producto})."
        )

    datos = crudo.loc[fila_header + 1 :, [0, 1]].dropna(how="all")
    datos.columns = ["fecha", "precio_ars_tn"]

    # Solo se aceptan celdas que ya son fechas: un número suelto (serial de
    # Excel sin formato) se convertiría en silencio a una fecha de 1970.
    no_fecha = datos["fecha"].map(lambda v: not isinstance(v, (dt.datetime, dt.date)))
    fechas = pd.to_datetime(datos["fecha"].where(~no_fecha), errors="coerce")
    # "S/C" = sin cotización: la Cámara no fijó pizarra ese día. Es un dato del
    # mercado, no un error; queda como faltante explícito, nunca rellenado.
    sin_cotizacion = datos["precio_ars_tn"].map(
        lambda v: isinstance(v, str) and v.strip().upper() == SIN_COTIZACION
    )
    precios = pd.to_numeric(datos["precio_ars_tn"].where(~sin_cotizacion), errors="coerce")
    no_finitos = precios.map(lambda v: pd.notna(v) and not math.isfinite(v))
    invalidas = datos[fechas.isna() | (precios.isna() & ~sin_cotizacion) | no_finitos]
    if not invalidas.empty:
        raise PizarraError(
            f"{len(invalidas)} fila(s) con fecha o precio no numérico, primeras: "
            f"{invalidas.head(5).to_dict('records')}"
        )

    # El export guarda la fecha como medianoche en UTC-3 (03:00 UTC), y en años
    # viejos con la hora de carga: nos quedamos con el día calendario.
    serie = pd.DataFrame(
        {
            "fecha": fechas.dt.date,
            "precio_ars_tn": precios.astype(float),
            "sin_cotizacion": sin_cotizacion.astype(bool),
        }
    )
    repetidas = serie[serie["fecha"].duplicated(keep=False)]
    if not repetidas.empty:
        raise PizarraError(f"Fechas repetidas en el export: {sorted(set(repetidas['fecha']))[:5]}")
    if (serie["precio_ars_tn"] <= 0).any():
        raise PizarraError("Hay precios menores o iguales a cero.")
    if anio is not None:
        fuera = serie[serie["fecha"].map(lambda d: d.year != anio)]
        if not fuera.empty:
            raise PizarraError(f"Fechas fuera de {anio} en el export: {list(fuera['fecha'][:5])}")

    return serie.sort_values("fecha").reset_index(drop=True)


def descargar_serie(
    producto: str,
    desde_anio: int,
    hasta_anio: int,
    cache_dir: Path,
    hoy: dt.date | None = None,
) -> pd.DataFrame:
    """Serie diaria multi-año, cacheando cada año en `cache_dir`.

    Solo se cachean años que ya estaban cerrados al momento de descargarlos;
    el año en curso se descarga siempre y nunca se escribe a disco, así un
    archivo parcial no puede quedar tomado como completo cuando cambia el año.
    """
    anio_actual = (hoy or dt.date.today()).year
    cache_dir.mkdir(parents=True, exist_ok=True)
    partes = []
    with requests.Session() as session:
        for anio in range(desde_anio, hasta_anio + 1):
            archivo = cache_dir / f"pizarra_{producto}_{anio}.xlsx"
            if anio < anio_actual and archivo.exists():
                contenido = archivo.read_bytes()
            else:
                contenido = descargar_anio(producto, anio, session)
                if anio < anio_actual:
                    archivo.write_bytes(contenido)
            partes.append(parsear_export(contenido, producto, anio))
    serie = pd.concat(partes, ignore_index=True)
    if serie["fecha"].duplicated().any():
        raise PizarraError("Fechas repetidas entre años distintos.")
    return serie
