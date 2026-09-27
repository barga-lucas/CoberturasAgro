import datetime as dt
import io

import pandas as pd
import pytest
from openpyxl import Workbook

from coberturas.data import a3, cbot, fx, pizarra


def _export_xlsx(producto="Soja", filas=None, header=("Fecha de operación", "Precio")):
    """Reproduce el layout del export real de la CAC."""
    wb = Workbook()
    ws = wb.active
    ws.append([None, None, None, "Consulta de precios"])
    ws.append([])
    ws.append([])
    ws.append([producto])
    ws.append(list(header))
    for fila in filas if filas is not None else [
        (dt.datetime(2024, 1, 3, 3), 264500),
        (dt.datetime(2024, 1, 2, 3), 261000),
    ]:
        ws.append(list(fila))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPizarra:
    def test_parsea_y_ordena_por_fecha(self):
        serie = pizarra.parsear_export(_export_xlsx(), "soja")
        assert list(serie["fecha"]) == [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
        assert list(serie["precio_ars_tn"]) == [261000.0, 264500.0]

    def test_producto_con_acento(self):
        serie = pizarra.parsear_export(_export_xlsx(producto="Maíz"), "maiz")
        assert len(serie) == 2

    def test_rechaza_producto_equivocado(self):
        with pytest.raises(pizarra.PizarraError, match="no corresponde"):
            pizarra.parsear_export(_export_xlsx(producto="Trigo"), "soja")

    def test_sin_cotizacion_queda_como_faltante_marcado(self):
        filas = [(dt.datetime(2015, 3, 11, 10, 18), "S/C"), (dt.datetime(2015, 3, 12, 10, 5), 2400)]
        serie = pizarra.parsear_export(_export_xlsx(filas=filas), "soja")
        assert serie["sin_cotizacion"].tolist() == [True, False]
        assert pd.isna(serie.iloc[0]["precio_ars_tn"])
        assert serie.iloc[1]["precio_ars_tn"] == 2400.0

    def test_rechaza_precio_no_numerico(self):
        filas = [(dt.datetime(2024, 1, 2, 3), "N/D")]
        with pytest.raises(pizarra.PizarraError, match="no numérico"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja")

    def test_rechaza_fecha_repetida(self):
        filas = [(dt.datetime(2024, 1, 2, 3), 1), (dt.datetime(2024, 1, 2, 3), 2)]
        with pytest.raises(pizarra.PizarraError, match="repetidas"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja")

    def test_rechaza_precio_cero(self):
        filas = [(dt.datetime(2024, 1, 2, 3), 0)]
        with pytest.raises(pizarra.PizarraError, match="cero"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja")

    def test_rechaza_encabezado_distinto(self):
        with pytest.raises(pizarra.PizarraError, match="Encabezado"):
            pizarra.parsear_export(_export_xlsx(header=("Fecha", "Precio USD")), "soja")

    def test_producto_desconocido(self):
        with pytest.raises(ValueError, match="desconocido"):
            pizarra.descargar_anio("cebada", 2024)

    def test_cache_no_redescarga_anios_cerrados(self, tmp_path, monkeypatch):
        (tmp_path / "pizarra_soja_2023.xlsx").write_bytes(_export_xlsx(filas=[(dt.datetime(2023, 5, 2, 3), 100)]))
        pedidos = []

        def falso(producto, anio, session=None):
            pedidos.append(anio)
            return _export_xlsx(filas=[(dt.datetime(anio, 1, 2, 3), 200)])

        monkeypatch.setattr(pizarra, "descargar_anio", falso)
        serie = pizarra.descargar_serie("soja", 2023, 2024, tmp_path, hoy=dt.date(2024, 6, 1))
        assert pedidos == [2024]
        assert len(serie) == 2


class TestFx:
    def _payload(self, detalle, status=200, id_variable=5):
        return {
            "status": status,
            "metadata": {"resultset": {"count": len(detalle), "offset": 0, "limit": 1000}},
            "results": [{"idVariable": id_variable, "detalle": detalle}],
        }

    def test_parsea(self):
        serie = fx.parsear_respuesta(self._payload([{"fecha": "2024-01-02", "valor": 810.65}]))
        assert serie.iloc[0]["fecha"] == dt.date(2024, 1, 2)
        assert serie.iloc[0]["ars_por_usd"] == 810.65

    def test_rechaza_otra_variable(self):
        with pytest.raises(fx.FxError, match="variable 5"):
            fx.parsear_respuesta(self._payload([], id_variable=4))

    def test_rechaza_status_error(self):
        with pytest.raises(fx.FxError, match="410"):
            fx.parsear_respuesta({"status": 410, "errorMessages": ["deprecado"]})


class TestCbot:
    def _payload(self, ts, cierres, moneda="USX"):
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": moneda, "exchangeTimezoneName": "America/New_York"},
                        "timestamp": ts,
                        "indicators": {"quote": [{"close": cierres}]},
                    }
                ],
                "error": None,
            }
        }

    def test_convierte_centavos_bushel_a_usd_tn(self):
        ts = int(pd.Timestamp("2024-01-02 14:30", tz="UTC").timestamp())
        serie = cbot.parsear_chart(self._payload([ts], [1000.0]))
        assert serie.iloc[0]["fecha"] == dt.date(2024, 1, 2)
        assert serie.iloc[0]["usd_por_tn"] == pytest.approx(10 * 36.7437)

    def test_fechas_reales_de_yahoo_julio_2025(self):
        # Timestamps reales de ZS=F: medianoche de Nueva York (04:00 UTC) y una
        # barra a las 09:30 (13:30 UTC). Con zona de Chicago, 07-01 caía en 06-30
        # y 07-03 quedaba duplicado.
        ts = [1751342400, 1751428800, 1751549400]
        serie = cbot.parsear_chart(self._payload(ts, [1024.75, 1050.5, 1056.25]))
        assert serie["fecha"].tolist() == [dt.date(2025, 7, 1), dt.date(2025, 7, 2), dt.date(2025, 7, 3)]

    def test_rechaza_respuesta_sin_zona_horaria(self):
        payload = self._payload([1751342400], [1000.0])
        del payload["chart"]["result"][0]["meta"]["exchangeTimezoneName"]
        with pytest.raises(cbot.CbotError, match="exchangeTimezoneName"):
            cbot.parsear_chart(payload)

    def test_cierre_nulo_queda_marcado(self):
        serie = cbot.parsear_chart(self._payload([1704205800, 1704292200], [None, 1200.0]))
        assert serie["sin_dato"].tolist() == [True, False]
        assert pd.isna(serie.iloc[0]["usd_por_tn"])
        assert serie.iloc[1]["usd_por_tn"] == pytest.approx(12 * 36.7437)

    def test_rechaza_fecha_repetida(self):
        # Dos timestamps del mismo día en Nueva York
        with pytest.raises(cbot.CbotError, match="repetidas"):
            cbot.parsear_chart(self._payload([1751342400, 1751349600], [1000.0, 1001.0]))

    @pytest.mark.parametrize("cierre", [0.0, -5.0, float("inf"), "x"])
    def test_rechaza_cierre_invalido(self, cierre):
        with pytest.raises(cbot.CbotError, match="Cierre inválido"):
            cbot.parsear_chart(self._payload([1704205800], [cierre]))

    def test_rechaza_longitudes_distintas(self):
        with pytest.raises(cbot.CbotError, match="timestamps"):
            cbot.parsear_chart(self._payload([1704205800], [1.0, 2.0]))

    def test_rechaza_moneda_inesperada(self):
        with pytest.raises(cbot.CbotError, match="Moneda"):
            cbot.parsear_chart(self._payload([1], [1.0], moneda="USD"))


def _fila_a3(simbolo="SOJ.ROS/MAY20", ajuste=261.5, tipo_opcion=None, strike=None, subyacente=None):
    return {
        "dateTime": "2020-01-02T00:00:00.000Z",
        "symbol": simbolo,
        "settlement": ajuste,
        "volume": 10,
        "openInterest": 100.0,
        "optionType": tipo_opcion,
        "strikePrice": strike,
        "underlying": subyacente,
    }


class TestA3:
    def test_parsea_futuro(self):
        serie = a3.parsear_pagina({"data": [_fila_a3()]}, "FUT")
        fila = serie.iloc[0]
        assert fila["fecha"] == dt.date(2020, 1, 2)
        assert fila["tipo"] == "Futuro"
        assert fila["subyacente"] == "SOJ.ROS/MAY20"
        assert fila["ajuste"] == 261.5

    def test_parsea_opcion(self):
        fila = _fila_a3("SOJ.ROS/NOV26 324 C", 58.2, "Call", 324.0, "SOJ.ROS/NOV26")
        serie = a3.parsear_pagina({"data": [fila]}, "OPT")
        assert serie.iloc[0]["tipo"] == "Call"
        assert serie.iloc[0]["strike"] == 324.0
        assert serie.iloc[0]["subyacente"] == "SOJ.ROS/NOV26"

    def test_rechaza_ajuste_faltante(self):
        with pytest.raises(a3.A3Error, match="ajuste inválido"):
            a3.parsear_pagina({"data": [_fila_a3(ajuste=None)]}, "FUT")

    def test_rechaza_opcion_sin_strike(self):
        fila = _fila_a3("X", 1.0, "Put", None, "SOJ.ROS/NOV26")
        with pytest.raises(a3.A3Error, match="strike"):
            a3.parsear_pagina({"data": [fila]}, "OPT")

    def test_rechaza_opcion_mezclada_en_futuros(self):
        fila = _fila_a3("X", 1.0, "Call", 300.0, "SOJ.ROS/NOV26")
        with pytest.raises(a3.A3Error, match="opción"):
            a3.parsear_pagina({"data": [fila]}, "FUT")

    def test_rechaza_fecha_anterior_a_2020(self):
        with pytest.raises(ValueError, match="antes de"):
            a3.descargar(dt.date(2019, 6, 1), dt.date(2020, 6, 1), "FUT")

    def test_pagina_hasta_completar_total(self, monkeypatch):
        monkeypatch.setattr(a3, "PAGE_SIZE", 1)
        paginas = {
            1: {"data": [_fila_a3("SOJ.ROS/MAY20")], "totalEntries": 2},
            2: {"data": [_fila_a3("SOJ.ROS/JUL20")], "totalEntries": 2},
        }

        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        class Sesion:
            def get(self, url, params, timeout):
                return Resp(paginas[params["page"]])

        serie = a3.descargar(dt.date(2020, 1, 1), dt.date(2020, 1, 31), "FUT", session=Sesion())
        assert list(serie["simbolo"]) == ["SOJ.ROS/JUL20", "SOJ.ROS/MAY20"]


class TestAuditoriaCodex:
    """Regresiones de la auditoría de Codex del 2026-09-27."""

    def test_pizarra_anio_en_curso_no_se_cachea(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            pizarra, "descargar_anio", lambda p, a, s=None: _export_xlsx(filas=[(dt.datetime(a, 1, 2, 3), 1)])
        )
        pizarra.descargar_serie("soja", 2025, 2026, tmp_path, hoy=dt.date(2026, 9, 27))
        assert (tmp_path / "pizarra_soja_2025.xlsx").exists()
        assert not (tmp_path / "pizarra_soja_2026.xlsx").exists()

    def test_pizarra_rechaza_fecha_numerica(self):
        filas = [(45293, 1000)]
        with pytest.raises(pizarra.PizarraError, match="no numérico"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja")

    def test_pizarra_rechaza_fecha_fuera_del_anio(self):
        filas = [(dt.datetime(2023, 12, 29, 3), 1000)]
        with pytest.raises(pizarra.PizarraError, match="fuera de 2024"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja", anio=2024)

    def test_pizarra_rechaza_infinito(self):
        filas = [(dt.datetime(2024, 1, 2, 3), "inf")]
        with pytest.raises(pizarra.PizarraError, match="no numérico"):
            pizarra.parsear_export(_export_xlsx(filas=filas), "soja")

    @pytest.mark.parametrize("valor", [None, float("nan"), 0, "810"])
    def test_fx_rechaza_valor_invalido(self, valor):
        payload = {"status": 200, "results": [{"idVariable": 5, "detalle": [{"fecha": "2024-01-02", "valor": valor}]}]}
        with pytest.raises(fx.FxError, match="inválido"):
            fx.parsear_respuesta(payload)

    def test_fx_rechaza_fecha_nula(self):
        payload = {"status": 200, "results": [{"idVariable": 5, "detalle": [{"fecha": None, "valor": 810.0}]}]}
        with pytest.raises(fx.FxError, match="Fecha inválida"):
            fx.parsear_respuesta(payload)

    def _fx_servidor(self, monkeypatch, paginas_por_offset, total):
        class Resp:
            def __init__(self, detalle):
                self._p = {
                    "status": 200,
                    "metadata": {"resultset": {"count": total}},
                    "results": [{"idVariable": 5, "detalle": detalle}],
                }

            def raise_for_status(self):
                pass

            def json(self):
                return self._p

        class Sesion:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url, params, timeout):
                return Resp(paginas_por_offset.get(params["offset"], []))

        monkeypatch.setattr(fx.requests, "Session", Sesion)

    def test_fx_pagina_capada_no_saltea_registros(self, monkeypatch):
        # El servidor devuelve 1 registro por página aunque pedimos 1000.
        paginas = {
            0: [{"fecha": "2024-01-02", "valor": 1.0}],
            1: [{"fecha": "2024-01-03", "valor": 2.0}],
        }
        self._fx_servidor(monkeypatch, paginas, total=2)
        serie = fx.descargar_a3500(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
        assert serie["ars_por_usd"].tolist() == [1.0, 2.0]

    def test_fx_pagina_vacia_prematura_falla(self, monkeypatch):
        self._fx_servidor(monkeypatch, {0: [{"fecha": "2024-01-02", "valor": 1.0}]}, total=3)
        with pytest.raises(fx.FxError, match="Página vacía"):
            fx.descargar_a3500(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    @pytest.mark.parametrize("strike", [None, -100.0, "garbage", float("inf")])
    def test_a3_rechaza_strike_invalido(self, strike):
        fila = _fila_a3("X", 1.0, "Put", strike, "SOJ.ROS/NOV26")
        with pytest.raises(a3.A3Error, match="strike"):
            a3.parsear_pagina({"data": [fila]}, "OPT")

    def test_a3_rechaza_opcion_sin_subyacente(self):
        fila = _fila_a3("X", 1.0, "Call", 300.0, None)
        with pytest.raises(a3.A3Error, match="subyacente"):
            a3.parsear_pagina({"data": [fila]}, "OPT")

    @pytest.mark.parametrize("ajuste", [float("nan"), float("inf"), -1.0])
    def test_a3_rechaza_ajuste_no_finito(self, ajuste):
        with pytest.raises(a3.A3Error, match="ajuste inválido"):
            a3.parsear_pagina({"data": [_fila_a3(ajuste=ajuste)]}, "FUT")

    def test_a3_prima_cero_es_valida(self):
        fila = _fila_a3("SOJ.ROS/NOV26 500 C", 0.0, "Call", 500.0, "SOJ.ROS/NOV26")
        assert a3.parsear_pagina({"data": [fila]}, "OPT").iloc[0]["ajuste"] == 0.0

    def test_a3_futuro_con_ajuste_cero_falla(self):
        with pytest.raises(a3.A3Error, match="ajuste 0"):
            a3.parsear_pagina({"data": [_fila_a3(ajuste=0.0)]}, "FUT")


def test_a3_serie_por_anio_cachea_solo_anios_cerrados(tmp_path, monkeypatch):
    pedidos = []

    def falso(desde, hasta, tipo, producto, session):
        pedidos.append((desde, hasta))
        return a3.parsear_pagina({"data": [dict(_fila_a3(), dateTime=f"{desde.isoformat()}T00:00:00.000Z")]}, "FUT")

    monkeypatch.setattr(a3, "descargar", falso)
    hoy = dt.date(2026, 9, 27)
    serie = a3.descargar_serie(2025, 2026, "FUT", tmp_path, hoy=hoy)
    assert pedidos == [(dt.date(2025, 1, 1), dt.date(2025, 12, 31)), (dt.date(2026, 1, 1), hoy)]
    assert (tmp_path / "a3_SOJ_Dolar_MATba_FUT_2025.csv").exists()
    assert not (tmp_path / "a3_SOJ_Dolar_MATba_FUT_2026.csv").exists()

    # Segunda corrida: 2025 sale de cache con las mismas fechas como date.
    pedidos.clear()
    otra = a3.descargar_serie(2025, 2026, "FUT", tmp_path, hoy=hoy)
    assert pedidos == [(dt.date(2026, 1, 1), hoy)]
    assert otra["fecha"].tolist() == serie["fecha"].tolist()


def test_a3_cache_de_anio_vacio_se_relee(tmp_path, monkeypatch):
    monkeypatch.setattr(a3, "descargar", lambda desde, hasta, tipo, producto, session: a3.parsear_pagina({"data": []}, "FUT"))
    hoy = dt.date(2026, 9, 27)
    a3.descargar_serie(2020, 2020, "FUT", tmp_path, hoy=hoy)
    releida = a3.descargar_serie(2020, 2020, "FUT", tmp_path, hoy=hoy)
    assert releida.empty
