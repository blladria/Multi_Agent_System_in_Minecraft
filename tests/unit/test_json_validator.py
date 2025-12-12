# -*- coding: utf-8 -*-
import pytest
from datetime import datetime, timedelta, timezone
import json
from core.json_validator import validate_message, ValidationError
from core.json_validator import MESSAGE_SCHEMAS, AGENT_IDENTIFIERS

# Genero una fecha y hora actual válida.
# Si no pongo esto, el validador podría rechazar el mensaje por ser "del pasado".
VALID_TIMESTAMP = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# --- Mensajes Base Válidos (para construir variaciones) ---
# Creo unos mensajes perfectos para usarlos de plantilla en las pruebas.
# Si modifico estos, sé exactamente qué estoy rompiendo.
VALID_MSG_BASE = {
    "type": "materials.requirements.v1", # Es una petición de materiales
    "source": "BuilderBot", # Lo pide el Constructor
    "target": "MinerBot", # Se lo pide al Minero
    "timestamp": VALID_TIMESTAMP,
    # Usando 'cobblestone' y 'dirt' para coincidir con el esquema actualizado
    "payload": {"cobblestone": 10, "dirt": 20},
    "status": "PENDING",
    "context": {"task_id": "TEST-001"}
}

VALID_MAP_MSG = {
    "type": "map.v1",
    "source": "ExplorerBot",
    "target": "BuilderBot",
    "timestamp": VALID_TIMESTAMP,
    # El mapa tiene datos más complejos (listas y diccionarios dentro)
    "payload": {
        "exploration_area": "(-50, -50) to (50, 50)",
        "elevation_map": [63.5, 63.8, 64.1],
        "optimal_zone": {"center": {"x": 0, "z": 0}, "variance": 0.5}
    },
    "status": "SUCCESS"
}

VALID_COMMAND_MSG = {
    "type": "command.control.v1", # Esto es una orden directa
    "source": "Manager", # Solo el Manager debería mandar esto
    "target": "MinerBot",
    "timestamp": VALID_TIMESTAMP,
    "payload": {
        "command_name": "start",
        "parameters": {"args": ["x=10", "z=20"]},
    },
    "status": "ACKNOWLEDGMENT",
}

# --- Casos de Prueba ---

def test_valid_message_pass():
    """
    Prueba de Control: El caso bueno.
    Cojo el mensaje perfecto, no le toco nada y debería pasar el filtro (True).
    Uso .copy() para no manchar la plantilla original.
    """
    assert validate_message(VALID_MSG_BASE.copy()) is True

def test_invalid_missing_required_field_fail():
    """
    Prueba de enviar algo sin un destinatario.
    Si borro el campo 'target', el sistema no sabe a quién enviarlo.
    Debe lanzar un error de validación (ValidationError).
    """
    invalid_msg = VALID_MSG_BASE.copy()
    del invalid_msg["target"] # Le quito el destino
    # Aquí le digo a pytest: "Espero que esto falle. Si NO falla, el test está mal".
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)

def test_invalid_type_in_payload_fail():
    """
    Prueba de Tipos de Datos (Integers vs Strings).
    En el payload, el sistema espera números (int).
    Si le paso la palabra "diez", la calculadora del bot explotará.
    El validador debe pillar esto.
    """
    invalid_msg = VALID_MSG_BASE.copy()
    # Le meto un string ("diez") donde debería ir un número (10), que representa el cobblestone
    invalid_msg["payload"] = {"cobblestone": "diez", "dirt": 20} 
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)

def test_valid_map_message_pass():
    """
    Prueba de Control del Mapa.
    Verifico que el mensaje del mapa (que tiene una estructura distinta) pasa bien.
    """
    assert validate_message(VALID_MAP_MSG.copy()) is True

def test_invalid_map_message_missing_elevation_map_fail():
    """
    Prueba de Mapa Incompleto.
    Si el explorador envía un mapa sin datos de altura, no sirve para nada.
    Debe dar error.
    """
    invalid_msg = VALID_MAP_MSG.copy()
    # Le borro la lista de alturas dentro del payload
    del invalid_msg["payload"]["elevation_map"]

    with pytest.raises(ValidationError):
        validate_message(invalid_msg)
        
def test_valid_command_message_pass():
    """
    Prueba de Control de Comandos.
    Verifico que una orden bien formada del Manager pasa el filtro.
    """
    assert validate_message(VALID_COMMAND_MSG.copy()) is True

def test_invalid_command_message_invalid_source_fail():
    """
    Prueba de Seguridad.
    Aquí compruebo que no cualquiera puede dar órdenes.
    Si el 'ExplorerBot' intenta enviar un comando de control,
    el validador debe detenerlo.
    """
    invalid_msg = VALID_COMMAND_MSG.copy()
    invalid_msg["source"] = "ExplorerBot" ## Falsificación de identidad 
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)