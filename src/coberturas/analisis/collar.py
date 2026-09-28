"""Opciones fuera del dinero y collar, sobre los mismos escenarios de `cobertura.escenarios`.

Mismo contrato, mismas fechas de entrada y salida y misma regla de primas
(compra y venta a la prima de ajuste) que el backtest principal. Lo nuevo:

- Put fuera del dinero: strike más cercano a F0 x (1 - distancia), entre los
  puts con strike < F0. Call fuera del dinero: más cercano a F0 x (1 + distancia),
  entre los calls con strike > F0. Empate: el strike más bajo.
- Si el strike elegido se aleja del objetivo más que `tolerancia` (en
  proporción de F0), la pata queda no disponible ("sin_strike_cercano"): no se
  reemplaza por una opción de otra distancia sin avisar.
- Caso A (comprado): put fuera del dinero solo, o collar = comprar ese put y
  vender ese call. Caso B (vendido): call fuera del dinero solo, o collar
  inverso = comprar el call y vender el put. Ambos collars usan las mismas dos
  patas. El collar existe solo si existen las dos patas.
- `collar_prima_neta` = prima del put - prima del call a la entrada (lo que
  paga el caso A; el caso B cobra lo mismo). Cercana a cero = "collar de costo cero".

Liquidez: A3 publica un precio de ajuste para cada strike listado aunque ese
día no se haya operado. Para las opciones fuera del dinero eso es lo habitual,
así que sus primas son en buena parte teóricas. Por eso cada pata guarda el
volumen y el interés abierto del día de entrada y el volumen del de salida, y
`liquidez` resume cuántas veces hubo operaciones. Vender un call en el collar
además exige margen, cuyo costo financiero no se incluye (igual que en
`cobertura`).
"""

from __future__ import annotations

import math

import pandas as pd

from coberturas.analisis.cobertura import CoberturaError

DISTANCIA = 0.05
TOLERANCIA = 0.02

ESTRATEGIAS_OTM = {
    "A": ("A_sin_cobertura", "A_futuro", "A_put", "A_put_otm", "A_collar"),
    "B": ("B_sin_cobertura", "B_futuro", "B_call", "B_call_otm", "B_collar"),
}

_PATAS = (("put_otm", "Put", -1), ("call_otm", "Call", +1))

# Margen para comparar distancias y bandas: 291 / 300 - 0,95 da 0,020000000000000018
# en punto flotante, y un strike justo en el límite no debe quedar afuera.
_EPS = 1e-9


def _numero(v) -> float:
    """Volumen o interés abierto: None/NaN quedan como NaN (dato desconocido, no cero)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return math.nan
    return float(v)


def _elegir_strike(cands: pd.DataFrame, f0: float, signo: int, distancia: float, tolerancia: float):
    lado = cands[(cands["strike"] - f0) * signo > 0]
    if lado.empty:
        return None, "sin_opcion_entrada"
    objetivo = f0 * (1 + signo * distancia)
    # Redondeo para que un empate exacto (p. ej. 105,05 y 107,05 con objetivo 106,05)
    # no se rompa por error de punto flotante: gana el strike más bajo.
    distancias = (lado["strike"] - objetivo).abs().round(9)
    elegida = lado.assign(d=distancias).sort_values(["d", "strike"]).iloc[0]
    if abs(elegida["strike"] / f0 - (1 + signo * distancia)) > tolerancia + _EPS:
        return None, "sin_strike_cercano"
    return elegida, None


def agregar_otm(
    esc: pd.DataFrame,
    opciones: pd.DataFrame,
    distancia: float = DISTANCIA,
    tolerancia: float = TOLERANCIA,
) -> pd.DataFrame:
    """Copia de `esc` con las columnas de las patas fuera del dinero y los resultados."""
    if not 0 < distancia < 1 or not 0 <= tolerancia < distancia:
        raise ValueError("Se necesita 0 < distancia < 1 y 0 <= tolerancia < distancia.")
    faltan = {"volumen", "interes_abierto"} - set(opciones.columns)
    if faltan:
        raise CoberturaError(f"Opciones sin columnas de liquidez: {sorted(faltan)}")
    if opciones.duplicated(["fecha", "subyacente", "tipo", "strike"]).any():
        raise CoberturaError("Opciones con (fecha, subyacente, tipo, strike) repetidos.")
    indice = {k: g for k, g in opciones.groupby(["fecha", "subyacente", "tipo"])}

    filas = []
    for fila in esc.to_dict("records"):
        fila = dict(fila)
        if fila.get("disponible") is not True:
            filas.append(fila)
            continue
        entrada, salida, contrato, f0 = fila["entrada"], fila["salida"], fila["contrato"], fila["f0"]
        resultado = {}
        for pref, tipo, signo in _PATAS:
            cands = indice.get((entrada, contrato, tipo), opciones.iloc[0:0])
            elegida, motivo = _elegir_strike(cands, f0, signo, distancia, tolerancia)
            strike = p0 = p1 = vol1 = None
            vol0 = oi0 = math.nan
            if elegida is not None:
                strike, p0 = float(elegida["strike"]), float(elegida["ajuste"])
                vol0, oi0 = _numero(elegida["volumen"]), _numero(elegida["interes_abierto"])
                en_salida = indice.get((salida, contrato, tipo), opciones.iloc[0:0])
                en_salida = en_salida[en_salida["strike"] == strike]
                if en_salida.empty:
                    motivo = "sin_prima_salida"
                else:
                    p1 = float(en_salida["ajuste"].iloc[0])
                    vol1 = _numero(en_salida["volumen"].iloc[0])
            fila.update(
                {
                    f"{pref}_strike": strike,
                    f"{pref}_p0": p0,
                    f"{pref}_p1": p1,
                    f"{pref}_motivo": motivo,
                    f"{pref}_vol_entrada": vol0,
                    f"{pref}_oi_entrada": oi0,
                    f"{pref}_vol_salida": math.nan if vol1 is None else vol1,
                }
            )
            resultado[pref] = None if motivo else p1 - p0

        ds = fila["s1"] - fila["s0"]
        put, call = resultado["put_otm"], resultado["call_otm"]
        ambas = put is not None and call is not None
        fila["collar_prima_neta"] = fila["put_otm_p0"] - fila["call_otm_p0"] if ambas else None
        fila["A_put_otm"] = None if put is None else ds + put
        fila["A_collar"] = ds + put - call if ambas else None
        fila["B_call_otm"] = None if call is None else -ds + call
        fila["B_collar"] = -ds + call - put if ambas else None
        filas.append(fila)
    return pd.DataFrame(filas)


def liquidez(esc_otm: pd.DataFrame, regimenes: set[str]) -> pd.DataFrame:
    """Por pata: en cuántas posiciones hubo operaciones el día de entrada y el de salida.

    Cuenta posiciones únicas (fecha de entrada, contrato, strike) para la
    entrada y (fecha de salida, contrato, strike) para la salida: varios
    escenarios comparten la misma opción y contarlos repetidos inflaría la
    muestra. Volumen o interés abierto desconocidos se informan aparte.
    """
    desconocidos = set(regimenes) - {"normal", "blend", "dolar_soja"}
    if desconocidos:
        raise ValueError(f"Regímenes desconocidos: {sorted(desconocidos)}")
    sub = esc_otm[(esc_otm["disponible"] == True) & esc_otm["regimen"].isin(regimenes)]  # noqa: E712
    filas = []
    for pref, _, _ in _PATAS:
        usadas = sub[sub[f"{pref}_motivo"].isna()]
        ent = usadas.drop_duplicates(["entrada", "contrato", f"{pref}_strike"])
        sal = usadas.drop_duplicates(["salida", "contrato", f"{pref}_strike"])
        vol0, oi0, vol1 = ent[f"{pref}_vol_entrada"], ent[f"{pref}_oi_entrada"], sal[f"{pref}_vol_salida"]
        filas.append(
            {
                "pata": pref,
                "posiciones_entrada": len(ent),
                "con_volumen_entrada": int((vol0 > 0).sum()),
                "con_interes_abierto_entrada": int((oi0 > 0).sum()),
                "volumen_desconocido_entrada": int(vol0.isna().sum()),
                "posiciones_salida": len(sal),
                "con_volumen_salida": int((vol1 > 0).sum()),
                "volumen_desconocido_salida": int(vol1.isna().sum()),
            }
        )
    return pd.DataFrame(filas)


def paridad_put_call(futuros: pd.DataFrame, opciones: pd.DataFrame, banda: float = 0.05) -> pd.DataFrame:
    """Desvío de la paridad put-call en los precios de ajuste de A3: C - P - (F - K).

    Un put sintético (vender futuro + comprar call del mismo strike) replica un
    put si C - P = F - K. Esto mide la paridad en un solo día; si una cobertura
    sintética rinde lo mismo que el put entre la entrada y la salida lo mide
    `comparar_put_sintetico`. Se compara cada par call/put del mismo día,
    subyacente y strike, con |K / F - 1| <= `banda`. Se ignora el descuento de
    (F - K) por el tiempo hasta el pago: con |F - K| <= 5% de F y tasas en
    dólares de un dígito, son centavos por tonelada.
    """
    if not 0 < banda < 1:
        raise ValueError("banda debe estar entre 0 y 1.")
    faltan = {"volumen"} - set(opciones.columns)
    if faltan:
        raise CoberturaError(f"Opciones sin columnas: {sorted(faltan)}")
    claves = ["fecha", "subyacente", "strike"]
    columnas = claves + ["ajuste", "volumen"]
    calls = opciones.loc[opciones["tipo"] == "Call", columnas]
    puts = opciones.loc[opciones["tipo"] == "Put", columnas]
    if calls.duplicated(claves).any() or puts.duplicated(claves).any():
        raise CoberturaError("Opciones con (fecha, subyacente, strike) repetidos.")
    fut = futuros[["fecha", "simbolo", "ajuste"]].rename(columns={"simbolo": "subyacente", "ajuste": "futuro"})
    if fut.duplicated(["fecha", "subyacente"]).any():
        raise CoberturaError("Futuros con (fecha, símbolo) repetidos.")
    pares = calls.merge(puts, on=claves, suffixes=("_call", "_put")).merge(fut, on=["fecha", "subyacente"])
    pares["distancia"] = pares["strike"] / pares["futuro"] - 1
    pares = pares[pares["distancia"].abs() <= banda + _EPS].copy()
    pares["desvio"] = pares["ajuste_call"] - pares["ajuste_put"] - (pares["futuro"] - pares["strike"])
    return pares.reset_index(drop=True)


def comparar_put_sintetico(esc: pd.DataFrame, opciones: pd.DataFrame) -> pd.DataFrame:
    """Caso A: put en el dinero del backtest contra put sintético del mismo strike.

    Put sintético = vender el futuro de cobertura + comprar el call del strike
    del put, con las mismas fechas y la misma regla de primas. Resultado:
    ΔS - ΔF + (C1 - C0). La diferencia con A_put es el cambio del desvío de
    paridad entre la entrada y la salida. Sin call de ese strike en alguna de
    las dos fechas, el escenario queda sin sintético y `sintetico_motivo` dice
    por qué.
    """
    claves = ["fecha", "subyacente", "strike"]
    calls = opciones.loc[opciones["tipo"] == "Call", claves + ["ajuste"]]
    if calls.duplicated(claves).any():
        raise CoberturaError("Calls con (fecha, subyacente, strike) repetidos.")
    prima = {(f, u, k): a for f, u, k, a in calls.itertuples(index=False)}
    sub = esc[(esc["disponible"] == True) & esc["put_motivo"].isna()].copy()  # noqa: E712
    filas = []
    for fila in sub.to_dict("records"):
        c0 = prima.get((fila["entrada"], fila["contrato"], fila["put_strike"]))
        c1 = prima.get((fila["salida"], fila["contrato"], fila["put_strike"]))
        motivo = "sin_call_entrada" if c0 is None else ("sin_call_salida" if c1 is None else None)
        sintetico = None
        if motivo is None:
            sintetico = fila["s1"] - fila["s0"] - (fila["f1"] - fila["f0"]) + (c1 - c0)
        filas.append(
            {
                "campania": fila["campania"], "mes_entrada": fila["mes_entrada"], "mes_salida": fila["mes_salida"],
                "regimen": fila["regimen"], "strike": fila["put_strike"], "A_sin_cobertura": fila["A_sin_cobertura"],
                "A_put": fila["A_put"], "A_put_sintetico": sintetico, "sintetico_motivo": motivo,
                "diferencia": None if sintetico is None else sintetico - fila["A_put"],
            }
        )
    return pd.DataFrame(filas)
