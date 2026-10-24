import json
import unittest

from antigravity_cli import construir_comando, interpretar_resultado


class TestComandoAntigravity(unittest.TestCase):
    def test_comando_usa_json_headless_y_sandbox_sin_omitir_permisos(self):
        cmd = construir_comando("Inspeccioná el diff", 12, model="gemini-test", effort="high")
        self.assertEqual(cmd[:3], ["agy", "--print", "Inspeccioná el diff"])
        self.assertIn("--output-format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("--print-timeout", cmd)
        self.assertIn("12m", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)

    def test_rechaza_prompt_vacio_timeout_invalido_y_effort_desconocido(self):
        with self.assertRaises(ValueError):
            construir_comando(" ", 2)
        with self.assertRaises(ValueError):
            construir_comando("prompt", 0)
        with self.assertRaises(ValueError):
            construir_comando("prompt", 2, effort="maximum")

    def test_acepta_solo_sobre_success_con_response(self):
        result = interpretar_resultado(json.dumps({
            "status": "SUCCESS", "response": "hecho", "conversation_id": "c1",
            "usage": {"input_tokens": 10, "output_tokens": 2}
        }), 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["response"], "hecho")
        self.assertEqual(result["usage"]["input_tokens"], 10)

    def test_status_error_falla_aunque_json_sea_valido(self):
        result = interpretar_resultado(json.dumps({
            "status": "ERROR", "response": "", "error": "auth required"
        }), 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "ERROR")

    def test_denied_actions_se_clasifica_como_motor_sin_respuesta(self):
        result = interpretar_resultado(json.dumps({
            "status": "SUCCESS", "response": "", "denied_actions": [
                {"action": "write_file", "display_name": "EditFile"}
            ]
        }), 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["motivo"], "permisos_denegados")
        self.assertEqual(result["denied_actions"][0]["action"], "write_file")

    def test_json_malformado_vacio_o_no_objeto_se_rechaza(self):
        for value in ("", "not-json", "[]", "null"):
            with self.subTest(value=value):
                self.assertFalse(interpretar_resultado(value, 0)["ok"])

    def test_timeout_es_error_explicito(self):
        result = interpretar_resultado("", -1, timeout=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
