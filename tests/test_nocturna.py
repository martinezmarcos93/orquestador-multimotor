import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import despachar  # noqa: E402
import nocturna  # noqa: E402

ENCARGO = '+++\nid="{id}"\nproyecto="p"\nrepo="/x"\nagente="tester"\ntema="t{id}"\npermitidos=["a"]\noraculo=["true"]\n+++\ncuerpo\n'


def _poner(carpeta: Path, id_: str, texto: str | None = None) -> Path:
    nocturna.preparar(carpeta)
    f = carpeta / "pendientes" / f"{id_}.md"
    f.write_text(texto if texto is not None else ENCARGO.format(id=id_), encoding="utf-8")
    return f


def _valido(_ruta, *a, **k):
    return {"valido": True, "errores": []}


class Nocturna(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_clasifica_listos_y_fallidos_y_escribe_resumen(self):
        _poner(self.dir, "001")
        _poner(self.dir, "002")

        def ejecutor(archivos, maximo, timeout):
            self.assertEqual(sorted(a.parent.name for a in archivos), ["en-curso", "en-curso"])
            return {"duracion_s": 5, "resultados": [
                {"proyecto": "p", "id": "001", "resultado": "pasa", "aprobacion": "no_requerida", "rama": "opencode/x"},
                {"proyecto": "p", "id": "002", "resultado": "falla_oraculo", "aprobacion": None}]}
        with mock.patch.object(despachar, "validar_encargo", _valido):
            r = nocturna.procesar(self.dir, ejecutor=ejecutor)
        self.assertEqual([x[0] for x in r["listos"]], ["001.md"])
        self.assertTrue((self.dir / "listos" / "001.md").exists())
        self.assertTrue((self.dir / "fallidos" / "002.md").exists())
        self.assertIn("falla_oraculo", (self.dir / "fallidos" / "002.md.nota.txt").read_text(encoding="utf-8"))
        self.assertEqual(list((self.dir / "pendientes").iterdir()), [])
        resumen = next((self.dir / "resumenes").iterdir()).read_text(encoding="utf-8")
        self.assertIn("Listos para revisar: **1**", resumen)
        self.assertIn("002.md", resumen)

    def test_aprobacion_bloqueada_no_es_lista(self):
        _poner(self.dir, "001")
        ej = lambda a, m, t: {"resultados": [{"proyecto": "p", "id": "001", "resultado": "pasa",
                                              "aprobacion": "bloqueado_por_revision"}]}
        with mock.patch.object(despachar, "validar_encargo", _valido):
            r = nocturna.procesar(self.dir, ejecutor=ej)
        self.assertEqual(r["listos"], [])
        self.assertTrue((self.dir / "fallidos" / "001.md").exists())

    def test_interrumpidos_no_se_relanzan_ni_se_duplican(self):
        nocturna.preparar(self.dir)
        (self.dir / "en-curso" / "007.md").write_text(ENCARGO.format(id="007"), encoding="utf-8")
        llamadas = []
        with mock.patch.object(despachar, "validar_encargo", _valido):
            r = nocturna.procesar(self.dir, ejecutor=lambda *a: llamadas.append(a))
        self.assertEqual(r["interrumpidos"], ["007.md"])
        self.assertEqual(llamadas, [])  # nada pendiente: no se lanza la cola
        self.assertTrue((self.dir / "fallidos" / "007.md").exists())
        self.assertFalse((self.dir / "en-curso" / "007.md").exists())

    def test_sin_veredicto_queda_en_curso_y_la_proxima_corrida_lo_marca(self):
        _poner(self.dir, "001")
        with mock.patch.object(despachar, "validar_encargo", _valido):
            r = nocturna.procesar(self.dir, ejecutor=lambda *a: None)
            self.assertEqual(r["fallidos"][0][1], "sin_veredicto")
            self.assertTrue((self.dir / "en-curso" / "001.md").exists())
            r2 = nocturna.procesar(self.dir, ejecutor=lambda *a: None)
        self.assertEqual(r2["interrumpidos"], ["001.md"])
        self.assertTrue((self.dir / "fallidos" / "001.md").exists())

    def test_encargo_invalido_no_frena_al_resto(self):
        _poner(self.dir, "001", "sin bloque de configuración")
        _poner(self.dir, "002")
        ej = lambda a, m, t: {"resultados": [{"proyecto": "p", "id": "002", "resultado": "pasa",
                                              "aprobacion": "aprobado"}]}
        with mock.patch.object(despachar, "validar_encargo", _valido):
            r = nocturna.procesar(self.dir, ejecutor=ej)
        self.assertIn("001.md", r["invalidos"])
        self.assertTrue((self.dir / "fallidos" / "001.md").exists())
        self.assertTrue((self.dir / "listos" / "002.md").exists())

    def test_no_pisa_archivos_existentes(self):
        nocturna.preparar(self.dir)
        (self.dir / "fallidos" / "001.md").write_text("viejo", encoding="utf-8")
        f = _poner(self.dir, "001")
        nuevo = nocturna.mover(f, self.dir / "fallidos")
        self.assertNotEqual(nuevo.name, "001.md")
        self.assertEqual((self.dir / "fallidos" / "001.md").read_text(encoding="utf-8"), "viejo")

    def test_una_sola_instancia(self):
        nocturna.preparar(self.dir)
        with nocturna.instancia_unica(self.dir):
            with self.assertRaises(SystemExit):
                with nocturna.instancia_unica(self.dir):
                    pass


if __name__ == "__main__":
    unittest.main()
