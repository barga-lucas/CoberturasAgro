"""Base = precio físico Rosario (USD/tn) − precio de ajuste del futuro SOJ.ROS.

Convenciones (decididas el 2026-09-27):
- Precio físico: pizarra de la Cámara Arbitral en ARS/tn dividida por el tipo
  de cambio A3500 del BCRA del *mismo día*. Validación empírica: en períodos
  normales el futuro converge a este precio en su vencimiento con una
  diferencia mediana de ~4-5 USD/tn; con el A3500 del día anterior el resultado
  casi no cambia.
- Día sin pizarra ("S/C") o sin A3500: el precio físico queda NaN con su marca;
  nunca se rellena con el día anterior.
- Solo contratos SOJ.ROS/MMMAA (entrega Rosario). Otras modalidades
  (SOJ.EXP, SOJ.QQ, SOJ.DAI.BS...) se excluyen.
- "Posición cercana": el contrato líquido de vencimiento más próximo que
  todavía cotiza ese día. Se usa como referencia de mercado para describir la
  base, no como regla de cobertura del acopiador (eso va en otro módulo).

Todas las funciones son puras: reciben DataFrames ya descargados.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd

MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}

# Por volumen operado 2020-2026, los únicos meses con liquidez relevante.
MESES_LIQUIDOS = ("ENE", "MAY", "JUL", "SEP", "NOV")

_PATRON_ROS = re.compile(r"SOJ\.ROS/([A-Z]{3})(\d{2})")


class BaseError(ValueError):
    """Datos de entrada inconsistentes para calcular la base."""


def contratos_rosario(futuros: pd.DataFrame, meses: tuple[str, ...] = MESES_LIQUIDOS) -> pd.DataFrame:
    """Filtra futuros SOJ.ROS de los meses dados y agrega mes de contrato y estado.

    No hay un calendario oficial de vencimientos descargable, así que el
    estado se infiere con una regla conservadora sobre `ultimo_dia` (el último
    ajuste del contrato en todo el dataset):
    - "vencido": dejó de cotizar ya dentro de su mes de entrega o después
      (en los datos, el último día cae entre el ~15 del mes y los primeros
      días del mes siguiente) y antes del final del dataset.
    - "vivo": cotiza el último día del dataset.
    - "incierto": dejó de cotizar antes de su mes de entrega. No se lo trata
      como vencido.
    """
    if futuros.empty:
        raise BaseError("No hay futuros.")
    ultima_fecha = futuros["fecha"].max()
    partes = futuros["simbolo"].str.fullmatch(_PATRON_ROS.pattern)
    ros = futuros[partes].copy()
    extraido = ros["simbolo"].str.extract(_PATRON_ROS.pattern)
    desconocidos = set(extraido[0]) - set(MESES)
    if desconocidos:
        raise BaseError(f"Meses de contrato desconocidos: {sorted(desconocidos)}")
    ros["mes"] = extraido[0]
    ros["mes_contrato"] = [dt.date(2000 + int(a), MESES[m], 1) for m, a in zip(extraido[0], extraido[1])]
    ros = ros[ros["mes"].isin(meses)]
    ultimo = ros.groupby("simbolo")["fecha"].transform("max")
    ros["ultimo_dia"] = ultimo
    ros["estado"] = "incierto"
    ros.loc[ultimo == ultima_fecha, "estado"] = "vivo"
    ros.loc[(ultimo < ultima_fecha) & (ultimo >= ros["mes_contrato"]), "estado"] = "vencido"
    ros["vencido"] = ros["estado"] == "vencido"
    return ros.reset_index(drop=True)


def precio_fisico_usd(pizarra: pd.DataFrame, a3500: pd.DataFrame) -> pd.DataFrame:
    """Pizarra en USD/tn con el A3500 del mismo día. Columnas: fecha, precio_usd_tn, sin_cotizacion, sin_tc."""
    if a3500["fecha"].duplicated().any() or pizarra["fecha"].duplicated().any():
        raise BaseError("Fechas repetidas en pizarra o tipo de cambio.")
    unido = pizarra.merge(a3500, on="fecha", how="left", validate="one_to_one")
    unido["sin_tc"] = unido["ars_por_usd"].isna()
    unido["precio_usd_tn"] = unido["precio_ars_tn"] / unido["ars_por_usd"]
    return unido[["fecha", "precio_usd_tn", "sin_cotizacion", "sin_tc"]]


def serie_base(fisico: pd.DataFrame, contratos: pd.DataFrame) -> pd.DataFrame:
    """Base diaria contra la posición cercana.

    Para cada fecha con precio físico, toma el contrato de `mes_contrato` más
    próximo entre los que tienen ajuste ese mismo día. Si ese día no hay
    ningún contrato, la fila queda con base NaN (no se usa el ajuste de otro día).
    """
    if contratos.duplicated(["fecha", "simbolo"]).any():
        raise BaseError("Futuros con (fecha, símbolo) repetidos.")
    cercano = (
        contratos.sort_values(["fecha", "mes_contrato"])
        .groupby("fecha", as_index=False)
        .first()[["fecha", "simbolo", "mes_contrato", "ajuste", "ultimo_dia", "vencido"]]
    )
    serie = fisico.merge(cercano, on="fecha", how="left", validate="one_to_one")
    serie["base_usd_tn"] = serie["precio_usd_tn"] - serie["ajuste"]
    return serie


def base_al_vencimiento(
    fisico: pd.DataFrame,
    contratos: pd.DataFrame,
    dias_mercado: list[dt.date],
    ultimos_dias: int = 3,
) -> pd.DataFrame:
    """Base promedio en los últimos `ultimos_dias` días de mercado de cada contrato vencido.

    La ventana se arma con el calendario del mercado (`dias_mercado`: todas las
    fechas con algún ajuste en A3), no con las filas del contrato, así un día
    sin ajuste de ese contrato queda como faltante dentro de la ventana en vez
    de correrla hacia atrás. `dias_con_dato` dice cuántos días de la ventana
    tienen futuro y físico a la vez; con cero, la base es NaN.
    """
    calendario = sorted(set(dias_mercado))
    vencidos = contratos[contratos["vencido"]]
    filas = []
    for simbolo, grupo in vencidos.groupby("simbolo"):
        ultimo = grupo["ultimo_dia"].iloc[0]
        if ultimo not in calendario:
            raise BaseError(f"{simbolo}: su último día {ultimo} no está en el calendario de mercado.")
        fin = calendario.index(ultimo)
        ventana = pd.DataFrame({"fecha": calendario[max(0, fin - ultimos_dias + 1) : fin + 1]})
        v = ventana.merge(grupo[["fecha", "ajuste"]], on="fecha", how="left", validate="one_to_one")
        v = v.merge(fisico[["fecha", "precio_usd_tn"]], on="fecha", how="left", validate="one_to_one")
        v["base_usd_tn"] = v["precio_usd_tn"] - v["ajuste"]
        filas.append(
            {
                "simbolo": simbolo,
                "mes_contrato": grupo["mes_contrato"].iloc[0],
                "ultimo_dia": ultimo,
                "ajuste_final": grupo.loc[grupo["fecha"] == ultimo, "ajuste"].iloc[0],
                "base_usd_tn": v["base_usd_tn"].mean(),
                "dias_con_dato": int(v["base_usd_tn"].notna().sum()),
                "dias_ventana": len(v),
            }
        )
    columnas = ["simbolo", "mes_contrato", "ultimo_dia", "ajuste_final", "base_usd_tn", "dias_con_dato", "dias_ventana"]
    return pd.DataFrame(filas, columns=columnas).sort_values("ultimo_dia").reset_index(drop=True)
