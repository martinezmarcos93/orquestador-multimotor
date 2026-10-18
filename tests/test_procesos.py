import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import procesos  # noqa: E402


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # un zombi cuenta como muerto
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


class Registro(unittest.TestCase):
    def test_terminar_activos_mata_el_grupo_completo(self):
        p = procesos.lanzar(["bash", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE, text=True)
        nieto = int(p.stdout.readline())
        self.assertTrue(_vivo(nieto))
        self.assertEqual(procesos.terminar_activos(gracia_s=2), 1)
        p.wait(timeout=5)
        time.sleep(0.3)
        self.assertFalse(_vivo(nieto))

    def test_sigterm_al_padre_no_deja_huerfanos(self):
        codigo = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(ROOT)!r})
            import procesos
            procesos.instalar_manejador()
            h = procesos.lanzar(["bash", "-c", "sleep 60 & echo $!; wait"])
            print(h.pid, flush=True)
            time.sleep(60)
        """)
        padre = subprocess.Popen([sys.executable, "-c", codigo], stdout=subprocess.PIPE, text=True)
        hijo = int(padre.stdout.readline())
        time.sleep(0.5)
        self.assertTrue(_vivo(hijo))
        padre.send_signal(signal.SIGTERM)
        self.assertEqual(padre.wait(timeout=10), 128 + signal.SIGTERM)
        time.sleep(0.5)
        self.assertFalse(_vivo(hijo))


if __name__ == "__main__":
    unittest.main()
