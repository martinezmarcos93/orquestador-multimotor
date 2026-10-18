# Evidencia P9 — cooldown de modelos en LiteLLM

Reproduce, sin gastar cuota, que el router de LiteLLM saltea un modelo caído y lo reintenta pasado el enfriamiento.

1. `python3 fake.py 4020 ok &` y `python3 fake.py 4021 bad &` (servidores OpenAI-compatibles falsos que cuentan peticiones).
2. `LITELLM_MASTER_KEY=sk-test-local-4010 litellm --config cfg.yaml --port 4010 &` (no tocar el proxy real del puerto 4000).
3. `bash run.sh`.

Resultado del 2026-10-17 (litellm 1.104.2, `allowed_fails: 1`, `cooldown_time: 8`): el modelo caído recibió 2 peticiones y 0 en las dos siguientes (todas respondidas por el de respaldo); tras esperar 10 s recibió una tercera. La configuración de producción (`~/.config/opencode-free/litellm.yaml`) ya declara `allowed_fails: 1` y `cooldown_time: 60`, así que **no hace falta código en el orquestador**.
