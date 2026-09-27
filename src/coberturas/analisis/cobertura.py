"""Backtest de coberturas de un acopiador de soja en Rosario (USD/tn, 1 tn cubierta 1:1).

Dos casos, según la posición neta expuesta del acopio (BCR, Landrein, "Acopios"):

- Caso A, comprado en el disponible: compró soja "a precio" y la tiene en
  stock. Pierde si el precio baja. Coberturas: vender futuro o comprar put.
- Caso B, vendido en el disponible: recibió soja "a fijar" y la vendió "a
  precio" para liberar espacio; paga al productor el precio del día en que
  fija. Pierde si el precio sube. Coberturas: comprar futuro o comprar call.

Calendario (Rosa, BCR 2001): la soja entra entre marzo y mayo y el productor
fija entre junio y noviembre. Cada escenario es un par (mes de entrada, mes de
salida) de una campaña: 3 x 6 = 18 escenarios por año. Los escenarios de una
misma campaña están muy correlacionados: la muestra efectiva son las campañas,
no los escenarios.

Reglas (sin aproximaciones silenciosas):
- Día operativo de un mes: el último día de mercado del mes que tiene precio
  físico y ajuste del contrato de cobertura. Si no hay ninguno, el escenario
  queda no disponible. Ojo: si el último día no tiene precio y se usa uno
  anterior, eso se sabe recién después; por eso esto es una comparación
  retrospectiva mensual, no una regla de trading ejecutable en tiempo real.
- Solo meses completos: si los datos terminan antes del último día
  calendario del mes de salida, el escenario no se incluye.
- Contrato de cobertura, el mismo para futuros y opciones: el primer SOJ.ROS
  de MAY/JUL/NOV cuyo mes sea al menos dos meses posterior al mes de salida.
  Motivo: las opciones vencen ~el 23 del mes anterior al del contrato y solo
  MAY/JUL/NOV tienen opciones con liquidez; con este margen la opción sigue
  cotizando el día de salida.
- Opción: strike más cercano al futuro del día de entrada (empate: el más
  bajo). Se compra a la prima de ajuste de entrada y se vende a la prima de
  ajuste del día de salida (no se usa valor intrínseco). Si falta alguna de
  las dos primas, la estrategia con opciones queda no disponible y
  `put_motivo`/`call_motivo` dice por qué; las demás estrategias del
  escenario se siguen reportando (ver `resumen`).
- No se incluyen comisiones, costo financiero de márgenes ni de la prima.
- Régimen: si el período entrada-salida se superpone con un programa de
  dólar soja, el escenario se marca "dolar_soja" y se reporta aparte; si se
  superpone con el dólar blend 80/20, se marca "blend".
"""

from __future__ import annotations

import calendar as cal
import datetime as dt
import math
from dataclasses import dataclass

import pandas as pd

MESES_ENTRADA = (3, 4, 5)
MESES_SALIDA = (6, 7, 8, 9, 10, 11)
MESES_CON_OPCIONES = (5, 7, 11)
_NOMBRE_MES = {5: "MAY", 7: "JUL", 11: "NOV"}


@dataclass(frozen=True)
class Regimen:
    nombre: str
    tipo: str  # "dolar_soja" o "blend"
    desde: dt.date
    hasta: dt.date
    fuente: str


# Fechas verificadas en el texto de cada decreto (Boletín Oficial / InfoLEG).
REGIMENES = (
    Regimen("PIE I", "dolar_soja", dt.date(2022, 9, 5), dt.date(2022, 9, 30), "Decreto 576/2022"),
    Regimen("PIE II", "dolar_soja", dt.date(2022, 11, 28), dt.date(2022, 12, 30), "Decreto 787/2022"),
    Regimen("PIE III", "dolar_soja", dt.date(2023, 4, 10), dt.date(2023, 5, 31), "Decreto 194/2023"),
    Regimen(
        "PIE IV y prórrogas",
        "dolar_soja",
        dt.date(2023, 9, 5),
        dt.date(2023, 12, 10),
        "Decretos 443/2023, 492/2023, 549/2023, 597/2023",
    ),
    Regimen("Dólar blend 80/20", "blend", dt.date(2023, 12, 13), dt.date(2025, 4, 14), "Decreto 28/2023, derogado por 269/2025"),
)


class CoberturaError(ValueError):
    """Datos de entrada inconsistentes para el backtest."""


def contrato_cobertura(anio_salida: int, mes_salida: int) -> str:
    """Primer SOJ.ROS de MAY/JUL/NOV con mes >= mes de salida + 2."""
    minimo = anio_salida * 12 + (mes_salida - 1) + 2
    for anio in (anio_salida, anio_salida + 1):
        for mes in MESES_CON_OPCIONES:
            if anio * 12 + (mes - 1) >= minimo:
                return f"SOJ.ROS/{_NOMBRE_MES[mes]}{anio % 100:02d}"
    raise CoberturaError(f"Sin contrato para salida {mes_salida}/{anio_salida}")  # inalcanzable


def regimen(entrada: dt.date, salida: dt.date, regimenes=REGIMENES) -> str:
    """'dolar_soja' tiene prioridad sobre 'blend'; si no hay superposición, 'normal'."""
    tipos = {r.tipo for r in regimenes if r.desde <= salida and entrada <= r.hasta}
    if "dolar_soja" in tipos:
        return "dolar_soja"
    if "blend" in tipos:
        return "blend"
    return "normal"


def _finito(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _dia_operativo(anio: int, mes: int, calendario: list[dt.date], fisico: dict, futuros: dict, contrato: str):
    dias = [d for d in calendario if d.year == anio and d.month == mes]
    for d in sorted(dias, reverse=True):
        if _finito(fisico.get(d)) and (d, contrato) in futuros:
            return d
    return None


def _strike_atm(opciones: pd.DataFrame, fecha: dt.date, contrato: str, tipo: str, futuro: float):
    candidatas = opciones[
        (opciones["fecha"] == fecha) & (opciones["subyacente"] == contrato) & (opciones["tipo"] == tipo)
    ]
    if candidatas.empty:
        return None, None
    distancia = (candidatas["strike"] - futuro).abs()
    elegida = candidatas.assign(d=distancia).sort_values(["d", "strike"]).iloc[0]
    return float(elegida["strike"]), float(elegida["ajuste"])


def _prima(opciones: pd.DataFrame, fecha: dt.date, contrato: str, tipo: str, strike: float):
    fila = opciones[
        (opciones["fecha"] == fecha)
        & (opciones["subyacente"] == contrato)
        & (opciones["tipo"] == tipo)
        & (opciones["strike"] == strike)
    ]
    if len(fila) > 1:
        raise CoberturaError(f"Prima repetida {contrato} {tipo} {strike} {fecha}")
    return None if fila.empty else float(fila["ajuste"].iloc[0])


def escenarios(
    fisico: pd.DataFrame,
    futuros: pd.DataFrame,
    opciones: pd.DataFrame,
    anios: range,
) -> pd.DataFrame:
    """Una fila por (campaña, mes de entrada, mes de salida) con precios y resultados.

    `fisico`: salida de base.precio_fisico_usd. `futuros` y `opciones`: salida
    de data.a3 (columnas fecha, simbolo/subyacente, tipo, strike, ajuste).
    """
    if futuros.empty:
        raise CoberturaError("No hay futuros.")
    if futuros.duplicated(["fecha", "simbolo"]).any():
        raise CoberturaError("Futuros con (fecha, símbolo) repetidos.")
    no_finitos = [v for v in futuros["ajuste"] if not _finito(v) or v <= 0]
    if no_finitos:
        raise CoberturaError(f"Ajustes de futuros inválidos: {no_finitos[:5]}")
    for col in ("strike", "ajuste"):
        malos = [v for v in opciones[col] if not _finito(v) or v < 0]
        if malos:
            raise CoberturaError(f"Opciones con {col} inválido: {malos[:5]}")
    if fisico["fecha"].duplicated().any():
        raise CoberturaError("Precio físico con fechas repetidas.")
    calendario = sorted(set(futuros["fecha"]))
    ultima_fecha = calendario[-1]
    precio_fisico = dict(zip(fisico["fecha"], fisico["precio_usd_tn"]))
    ajuste = {(f, s): a for f, s, a in zip(futuros["fecha"], futuros["simbolo"], futuros["ajuste"])}

    filas = []
    for anio in anios:
        for mes_in in MESES_ENTRADA:
            for mes_out in MESES_SALIDA:
                contrato = contrato_cobertura(anio, mes_out)
                fila = {"campania": anio, "mes_entrada": mes_in, "mes_salida": mes_out, "contrato": contrato}
                fin_mes_salida = dt.date(anio, mes_out, cal.monthrange(anio, mes_out)[1])
                if fin_mes_salida > ultima_fecha:
                    continue  # el mes de salida no terminó (o no empezó) en los datos
                entrada = _dia_operativo(anio, mes_in, calendario, precio_fisico, ajuste, contrato)
                salida = _dia_operativo(anio, mes_out, calendario, precio_fisico, ajuste, contrato)
                fila.update(entrada=entrada, salida=salida)
                if entrada is None or salida is None:
                    fila["disponible"] = False
                    filas.append(fila)
                    continue
                s0, s1 = precio_fisico[entrada], precio_fisico[salida]
                f0, f1 = ajuste[(entrada, contrato)], ajuste[(salida, contrato)]
                fila.update(disponible=True, regimen=regimen(entrada, salida), s0=s0, s1=s1, f0=f0, f1=f1)

                ds, df_ = s1 - s0, f1 - f0
                resultado_opcion = {}
                for tipo, pref in (("Put", "put"), ("Call", "call")):
                    strike, p0 = _strike_atm(opciones, entrada, contrato, tipo, f0)
                    p1 = None if strike is None else _prima(opciones, salida, contrato, tipo, strike)
                    motivo = "sin_opcion_entrada" if strike is None else ("sin_prima_salida" if p1 is None else None)
                    fila.update({f"{pref}_strike": strike, f"{pref}_p0": p0, f"{pref}_p1": p1, f"{pref}_motivo": motivo})
                    resultado_opcion[pref] = None if motivo else p1 - p0

                # Caso A: comprado en el disponible.
                fila["A_sin_cobertura"] = ds
                fila["A_futuro"] = ds - df_
                fila["A_put"] = None if resultado_opcion["put"] is None else ds + resultado_opcion["put"]
                # Caso B: vendido en el disponible.
                fila["B_sin_cobertura"] = -ds
                fila["B_futuro"] = -ds + df_
                fila["B_call"] = None if resultado_opcion["call"] is None else -ds + resultado_opcion["call"]
                filas.append(fila)
    return pd.DataFrame(filas, columns=_COLUMNAS_ESCENARIO)


_COLUMNAS_ESCENARIO = [
    "campania", "mes_entrada", "mes_salida", "contrato", "entrada", "salida", "disponible", "regimen",
    "s0", "s1", "f0", "f1",
    "put_strike", "put_p0", "put_p1", "put_motivo", "call_strike", "call_p0", "call_p1", "call_motivo",
    "A_sin_cobertura", "A_futuro", "A_put", "B_sin_cobertura", "B_futuro", "B_call",
]


ESTRATEGIAS = {
    "A": ("A_sin_cobertura", "A_futuro", "A_put"),
    "B": ("B_sin_cobertura", "B_futuro", "B_call"),
}


def resumen(esc: pd.DataFrame, caso: str, regimenes: set[str], muestra: str = "comun") -> pd.DataFrame:
    """Estadísticos por estrategia para los regímenes pedidos (obligatorio: no se mezclan por defecto).

    `muestra="comun"`: solo escenarios donde las tres estrategias existen, para
    comparar sobre los mismos casos. `muestra="completa"`: cada estrategia con
    todos sus escenarios disponibles; así la ausencia de primas de opciones no
    recorta los resultados de futuros y sin cobertura.
    `efectividad` = 1 - varianza con cobertura / varianza sin cobertura, ambas
    sobre los escenarios de esa estrategia.
    """
    if muestra not in ("comun", "completa"):
        raise ValueError("muestra debe ser 'comun' o 'completa'")
    desconocidos = set(regimenes) - {"normal", "blend", "dolar_soja"}
    if desconocidos:
        raise ValueError(f"Regímenes desconocidos: {sorted(desconocidos)}")
    columnas = list(ESTRATEGIAS[caso])
    base_ok = esc[(esc["disponible"] == True) & esc["regimen"].isin(regimenes)]  # noqa: E712
    if base_ok.empty:
        raise CoberturaError("No hay escenarios disponibles para esos regímenes.")
    comun = base_ok.dropna(subset=columnas)
    if muestra == "comun" and comun.empty:
        raise CoberturaError("No hay escenarios con las tres estrategias disponibles.")
    filas = []
    for col in columnas:
        sub = comun if muestra == "comun" else base_ok.dropna(subset=[col])
        var_sin = sub[columnas[0]].astype(float).var()
        x = sub[col].astype(float)
        filas.append(
            {
                "estrategia": col,
                "n": len(x),
                "campanias": sub["campania"].nunique(),
                "media": x.mean(),
                "mediana": x.median(),
                "desvio": x.std(),
                "peor": x.min(),
                "mejor": x.max(),
                "efectividad": 1 - x.var() / var_sin if var_sin > 0 else float("nan"),
            }
        )
    return pd.DataFrame(filas)
