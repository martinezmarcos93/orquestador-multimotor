import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import despachar as d  # noqa: E402
import sandbox  # noqa: E402


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                                 "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


class ArgvBwrap(unittest.TestCase):
    def test_argv_aisla_home_limpia_entorno_y_monta_solo_lo_necesario(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            repo = _repo(tmp)
            argv = sandbox.envolver(["echo", "hola"], wt=repo, datos=tmp / "datos", ro_extra=[])
            self.assertIn("--clearenv", argv)
            self.assertIn("--die-with-parent", argv)
            self.assertNotIn("--unshare-net", argv)  # el proxy LiteLLM vive en 127.0.0.1
            i = argv.index("--tmpfs", argv.index("/tmp"))
            self.assertEqual(argv[i + 1], str(Path.home()))
            self.assertEqual(argv[-3:], ["--", "echo", "hola"][-3:])
            self.assertTrue((tmp / "datos").is_dir())
            # el home real no se monta entero
            pares = [(argv[j], argv[j + 1]) for j, a in enumerate(argv[:-1]) if a == "--bind"]
            self.assertNotIn(str(Path.home()), [p[0] for p in pares])

    def test_modo_invalido_en_encargo(self):
        texto = ('+++\nid="1"\nproyecto="p"\nrepo="/x"\nagente="tester"\ntema="t"\n'
                 'permitidos=["a"]\noraculo=["true"]\nsandbox="docker"\n+++\ncuerpo\n')
        with self.assertRaises(ValueError):
            d.parsear_encargo(texto)

    def test_bwrap_no_aplica_a_codex(self):
        texto = ('+++\nid="1"\nproyecto="p"\nrepo="/x"\nagente="tester"\ntema="t"\n'
                 'permitidos=["a"]\noraculo=["true"]\nmotor="codex"\nsandbox="bwrap"\n+++\ncuerpo\n')
        with self.assertRaises(ValueError):
            d.parsear_encargo(texto)

    def test_confinar_sin_sandbox_no_toca_el_comando(self):
        self.assertEqual(d.confinar(["x"], {"sandbox": "ninguno"}, Path("/w"), Path("/r")), ["x"])


@unittest.skipUnless(sandbox.disponible(), "bwrap no disponible en este host")
class AislamientoReal(unittest.TestCase):
    def test_no_ve_home_ni_secretos_pero_puede_commitear(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            repo = _repo(tmp)
            centinela = Path.home() / f".orq-centinela-{os.getpid()}"
            centinela.write_text("secreto", encoding="utf-8")
            os.environ["ORQ_TEST_SECRETO"] = "no-debe-verse"
            try:
                script = (f"cat {centinela} 2>/dev/null; echo ENV=$ORQ_TEST_SECRETO; "
                          "echo x > f.txt && git add f.txt && "
                          "git -c user.name=t -c user.email=t@t commit -qm t && echo COMMIT; "
                          "touch /usr/no 2>/dev/null || echo USR_RO")
                cmd = sandbox.envolver(["bash", "-c", script], wt=repo, datos=tmp / "datos", ro_extra=[])
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=repo, timeout=60)
            finally:
                centinela.unlink(missing_ok=True)
                os.environ.pop("ORQ_TEST_SECRETO", None)
            self.assertNotIn("secreto", r.stdout)
            self.assertIn("ENV=\n", r.stdout)
            self.assertIn("COMMIT", r.stdout)
            self.assertIn("USR_RO", r.stdout)


if __name__ == "__main__":
    unittest.main()
