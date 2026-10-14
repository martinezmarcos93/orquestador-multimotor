import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import despachar as d

ENCARGO = '''+++
id = "001"
proyecto = "demo"
repo = "/tmp/demo"
agente = "tester"
tema = "tests-nucleo"
permitidos = ["tests/**"]
oraculo = ["pytest -q"]
+++
# Encargo 001
'''


class TestParseo(unittest.TestCase):
    def test_parsea_y_aplica_defaults(self):
        cfg = d.parsear_encargo(ENCARGO)
        self.assertEqual(cfg["base"], "main")
        self.assertEqual(cfg["timeout_min"], 20)
        self.assertEqual(cfg["permitidos"], ["tests/**"])

    def test_mutacion_con_defaults(self):
        cfg = d.parsear_encargo(ENCARGO.replace("+++\n# Encargo", '[mutacion]\narchivos = ["a.py"]\n+++\n# Encargo'))
        self.assertEqual(cfg["mutacion"]["umbral"], 0.8)
        self.assertEqual(cfg["mutacion"]["max"], 80)

    def test_mutacion_sin_archivos_falla(self):
        with self.assertRaises(ValueError):
            d.parsear_encargo(ENCARGO.replace("+++\n# Encargo", '[mutacion]\numbral = 0.5\n+++\n# Encargo'))

    def test_sin_bloque_falla(self):
        with self.assertRaises(ValueError):
            d.parsear_encargo("# solo markdown")

    def test_faltan_campos(self):
        with self.assertRaises(ValueError):
            d.parsear_encargo('+++\nid = "1"\n+++\n')

    def test_rechaza_tema_con_path_traversal(self):
        with self.assertRaises(ValueError):
            d.parsear_encargo(ENCARGO.replace("tests-nucleo", "../x"))


class TestMensaje(unittest.TestCase):
    def test_incrusta_cuerpo_sin_bloque_toml(self):
        m = d.mensaje_para_opencode(ENCARGO, Path("/tmp/wt"))
        self.assertIn("# Encargo 001", m)
        self.assertNotIn("+++", m)
        self.assertNotIn("oraculo =", m)


class TestEntornos(unittest.TestCase):
    def test_enlaza_venv_y_lo_excluye_de_git(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run = lambda *a, cwd=repo: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                                      cwd=cwd, check=True, capture_output=True)
            run("init", "-q", "-b", "main")
            (repo / ".venv").mkdir()
            (repo / "a.txt").write_text("x", encoding="utf-8")
            run("add", "a.txt")
            run("commit", "-qm", "base")
            wt = Path(tmp) / "wt"
            run("worktree", "add", str(wt), "-b", "opencode/x", "main")
            self.assertEqual(d.enlazar_entornos(repo, wt), [".venv"])
            self.assertTrue((wt / ".venv").is_symlink())
            self.assertEqual(d.git(wt, "status", "--porcelain"), "")
            self.assertEqual(d.enlazar_entornos(repo, wt), [])

    def test_sucios_lista_archivos_no_carpetas(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "docs" / "opencode").mkdir(parents=True)
            (repo / "docs" / "opencode" / "A.md").write_text("x", encoding="utf-8")
            self.assertEqual(d.listar_sucios(repo), ["docs/opencode/A.md"])
            self.assertEqual(d.fuera_de_alcance(d.listar_sucios(repo), ["tests/**"]), [])

    def test_mensaje_reemplaza_ruta_del_repo(self):
        m = d.mensaje_para_opencode(ENCARGO + "\nusar /tmp/demo/.venv/bin/python", Path("/tmp/wt"), Path("/tmp/demo"))
        self.assertIn("/tmp/wt/.venv/bin/python", m)
        self.assertNotIn("/tmp/demo", m)


class TestRevision(unittest.TestCase):
    def _evento(self, texto):
        import json
        return json.dumps({"type": "text", "part": {"type": "text", "text": texto}})

    def test_toma_la_respuesta_final_con_hallazgos(self):
        final = "## Veredicto\nCON_OBSERVACIONES\n\n## Hallazgos\n- [ALTA] a.py:3 — x\n- [BAJA] b.py:1 — y"
        lineas = [self._evento("Voy a mirar el diff"), "no es json", self._evento(final), self._evento("Listo")]
        self.assertEqual(d.texto_final_de_eventos(lineas), final)

    def test_resumen_cuenta_niveles(self):
        r = d.resumir_revision("## Veredicto\nCON_OBSERVACIONES\n\n## Hallazgos\n- [ALTA] a:1 — x\n- [MEDIA] b:2 — y\n- [MEDIA] c:3 — z")
        self.assertEqual((r["veredicto"], r["altas"], r["medias"], r["bajas"]), ("CON_OBSERVACIONES", 1, 2, 0))

    def test_sin_hallazgos(self):
        r = d.resumir_revision("## Veredicto\nAPTO\n\n## Hallazgos\n- ninguno")
        self.assertEqual((r["veredicto"], r["altas"]), ("APTO", 0))

    def test_cuerpo_sin_bloque(self):
        self.assertTrue(d.cuerpo_encargo(ENCARGO).startswith("# Encargo 001"))


class TestAlcance(unittest.TestCase):
    def test_dentro(self):
        self.assertEqual(d.fuera_de_alcance(["tests/test_a.py", "tests/sub/test_b.py"], ["tests/**"]), [])

    def test_fuera(self):
        self.assertEqual(d.fuera_de_alcance(["tests/a.py", "src/x.py"], ["tests/**"]), ["src/x.py"])

    def test_un_asterisco_no_cruza_directorios(self):
        self.assertEqual(d.fuera_de_alcance(["tests/sub/a.py"], ["tests/*.py"]), ["tests/sub/a.py"])

    def test_reporte_siempre_permitido(self):
        self.assertEqual(d.fuera_de_alcance(["REPORTE.md", "docs/opencode/x/BITACORA.md"], ["tests/**"]), [])

    def test_no_confunde_prefijos(self):
        self.assertEqual(d.fuera_de_alcance(["tests_extra/a.py"], ["tests/**"]), ["tests_extra/a.py"])


class TestVeredicto(unittest.TestCase):
    base = dict(timeout=False, rc_opencode=0, commits=1, sucios=[], fuera=[], oraculo_ok=True,
                dependencias=[], secretos=False)

    def v(self, **kw):
        return d.decidir_resultado(**{**self.base, **kw})

    def test_pasa(self):
        self.assertEqual(self.v(), "pasa")

    def test_gravedad_secreto_gana(self):
        self.assertEqual(self.v(secretos=True, fuera=["x"], oraculo_ok=False), "posible_secreto")

    def test_fuera_antes_que_oraculo(self):
        self.assertEqual(self.v(fuera=["src/x.py"], oraculo_ok=False), "fuera_de_alcance")

    def test_sin_cambios_y_error(self):
        self.assertEqual(self.v(commits=0), "sin_cambios")
        self.assertEqual(self.v(commits=0, rc_opencode=1), "error_opencode")

    def test_sin_commitear(self):
        self.assertEqual(self.v(sucios=["a.py"]), "trabajo_sin_commitear")

    def test_tests_debiles_por_mutacion(self):
        self.assertEqual(self.v(puntaje_mutacion=0.5, umbral_mutacion=0.8), "tests_debiles")
        self.assertEqual(self.v(puntaje_mutacion=0.9, umbral_mutacion=0.8), "pasa")
        self.assertEqual(self.v(puntaje_mutacion=None, umbral_mutacion=0.8), "pasa")

    def test_mutacion_no_enmascara_un_oraculo_roto(self):
        self.assertEqual(self.v(oraculo_ok=False, puntaje_mutacion=0.1, umbral_mutacion=0.8), "falla_oraculo")

    def test_falla_oraculo_y_timeout(self):
        self.assertEqual(self.v(oraculo_ok=False), "falla_oraculo")
        self.assertEqual(self.v(timeout=True), "timeout")


if __name__ == "__main__":
    unittest.main()
