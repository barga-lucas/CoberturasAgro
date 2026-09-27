import datetime as dt

import numpy as np
import pandas as pd
import pytest

from coberturas.analisis import base

D = dt.date


def _fut(filas):
    return pd.DataFrame(filas, columns=["fecha", "simbolo", "ajuste"])


def _contratos():
    futuros = _fut(
        [
            (D(2024, 5, 27), "SOJ.ROS/MAY24", 300.0),
            (D(2024, 5, 27), "SOJ.ROS/JUL24", 310.0),
            (D(2024, 5, 28), "SOJ.ROS/MAY24", 302.0),
            (D(2024, 5, 28), "SOJ.ROS/JUL24", 311.0),
            (D(2024, 5, 29), "SOJ.ROS/JUL24", 312.0),
            (D(2024, 5, 29), "SOJ.ROS/JUN24", 305.0),  # mes no líquido
            (D(2024, 5, 29), "SOJ.EXP/JUL24", 320.0),  # otra modalidad
        ]
    )
    return base.contratos_rosario(futuros)


def _fisico(filas):
    return pd.DataFrame(filas, columns=["fecha", "precio_usd_tn", "sin_cotizacion", "sin_tc"])


class TestContratos:
    def test_filtra_modalidad_y_meses_iliquidos(self):
        assert set(_contratos()["simbolo"]) == {"SOJ.ROS/MAY24", "SOJ.ROS/JUL24"}

    def test_mes_contrato_y_vencido(self):
        c = _contratos().drop_duplicates("simbolo").set_index("simbolo")
        assert c.loc["SOJ.ROS/MAY24", "mes_contrato"] == D(2024, 5, 1)
        assert bool(c.loc["SOJ.ROS/MAY24", "vencido"]) is True
        # JUL24 sigue cotizando el último día del dataset: no está vencido.
        assert bool(c.loc["SOJ.ROS/JUL24", "vencido"]) is False

    def test_mes_desconocido_falla(self):
        with pytest.raises(base.BaseError, match="desconocidos"):
            base.contratos_rosario(_fut([(D(2024, 1, 2), "SOJ.ROS/XYZ24", 1.0)]))


class TestPrecioFisico:
    def test_convierte_con_tc_del_mismo_dia_y_no_rellena(self):
        pizarra = pd.DataFrame(
            {
                "fecha": [D(2024, 1, 2), D(2024, 1, 3), D(2024, 1, 4)],
                "precio_ars_tn": [261000.0, np.nan, 265000.0],
                "sin_cotizacion": [False, True, False],
            }
        )
        tc = pd.DataFrame({"fecha": [D(2024, 1, 2), D(2024, 1, 3)], "ars_por_usd": [810.0, 811.0]})
        r = base.precio_fisico_usd(pizarra, tc)
        assert r.iloc[0]["precio_usd_tn"] == pytest.approx(261000 / 810)
        assert pd.isna(r.iloc[1]["precio_usd_tn"]) and r.iloc[1]["sin_cotizacion"]
        # 4/1 sin TC: NaN marcado, no se usa el TC del 3/1.
        assert pd.isna(r.iloc[2]["precio_usd_tn"]) and r.iloc[2]["sin_tc"]

    def test_tc_repetido_falla(self):
        pizarra = pd.DataFrame({"fecha": [D(2024, 1, 2)], "precio_ars_tn": [1.0], "sin_cotizacion": [False]})
        tc = pd.DataFrame({"fecha": [D(2024, 1, 2)] * 2, "ars_por_usd": [1.0, 2.0]})
        with pytest.raises(base.BaseError, match="repetidas"):
            base.precio_fisico_usd(pizarra, tc)


class TestSerieBase:
    def test_usa_posicion_cercana_del_mismo_dia(self):
        fisico = _fisico(
            [
                (D(2024, 5, 27), 305.0, False, False),
                (D(2024, 5, 29), 309.0, False, False),
                (D(2024, 5, 30), 309.0, False, False),
            ]
        )
        s = base.serie_base(fisico, _contratos()).set_index("fecha")
        assert s.loc[D(2024, 5, 27), "simbolo"] == "SOJ.ROS/MAY24"
        assert s.loc[D(2024, 5, 27), "base_usd_tn"] == pytest.approx(5.0)
        # MAY24 ya no cotiza el 29: pasa a JUL24.
        assert s.loc[D(2024, 5, 29), "simbolo"] == "SOJ.ROS/JUL24"
        assert s.loc[D(2024, 5, 29), "base_usd_tn"] == pytest.approx(-3.0)
        # Sin futuros ese día: base NaN, no se arrastra el ajuste anterior.
        assert pd.isna(s.loc[D(2024, 5, 30), "base_usd_tn"])

    def test_fisico_faltante_da_base_nan(self):
        fisico = _fisico([(D(2024, 5, 27), np.nan, True, False)])
        s = base.serie_base(fisico, _contratos())
        assert pd.isna(s.iloc[0]["base_usd_tn"])
        assert s.iloc[0]["simbolo"] == "SOJ.ROS/MAY24"


class TestBaseAlVencimiento:
    def test_promedia_ultimos_dias_de_contratos_vencidos(self):
        fisico = _fisico(
            [
                (D(2024, 5, 27), 298.0, False, False),
                (D(2024, 5, 28), np.nan, True, False),
            ]
        )
        dias = [D(2024, 5, 27), D(2024, 5, 28), D(2024, 5, 29)]
        r = base.base_al_vencimiento(fisico, _contratos(), dias, ultimos_dias=2)
        assert list(r["simbolo"]) == ["SOJ.ROS/MAY24"]  # JUL24 no vencido
        fila = r.iloc[0]
        assert fila["base_usd_tn"] == pytest.approx(-2.0)  # solo el 27, el 28 es S/C
        assert fila["dias_con_dato"] == 1
        assert fila["ajuste_final"] == 302.0


class TestAuditoriaCodexBase:
    """Regresiones de la auditoría de Codex sobre base.py (2026-09-27)."""

    def test_contrato_que_desaparece_antes_de_su_mes_no_es_vencido(self):
        futuros = _fut(
            [
                (D(2024, 5, 28), "SOJ.ROS/JUL24", 310.0),
                (D(2024, 5, 28), "SOJ.ROS/SEP24", 320.0),
                (D(2024, 5, 29), "SOJ.ROS/SEP24", 321.0),
            ]
        )
        c = base.contratos_rosario(futuros).drop_duplicates("simbolo").set_index("simbolo")
        assert c.loc["SOJ.ROS/JUL24", "estado"] == "incierto"
        assert not c.loc["SOJ.ROS/JUL24", "vencido"]
        assert c.loc["SOJ.ROS/SEP24", "estado"] == "vivo"

    def test_vencido_despues_de_su_mes(self):
        # SEP20 real: último ajuste el 2020-10-05.
        futuros = _fut(
            [
                (D(2020, 10, 5), "SOJ.ROS/SEP20", 290.0),
                (D(2020, 10, 6), "SOJ.ROS/NOV20", 300.0),
            ]
        )
        c = base.contratos_rosario(futuros).drop_duplicates("simbolo").set_index("simbolo")
        assert c.loc["SOJ.ROS/SEP20", "estado"] == "vencido"

    def test_ventana_usa_dias_de_mercado_no_filas(self):
        # MAY24 no tiene ajuste el 28: la ventana de 3 días es 27-28-29 con un
        # hueco, no 24-27-29.
        futuros = _fut(
            [
                (D(2024, 5, 24), "SOJ.ROS/MAY24", 290.0),
                (D(2024, 5, 27), "SOJ.ROS/MAY24", 300.0),
                (D(2024, 5, 29), "SOJ.ROS/MAY24", 302.0),
                (D(2024, 5, 30), "SOJ.ROS/JUL24", 310.0),
            ]
        )
        c = base.contratos_rosario(futuros)
        fisico = _fisico([(d, 305.0, False, False) for d in [D(2024, 5, 24), D(2024, 5, 27), D(2024, 5, 28), D(2024, 5, 29)]])
        dias = [D(2024, 5, 24), D(2024, 5, 27), D(2024, 5, 28), D(2024, 5, 29), D(2024, 5, 30)]
        r = base.base_al_vencimiento(fisico, c, dias, ultimos_dias=3).iloc[0]
        assert r["dias_ventana"] == 3
        assert r["dias_con_dato"] == 2
        assert r["base_usd_tn"] == pytest.approx(((305 - 300) + (305 - 302)) / 2)
