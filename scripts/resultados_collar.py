"""Imprime las tablas del README sobre opciones fuera del dinero y collar.

Uso: .venv/Scripts/python.exe scripts/resultados_collar.py
Usa los mismos datos (y la misma caché) que scripts/graficos.py.
"""

from __future__ import annotations

import pandas as pd
from graficos import cargar

from coberturas.analisis import cobertura as cob
from coberturas.analisis import collar
from coberturas.analisis import robustez as rob

MUESTRA = {"normal", "blend"}
SENSIBILIDAD = ((0.03, 0.015), (0.05, 0.02), (0.10, 0.03))


def main():
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    fisico, fut, opc = cargar()
    esc = cob.escenarios(fisico, fut, opc, range(2020, 2027))
    otm = collar.agregar_otm(esc, opc)
    for caso in "AB":
        print(f"\nCaso {caso}, muestra principal (cada estrategia con sus escenarios)")
        print(cob.resumen(otm, caso, MUESTRA, "completa", collar.ESTRATEGIAS_OTM).round(2))
        print(rob.intervalos_bootstrap(otm, caso, MUESTRA, estrategias=collar.ESTRATEGIAS_OTM).round(2))
        print(f"\nCaso {caso}, dólar soja")
        print(cob.resumen(otm, caso, {"dolar_soja"}, "completa", collar.ESTRATEGIAS_OTM).round(2))
    principal = otm[(otm["disponible"] == True) & otm["regimen"].isin(MUESTRA)]  # noqa: E712
    print("\nPrima neta del collar a la entrada (put - call), USD/tn")
    print(principal["collar_prima_neta"].describe().round(2))
    print("\nLiquidez de las patas fuera del dinero")
    print(collar.liquidez(otm, MUESTRA))
    par = collar.paridad_put_call(fut, opc)
    print(f"\nParidad put-call, strikes a <= 5% del futuro: {len(par)} pares")
    print(par["desvio"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(2))
    print("|desvío| <= 1 USD/tn:", round((par["desvio"].abs() <= 1).mean(), 3),
          "| <= 2 USD/tn:", round((par["desvio"].abs() <= 2).mean(), 3))
    sint = collar.comparar_put_sintetico(esc, opc)
    sint = sint[sint["regimen"].isin(MUESTRA)]
    print("\nPut sintético contra put (caso A, muestra principal)")
    print(sint["sintetico_motivo"].value_counts(dropna=False))
    ok = sint.dropna(subset=["A_put_sintetico"])
    print(ok["diferencia"].astype(float).abs().describe(percentiles=[0.5, 0.9]).round(2))
    var_sin = ok["A_sin_cobertura"].astype(float).var()
    for col in ("A_put", "A_put_sintetico"):
        print(col, "efectividad", round(1 - ok[col].astype(float).var() / var_sin, 3), "peor", round(ok[col].min(), 2))
    print("\nSensibilidad a la distancia del strike (muestra común)")
    for distancia, tolerancia in SENSIBILIDAD:
        con_distancia = collar.agregar_otm(esc, opc, distancia, tolerancia)
        for caso in "AB":
            r = cob.resumen(con_distancia, caso, MUESTRA, "comun", collar.ESTRATEGIAS_OTM)
            print(f"{distancia:.0%} {caso}", r[["estrategia", "n", "efectividad"]].round(2).to_dict("records")[3:])


if __name__ == "__main__":
    main()
