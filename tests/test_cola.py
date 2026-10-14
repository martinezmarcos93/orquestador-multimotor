import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cola


def enc(id_, repo="/r", tema=None, permitidos=("tests/**",)):
    return {"ruta": Path(f"/e/{id_}.md"),
            "cfg": {"id": id_, "proyecto": "p", "repo": repo, "tema": tema or f"t{id_}", "permitidos": list(permitidos)}}


class Sonda:
    """Runner falso que registra concurrencia máxima y solapamientos entre ids."""
    def __init__(self, resultado="pasa", demora=0.05, por_id=None):
        self.activos, self.maximo, self.solapes = set(), 0, []
        self.lock, self.resultado, self.demora, self.por_id = threading.Lock(), resultado, demora, por_id or {}
        self.lanzados = []

    def __call__(self, e):
        id_ = e["cfg"]["id"]
        with self.lock:
            self.solapes += [(id_, o) for o in self.activos]
            self.activos.add(id_)
            self.maximo = max(self.maximo, len(self.activos))
            self.lanzados.append(id_)
        time.sleep(self.demora)
        with self.lock:
            self.activos.discard(id_)
        return {"id": id_, "proyecto": "p", "resultado": self.por_id.get(id_, self.resultado)}


class TestSePisan(unittest.TestCase):
    def test_repos_distintos_no_se_pisan(self):
        self.assertFalse(cola.se_pisan(enc("1", repo="/a")["cfg"], enc("2", repo="/b")["cfg"]))

    def test_mismo_tema_se_pisan(self):
        self.assertTrue(cola.se_pisan(enc("1", tema="x", permitidos=["a/**"])["cfg"],
                                      enc("2", tema="x", permitidos=["b/**"])["cfg"]))

    def test_prefijos_anidados_se_pisan(self):
        self.assertTrue(cola.se_pisan(enc("1", permitidos=["tests/**"])["cfg"],
                                      enc("2", permitidos=["tests/test_a.py"])["cfg"]))

    def test_disjuntos_no_se_pisan(self):
        self.assertFalse(cola.se_pisan(enc("1", permitidos=["src/**"])["cfg"],
                                       enc("2", permitidos=["tests/**"])["cfg"]))

    def test_comodin_total_pisa_todo(self):
        self.assertTrue(cola.se_pisan(enc("1", permitidos=["**"])["cfg"], enc("2", permitidos=["src/x.py"])["cfg"]))


class TestPlanificar(unittest.TestCase):
    def test_respeta_el_maximo_de_paralelismo(self):
        s = Sonda()
        cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(6)], s, max_paralelo=2)
        self.assertEqual(s.maximo, 2)
        self.assertEqual(len(s.lanzados), 6)

    def test_nunca_pasa_del_tope_duro(self):
        s = Sonda()
        cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(8)], s, max_paralelo=10)
        self.assertLessEqual(s.maximo, cola.MAX_PERMITIDO)

    def test_conflictivos_no_se_solapan(self):
        s = Sonda()
        cola.planificar([enc("1", permitidos=["tests/**"]), enc("2", permitidos=["tests/a.py"]),
                         enc("3", permitidos=["src/**"])], s, max_paralelo=3)
        self.assertNotIn(("2", "1"), s.solapes)
        self.assertNotIn(("1", "2"), s.solapes)
        self.assertEqual(sorted(s.lanzados), ["1", "2", "3"])

    def test_independientes_si_corren_juntos(self):
        s = Sonda(demora=0.15)
        cola.planificar([enc("1", permitidos=["a/**"]), enc("2", permitidos=["b/**"])], s, max_paralelo=2)
        self.assertTrue(s.solapes)

    def test_corta_tras_fallos_de_infraestructura_seguidos(self):
        s = Sonda(resultado="timeout")
        res = cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(6)], s, max_paralelo=1, corte_fallos=2)
        self.assertEqual(len(s.lanzados), 2)
        self.assertEqual(sum(1 for r in res if r["resultado"] == "no_lanzado"), 4)

    def test_un_exito_reinicia_la_racha(self):
        s = Sonda(por_id={"0": "timeout", "2": "timeout"})
        res = cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(4)], s, max_paralelo=1, corte_fallos=2)
        self.assertEqual(len(s.lanzados), 4)
        self.assertFalse(any(r["resultado"] == "no_lanzado" for r in res))

    def test_excepcion_del_runner_no_tumba_la_cola(self):
        def malo(e):
            if e["cfg"]["id"] == "1":
                raise RuntimeError("boom")
            return {"id": e["cfg"]["id"], "proyecto": "p", "resultado": "pasa"}
        res = cola.planificar([enc("1", permitidos=["a/**"]), enc("2", permitidos=["b/**"])], malo, max_paralelo=2)
        self.assertEqual({r["id"]: r["resultado"] for r in res}, {"1": "error_cola", "2": "pasa"})


if __name__ == "__main__":
    unittest.main()
