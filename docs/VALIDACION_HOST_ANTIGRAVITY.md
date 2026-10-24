# Validación de Antigravity CLI en el equipo anfitrión

Este procedimiento es una puerta de aceptación pendiente. Las pruebas unitarias del adaptador no demuestran que `agy` esté instalado, autenticado, que su formato real coincida con los fixtures ni que el sandbox aísle procesos en esta máquina.

## Condiciones previas

- Revisar los términos y políticas vigentes del proveedor para este modo de uso.
- Confirmar que se acepta el tratamiento externo de prompts, fragmentos de código y metadatos que implique el servicio.
- No ejecutar la primera prueba sobre un repositorio de trabajo real ni con secretos en el entorno.
- No usar `--dangerously-skip-permissions` ni opciones equivalentes que desactiven controles.
- Usar un directorio temporal descartable y una cuenta sin credenciales o archivos sensibles accesibles, en la medida que el entorno lo permita.

## Secuencia de comprobación

1. Registrar sistema operativo, fecha, versión de Antigravity CLI y ubicación del ejecutable:

   ```sh
   command -v agy
   agy --version
   agy --help
   ```

   Si alguno de estos comandos falla, detener la prueba; no instalar ni autenticar automáticamente.

2. Confirmar autenticación con el mecanismo oficial de la instalación. No copiar tokens, cookies ni salida sensible al informe.

3. Desde un directorio temporal vacío, realizar una petición inocua que no solicite cambios de archivos:

   ```sh
   agy --print "Respondé únicamente VALIDACION_AGY_OK. No ejecutes herramientas ni modifiques archivos." --output-format json --print-timeout 2m --sandbox
   ```

   Comprobar que el código de salida sea cero, que stdout sea JSON válido y que el objeto incluya `status` igual a `SUCCESS` y una respuesta textual no vacía. Registrar los nombres de campos observados, sin publicar prompts privados, credenciales ni el contenido completo de la conversación.

4. Verificar el comportamiento del sandbox por separado. La presencia de `--sandbox` en el comando **no demuestra** que el aislamiento esté activo. Usar solo un procedimiento de prueba revisado por el responsable del equipo, con archivos centinela desechables y sin datos reales. Si no puede demostrarse una denegación efectiva de una acción fuera del ámbito permitido, anotar el resultado como «aislamiento no verificado» y no usar Antigravity para encargos que dependan de esa frontera.

5. Probar el adaptador del orquestador únicamente después de completar las comprobaciones anteriores. Usar un encargo temporal de lectura sin cambios permitidos y un oráculo inocuo; revisar el estado, los logs y el diff resultante.

## Evidencia mínima

Registrar en un informe local:

- fecha y sistema operativo;
- versión de `agy`;
- estado de autenticación (solo aprobado/fallido, sin datos de cuenta);
- resultado de parseo JSON y campos reales observados;
- timeout probado o pendiente;
- sandbox: probado y denegación observada / no verificado / fallido;
- resultado de la ejecución a través del adaptador;
- incidencias y decisión de habilitar o no el backend.

No incluir tokens, cookies, contenido privado de prompts, rutas personales innecesarias ni logs completos con datos sensibles. La evidencia puede resumirse y sanitizarse antes de incorporarla al repositorio.

## Criterio de salida

La fase de validación anfitriona solo se considera aprobada cuando la autenticación y el contrato de salida se verifican en la instalación real, y el nivel de aislamiento requerido queda demostrado o se decide explícitamente no depender de él. Hasta entonces, Antigravity permanece optativo y no debe usarse como fallback automático.

## Resultado de la validación en el host (23/10/2026)

- Pasos 1-3: **aprobados** (`agy` 1.4.5, autenticación correcta, contrato JSON verificado).
- Paso 4 (sandbox): **no verificado**.
- Paso 5 (adaptador con encargos reales): **fallido**. En modo `--print`, `agy` deniega automáticamente las herramientas `command` y `write_file` si no hay reglas en `permissions.allow` de `~/.gemini/antigravity-cli/settings.json`, y aun así devuelve `status: SUCCESS` con `response` vacío.

**Decisión vigente:** Antigravity queda **deshabilitado para encargos que escriben archivos** hasta que Marcos decida si configura reglas de permiso acotadas (afectan a todo el host). Detalle, consumo observado y opciones en [evidencia/2026-10-23-antigravity-y-tanda-hanna.md](evidencia/2026-10-23-antigravity-y-tanda-hanna.md).
