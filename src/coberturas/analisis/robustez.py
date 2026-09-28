"""Robustez del backtest: ratio de cobertura de mínima varianza e intervalos de confianza.

1. Ratio de mínima varianza (Ederington, 1979): h* = Cov(ΔS, ΔF) / Var(ΔF),
   con ΔS el cambio del precio físico y ΔF el del futuro de cobertura entre la
   entrada y la salida de cada escenario. El resultado cubierto del caso A es
   ΔS − h·ΔF; el del caso B es su opuesto, así que la efectividad es la misma.

   Se estima *fuera de muestra*, campaña por campaña: el h que se aplica a los
   escenarios de la campaña Y sale solo de escenarios de campañas anteriores,
   todos terminados (salida en noviembre como tarde) antes de la primera
   entrada de Y (marzo). La estimación excluye los escenarios de dólar soja:
   a la fecha de entrada esos períodos ya se conocían como anómalos. La
   pregunta de fondo es la de Wang, Wu y Yang (2015, Management Science):
   ¿un ratio estimado le gana al 1 a 1 con datos que no vio?

2. Intervalos de confianza por bootstrap de campañas: se remuestrean campañas
   enteras con reposición (los 18 escenarios de una campaña están muy
   correlacionados, remuestrear escenarios sueltos daría intervalos
   falsamente angostos). Con 6 campañas el bootstrap es tosco: los intervalos
   indican orden de magnitud de la incertidumbre, no una precisión fina.
   Además: (a) en `bootstrap_mejora_ratio` los ratios quedan fijos, así que el
   intervalo no incluye la incertidumbre de reestimarlos; (b) la efectividad
   se mide sobre escenarios superpuestos agrupados, no sobre resultados
   anuales de una cartera; (c) la proporción de remuestreos con mejora es una
   frecuencia del bootstrap, no una probabilidad posterior.
   Los remuestreos en los que una medida no está definida (sin datos de esa
   estrategia, o varianza sin cobertura igual a cero) se descartan y se
   informa cuántos quedaron válidos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from coberturas.analisis.cobertura import ESTRATEGIAS, CoberturaError

_REGIMENES_VALIDOS = {"normal", "blend", "dolar_soja"}


def _validar_regimenes(regimenes: set[str]) -> None:
    desconocidos = set(regimenes) - _REGIMENES_VALIDOS
    if desconocidos:
        raise ValueError(f"Regímenes desconocidos: {sorted(desconocidos)}")


def _disponibles(esc: pd.DataFrame, regimenes: set[str]) -> pd.DataFrame:
    _validar_regimenes(regimenes)
    sub = esc[(esc["disponible"] == True) & esc["regimen"].isin(regimenes)].copy()  # noqa: E712
    sub["dS"] = sub["s1"].astype(float) - sub["s0"].astype(float)
    sub["dF"] = sub["f1"].astype(float) - sub["f0"].astype(float)
    return sub


def ratio_minima_varianza(ds: pd.Series, df: pd.Series) -> float:
    """h* = Cov(ΔS, ΔF) / Var(ΔF). Error si hay menos de 2 datos o ΔF no varía."""
    ds, df = np.asarray(ds, dtype=float), np.asarray(df, dtype=float)
    if len(ds) != len(df) or len(ds) < 2:
        raise CoberturaError("Se necesitan al menos 2 escenarios para estimar el ratio.")
    if not (np.isfinite(ds).all() and np.isfinite(df).all()):
        raise CoberturaError("ΔS o ΔF con valores no finitos.")
    var_f = np.var(df, ddof=1)
    if var_f == 0:
        raise CoberturaError("El futuro no varía: el ratio no está definido.")
    return float(np.cov(ds, df, ddof=1)[0, 1] / var_f)


def ratios_fuera_de_muestra(
    esc: pd.DataFrame,
    regimenes_estimacion: set[str] = frozenset({"normal", "blend"}),
    min_campanias: int = 1,
) -> dict[int, float]:
    """h estimado para cada campaña con los escenarios de las campañas previas.

    Las campañas sin al menos `min_campanias` previas con datos no reciben h
    (no se inventa uno).
    """
    historia = _disponibles(esc, set(regimenes_estimacion))
    ratios = {}
    for campania in sorted(esc["campania"].unique()):
        previa = historia[historia["campania"] < campania]
        if previa["campania"].nunique() < min_campanias or len(previa) < 2:
            continue
        ratios[int(campania)] = ratio_minima_varianza(previa["dS"], previa["dF"])
    return ratios


def comparar_ratio(
    esc: pd.DataFrame,
    regimenes: set[str],
    ratios: dict[int, float],
) -> pd.DataFrame:
    """Caso A sin cobertura, 1 a 1 y mínima varianza fuera de muestra, sobre los mismos escenarios.

    Solo entran escenarios de campañas con ratio estimado. La efectividad es
    idéntica para el caso B (resultados con signo opuesto).
    """
    sub = _disponibles(esc, regimenes)
    sub = sub[sub["campania"].isin(ratios)]
    if len(sub) < 2:
        raise CoberturaError("No hay escenarios con ratio fuera de muestra.")
    h = sub["campania"].map(ratios).astype(float)
    resultados = {
        "sin_cobertura": sub["dS"],
        "ratio_1_a_1": sub["dS"] - sub["dF"],
        "minima_varianza_oos": sub["dS"] - h * sub["dF"],
    }
    var_sin = resultados["sin_cobertura"].var()
    filas = []
    for nombre, x in resultados.items():
        filas.append(
            {
                "estrategia": nombre,
                "n": len(x),
                "campanias": sub["campania"].nunique(),
                "media": x.mean(),
                "desvio": x.std(),
                "peor": x.min(),
                "efectividad": 1 - x.var() / var_sin,
            }
        )
    return pd.DataFrame(filas)


def intervalos_bootstrap(
    esc: pd.DataFrame,
    caso: str,
    regimenes: set[str],
    n: int = 5000,
    semilla: int = 0,
    nivel: float = 0.95,
) -> pd.DataFrame:
    """Intervalos para media y efectividad de cada estrategia, remuestreando campañas.

    Cada estrategia usa sus escenarios disponibles (igual que
    `resumen(..., muestra="completa")`), y su efectividad se calcula contra el
    resultado sin cobertura de esos mismos escenarios en cada remuestreo.
    """
    columnas = list(ESTRATEGIAS[caso])
    sub = _disponibles(esc, regimenes)
    campanias = np.array(sorted(sub["campania"].unique()))
    if len(campanias) < 2:
        raise CoberturaError("El bootstrap por campaña necesita al menos 2 campañas.")
    grupos = {c: sub[sub["campania"] == c] for c in campanias}
    rng = np.random.default_rng(semilla)
    alfa = (1 - nivel) / 2

    muestras = {col: {"media": [], "efectividad": []} for col in columnas}
    for _ in range(n):
        elegidas = rng.choice(campanias, size=len(campanias), replace=True)
        remuestra = pd.concat([grupos[c] for c in elegidas], ignore_index=True)
        for col in columnas:
            filas = remuestra.dropna(subset=[col])
            if len(filas) < 2:
                muestras[col]["media"].append(np.nan)
                muestras[col]["efectividad"].append(np.nan)
                continue
            x = filas[col].astype(float)
            var_sin = filas[columnas[0]].astype(float).var()
            muestras[col]["media"].append(x.mean())
            muestras[col]["efectividad"].append(1 - x.var() / var_sin if var_sin > 0 else np.nan)

    filas = []
    for col in columnas:
        # Una estrategia con datos en una sola campaña no admite bootstrap por campaña.
        soporte = sub.dropna(subset=[col])["campania"].nunique()
        media = np.array(muestras[col]["media"])
        efect = np.array(muestras[col]["efectividad"])
        media, efect = media[np.isfinite(media)], efect[np.isfinite(efect)]
        definido = soporte >= 2
        filas.append(
            {
                "estrategia": col,
                "campanias_con_datos": soporte,
                "media_inf": np.quantile(media, alfa) if definido and len(media) else np.nan,
                "media_sup": np.quantile(media, 1 - alfa) if definido and len(media) else np.nan,
                "efectividad_inf": np.quantile(efect, alfa) if definido and len(efect) else np.nan,
                "efectividad_sup": np.quantile(efect, 1 - alfa) if definido and len(efect) else np.nan,
                "remuestreos_validos": int(len(efect)) if definido else 0,
                "remuestreos": n,
            }
        )
    return pd.DataFrame(filas)


def bootstrap_mejora_ratio(
    esc: pd.DataFrame,
    regimenes: set[str],
    ratios: dict[int, float],
    n: int = 5000,
    semilla: int = 0,
    nivel: float = 0.95,
) -> dict:
    """¿La mínima varianza fuera de muestra le gana al 1 a 1? Bootstrap por campaña.

    Devuelve la mejora puntual de efectividad (mínima varianza − 1 a 1), su
    intervalo y la proporción de remuestreos con mejora positiva.
    """
    sub = _disponibles(esc, regimenes)
    sub = sub[sub["campania"].isin(ratios)].copy()
    campanias = np.array(sorted(sub["campania"].unique()))
    if len(campanias) < 2:
        raise CoberturaError("El bootstrap por campaña necesita al menos 2 campañas.")
    sub["uno"] = sub["dS"] - sub["dF"]
    sub["mv"] = sub["dS"] - sub["campania"].map(ratios).astype(float) * sub["dF"]

    def mejora(x: pd.DataFrame) -> float:
        var_sin = x["dS"].var()
        if not var_sin > 0:
            return np.nan
        return x["uno"].var() / var_sin - x["mv"].var() / var_sin

    punto = mejora(sub)
    if not np.isfinite(punto):
        raise CoberturaError("La varianza sin cobertura es cero: la mejora no está definida.")
    grupos = {c: sub[sub["campania"] == c] for c in campanias}
    rng = np.random.default_rng(semilla)
    difs = np.array(
        [mejora(pd.concat([grupos[c] for c in rng.choice(campanias, size=len(campanias))])) for _ in range(n)]
    )
    validos = difs[np.isfinite(difs)]
    if len(validos) == 0:
        raise CoberturaError("Ningún remuestreo válido.")
    alfa = (1 - nivel) / 2
    return {
        "mejora": float(punto),
        "inf": float(np.quantile(validos, alfa)),
        "sup": float(np.quantile(validos, 1 - alfa)),
        "frecuencia_mejora_positiva": float((validos > 0).mean()),
        "remuestreos_validos": int(len(validos)),
        "campanias": len(campanias),
    }
