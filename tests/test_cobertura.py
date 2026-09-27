import datetime as dt

import numpy as np
import pandas as pd
import pytest

from coberturas.analisis import cobertura as cob

D = dt.date


class TestContratoCobertura:
    @pytest.mark.parametrize(
        "mes_salida, esperado",
        [
            (6, "SOJ.ROS/NOV24"),  # JUL vence opciones ~23/6: no sirve
            (7, "SOJ.ROS/NOV24"),
            (9, "SOJ.ROS/NOV24"),  # NOV24 = sep + 2
            (10, "SOJ.ROS/MAY25"),
            (11, "SOJ.ROS/MAY25"),
        ],
    )
    def test_primer_contrato_con_opciones_dos_meses_despues(self, mes_salida, esperado):
        assert cob.contrato_cobertura(2024, mes_salida) == esperado

    def test_salida_en_marzo_usa_mayo(self):
        assert cob.contrato_cobertura(2024, 3) == "SOJ.ROS/MAY24"


class TestRegimen:
    def test_normal(self):
        assert cob.regimen(D(2021, 3, 31), D(2021, 9, 30)) == "normal"

    def test_superposicion_parcial_con_dolar_soja(self):
        # Entra en mayo 2022, sale el 5/9/2022: primer día del PIE I.
        assert cob.regimen(D(2022, 5, 31), D(2022, 9, 5)) == "dolar_soja"
        assert cob.regimen(D(2022, 5, 31), D(2022, 9, 2)) == "normal"

    def test_dolar_soja_tiene_prioridad_sobre_blend(self):
        assert cob.regimen(D(2023, 11, 1), D(2024, 1, 31)) == "dolar_soja"

    def test_blend(self):
        assert cob.regimen(D(2024, 3, 28), D(2024, 9, 30)) == "blend"
        assert cob.regimen(D(2025, 4, 15), D(2025, 9, 30)) == "normal"


def _datos(con_put_salida=True, sc_ultimo_dia_entrada=False):
    """Una campaña 2021 mínima: entrada en marzo, salida en junio, contrato NOV21."""
    dias = [D(2021, 3, 30), D(2021, 3, 31), D(2021, 6, 29), D(2021, 6, 30)]
    fisico = pd.DataFrame(
        {
            "fecha": dias,
            "precio_usd_tn": [300.0, np.nan if sc_ultimo_dia_entrada else 301.0, 280.0, 281.0],
        }
    )
    futuros = pd.DataFrame(
        {
            "fecha": dias,
            "simbolo": ["SOJ.ROS/NOV21"] * 4,
            "ajuste": [305.0, 306.0, 284.0, 285.0],
        }
    )
    opciones = [
        (D(2021, 3, 30), "Put", 305.0, 12.0),
        (D(2021, 3, 31), "Put", 300.0, 9.0),
        (D(2021, 3, 31), "Put", 310.0, 14.0),  # |310-306|=4 < |300-306|=6: gana 310
        (D(2021, 3, 31), "Call", 300.0, 15.0),
        (D(2021, 3, 31), "Call", 311.0, 8.0),  # |311-306|=5 < 6: gana 311
        (D(2021, 6, 30), "Call", 311.0, 1.0),
    ]
    if con_put_salida:
        opciones.append((D(2021, 6, 30), "Put", 310.0, 26.0))
    opc = pd.DataFrame(opciones, columns=["fecha", "tipo", "strike", "ajuste"])
    opc["subyacente"] = "SOJ.ROS/NOV21"
    return fisico, futuros, opc


class TestEscenarios:
    def _fila(self, **kw):
        fisico, futuros, opc = _datos(**kw)
        esc = cob.escenarios(fisico, futuros, opc, range(2021, 2022))
        return esc[(esc["mes_entrada"] == 3) & (esc["mes_salida"] == 6)].iloc[0]

    def test_resultados_caso_a_y_b(self):
        f = self._fila()
        assert f["entrada"] == D(2021, 3, 31) and f["salida"] == D(2021, 6, 30)
        assert f["regimen"] == "normal"
        ds, df_ = 281.0 - 301.0, 285.0 - 306.0
        assert f["A_sin_cobertura"] == pytest.approx(ds)
        assert f["A_futuro"] == pytest.approx(ds - df_)  # = cambio de base = +1
        assert f["put_strike"] == 310.0  # más cercano a 306
        assert f["A_put"] == pytest.approx(ds + 26.0 - 14.0)
        assert f["B_sin_cobertura"] == pytest.approx(-ds)
        assert f["B_futuro"] == pytest.approx(-ds + df_)
        assert f["call_strike"] == 311.0
        assert f["B_call"] == pytest.approx(-ds + 1.0 - 8.0)

    def test_sin_prima_de_salida_la_opcion_queda_no_disponible(self):
        f = self._fila(con_put_salida=False)
        assert pd.isna(f["A_put"])
        assert f["A_futuro"] == pytest.approx((281.0 - 301.0) - (285.0 - 306.0))

    def test_dia_sin_fisico_usa_el_dia_anterior_del_mismo_mes(self):
        f = self._fila(sc_ultimo_dia_entrada=True)
        assert f["entrada"] == D(2021, 3, 30)
        assert f["s0"] == 300.0

    def test_mes_sin_datos_queda_no_disponible(self):
        fisico, futuros, opc = _datos()
        esc = cob.escenarios(fisico, futuros, opc, range(2021, 2022))
        abril = esc[esc["mes_entrada"] == 4].iloc[0]
        assert not abril["disponible"]

    def test_meses_futuros_se_omiten(self):
        fisico, futuros, opc = _datos()
        esc = cob.escenarios(fisico, futuros, opc, range(2021, 2022))
        # El dataset termina el 30/6/2021: no hay escenarios con salida jul-nov.
        assert set(esc["mes_salida"]) == {6}


class TestResumen:
    def test_efectividad_y_muestra_comun(self):
        esc = pd.DataFrame(
            {
                "campania": [2021, 2021, 2022],
                "disponible": [True, True, True],
                "regimen": ["normal"] * 3,
                "A_sin_cobertura": [-10.0, 10.0, 0.0],
                "A_futuro": [-1.0, 1.0, 0.0],
                "A_put": [2.0, 8.0, np.nan],  # la 3ra fila sale de la muestra común
            }
        )
        r = cob.resumen(esc, "A", {"normal"}).set_index("estrategia")
        assert r.loc["A_sin_cobertura", "n"] == 2
        assert r.loc["A_futuro", "efectividad"] == pytest.approx(1 - 2 / 200)
        assert r.loc["A_sin_cobertura", "efectividad"] == pytest.approx(0.0)
        assert r.loc["A_put", "peor"] == 2.0


def test_strike_empatado_elige_el_mas_bajo():
    opc = pd.DataFrame(
        {
            "fecha": [D(2021, 3, 31)] * 2,
            "subyacente": ["SOJ.ROS/NOV21"] * 2,
            "tipo": ["Call"] * 2,
            "strike": [312.0, 300.0],
            "ajuste": [8.0, 15.0],
        }
    )
    assert cob._strike_atm(opc, D(2021, 3, 31), "SOJ.ROS/NOV21", "Call", 306.0) == (300.0, 15.0)


class TestAuditoriaCodexCobertura:
    """Regresiones de la auditoría de Codex sobre cobertura.py (2026-09-27)."""

    def _esc(self):
        return pd.DataFrame(
            {
                "campania": [2021, 2021, 2022, 2023],
                "disponible": [True, True, True, True],
                "regimen": ["normal", "normal", "normal", "dolar_soja"],
                "A_sin_cobertura": [-10.0, 10.0, 30.0, 100.0],
                "A_futuro": [-1.0, 1.0, 3.0, 90.0],
                "A_put": [2.0, 8.0, np.nan, 50.0],
            }
        )

    def test_muestra_completa_no_recorta_futuros_por_falta_de_opciones(self):
        r = cob.resumen(self._esc(), "A", {"normal"}, muestra="completa").set_index("estrategia")
        assert r.loc["A_futuro", "n"] == 3
        assert r.loc["A_put", "n"] == 2
        r_comun = cob.resumen(self._esc(), "A", {"normal"}).set_index("estrategia")
        assert r_comun.loc["A_futuro", "n"] == 2

    def test_regimenes_no_se_mezclan(self):
        r = cob.resumen(self._esc(), "A", {"dolar_soja"}).set_index("estrategia")
        assert r.loc["A_sin_cobertura", "n"] == 1
        with pytest.raises(ValueError, match="desconocidos"):
            cob.resumen(self._esc(), "A", {"normales"})

    def test_mes_de_salida_incompleto_se_excluye(self):
        fisico, futuros, opc = _datos()
        # Datos hasta el 29/6: junio no terminó.
        futuros = futuros[futuros["fecha"] < D(2021, 6, 30)]
        esc = cob.escenarios(fisico, futuros, opc, range(2021, 2022))
        assert esc.empty
        assert "A_futuro" in esc.columns  # esquema estable aun sin filas

    def test_ajuste_no_finito_falla(self):
        fisico, futuros, opc = _datos()
        futuros.loc[0, "ajuste"] = np.nan
        with pytest.raises(cob.CoberturaError, match="Ajustes"):
            cob.escenarios(fisico, futuros, opc, range(2021, 2022))

    def test_prima_invalida_falla(self):
        fisico, futuros, opc = _datos()
        opc.loc[0, "ajuste"] = np.inf
        with pytest.raises(cob.CoberturaError, match="ajuste inválido"):
            cob.escenarios(fisico, futuros, opc, range(2021, 2022))

    def test_motivo_de_opcion_faltante(self):
        fisico, futuros, opc = _datos(con_put_salida=False)
        f = cob.escenarios(fisico, futuros, opc, range(2021, 2022)).iloc[0]
        assert f["put_motivo"] == "sin_prima_salida"
        assert pd.isna(f["call_motivo"])
        sin_entrada = opc[opc["tipo"] != "Put"]
        f2 = cob.escenarios(fisico, futuros, sin_entrada, range(2021, 2022)).iloc[0]
        assert f2["put_motivo"] == "sin_opcion_entrada"

    def test_sin_escenarios_disponibles_da_error_claro(self):
        esc = self._esc().assign(disponible=False)
        with pytest.raises(cob.CoberturaError, match="No hay escenarios"):
            cob.resumen(esc, "A", {"normal"})


class TestEquilibrioAlmacenaje:
    def test_ganancia_mensual_y_rendimiento_anual(self):
        esc = pd.DataFrame(
            {
                "campania": [2021],
                "mes_entrada": [3],
                "mes_salida": [9],
                "disponible": [True],
                "regimen": ["normal"],
                "entrada": [D(2021, 3, 31)],
                "salida": [D(2021, 9, 30)],
                "A_futuro": [12.0],
                "s0": [400.0],
            }
        )
        r = cob.equilibrio_almacenaje(esc, {"normal"}).iloc[0]
        meses = 183 / (365.25 / 12)
        assert r["meses"] == pytest.approx(meses)
        assert r["ganancia_mensual"] == pytest.approx(12.0 / meses)
        assert r["rendimiento_anual"] == pytest.approx(12.0 / 400.0 * 12 / meses)

    def test_filtra_regimen_y_rechaza_desconocido(self):
        esc = pd.DataFrame(
            {
                "campania": [2021, 2023], "mes_entrada": [3, 3], "mes_salida": [9, 9],
                "disponible": [True, True], "regimen": ["normal", "dolar_soja"],
                "entrada": [D(2021, 3, 31), D(2023, 3, 31)], "salida": [D(2021, 9, 30), D(2023, 9, 29)],
                "A_futuro": [12.0, 90.0], "s0": [400.0, 500.0],
            }
        )
        assert len(cob.equilibrio_almacenaje(esc, {"normal"})) == 1
        with pytest.raises(ValueError):
            cob.equilibrio_almacenaje(esc, {"otro"})
