import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ver
import visor


class HerdrFalso:
    """Simula las respuestas JSON reales de herdr (tab list/create, pane list/split/rename/run)."""
    def __init__(self, tabs_previas=None, falla=None):
        self.tabs = list(tabs_previas or [])      # [{"tab_id","label"}]
        self.panes = []                           # [{"pane_id","tab_id"}]
        self.llamadas, self.n, self.falla = [], 100, falla

    def __call__(self, *args):
        self.llamadas.append(args)
        if self.falla and args[:2] == self.falla:
            return None
        g, c = args[0], args[1]
        if (g, c) == ("tab", "list"):
            return {"tabs": self.tabs}
        if (g, c) == ("tab", "create"):
            self.n += 1
            tab, pane = f"w1:t{self.n}", f"w1:p{self.n}"
            self.tabs.append({"tab_id": tab, "label": args[args.index("--label") + 1]})
            self.panes.append({"pane_id": pane, "tab_id": tab})
            return {"tab": {"tab_id": tab}, "root_pane": {"pane_id": pane}}
        if (g, c) == ("pane", "list"):
            return {"panes": self.panes}
        if (g, c) == ("pane", "split"):
            self.n += 1
            tab = next(p["tab_id"] for p in self.panes if p["pane_id"] == args[2])
            self.panes.append({"pane_id": f"w1:p{self.n}", "tab_id": tab})
            return {"pane": {"pane_id": f"w1:p{self.n}"}}
        return {}

    def cuantas(self, g, c):
        return sum(1 for a in self.llamadas if a[:2] == (g, c))


class TestVisor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.h = HerdrFalso(tabs_previas=[{"tab_id": "w1:t1", "label": "Director"}])
        self.v = visor.Visor(self.tmp / "visor.json", workspace="w1", herdr=self.h)

    def abrir(self, n):
        return self.v.abrir(f"run{n}", ["python3", "ver.py", f"/runs/{n}"], "/tmp")

    def test_primer_panel_usa_la_pestana_nueva_y_no_roba_foco(self):
        p = self.abrir(1)
        self.assertTrue(p)
        creacion = next(a for a in self.h.llamadas if a[:2] == ("tab", "create"))
        self.assertIn("--no-focus", creacion)
        self.assertEqual(self.h.cuantas("pane", "split"), 0, "la primera corrida usa el panel raíz")

    def test_no_crea_la_pestana_dos_veces(self):
        self.abrir(1)
        self.abrir(2)
        self.assertEqual(self.h.cuantas("tab", "create"), 1)

    def test_splits_con_no_focus_y_direccion(self):
        for i in range(3):
            self.abrir(i)
        splits = [a for a in self.h.llamadas if a[:2] == ("pane", "split")]
        self.assertEqual([a[a.index("--direction") + 1] for a in splits], ["right", "down"])
        self.assertTrue(all("--no-focus" in a for a in splits))

    def test_tope_de_paneles(self):
        resultados = [self.abrir(i) for i in range(visor.MAX_PANELES + 2)]
        self.assertEqual(sum(1 for r in resultados if r), visor.MAX_PANELES)
        self.assertIsNone(resultados[-1])

    def test_liberar_permite_reutilizar_con_clear(self):
        paneles = [self.abrir(i) for i in range(visor.MAX_PANELES)]
        self.v.liberar(paneles[1])
        p = self.abrir(99)
        self.assertEqual(p, paneles[1])
        ultimo_run = [a for a in self.h.llamadas if a[:2] == ("pane", "run")][-1]
        self.assertTrue(ultimo_run[3].startswith("clear; "))

    def test_nunca_toca_paneles_ajenos(self):
        self.h.panes.append({"pane_id": "w1:p1", "tab_id": "w1:t1"})   # panel del usuario en otra pestaña
        for i in range(3):
            self.abrir(i)
        tocados = {a[2] for a in self.h.llamadas if a[:2] in (("pane", "run"), ("pane", "rename"))}
        self.assertNotIn("w1:p1", tocados)

    def test_un_fallo_de_herdr_devuelve_none_sin_excepcion(self):
        self.h.falla = ("tab", "create")
        self.assertIsNone(self.abrir(1))

    def test_herdr_real_acepta_stdout_vacio(self):
        """Regresión: `herdr pane run` responde rc 0 con stdout vacío; antes reventaba con JSONDecodeError."""
        from unittest import mock
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(visor.subprocess, "run", return_value=ok):
            self.assertEqual(visor._herdr_real("pane", "run", "w1:p1", "echo"), {})
        mal = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch.object(visor.subprocess, "run", return_value=mal):
            self.assertIsNone(visor._herdr_real("pane", "run", "w1:p1", "echo"))

    def test_el_panel_queda_reservado_aunque_falle_el_run(self):
        self.h.falla = ("pane", "run")
        self.assertIsNone(self.abrir(1))
        estado = json.loads((self.tmp / "visor.json").read_text(encoding="utf-8"))
        self.assertTrue(all(v["estado"] == "libre" for v in estado["paneles"].values()))

    def test_dos_corridas_seguidas_no_comparten_panel(self):
        a, b = self.abrir(1), self.abrir(2)
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)

    def test_primer_panel_no_hace_clear(self):
        self.abrir(1)
        primer_run = next(a for a in self.h.llamadas if a[:2] == ("pane", "run"))
        self.assertFalse(primer_run[3].startswith("clear"))

    def test_disponible_exige_dentro_de_herdr(self):
        self.assertFalse(visor.disponible({}))
        self.assertFalse(visor.disponible({"HERDR_ENV": "1"}))


class TestVer(unittest.TestCase):
    def test_formatea_herramienta_texto_y_error(self):
        tool = json.dumps({"part": {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "git status -s"}}}})
        pendiente = json.dumps({"part": {"type": "tool", "tool": "bash", "state": {"status": "running", "input": {"command": "x"}}}})
        texto = json.dumps({"part": {"type": "text", "text": "Voy a  revisar\nel diff"}})
        self.assertIn("▸ bash", ver.formatear_evento(tool, "trabajador"))
        self.assertIn("git status -s", ver.formatear_evento(tool, "trabajador"))
        self.assertIsNone(ver.formatear_evento(pendiente, "trabajador"))
        self.assertIn("Voy a revisar el diff", ver.formatear_evento(texto, "revisor"))
        self.assertIsNone(ver.formatear_evento("no es json", "revisor"))

    def test_seguir_termina_con_FIN_y_muestra_el_resultado(self):
        run = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(run, ignore_errors=True))
        (run / "etapas.log").write_text("10:00:00 oráculo antes\n", encoding="utf-8")
        (run / "opencode.jsonl").write_text(json.dumps({"part": {"type": "text", "text": "hola"}}) + "\n", encoding="utf-8")
        (run / "estado.json").write_text(json.dumps({"resultado": "pasa", "commits": 2}), encoding="utf-8")
        (run / "FIN").touch()
        salida = io.StringIO()
        ver.seguir(run, salida, espera=0.01)
        s = salida.getvalue()
        self.assertIn("oráculo antes", s)
        self.assertIn("tra │ hola", s)
        self.assertIn("fin: pasa · commits 2", s)


if __name__ == "__main__":
    unittest.main()
