# Orquestador post-llamada — Kontaktu

## Cómo se ejecuta

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # rellenar OPENAI_API_KEY; MODELO ya trae gpt-4o-mini por defecto

python run.py eventos/01-call-ended-nuria.json
```

Cada invocación es un proceso nuevo, tal como pide el enunciado: no hay estado en memoria entre
llamadas. Todo lo que sobrevive entre ejecuciones vive en `estado/kontaktu.sqlite3` (se crea solo,
gitignored). Para reproducir el lote completo desde cero, en el orden correcto:

```bash
rm -rf estado salida
tail -n +2 eventos/orden.txt | while read -r f; do python run.py "eventos/$f"; done
```

`salida/decisiones.jsonl` y `salida/ordenes.jsonl` se van generando por *append*. `visor/index.html`
carga esa carpeta para inspeccionarlo visualmente.

## Modelo elegido y por qué

`gpt-4o-mini`, vía el SDK oficial de `openai` (sin LangChain: hay un único punto de integración
con el modelo — el nodo que lee el transcript — y añadir una capa de abstracción de LangChain
encima no aporta nada con un solo caso de uso; sí añadiría una dependencia más). Se usa con
**salida estructurada** (`response_format` con un modelo pydantic), para que la respuesta venga
ya tipada y validada, no texto libre que haya que parsear.

Es un modelo barato y rápido porque la tarea que se le pide es deliberadamente acotada: extraer
hechos objetivos de una transcripción corta (¿pide callback?, ¿rechaza WhatsApp?, ¿se acordó una
visita?...), no razonar ni decidir la etiqueta final — eso lo hace `business_rules.py`, en
Python plano y auditable. El modelo solo se invoca cuando la señalización SIP/AMD no basta para
clasificar la llamada (`telephony.classify_from_signaling` devuelve `None`); en el resto de casos
no se gasta ni un token.

## Qué decidí dejar fuera, y por qué

- **Sin checkpointer de LangGraph para persistir entre procesos.** La memoria entre ejecuciones
  (intentos, recordatorios, bajas, dedupe) la lleva una capa SQLite propia (`repository.py`), no
  el mecanismo interno de checkpoints de LangGraph. Es más código a mano, pero cada tabla y cada
  query son explícitos y fáciles de auditar, en vez de depender de la semántica de fusión de
  snapshots del framework.
- **Sin reintentos automáticos si la llamada al LLM falla** (rate limit, timeout de red). Un
  fallo ahí hace que ese evento termine con código de salida distinto de cero, sin afectar a los
  demás (R8) — no se implementó backoff/retry porque el reto no lo pide y añadía complejidad sin
  un caso de prueba real que lo justificara.
- **No se valida cada combinación imposible de señales** que en teoría podría devolver el LLM
  (p. ej. que marque `pide_callback` y `ya_no_busca_propiedad` a la vez). En su lugar, hay una
  prioridad fija y total en `business_rules.classify_from_signals` — la primera condición que se
  cumple gana, sin necesitar que las demás sean mutuamente excluyentes por contrato.
- **Sin tests automatizados** (no los pide el enunciado). La verificación se hizo de forma manual
  y reproducible — ver el apartado siguiente.

## Cómo verifiqué que hace lo que creo que hace

1. **Los 16 eventos de `eventos/orden.txt`, en orden, desde cero**: cada etiqueta y cada orden
   generada se comparó a mano contra `casos.md`. El evento 09 (Javier, `callback`) coincide
   carácter por carácter con el ejemplo que trae el propio `enunciado.md` (`entry_id`, `teléfono`,
   `no_antes_de`, y la interpretación de "mañana a las seis" → `18:00`). Los `orden_id` que genera
   mi código para el evento del `ejemplo-resuelto` coinciden también carácter por carácter con los
   oficiales, confirmando que uso el mismo esquema de hash (`sha1(idempotency_key)[:8]`).
2. **Reentrega (evento 15)**: confirmado que repite la etiqueta original sin duplicar ninguna
   orden (R5).
3. **Los 3 casos del catálogo sin evento de ejemplo** (`rechazada`/603, `callback` fuera de
   ventana, `descartado`) los probé construyendo eventos sintéticos en memoria — sin tocar
   `eventos/` — a partir de eventos reales con el campo relevante modificado. Los tres se
   comportaron tal como los describe `casos.md`.
4. **Persistencia de N1 y N2 entre procesos separados**: un lead ya vetado (`no_contactar`) que
   recibe una llamada nueva en la que pide un callback se clasifica correctamente como `callback`,
   pero **no genera ninguna orden de seguimiento** — solo `cerrar_llamada`. Un lead que rechazó
   WhatsApp en una llamada y no lo repite en la siguiente sigue recibiendo `documentacion_pendiente`
   (tarea por email), no WhatsApp. Ambos probados con eventos sintéticos de la misma forma.
5. **Calibración del prompt**: en pruebas repetidas encontré que el criterio de "corte a mitad de
   llamada" era demasiado ambiguo para `gpt-4o-mini` — fallaba 4 de 5 veces en un caso real. Lo
   reescribí para que fuera mecánico ("mira si el último mensaje de la transcripción termina a
   mitad de una palabra o frase") y quedó estable 5/5 en repeticiones.
6. **`scripts/trace_event.py`**: herramienta de inspección (no forma parte del pipeline de
   producción) que corre el grafo real sobre un evento y muestra, nodo a nodo, qué se ejecutó y
   qué añadió al estado — útil para depurar y para explicar el flujo en la revisión de código.

## Ficheros propios (no entregados en el zip original)

```
orchestrator/          paquete con toda la logica: repository (SQLite), telephony, dates,
                        business_rules, order_builder, orders, llm_extraction, output, graph
prompts/                prompt versionado que usa el nodo del LLM
scripts/trace_event.py  herramienta de inspeccion, no de produccion
run.py                  punto de entrada
```
