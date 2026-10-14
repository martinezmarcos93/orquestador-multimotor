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
        self.assertEqual(cfg["timeout_cola_min"], 50)
        self.assertFalse(cfg["permitir_entornos_compartidos"])
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

    def test_timeout_cola_debe_superar_timeout_del_worker(self):
        texto = ENCARGO.replace('oraculo = ["pytest -q"]', 'oraculo = ["pytest -q"]\ntimeout_min = 20\ntimeout_cola_min = 20')
        with self.assertRaisesRegex(ValueError, "timeout_cola_min"):
            d.parsear_encargo(texto)

    def test_timeout_worker_no_acepta_valores_no_positivos(self):
        texto = ENCARGO.replace('oraculo = ["pytest -q"]', 'oraculo = ["pytest -q"]\ntimeout_min = 0')
        with self.assertRaisesRegex(ValueError, "timeout_min"):
            d.parsear_encargo(texto)


class TestControlesHeuristicos(unittest.TestCase):
    def test_detecta_secreto_asignado_y_formato_json(self):
        self.assertTrue(d.posible_secreto('API_KEY="abcdefghijklmnop"'))
        self.assertTrue(d.posible_secreto('"client_secret": "abcdefghijklmnop"'))
        self.assertTrue(d.posible_secreto("AWS_ACCESS_KEY=AKIA1234567890ABCDEF"))
        self.assertFalse(d.posible_secreto('api_key = "corto"'))

    def test_detecta_formatos_comunes_de_tokens(self):
        self.assertTrue(d.posible_secreto("token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"))
        self.assertTrue(d.posible_secreto("-----BEGIN PRIVATE KEY-----"))

    def test_detecta_manifiestos_y_lockfiles_de_varios_ecosistemas(self):
        for ruta in ("requirements-dev.txt", "requirements-prod.in", "pnpm-lock.yaml",
                     "Cargo.lock", "go.mod", "composer.lock", "src/pyproject.toml"):
            with self.subTest(ruta=ruta):
                self.assertTrue(d.es_archivo_dependencias(ruta))

    def test_no_confunde_archivos_comunes_con_dependencias(self):
        self.assertFalse(d.es_archivo_dependencias("src/requirements_notes.md"))
        self.assertFalse(d.es_archivo_dependencias("src/application.py"))


class TestMensaje(unittest.TestCase):
    def test_incrusta_cuerpo_sin_bloque_toml(self):
        m = d.mensaje_para_opencode(ENCARGO, Path("/tmp/wt"))
        self.assertIn("# Encargo 001", m)
        self.assertNotIn("+++", m)
        self.assertNotIn("oraculo =", m)


class TestWorktreeBase(unittest.TestCase):
    def setUp(self):
        self.src_original = d.SRC
        self.addCleanup(setattr, d, "SRC", self.src_original)

    def _repo(self, root):
        import subprocess
        root.mkdir(parents=True)
        run = lambda *a, cwd=root: subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
            cwd=cwd, check=True, capture_output=True, text=True
        )
        run("init", "-q", "-b", "main")
        (root / "a.txt").write_text("base\n", encoding="utf-8")
        run("add", "a.txt")
        run("commit", "-qm", "base")
        return run

    def test_base_fijada_es_ancestro_del_worktree_nuevo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            run = self._repo(repo)
            d.SRC = root / "src"
            d.SRC.mkdir()
            cfg = {"proyecto": "demo", "tema": "tests-nucleo", "base": "main"}
            base_sha = d.git(repo, "rev-parse", "main")
            # Simula que la rama destino avanza entre capturar el SHA y crear el worktree.
            (repo / "race.txt").write_text("avance de main\n", encoding="utf-8")
            run("add", "race.txt")
            run("commit", "-qm", "avance durante preparación")
            wt, rama, reutilizado = d.preparar_worktree(cfg, repo, base_sha)
            self.assertFalse(reutilizado)
            self.assertTrue(rama.startswith("opencode/"))
            self.assertEqual(d.git(wt, "rev-parse", "HEAD"), base_sha)
            self.assertNotEqual(d.git(repo, "rev-parse", "main"), base_sha)
            self.assertTrue(d.base_es_ancestro(base_sha, wt))

    def test_base_que_avanza_deja_de_ser_ancestro_del_worktree_viejo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            run = self._repo(repo)
            d.SRC = root / "src"
            d.SRC.mkdir()
            cfg = {"proyecto": "demo", "tema": "tests-nucleo", "base": "main"}
            base_sha = d.git(repo, "rev-parse", "main")
            wt, _, _ = d.preparar_worktree(cfg, repo, base_sha)
            (repo / "a.txt").write_text("main avanzado\n", encoding="utf-8")
            run("add", "a.txt")
            run("commit", "-qm", "avanza main")
            base_nueva = d.git(repo, "rev-parse", "main")
            self.assertFalse(d.base_es_ancestro(base_nueva, wt))

    def test_diff_conserva_base_inicial_si_main_avanza_durante_la_corrida(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            run = self._repo(repo)
            d.SRC = root / "src"
            d.SRC.mkdir()
            cfg = {"proyecto": "demo", "tema": "tests-nucleo", "base": "main"}
            base_inicial = d.git(repo, "rev-parse", "main")
            wt, _, _ = d.preparar_worktree(cfg, repo, base_inicial)

            (wt / "worker.txt").write_text("cambio del worker\n", encoding="utf-8")
            run("add", "worker.txt", cwd=wt)
            run("commit", "-qm", "cambio worker", cwd=wt)

            (repo / "main.txt").write_text("avance externo\n", encoding="utf-8")
            run("add", "main.txt")
            run("commit", "-qm", "avance externo")
            base_actual = d.git(repo, "rev-parse", "main")

            self.assertNotEqual(base_inicial, base_actual)
            self.assertTrue(d.base_es_ancestro(base_inicial, wt))
            self.assertFalse(d.base_es_ancestro(base_actual, wt))
            self.assertEqual(
                d.git(wt, "diff", "--name-only", f"{base_inicial}..HEAD").splitlines(),
                ["worker.txt"],
            )

    def test_rechaza_rama_inesperada_en_worktree_reutilizado(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            run = self._repo(repo)
            d.SRC = root / "src"
            d.SRC.mkdir()
            wt = d.SRC / "demo-tests-nucleo"
            run("worktree", "add", str(wt), "-b", "feature/inesperada", "main")
            with self.assertRaisesRegex(RuntimeError, "rama inesperada"):
                d.preparar_worktree(
                    {"proyecto": "demo", "tema": "tests-nucleo", "base": "main"}, repo,
                    d.git(repo, "rev-parse", "main")
                )


class TestDryRunCLI(unittest.TestCase):
    def test_cli_dry_run_no_invoca_binario_opencode(self):
        import json, os, shutil, subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, repo, bin_dir = root / "home", root / "repo", root / "bin"
            home.mkdir()
            (home / ".config" / "opencode" / "agents").mkdir(parents=True)
            (home / ".config" / "opencode" / "agents" / "tester.md").write_text("agent test\\n", encoding="utf-8")
            repo.mkdir()
            bin_dir.mkdir()
            real_run = subprocess.run
            real_run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
            real_run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                      "commit", "--allow-empty", "-qm", "base"], cwd=repo, check=True, capture_output=True)
            marker = root / "opencode-invocado"
            fake = bin_dir / "opencode"
            fake.write_text("#!/usr/bin/env bash\nprintf called > " + str(marker) + "\n", encoding="utf-8")
            fake.chmod(0o755)
            proyecto = "drycli-" + root.name.replace("-", "")[:12]
            encargo_id = "dry-" + root.name.replace("-", "")[:12]
            encargo = root / "encargo.md"
            encargo.write_text(
                '+++\nid = "' + encargo_id + '"\nproyecto = "' + proyecto + '"\nrepo = "' +
                str(repo) + '"\nagente = "tester"\ntema = "dry-run"\nbase = "main"\n'
                'permitidos = ["tests/**"]\noraculo = ["false"]\n+++\n'
                '# Encargo de prueba\nNo modificar archivos; validar dry-run.\n',
                encoding="utf-8",
            )
            env = {**os.environ, "HOME": str(home), "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
            run_base = d.RUNS / f"{proyecto}-{encargo_id}"
            try:
                result = real_run(
                    [sys.executable, "-B", str(Path(d.__file__).resolve()), str(encargo), "--dry-run"],
                    cwd=Path(d.__file__).resolve().parent, env=env, capture_output=True, text=True, timeout=15
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr + "\n" + result.stdout)
                estado = json.loads(result.stdout)
                self.assertEqual(estado["resultado"], "dry_run")
                self.assertFalse(marker.exists(), "el CLI invocó opencode durante --dry-run")
                estado_path = Path(estado["estado_json"])
                self.assertTrue(estado_path.is_file())
                persistido = json.loads(estado_path.read_text(encoding="utf-8"))
                self.assertEqual(persistido["base_sha"], estado["base_sha"])
                self.assertEqual(persistido["head_sha_fin"], estado["head_sha_fin"])
                self.assertFalse(persistido["base_movida"])
                self.assertEqual(persistido["schema_version"], 1)
                self.assertEqual(persistido["estado_json"], str(estado_path))
                self.assertTrue(persistido["siguiente_accion"])
                self.assertEqual(d.validar_estado_v1(persistido), [])
            finally:
                shutil.rmtree(run_base, ignore_errors=True)

class TestWorktreeReutilizado(unittest.TestCase):
    def test_bloquea_worktree_reutilizado_con_cambios_sin_commitear(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            run_git = lambda *args, cwd=repo: subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                cwd=cwd, check=True, capture_output=True, text=True
            )
            run_git("init", "-q", "-b", "main")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            run_git("add", "base.txt")
            run_git("commit", "-qm", "base")
            old_runs, old_src = d.RUNS, d.SRC
            d.RUNS, d.SRC = root / "runs", root / "src"
            d.RUNS.mkdir()
            d.SRC.mkdir()
            self.addCleanup(setattr, d, "RUNS", old_runs)
            self.addCleanup(setattr, d, "SRC", old_src)
            wt = d.SRC / "demo-tests-nucleo"
            run_git("worktree", "add", str(wt), "-b", "opencode/test-tests-nucleo", "main")
            (wt / "intruso.txt").write_text("cambio ajeno\n", encoding="utf-8")
            marker = root / "oraculo_ejecutado"
            encargo = root / "encargo.md"
            encargo.write_text(
                '+++\nid = "dirty-001"\nproyecto = "demo"\nrepo = "' + str(repo) +
                '"\nagente = "tester"\ntema = "tests-nucleo"\nbase = "main"\n'
                'permitidos = ["tests/**"]\noraculo = ["touch ' + str(marker) + '"]\n+++\n# Encargo\n',
                encoding="utf-8",
            )
            estado = d.despachar(encargo)
            self.assertEqual(estado["resultado"], "worktree_reutilizado_sucio")
            self.assertIn("intruso.txt", estado["archivos_sucios_inicio"])
            self.assertFalse(marker.exists(), "no debe ejecutarse el oráculo sobre un worktree contaminado")


class TestDryRunIntegracion(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs_original, self.src_original = d.RUNS, d.SRC
        d.RUNS, d.SRC = self.root / "runs", self.root / "src"
        d.RUNS.mkdir()
        d.SRC.mkdir()
        self.addCleanup(setattr, d, "RUNS", self.runs_original)
        self.addCleanup(setattr, d, "SRC", self.src_original)

    def _git(self, repo, *args):
        import subprocess
        return subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
            cwd=repo, check=True, capture_output=True, text=True
        )

    def test_dry_run_prepara_worktree_y_no_lanza_opencode_ni_oraculo(self):
        import subprocess
        from unittest.mock import patch

        repo = self.root / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        self._git(repo, "add", "app.py")
        self._git(repo, "commit", "-qm", "base")
        encargo = self.root / "encargo.md"
        encargo.write_text(
            '+++\nid = "dry-001"\nproyecto = "demo"\nrepo = "' + str(repo) +
            '"\nagente = "tester"\ntema = "dry-run"\nbase = "main"\n'
            'permitidos = ["tests/**"]\noraculo = ["python -c \\\"raise SystemExit(99)\\\""]\n+++\n'
            '# Encargo de prueba\nCrear tests ficticios sin cambiar producción.\n',
            encoding="utf-8",
        )
        real_run = subprocess.run
        commands = []

        def registrar_run(args, *a, **kw):
            if isinstance(args, (list, tuple)):
                commands.append(list(args))
            return real_run(args, *a, **kw)

        with patch("despachar.subprocess.run", side_effect=registrar_run), \
             patch("despachar.ejecutar_proceso_con_timeout") as modelo:
            estado = d.despachar(encargo, dry_run=True)
        modelo.assert_not_called()

        self.assertEqual(estado["resultado"], "dry_run")
        self.assertEqual(estado["base_sha"], estado["head_sha_inicio"])
        self.assertEqual(estado["head_sha_inicio"], estado["head_sha_fin"])
        self.assertFalse(estado["base_movida"])
        self.assertIn("Crear tests ficticios", estado["mensaje"])
        self.assertFalse(any(cmd and cmd[0] == "opencode" for cmd in commands))
        self.assertFalse(any(cmd and cmd[0] == "python" and "-c" in cmd for cmd in commands))
        self.assertFalse((Path(estado["worktree"]) / "app.py").read_text(encoding="utf-8").startswith("raise"))


class TestSalidaTemprana(unittest.TestCase):
    def test_baseline_rojo_persiste_snapshots_sin_lanzar_opencode(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            run_git = lambda *args: __import__("subprocess").run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                cwd=repo, check=True, capture_output=True, text=True
            )
            run_git("init", "-q", "-b", "main")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            run_git("add", "base.txt")
            run_git("commit", "-qm", "base")
            encargo = root / "encargo.md"
            encargo.write_text(
                '+++\nid = "early-001"\nproyecto = "early"\nrepo = "' + str(repo) +
                '"\nagente = "tester"\ntema = "baseline"\nbase = "main"\n'
                'permitidos = ["tests/**"]\noraculo = ["false"]\n'
                'exige_baseline_verde = true\n+++\n# Prueba\n',
                encoding="utf-8",
            )
            old_runs, old_src = d.RUNS, d.SRC
            d.RUNS, d.SRC = root / "runs", root / "src"
            d.RUNS.mkdir()
            d.SRC.mkdir()
            self.addCleanup(setattr, d, "RUNS", old_runs)
            self.addCleanup(setattr, d, "SRC", old_src)
            with patch("despachar.subprocess.run", wraps=__import__("subprocess").run) as mocked, \
                 patch("despachar.ejecutar_proceso_con_timeout") as modelo:
                estado = d.despachar(encargo)
            modelo.assert_not_called()
            self.assertEqual(estado["resultado"], "baseline_rojo")
            self.assertEqual(estado["base_sha"], estado["base_sha_actual_fin"])
            self.assertEqual(estado["head_sha_inicio"], estado["head_sha_fin"])
            self.assertFalse(estado["base_movida"])
            self.assertTrue(estado["main_intacto"])
            self.assertFalse(any(
                isinstance(call.args[0], (list, tuple)) and call.args[0] and call.args[0][0] == "opencode"
                for call in mocked.call_args_list
            ))


class TestEntornos(unittest.TestCase):
    def test_no_comparte_entornos_por_defecto(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run = lambda *a, cwd=repo: subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                cwd=cwd, check=True, capture_output=True
            )
            run("init", "-q", "-b", "main")
            (repo / ".venv").mkdir()
            (repo / "a.txt").write_text("x", encoding="utf-8")
            run("add", "a.txt")
            run("commit", "-qm", "base")
            wt = Path(tmp) / "wt"
            run("worktree", "add", str(wt), "-b", "opencode/x", "main")
            self.assertEqual(d.enlazar_entornos(repo, wt), [])
            self.assertFalse((wt / ".venv").exists())
            self.assertFalse((wt / ".venv").is_symlink())

    def test_opt_in_de_entornos_compartidos_debe_ser_booleano(self):
        texto = ENCARGO.replace('oraculo = ["pytest -q"]',
                                'oraculo = ["pytest -q"]\npermitir_entornos_compartidos = "si"')
        with self.assertRaisesRegex(ValueError, "debe ser booleano"):
            d.parsear_encargo(texto)

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
            self.assertEqual(d.enlazar_entornos(repo, wt, permitir_compartidos=True), [".venv"])
            self.assertTrue((wt / ".venv").is_symlink())
            self.assertEqual(d.git(wt, "status", "--porcelain"), "")
            self.assertEqual(d.enlazar_entornos(repo, wt, permitir_compartidos=True), [])

    def test_sucios_no_pierde_la_primera_letra_de_un_archivo_modificado(self):
        """Regresión: git() hacía strip() y ' M archivo' perdía un carácter ('arket_analyzer.py')."""
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                            cwd=repo, check=True, capture_output=True)
            run("init", "-q", "-b", "main")
            (repo / "market_analyzer.py").write_text("a", encoding="utf-8")
            (repo / "docs").mkdir()
            (repo / "docs" / "x.md").write_text("a", encoding="utf-8")
            run("add", "-A")
            run("commit", "-qm", "base")
            (repo / "market_analyzer.py").write_text("b", encoding="utf-8")      # ' M'
            (repo / "docs" / "x.md").write_text("b", encoding="utf-8")           # ' M'
            self.assertEqual(sorted(d.listar_sucios(repo)), ["docs/x.md", "market_analyzer.py"])

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

    def test_revision_apta_y_sin_hallazgos_aprueba(self):
        texto = "## Veredicto\nAPTO\n\n## Hallazgos\n- ninguno"
        r = d.validar_formato_revision(texto)
        self.assertTrue(r["formato_valido"])
        self.assertEqual(d.aprobar_revision(r), "aprobado")

    def test_revision_con_observaciones_no_aprueba(self):
        texto = ("## Veredicto\nCON_OBSERVACIONES\n\n## Hallazgos\n"
                 "- [ALTA] src/a.py:3 — posible regresión. Evidencia: diff de la función")
        r = d.validar_formato_revision(texto)
        self.assertTrue(r["formato_valido"])
        self.assertEqual(d.aprobar_revision(r), "con_observaciones")

    def test_revision_malformada_no_aprueba(self):
        r = d.validar_formato_revision("APTO, todo bien")
        self.assertFalse(r["formato_valido"])
        self.assertEqual(d.aprobar_revision(r), "revision_formato_invalido")

    def test_revision_apta_con_hallazgo_alto_es_inconsistente(self):
        texto = ("## Veredicto\nAPTO\n\n## Hallazgos\n"
                 "- [ALTA] src/a.py:3 — posible regresión. Evidencia: diff de la función")
        r = d.validar_formato_revision(texto)
        self.assertFalse(r["formato_valido"])
        self.assertEqual(d.aprobar_revision(r), "revision_formato_invalido")

    def test_error_o_timeout_del_revisor_bloquea_aprobacion(self):
        self.assertEqual(d.aprobar_revision({"error": "timeout"}), "revision_error")


class TestRevisionProceso(unittest.TestCase):
    def setUp(self):
        import tempfile, subprocess
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wt = self.root / "repo"
        self.wt.mkdir()
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.real_run = subprocess.run
        self.real_run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "init", "-q", "-b", "main"],
            cwd=self.wt, check=True, capture_output=True
        )
        (self.wt / "base.txt").write_text("base\n", encoding="utf-8")
        self.real_run(["git", "add", "base.txt"], cwd=self.wt, check=True, capture_output=True)
        self.real_run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"],
            cwd=self.wt, check=True, capture_output=True
        )

    def _runner_mock(self, report, returncode=0, mutate=False, timeout=False):
        import json

        def fake(cmd, **kwargs):
            if mutate:
                (self.wt / "intruso.txt").write_text("modificado\\n", encoding="utf-8")
            if report is not None:
                kwargs["stdout"].write(json.dumps({
                    "type": "text", "part": {"type": "text", "text": report}
                }) + "\n")
                kwargs["stdout"].flush()
            return (-1 if timeout else returncode, timeout)
        return fake

    def test_revision_rechaza_worktree_sucio_sin_lanzar_modelo(self):
        from unittest.mock import patch
        (self.wt / "cambio_preexistente.txt").write_text("sin commitear\\n", encoding="utf-8")
        with patch("despachar.ejecutar_proceso_con_timeout") as modelo:
            r = d.revisar({"id": "r0", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertIn("cambios sin commitear", r["error"])
        self.assertIn("cambio_preexistente.txt", r["archivos_sucios"])
        modelo.assert_not_called()

    def test_revision_valida_con_open_code_simulado(self):
        from unittest.mock import patch
        reporte = "## Veredicto\nAPTO\n\n## Hallazgos\n- ninguno"
        with patch("despachar.ejecutar_proceso_con_timeout", side_effect=self._runner_mock(reporte)):
            r = d.revisar({"id": "r1", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertTrue(r["formato_valido"])
        self.assertEqual(d.aprobar_revision(r), "aprobado")

    def test_timeout_real_del_runner_simulado_bloquea_revision(self):
        from unittest.mock import patch
        with patch("despachar.ejecutar_proceso_con_timeout", side_effect=self._runner_mock(None, timeout=True)):
            r = d.revisar({"id": "r2", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertIn("excedió el tiempo", r["error"])
        self.assertEqual(d.aprobar_revision(r), "revision_error")

    def test_codigo_no_cero_bloquea_revision_aunque_haya_texto(self):
        from unittest.mock import patch
        reporte = "## Veredicto\nAPTO\n\n## Hallazgos\n- ninguno"
        with patch("despachar.ejecutar_proceso_con_timeout", side_effect=self._runner_mock(reporte, returncode=7)):
            r = d.revisar({"id": "r3", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertIn("código 7", r["error"])
        self.assertEqual(d.aprobar_revision(r), "revision_error")

    def test_mutacion_del_worktree_bloquea_revision(self):
        from unittest.mock import patch
        reporte = "## Veredicto\nAPTO\n\n## Hallazgos\n- ninguno"
        with patch("despachar.ejecutar_proceso_con_timeout", side_effect=self._runner_mock(reporte, mutate=True)):
            r = d.revisar({"id": "r4", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertIn("modificó el worktree", r["error"])
        self.assertEqual(d.aprobar_revision(r), "revision_error")

    def test_salida_vacia_o_malformada_bloquea_revision(self):
        from unittest.mock import patch
        with patch("despachar.ejecutar_proceso_con_timeout", side_effect=self._runner_mock(None)):
            r = d.revisar({"id": "r5", "timeout_min": 1}, ENCARGO, self.wt, self.run_dir, "main")
        self.assertIn("no devolvió texto", r["error"])
        self.assertEqual(d.aprobar_revision(r), "revision_error")


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

    def test_mutacion_sin_candidatos_o_con_error_no_aprueba(self):
        self.assertEqual(
            self.v(puntaje_mutacion=None, umbral_mutacion=0.8, sin_candidatos_mutacion=True),
            "mutacion_sin_candidatos",
        )
        self.assertEqual(self.v(error_mutacion=True), "error_mutacion")

    def test_mutacion_no_enmascara_un_oraculo_roto(self):
        self.assertEqual(self.v(oraculo_ok=False, puntaje_mutacion=0.1, umbral_mutacion=0.8), "falla_oraculo")

    def test_falla_oraculo_y_timeout(self):
        self.assertEqual(self.v(oraculo_ok=False), "falla_oraculo")
        self.assertEqual(self.v(timeout=True), "timeout")




class TestOraculoTimeout(unittest.TestCase):
    def test_timeout_de_open_code_termina_grupo_completo(self):
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "sobrevivio.txt"
            child = (
                "import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(0.5); pathlib.Path(" + repr(str(marker)) + ").write_text('vivo')"
            )
            parent = (
                "import signal,subprocess,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(10)"
            )
            with (root / "stdout.log").open("w", encoding="utf-8") as out, \
                 (root / "stderr.log").open("w", encoding="utf-8") as err:
                codigo, agotado = d.ejecutar_proceso_con_timeout(
                    [sys.executable, "-c", parent], cwd=root, timeout_s=0.1,
                    stdout=out, stderr=err, gracia_s=0.1,
                )
            self.assertTrue(agotado)
            self.assertIsNotNone(codigo)
            time.sleep(0.6)
            self.assertFalse(marker.exists(), "un descendiente de OpenCode sobrevivió al timeout")

    def test_timeout_termina_descendiente_del_oraculo(self):
        import shlex
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "sobrevivio.txt"
            child = (
                "import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(0.6); pathlib.Path(" + repr(str(marker)) + ").write_text('vivo')"
            )
            parent = (
                "import signal,subprocess,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(10)"
            )
            comando = shlex.quote(sys.executable) + " -c " + shlex.quote(parent)
            log = root / "oraculo.log"
            ok = d.correr_oraculo([comando], root, root, log, timeout_s=0.1, gracia_s=0.1)
            self.assertFalse(ok)
            self.assertIn("timeout tras", log.read_text(encoding="utf-8"))
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "un descendiente del oráculo sobrevivió al timeout")


class TestEstadoVersionado(unittest.TestCase):
    def test_normaliza_estado_con_accion_y_timestamps_utc(self):
        estado = d.normalizar_estado({"resultado": "baseline_rojo"}, "2026-10-14T00:00:00+00:00")
        self.assertEqual(estado["schema_version"], 1)
        self.assertEqual(estado["inicio_utc"], "2026-10-14T00:00:00+00:00")
        self.assertTrue(estado["fin_utc"].endswith("+00:00"))
        self.assertIn("baseline", estado["siguiente_accion"])
        self.assertEqual(d.validar_estado_v1(estado), [])

    def test_rechaza_estado_sin_zona_horaria_o_version_incorrecta(self):
        estado = d.normalizar_estado({"resultado": "pasa"}, "2026-10-14T00:00:00")
        estado["schema_version"] = 2
        errores = d.validar_estado_v1(estado)
        self.assertTrue(any("schema_version" in e for e in errores))
        self.assertTrue(any("zona horaria" in e for e in errores))

    def test_schema_documenta_contrato_minimo_versionado(self):
        import json
        schema_path = Path(d.__file__).resolve().parent / "schemas" / "estado.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertTrue({"schema_version", "inicio_utc", "fin_utc", "resultado", "siguiente_accion"}
                        <= set(schema["required"]))

class TestValidacionEncargo(unittest.TestCase):
    def test_detecta_rutas_absolutas_externas_sin_confundir_repo_o_url(self):
        cuerpo = (
            "+++\nid = \"1\"\n+++\n"
            "Editar /tmp/proyecto/src/app.py, no /etc/passwd. "
            "Referencia https://example.com/docs."
        )
        self.assertEqual(
            d.rutas_absolutas_externas(cuerpo, Path("/tmp/proyecto")),
            ["/etc/passwd"],
        )

    def test_rechaza_campos_identificadores_que_no_sean_cadenas(self):
        valores = {"id": "001", "proyecto": "demo", "agente": "tester", "tema": "tests-nucleo"}
        for campo, valor in valores.items():
            texto = ENCARGO.replace(f'{campo} = "{valor}"', f"{campo} = 123")
            with self.subTest(campo=campo), self.assertRaisesRegex(ValueError, campo):
                d.parsear_encargo(texto)

    def test_rechaza_patrones_de_alcance_absolutos_o_con_traversal(self):
        for patron in ("/etc/**", "../secreto.txt", "src/../../secreto.txt"):
            with self.subTest(patron=patron), self.assertRaisesRegex(ValueError, "patrón inseguro"):
                d.parsear_encargo(ENCARGO.replace('["tests/**"]', f'["{patron}"]'))

    def test_normaliza_encargo_con_finales_de_linea_windows(self):
        texto = ENCARGO.replace("\n", "\r\n")
        cfg = d.parsear_encargo(texto)
        self.assertEqual(cfg["id"], "001")
        self.assertEqual(d.cuerpo_encargo(texto), "# Encargo 001")

    def test_rechaza_ejecutable_de_oraculo_inexistente(self):
        error, aviso = d.validar_comando_oraculo("ejecutable_oraculo_que_no_existe_123", Path("/tmp/repo"))
        self.assertIn("no se encuentra", error)
        self.assertIsNone(aviso)

    def test_advierte_si_el_oraculo_depende_de_sintaxis_de_shell(self):
        error, aviso = d.validar_comando_oraculo("cd src && pytest -q", Path("/tmp/repo"))
        self.assertIsNone(error)
        self.assertIn("no se verifica estáticamente", aviso)

    def test_rechaza_oraculo_que_no_es_lista_de_comandos(self):
        texto = ENCARGO.replace('oraculo = ["pytest -q"]', 'oraculo = "pytest -q"')
        with self.assertRaisesRegex(ValueError, "oraculo"):
            d.parsear_encargo(texto)

    def test_rechaza_umbral_de_mutacion_fuera_de_rango(self):
        texto = ENCARGO.replace(
            "+++\n# Encargo",
            '[mutacion]\narchivos = ["src.py"]\numbral = 1.5\n+++\n# Encargo',
        )
        with self.assertRaisesRegex(ValueError, "mutacion.umbral"):
            d.parsear_encargo(texto)

    def test_valida_repo_base_y_agente_sin_ejecutar_oraculo(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

            agentes = root / "agents"
            agentes.mkdir()
            (agentes / "tester.md").write_text("agent test\n", encoding="utf-8")
            encargo = root / "encargo.md"
            comando_no_ejecutar = "touch " + str(repo / "NO_EJECUTAR")
            texto = ENCARGO.replace("/tmp/demo", str(repo)).replace(
                'oraculo = ["pytest -q"]',
                f'oraculo = ["{comando_no_ejecutar}"]',
            )
            encargo.write_text(texto, encoding="utf-8")

            resultado = d.validar_encargo(encargo, directorio_agentes=agentes)

            self.assertTrue(resultado["valido"], resultado)
            self.assertEqual(resultado["resultado"], "encargo_valido")
            self.assertFalse((repo / "NO_EJECUTAR").exists())

            (agentes / "revisor.md").write_text("agent review\\n", encoding="utf-8")
            (agentes / "tester.md").unlink()
            solo_revision = d.validar_encargo(encargo, directorio_agentes=agentes, solo_revisor=True)
            self.assertTrue(solo_revision["valido"], solo_revision)
            (agentes / "tester.md").write_text("agent test\\n", encoding="utf-8")

            encargo.write_text(texto.replace(comando_no_ejecutar, "oraculo_no_existe_123"), encoding="utf-8")
            oraculo_invalido = d.validar_encargo(encargo, directorio_agentes=agentes)
            self.assertFalse(oraculo_invalido["valido"])
            self.assertTrue(any("no se encuentra el ejecutable" in e for e in oraculo_invalido["errores"]))

            (agentes / "higiene.md").write_text("agent test\\n", encoding="utf-8")
            encargo.write_text(texto.replace('agente = "tester"', 'agente = "higiene"'), encoding="utf-8")
            higiene = d.validar_encargo(encargo, directorio_agentes=agentes)
            self.assertFalse(higiene["valido"])
            self.assertTrue(any("exige_baseline_verde = true" in e for e in higiene["errores"]))

            encargo.write_text(texto.replace('agente = "tester"', 'agente = "tester"\nbase = "rama-inexistente"'), encoding="utf-8")
            base_invalida = d.validar_encargo(encargo, directorio_agentes=agentes)
            self.assertFalse(base_invalida["valido"])
            self.assertTrue(any("referencia base" in e for e in base_invalida["errores"]))

            encargo.write_text(texto + ("x" * d.MAX_CUERPO_ENCARGO), encoding="utf-8")
            cuerpo_largo = d.validar_encargo(encargo, directorio_agentes=agentes)
            self.assertFalse(cuerpo_largo["valido"])
            self.assertTrue(any("supera el límite" in e for e in cuerpo_largo["errores"]))

    def test_cli_validar_no_crea_worktree_ni_ejecuta_oraculo(self):
        import json
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "README.md").write_text("base\\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

            home = root / "home"
            agentes = home / ".config" / "opencode" / "agents"
            agentes.mkdir(parents=True)
            (agentes / "tester.md").write_text("agent test\\n", encoding="utf-8")
            encargo = root / "encargo.md"
            comando_no_ejecutar = "touch " + str(repo / "NO_EJECUTAR")
            texto = ENCARGO.replace("/tmp/demo", str(repo)).replace(
                'oraculo = ["pytest -q"]',
                f'oraculo = ["{comando_no_ejecutar}"]',
            )
            encargo.write_text(texto, encoding="utf-8")

            entorno = os.environ.copy()
            entorno["HOME"] = str(home)
            proceso = subprocess.run(
                [sys.executable, str(Path(d.__file__).resolve()), str(encargo), "--validar"],
                cwd=root, env=entorno, capture_output=True, text=True, check=False,
            )

            self.assertEqual(proceso.returncode, 0, proceso.stderr + proceso.stdout)
            resultado = json.loads(proceso.stdout)
            self.assertTrue(resultado["valido"], resultado)
            self.assertFalse((repo / "NO_EJECUTAR").exists())
            self.assertFalse((home / "src").exists())


    def test_cli_bloquea_encargo_si_falta_agente_instalado(self):
        import json
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "README.md").write_text("base\\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
            home = root / "home"
            (home / ".config" / "opencode" / "agents").mkdir(parents=True)
            encargo = root / "encargo.md"
            comando_no_ejecutar = "touch " + str(repo / "NO_EJECUTAR")
            encargo.write_text(
                ENCARGO.replace("/tmp/demo", str(repo)).replace(
                    'oraculo = ["pytest -q"]', f'oraculo = ["{comando_no_ejecutar}"]'
                ),
                encoding="utf-8",
            )
            entorno = os.environ.copy()
            entorno["HOME"] = str(home)
            proceso = subprocess.run(
                [sys.executable, str(Path(d.__file__).resolve()), str(encargo), "--dry-run"],
                cwd=root, env=entorno, capture_output=True, text=True, check=False,
            )
            resultado = json.loads(proceso.stdout)
            self.assertEqual(proceso.returncode, 1)
            self.assertEqual(resultado["resultado"], "encargo_invalido")
            self.assertTrue(any("no está instalado" in e for e in resultado["errores"]))
            self.assertFalse((repo / "NO_EJECUTAR").exists())
            self.assertFalse((home / "src").exists())


if __name__ == "__main__":
    unittest.main()
