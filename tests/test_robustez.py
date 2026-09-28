import numpy as np
import pandas as pd
import pytest

from coberturas.analisis import robustez as rob
from coberturas.analisis.cobertura import CoberturaError


def _esc(filas):
    """filas: (campania, regimen, dS, dF). Construye s0/s1/f0/f1 y resultados A."""
    df = pd.DataFrame(filas, columns=["campania", "regimen", "dS", "dF"])
    df["disponible"] = True
    df["s0"], df["f0"] = 300.0, 305.0
    df["s1"], df["f1"] = 300.0 + df["dS"], 305.0 + df["dF"]
    df["A_sin_cobertura"] = df["dS"]
    df["A_futuro"] = df["dS"] - df["dF"]
    df["A_put"] = df["dS"] * 0.5
    return df.drop(columns=["dS", "dF"])


class TestRatioMinimaVarianza:
    def test_recupera_pendiente_exacta(self):
        df = pd.Series([1.0, -2.0, 3.0, 5.0])
        assert rob.ratio_minima_varianza(0.8 * df + 2.0, df) == pytest.approx(0.8)

    def test_futuro_constante_falla(self):
        with pytest.raises(CoberturaError, match="no varía"):
            rob.ratio_minima_varianza([1.0, 2.0], [3.0, 3.0])

    def test_pocos_datos_falla(self):
        with pytest.raises(CoberturaError, match="al menos 2"):
            rob.ratio_minima_varianza([1.0], [1.0])


class TestFueraDeMuestra:
    def _datos(self):
        return _esc(
            [
                (2020, "normal", 10.0, 10.0),
                (2020, "normal", -10.0, -12.0),
                (2021, "normal", 5.0, 4.0),
                (2021, "dolar_soja", 100.0, 0.0),  # no debe entrar en la estimación
                (2022, "normal", 8.0, 9.0),
            ]
        )

    def test_solo_usa_campanias_previas_y_excluye_dolar_soja(self):
        esc = self._datos()
        ratios = rob.ratios_fuera_de_muestra(esc)
        assert 2020 not in ratios  # sin historia
        # 2021 se estima solo con 2020
        assert ratios[2021] == pytest.approx(rob.ratio_minima_varianza([10.0, -10.0], [10.0, -12.0]))
        # 2022 con 2020 y la fila normal de 2021 (la de dólar soja queda afuera)
        assert ratios[2022] == pytest.approx(
            rob.ratio_minima_varianza([10.0, -10.0, 5.0], [10.0, -12.0, 4.0])
        )

    def test_no_mira_el_futuro(self):
        esc = self._datos()
        base = rob.ratios_fuera_de_muestra(esc)[2021]
        # Cambiar datos de 2022 no puede mover el ratio de 2021.
        esc.loc[esc["campania"] == 2022, "s1"] += 500
        assert rob.ratios_fuera_de_muestra(esc)[2021] == pytest.approx(base)

    def test_min_campanias(self):
        ratios = rob.ratios_fuera_de_muestra(self._datos(), min_campanias=2)
        assert set(ratios) == {2022}

    def test_comparar_usa_mismos_escenarios(self):
        esc = self._datos()
        r = rob.comparar_ratio(esc, {"normal"}, {2021: 1.0, 2022: 0.5}).set_index("estrategia")
        assert r.loc["sin_cobertura", "n"] == 2  # 2021 normal + 2022
        # con h = 1 en 2021 y 0,5 en 2022
        esperado = pd.Series([5.0 - 1.0 * 4.0, 8.0 - 0.5 * 9.0])
        assert r.loc["minima_varianza_oos", "media"] == pytest.approx(esperado.mean())
        assert r.loc["ratio_1_a_1", "media"] == pytest.approx(((5 - 4) + (8 - 9)) / 2)


class TestBootstrap:
    def test_intervalos_contienen_estimacion_y_son_reproducibles(self):
        rng = np.random.default_rng(1)
        filas = []
        for c in range(2020, 2026):
            for _ in range(6):
                df_ = rng.normal(0, 20)
                filas.append((c, "normal", df_ + rng.normal(0, 5), df_))
        esc = _esc(filas)
        a = rob.intervalos_bootstrap(esc, "A", {"normal"}, n=400, semilla=7).set_index("estrategia")
        b = rob.intervalos_bootstrap(esc, "A", {"normal"}, n=400, semilla=7).set_index("estrategia")
        pd.testing.assert_frame_equal(a, b)
        fila = a.loc["A_futuro"]
        punto = 1 - esc["A_futuro"].var() / esc["A_sin_cobertura"].var()
        assert fila["efectividad_inf"] <= punto <= fila["efectividad_sup"]
        assert fila["efectividad_sup"] <= 1.0

    def test_una_sola_campania_falla(self):
        esc = _esc([(2020, "normal", 1.0, 1.0), (2020, "normal", 2.0, 1.5)])
        with pytest.raises(CoberturaError, match="al menos 2 campañas"):
            rob.intervalos_bootstrap(esc, "A", {"normal"}, n=10)

    def test_regimen_desconocido(self):
        with pytest.raises(ValueError):
            rob.intervalos_bootstrap(_esc([(2020, "normal", 1.0, 1.0)]), "A", {"raro"})


def test_bootstrap_mejora_ratio_detecta_ratio_correcto():
    rng = np.random.default_rng(3)
    filas = []
    for c in range(2020, 2027):
        for _ in range(8):
            df_ = rng.normal(0, 20)
            filas.append((c, "normal", 1.3 * df_ + rng.normal(0, 3), df_))
    esc = _esc(filas)
    ratios = rob.ratios_fuera_de_muestra(esc)
    r = rob.bootstrap_mejora_ratio(esc, {"normal"}, ratios, n=300, semilla=1)
    # Con h verdadero 1,3 la mínima varianza tiene que ganarle al 1 a 1.
    assert r["mejora"] > 0
    assert r["inf"] <= r["mejora"] <= r["sup"]
    assert r["frecuencia_mejora_positiva"] > 0.9


class TestAuditoriaCodexRobustez:
    def test_opcion_con_una_sola_campania_no_tiene_intervalo(self):
        filas = [(c, "normal", float(i), float(i) * 0.9 + (c % 3)) for c in (2020, 2021, 2022) for i in range(-3, 4)]
        esc = _esc(filas)
        esc.loc[esc["campania"] != 2020, "A_put"] = np.nan  # put solo en 2020
        r = rob.intervalos_bootstrap(esc, "A", {"normal"}, n=200, semilla=0).set_index("estrategia")
        assert r.loc["A_put", "campanias_con_datos"] == 1
        assert np.isnan(r.loc["A_put", "efectividad_inf"]) and r.loc["A_put", "remuestreos_validos"] == 0
        assert np.isfinite(r.loc["A_futuro", "efectividad_inf"])

    def test_remuestreos_con_varianza_cero_se_descartan(self):
        # 2021 tiene ΔS constante: remuestreos con solo 2021 no definen la mejora.
        filas = [(2020, "normal", 1.0, 1.0), (2020, "normal", 9.0, 5.0)]
        filas += [(2021, "normal", 2.0, 1.0), (2021, "normal", 2.0, 3.0)]
        filas += [(2022, "normal", 4.0, 2.0), (2022, "normal", -6.0, -5.0)]
        esc = _esc(filas)
        r = rob.bootstrap_mejora_ratio(esc, {"normal"}, {2020: 1.2, 2021: 1.2, 2022: 1.2}, n=300, semilla=2)
        assert r["remuestreos_validos"] < 300
        assert np.isfinite(r["inf"]) and np.isfinite(r["sup"])
