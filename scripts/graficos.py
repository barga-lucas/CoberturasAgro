"""Genera los gráficos del README (versión clara y oscura) en docs/img/.

Uso: .venv/Scripts/python.exe scripts/graficos.py
Descarga (o lee de caché) los mismos datos que el análisis y recalcula todo.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from coberturas.analisis import base, collar, cobertura as cob  # noqa: E402
from coberturas.data import a3, fx, pizarra  # noqa: E402

SALIDA = RAIZ / "docs" / "img"
CACHE = RAIZ / "data" / "raw"

# Paleta de referencia validada (dataviz): slots 1-4 categóricos + tinta y superficie.
TEMAS = {
    "light": {
        "superficie": "#fcfcfb",
        "tinta": "#0b0b0b",
        "secundaria": "#52514e",
        "apagada": "#898781",
        "grilla": "#e1e0d9",
        "eje": "#c3c2b7",
        "banda": "#f0efec",
        "serie1": "#2a78d6",
        "serie2": "#eb6834",
        "serie3": "#1baf7a",
        "serie4": "#eda100",
        "neutra": "#898781",
    },
    "dark": {
        "superficie": "#1a1a19",
        "tinta": "#ffffff",
        "secundaria": "#c3c2b7",
        "apagada": "#898781",
        "grilla": "#2c2c2a",
        "eje": "#383835",
        "banda": "#383835",
        "serie1": "#3987e5",
        "serie2": "#d95926",
        "serie3": "#199e70",
        "serie4": "#c98500",
        "neutra": "#898781",
    },
}

FUENTE = ["Segoe UI", "DejaVu Sans", "sans-serif"]


def _estilo(ax, t):
    ax.set_facecolor(t["superficie"])
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(t["eje"])
    ax.tick_params(colors=t["apagada"], labelsize=9, length=0)
    ax.grid(axis="y", color=t["grilla"], linewidth=1)
    ax.set_axisbelow(True)


def _figura(t, ancho=10, alto=4.6, **kw):
    plt.rcParams["font.family"] = FUENTE
    fig, ax = plt.subplots(figsize=(ancho, alto), dpi=150, **kw)
    fig.patch.set_facecolor(t["superficie"])
    return fig, ax


def cargar():
    fut = a3.descargar_serie(2020, 2026, "FUT", CACHE / "a3")
    opc = a3.descargar_serie(2020, 2026, "OPT", CACHE / "a3")
    piz = pizarra.descargar_serie("soja", 2020, 2026, CACHE / "pizarra")
    tc = fx.descargar_a3500(dt.date(2020, 1, 1), dt.date.today())
    fisico = base.precio_fisico_usd(piz, tc)
    return fisico, fut, opc


def grafico_base(serie: pd.DataFrame, modo: str):
    t = TEMAS[modo]
    fig, ax = _figura(t)
    _estilo(ax, t)
    fechas = pd.to_datetime(serie["fecha"])

    for r in cob.REGIMENES:
        if r.tipo == "dolar_soja":
            ax.axvspan(pd.Timestamp(r.desde), pd.Timestamp(r.hasta), color=t["banda"], linewidth=0, zorder=0)
    ax.text(
        pd.Timestamp("2020-02-01"), 245, "Shaded: “dólar soja” export-FX program windows",
        color=t["secundaria"], fontsize=9, ha="left", va="center",
    )

    ax.axhline(0, color=t["eje"], linewidth=1, zorder=1)
    ax.plot(fechas, serie["base_usd_tn"], color=t["serie1"], linewidth=1.2, solid_joinstyle="round", zorder=2)

    ax.set_ylabel("USD per tonne", color=t["secundaria"], fontsize=9)
    ax.set_title(
        "Rosario soybean basis: physical price − nearby SOJ.ROS future",
        color=t["tinta"], fontsize=12, loc="left", pad=22, fontweight="bold",
    )
    ax.text(
        0, 1.02, "Daily, USD/t. Physical = Cámara Arbitral pizarra ÷ BCRA A3500. Gaps = days without a pizarra price.",
        transform=ax.transAxes, color=t["secundaria"], fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(SALIDA / f"base_{modo}.png", facecolor=t["superficie"])
    plt.close(fig)


def grafico_estrategias(esc: pd.DataFrame, modo: str):
    t = TEMAS[modo]
    regimenes = {"normal", "blend"}
    filas = [
        ("A", "A_sin_cobertura", "Unhedged", t["neutra"]),
        ("A", "A_futuro", "Short futures", t["serie1"]),
        ("A", "A_put", "Long put (at the money)", t["serie2"]),
        ("A", "A_put_otm", "Long put (5% out)", t["serie4"]),
        ("A", "A_collar", "Collar (±5%)", t["serie3"]),
        ("B", "B_sin_cobertura", "Unhedged", t["neutra"]),
        ("B", "B_futuro", "Long futures", t["serie1"]),
        ("B", "B_call", "Long call (at the money)", t["serie2"]),
        ("B", "B_call_otm", "Long call (5% out)", t["serie4"]),
        ("B", "B_collar", "Reverse collar (±5%)", t["serie3"]),
    ]
    resumenes = {
        c: cob.resumen(esc, c, regimenes, "completa", collar.ESTRATEGIAS_OTM).set_index("estrategia") for c in "AB"
    }
    datos = esc[(esc["disponible"] == True) & esc["regimen"].isin(regimenes)]  # noqa: E712

    plt.rcParams["font.family"] = FUENTE
    fig, ejes = plt.subplots(2, 1, figsize=(10, 6.2), dpi=150, sharex=True)
    fig.patch.set_facecolor(t["superficie"])
    titulos = {"A": "Case A — long physical (stock)", "B": "Case B — short physical (sold ahead)"}
    for ax, caso in zip(ejes, "AB"):
        _estilo(ax, t)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=t["grilla"], linewidth=1)
        ax.spines["bottom"].set_visible(False)
        ax.axvline(0, color=t["eje"], linewidth=1, zorder=1)
        propias = [f for f in filas if f[0] == caso]
        for i, (_, col, nombre, color) in enumerate(reversed(propias)):
            x = datos[col].dropna().astype(float)
            q1, med, q3 = x.quantile([0.25, 0.5, 0.75])
            ax.hlines(i, x.min(), x.max(), color=color, linewidth=2, zorder=2)
            ax.hlines(i, q1, q3, color=color, linewidth=9, zorder=3)
            ax.plot(med, i, "o", markersize=8, color=color, markeredgecolor=t["superficie"], markeredgewidth=2, zorder=4)
            ef = resumenes[caso].loc[col, "efectividad"]
            etiqueta = "" if col.endswith("sin_cobertura") else f"{ef:.0%} of risk removed"
            ax.text(x.max() + 6, i, etiqueta, va="center", fontsize=8.5, color=t["secundaria"])
        ax.set_yticks(range(len(propias)))
        ax.set_yticklabels([f[2] for f in reversed(propias)], color=t["tinta"], fontsize=9.5)
        ax.set_title(titulos[caso], color=t["tinta"], fontsize=10.5, loc="left", fontweight="bold")
        if caso == "B":
            ax.set_xlabel("Result, USD per tonne", color=t["secundaria"], fontsize=9)
        ax.set_xlim(-140, 190)
    fig.suptitle(
        "Hedging results per scenario, 2020–2026 (excluding “dólar soja” periods)",
        color=t["tinta"], fontsize=12, x=0.01, ha="left", fontweight="bold",
    )
    fig.text(
        0.01, 0.93, "Thin line = worst to best · thick bar = middle 50% · dot = median. Entry Mar–May, exit Jun–Nov.",
        color=t["secundaria"], fontsize=9, ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(SALIDA / f"estrategias_{modo}.png", facecolor=t["superficie"])
    plt.close(fig)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    fisico, fut, opc = cargar()
    serie = base.serie_base(fisico, base.contratos_rosario(fut))
    esc = collar.agregar_otm(cob.escenarios(fisico, fut, opc, range(2020, 2027)), opc)
    for modo in TEMAS:
        grafico_base(serie, modo)
        grafico_estrategias(esc, modo)
    print(f"Gráficos en {SALIDA}")


if __name__ == "__main__":
    main()
