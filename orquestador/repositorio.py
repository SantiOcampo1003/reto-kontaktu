import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB_PATH = RAIZ_PROYECTO / "estado" / "kontaktu.sqlite3"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS leads (
    contact_id TEXT PRIMARY KEY,
    dnc INTEGER NOT NULL DEFAULT 0,
    motivo_dnc TEXT,
    whatsapp_bloqueado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS historial_llamadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    etiqueta TEXT NOT NULL,
    detalle_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_historial_contact ON historial_llamadas(contact_id);

CREATE TABLE IF NOT EXISTS eventos_procesados (
    idempotency_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    etiqueta TEXT NOT NULL,
    ordenes_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recordatorios (
    reminder_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente'
);
CREATE INDEX IF NOT EXISTS idx_recordatorios_contact ON recordatorios(contact_id, estado);
"""


@contextmanager
def abrir_conexion():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(ESQUEMA)
    try:
        yield conexion
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


def esta_vetado(conexion, contact_id):
    fila = conexion.execute(
        "SELECT dnc FROM leads WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    return bool(fila and fila["dnc"])


def whatsapp_bloqueado(conexion, contact_id):
    fila = conexion.execute(
        "SELECT whatsapp_bloqueado FROM leads WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    return bool(fila and fila["whatsapp_bloqueado"])


def marcar_no_contactar(conexion, contact_id, motivo):
    conexion.execute(
        """
        INSERT INTO leads (contact_id, dnc, motivo_dnc)
        VALUES (?, 1, ?)
        ON CONFLICT(contact_id) DO UPDATE SET dnc = 1, motivo_dnc = excluded.motivo_dnc
        """,
        (contact_id, motivo),
    )


def bloquear_whatsapp(conexion, contact_id):
    conexion.execute(
        """
        INSERT INTO leads (contact_id, whatsapp_bloqueado)
        VALUES (?, 1)
        ON CONFLICT(contact_id) DO UPDATE SET whatsapp_bloqueado = 1
        """,
        (contact_id,),
    )


def contar_intentos(conexion, contact_id):
    fila = conexion.execute(
        "SELECT COUNT(*) AS n FROM historial_llamadas WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()
    return fila["n"]


def ultimo_intento(conexion, contact_id):
    fila = conexion.execute(
        """
        SELECT occurred_at FROM historial_llamadas
        WHERE contact_id = ? ORDER BY occurred_at DESC LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    return fila["occurred_at"] if fila else None


def veces_cortada(conexion, contact_id):
    fila = conexion.execute(
        """
        SELECT COUNT(*) AS n FROM historial_llamadas
        WHERE contact_id = ? AND etiqueta IN ('cortada', 'visita_sin_confirmar')
        """,
        (contact_id,),
    ).fetchone()
    return fila["n"]


def registrar_llamada(conexion, contact_id, idempotency_key, occurred_at, etiqueta, detalle):
    conexion.execute(
        """
        INSERT INTO historial_llamadas (contact_id, idempotency_key, occurred_at, etiqueta, detalle_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (contact_id, idempotency_key, occurred_at, etiqueta, json.dumps(detalle, ensure_ascii=False)),
    )


def buscar_evento_procesado(conexion, idempotency_key):
    fila = conexion.execute(
        "SELECT * FROM eventos_procesados WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if fila is None:
        return None
    return {
        "idempotency_key": fila["idempotency_key"],
        "event_id": fila["event_id"],
        "etiqueta": fila["etiqueta"],
        "ordenes": json.loads(fila["ordenes_json"]),
    }


def registrar_evento_procesado(conexion, idempotency_key, event_id, etiqueta, ordenes):
    conexion.execute(
        """
        INSERT INTO eventos_procesados (idempotency_key, event_id, etiqueta, ordenes_json)
        VALUES (?, ?, ?, ?)
        """,
        (idempotency_key, event_id, etiqueta, json.dumps(ordenes, ensure_ascii=False)),
    )


def recordatorios_pendientes(conexion, contact_id):
    filas = conexion.execute(
        """
        SELECT reminder_id, canal FROM recordatorios
        WHERE contact_id = ? AND estado = 'pendiente'
        """,
        (contact_id,),
    ).fetchall()
    return [{"reminder_id": f["reminder_id"], "canal": f["canal"]} for f in filas]


def crear_recordatorio(conexion, reminder_id, contact_id, canal):
    conexion.execute(
        "INSERT INTO recordatorios (reminder_id, contact_id, canal) VALUES (?, ?, ?)",
        (reminder_id, contact_id, canal),
    )


def cancelar_recordatorio(conexion, reminder_id):
    conexion.execute(
        "UPDATE recordatorios SET estado = 'cancelado' WHERE reminder_id = ?",
        (reminder_id,),
    )
