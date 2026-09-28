import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from coberturas.analisis import cobertura as cob
from coberturas.analisis import collar
from coberturas.analisis import robustez as rob

D = dt.date
C = "SOJ.ROS/NOV21"
E, S = D(2021, 3, 31), D(2021, 6, 30)


def _esc(**kw):
    fila = {
        "campania": 2021, "mes_entrada": 3, "mes_salida": 6, "contrato": C, "entrada": E, "salida": S,
        "disponible": True, "regimen": "normal", "s0": 290.0, "s1": 270.0, "f0": 300.0, "f1": 282.0,
    }
    fila.update(kw)
    fila["A_sin_cobertura"] = fila["s1"] - fila["s0"]
    fila["B_sin_cobertura"] = -fila["A_sin_cobertura"]
    return pd.DataFrame([fila])


def _opc(filas):
    """filas: (fecha, tipo, strike, ajuste[, volumen, interes_abierto])."""
    completas = [f if len(f) == 6 else f + (0, 10) for f in filas]
    df = pd.DataFrame(completas, columns=["fecha", "tipo", "strike", "ajuste", "volumen", "interes_abierto"])
    df["subyacente"] = C
    return df


# F0 = 300: objetivo put 285, objetivo call 315.
BASE = [
    (E, "Put", 280.0, 4.0),
    (E, "Put", 284.0, 5.0),  # |284-285| = 1: el elegido
    (E, "Put", 288.0, 7.0),
    (E, "Put", 304.0, 15.0),  # dentro del dinero: nunca se elige
    (E, "Call", 312.0, 8.0),
    (E, "Call", 316.0, 6.0),  # |316-315| = 1: el elegido
    (E, "Call", 296.0, 14.0),  # dentro del dinero
    (S, "Put", 284.0, 15.0),
    (S, "Call", 316.0, 1.0),
]


def _fila(esc=None, opc=None, **kw):
    out = collar.agregar_otm(_esc() if esc is None else esc, _opc(BASE) if opc is None else opc, **kw)
    return out.iloc[0]


class TestElegirStrike:
    def test_strike_mas_cercano_al_objetivo_de_cada_lado(self):
        f = _fila()
        assert f["put_otm_strike"] == 284.0 and f["put_otm_p0"] == 5.0 and f["put_otm_p1"] == 15.0
        assert f["call_otm_strike"] == 316.0 and f["call_otm_p0"] == 6.0 and f["call_otm_p1"] == 1.0

    def test_empate_elige_el_strike_mas_bajo(self):
        opc = _opc([(E, "Put", 283.0, 4.0), (E, "Put", 287.0, 6.0), (S, "Put", 283.0, 9.0), (S, "Put", 287.0, 11.0)])
        assert _fila(opc=opc)["put_otm_strike"] == 283.0

    def test_solo_opciones_dentro_del_dinero_no_se_usan(self):
        opc = _opc([(E, "Put", 304.0, 15.0), (S, "Put", 304.0, 25.0), (E, "Call", 296.0, 14.0), (S, "Call", 296.0, 1.0)])
        f = _fila(opc=opc)
        assert f["put_otm_motivo"] == "sin_opcion_entrada" and f["call_otm_motivo"] == "sin_opcion_entrada"
        assert f["A_collar"] is None and f["B_collar"] is None

    def test_strike_lejos_del_objetivo_no_se_reemplaza(self):
        # Único put fuera del dinero a -10%: con objetivo -5% y tolerancia 2% no sirve.
        opc = _opc([(E, "Put", 270.0, 2.0), (S, "Put", 270.0, 5.0), (E, "Call", 316.0, 6.0), (S, "Call", 316.0, 1.0)])
        f = _fila(opc=opc)
        assert f["put_otm_motivo"] == "sin_strike_cercano" and f["put_otm_strike"] is None
        assert f["A_put_otm"] is None and f["A_collar"] is None and f["B_collar"] is None
        assert f["B_call_otm"] == pytest.approx(20 + (1 - 6))

    @pytest.mark.parametrize("tipo, strike", [("Put", 279.0), ("Put", 291.0), ("Call", 309.0), ("Call", 321.0)])
    def test_tolerancia_en_el_limite_se_acepta(self, tipo, strike):
        # Con F0 = 300, objetivo ±5% y tolerancia 2%: los cuatro están justo en el borde
        # (291 / 300 - 0,95 da 0,020000000000000018 en punto flotante).
        opc = _opc([(E, tipo, strike, 4.0), (S, tipo, strike, 9.0)])
        pref = "put_otm" if tipo == "Put" else "call_otm"
        assert _fila(opc=opc)[f"{pref}_strike"] == strike

    def test_apenas_fuera_de_la_tolerancia_se_rechaza(self):
        opc = _opc([(E, "Put", 278.9, 4.0), (S, "Put", 278.9, 9.0)])
        assert _fila(opc=opc)["put_otm_motivo"] == "sin_strike_cercano"

    def test_empate_con_objetivo_decimal_elige_el_mas_bajo(self):
        # F0 = 101: objetivo call 106,05; 105,05 y 107,05 están a 1 exacto.
        esc = _esc(f0=101.0)
        opc = _opc([(E, "Call", 107.05, 1.0), (E, "Call", 105.05, 2.0), (S, "Call", 105.05, 3.0), (S, "Call", 107.05, 4.0)])
        assert _fila(esc=esc, opc=opc)["call_otm_strike"] == 105.05

    def test_otra_distancia(self):
        # 10%: objetivo put 270, objetivo call 330.
        opc = _opc(BASE + [(E, "Put", 272.0, 2.0), (S, "Put", 272.0, 8.0), (E, "Call", 328.0, 3.0), (S, "Call", 328.0, 0.5)])
        f = _fila(opc=opc, distancia=0.10, tolerancia=0.03)
        assert f["put_otm_strike"] == 272.0 and f["call_otm_strike"] == 328.0


class TestResultados:
    def test_formulas(self):
        f = _fila()
        ds = 270.0 - 290.0
        put, call = 15.0 - 5.0, 1.0 - 6.0
        assert f["A_put_otm"] == pytest.approx(ds + put)
        assert f["A_collar"] == pytest.approx(ds + put - call)
        assert f["B_call_otm"] == pytest.approx(-ds + call)
        assert f["B_collar"] == pytest.approx(-ds + call - put)
        assert f["B_collar"] == pytest.approx(-f["A_collar"])
        assert f["collar_prima_neta"] == pytest.approx(5.0 - 6.0)

    def test_sin_prima_de_salida(self):
        opc = _opc([r for r in BASE if not (r[0] == S and r[1] == "Call")])
        f = _fila(opc=opc)
        assert f["call_otm_motivo"] == "sin_prima_salida" and f["call_otm_strike"] == 316.0
        assert f["B_call_otm"] is None and f["A_collar"] is None
        assert f["A_put_otm"] == pytest.approx(-20 + 10)

    def test_escenario_no_disponible_pasa_sin_cambios(self):
        esc = pd.concat([_esc(), _esc(disponible=False, entrada=None, salida=None)], ignore_index=True)
        out = collar.agregar_otm(esc, _opc(BASE))
        assert len(out) == 2
        assert out.iloc[1]["disponible"] == False  # noqa: E712
        assert pd.isna(out.iloc[1]["A_collar"])

    def test_columnas_originales_no_cambian(self):
        esc = _esc()
        out = collar.agregar_otm(esc, _opc(BASE))
        pd.testing.assert_frame_equal(out[esc.columns], esc)


class TestLiquidezYValidaciones:
    def test_guarda_volumen_e_interes_abierto(self):
        opc = _opc([r + ((3, 50) if r[:3] == (E, "Put", 284.0) else (0, 10)) for r in BASE])
        f = _fila(opc=opc)
        assert f["put_otm_vol_entrada"] == 3 and f["put_otm_oi_entrada"] == 50
        assert f["call_otm_vol_entrada"] == 0 and f["put_otm_vol_salida"] == 0

    def test_volumen_desconocido_queda_nan(self):
        opc = _opc([r + (None, None) for r in BASE])
        f = _fila(opc=opc)
        assert math.isnan(f["put_otm_vol_entrada"]) and math.isnan(f["put_otm_oi_entrada"])

    def test_liquidez_cuenta_posiciones_unicas(self):
        # Dos escenarios con la misma entrada y strike, distintas salidas.
        s2 = D(2021, 7, 30)
        esc = pd.concat([_esc(), _esc(mes_salida=7, salida=s2)], ignore_index=True)
        filas = BASE + [(s2, "Put", 284.0, 12.0, 4, 10), (s2, "Call", 316.0, 0.5, None, 10)]
        filas = [r + ((2, 10) if r[:3] == (E, "Put", 284.0) else ()) for r in filas]
        out = collar.agregar_otm(esc, _opc(filas))
        liq = collar.liquidez(out, {"normal"}).set_index("pata")
        assert liq.loc["put_otm", "posiciones_entrada"] == 1
        assert liq.loc["put_otm", "con_volumen_entrada"] == 1
        assert liq.loc["put_otm", "posiciones_salida"] == 2
        assert liq.loc["put_otm", "con_volumen_salida"] == 1
        assert liq.loc["call_otm", "con_volumen_entrada"] == 0
        assert liq.loc["call_otm", "volumen_desconocido_salida"] == 1

    def test_liquidez_regimen_desconocido(self):
        with pytest.raises(ValueError):
            collar.liquidez(collar.agregar_otm(_esc(), _opc(BASE)), {"otro"})

    def test_faltan_columnas_de_liquidez(self):
        with pytest.raises(cob.CoberturaError, match="liquidez"):
            collar.agregar_otm(_esc(), _opc(BASE).drop(columns=["volumen"]))

    def test_opciones_repetidas(self):
        with pytest.raises(cob.CoberturaError, match="repetidos"):
            collar.agregar_otm(_esc(), _opc(BASE + [BASE[1]]))

    @pytest.mark.parametrize("distancia, tolerancia", [(0, 0), (1, 0.1), (0.05, 0.05), (0.05, -0.01)])
    def test_parametros_invalidos(self, distancia, tolerancia):
        with pytest.raises(ValueError):
            collar.agregar_otm(_esc(), _opc(BASE), distancia, tolerancia)


class TestConResumenYBootstrap:
    def _varias_campanias(self):
        rng = np.random.default_rng(1)
        filas = []
        for anio in (2020, 2021, 2022):
            for i in range(3):
                ds = float(rng.normal(0, 30))
                pp, pc = float(rng.normal(0, 5)), float(rng.normal(0, 5))
                filas.append(
                    {"campania": anio, "disponible": True, "regimen": "normal",
                     "A_sin_cobertura": ds, "A_futuro": ds * 0.2, "A_put": ds + pp,
                     "A_put_otm": ds + pp, "A_collar": ds + pp - pc,
                     "B_sin_cobertura": -ds, "B_futuro": -ds * 0.2, "B_call": -ds + pc,
                     "B_call_otm": -ds + pc, "B_collar": -ds + pc - pp,
                     "s0": 300.0, "s1": 300.0 + ds, "f0": 300.0, "f1": 300.0 + ds}
                )
        return pd.DataFrame(filas)

    def test_resumen_con_estrategias_otm(self):
        r = cob.resumen(self._varias_campanias(), "A", {"normal"}, "comun", collar.ESTRATEGIAS_OTM)
        assert list(r["estrategia"]) == list(collar.ESTRATEGIAS_OTM["A"])
        assert r.iloc[0]["efectividad"] == 0

    def test_resumen_por_defecto_no_cambia(self):
        r = cob.resumen(self._varias_campanias(), "B", {"normal"})
        assert list(r["estrategia"]) == list(cob.ESTRATEGIAS["B"])

    def test_bootstrap_con_estrategias_otm(self):
        r = rob.intervalos_bootstrap(self._varias_campanias(), "B", {"normal"}, n=50, estrategias=collar.ESTRATEGIAS_OTM)
        assert list(r["estrategia"]) == list(collar.ESTRATEGIAS_OTM["B"])
        assert (r["remuestreos_validos"] == 50).all()


class TestParidad:
    def _datos(self):
        fut = pd.DataFrame({"fecha": [E, E], "simbolo": [C, "SOJ.ROS/MAY22"], "ajuste": [300.0, 310.0]})
        opc = _opc(
            [
                (E, "Call", 296.0, 10.0),
                (E, "Put", 296.0, 6.5),  # C - P - (F - K) = 3.5 - 4 = -0.5
                (E, "Call", 304.0, 5.0),
                (E, "Put", 304.0, 9.0),  # 5 - 9 - (-4) = 0
                (E, "Call", 340.0, 1.0),
                (E, "Put", 340.0, 40.0),  # fuera de la banda del 5%
                (E, "Call", 308.0, 3.0),  # sin put del mismo strike
            ]
        )
        return fut, opc

    def test_desvio_y_banda(self):
        r = collar.paridad_put_call(*self._datos()).set_index("strike")
        assert list(r.index) == [296.0, 304.0]
        assert r.loc[296.0, "desvio"] == pytest.approx(-0.5)
        assert r.loc[304.0, "desvio"] == pytest.approx(0.0)

    def test_solo_su_propio_subyacente(self):
        fut, opc = self._datos()
        otro = opc.assign(subyacente="SOJ.ROS/MAY22")
        r = collar.paridad_put_call(fut, pd.concat([opc, otro], ignore_index=True))
        assert (r.loc[r["subyacente"] == "SOJ.ROS/MAY22", "futuro"] == 310.0).all()
        assert (r.loc[r["subyacente"] == C, "futuro"] == 300.0).all()

    def test_borde_de_la_banda_incluido(self):
        fut = pd.DataFrame({"fecha": [E], "simbolo": [C], "ajuste": [300.0]})
        opc = _opc([(E, "Call", 285.0, 16.0), (E, "Put", 285.0, 1.0), (E, "Call", 315.0, 1.0), (E, "Put", 315.0, 16.0)])
        assert sorted(collar.paridad_put_call(fut, opc)["strike"]) == [285.0, 315.0]

    def test_repetidos_y_parametros(self):
        fut, opc = self._datos()
        with pytest.raises(cob.CoberturaError):
            collar.paridad_put_call(fut, pd.concat([opc, opc.iloc[[0]]], ignore_index=True))
        with pytest.raises(cob.CoberturaError):
            collar.paridad_put_call(pd.concat([fut, fut.iloc[[0]]], ignore_index=True), opc)
        with pytest.raises(ValueError):
            collar.paridad_put_call(fut, opc, banda=0)


class TestPutSintetico:
    def _esc(self):
        esc = _esc()
        esc["put_strike"], esc["put_motivo"], esc["A_put"] = 300.0, None, -20.0 + (15.0 - 9.0)
        return esc

    def test_resultado_y_diferencia(self):
        opc = _opc([(E, "Call", 300.0, 8.0), (S, "Call", 300.0, 2.5)])
        r = collar.comparar_put_sintetico(self._esc(), opc).iloc[0]
        # ΔS = -20, ΔF = -18, call 2,5 - 8 = -5,5: -20 + 18 - 5,5 = -7,5.
        assert r["A_put_sintetico"] == pytest.approx(-7.5)
        assert r["diferencia"] == pytest.approx(-7.5 - (-14.0))

    def test_paridad_exacta_da_el_mismo_resultado(self):
        # C - P = F - K en las dos fechas: el sintético replica el put.
        esc = self._esc()
        esc["A_put"] = -20.0 + (19.0 - 2.0)  # put: 2 a la entrada (F0=300), 19 a la salida (F1=282)
        opc = _opc([(E, "Call", 300.0, 2.0), (S, "Call", 300.0, 1.0)])
        assert collar.comparar_put_sintetico(esc, opc).iloc[0]["diferencia"] == pytest.approx(0.0)

    @pytest.mark.parametrize("fecha, motivo", [(E, "sin_call_salida"), (S, "sin_call_entrada")])
    def test_falta_el_call(self, fecha, motivo):
        r = collar.comparar_put_sintetico(self._esc(), _opc([(fecha, "Call", 300.0, 5.0)])).iloc[0]
        assert r["sintetico_motivo"] == motivo and r["A_put_sintetico"] is None

    def test_sin_put_no_hay_comparacion(self):
        esc = self._esc()
        esc["put_motivo"] = "sin_prima_salida"
        assert collar.comparar_put_sintetico(esc, _opc([(E, "Call", 300.0, 5.0)])).empty
