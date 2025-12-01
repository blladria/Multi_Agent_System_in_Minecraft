# -*- coding: utf-8 -*-
import pytest
from datetime import datetime, timedelta, timezone
import json
from core.json_validator import validate_message, ValidationError
from core.json_validator import MESSAGE_SCHEMAS, AGENT_IDENTIFIERS

# Generar un timestamp válido para las pruebas
VALID_TIMESTAMP = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# --- Mensajes Base Válidos (para construir variaciones) ---

VALID_MSG_BASE = {
    "type": "materials.requirements.v1",
    "source": "BuilderBot",
    "target": "MinerBot",
    "timestamp": VALID_TIMESTAMP,
    # CORRECCIÓN: Usando 'cobblestone' y 'dirt' para coincidir con el esquema actualizado
    "payload": {"cobblestone": 10, "dirt": 20},
    "status": "PENDING",
    "context": {"task_id": "TEST-001"}
}

VALID_MAP_MSG = {
    "type": "map.v1",
    "source": "ExplorerBot",
    "target": "BuilderBot",
    "timestamp": VALID_TIMESTAMP,
    "payload": {
        "exploration_area": "(-50, -50) to (50, 50)",
        "elevation_map": [63.5, 63.8, 64.1],
        "optimal_zone": {"center": {"x": 0, "z": 0}, "variance": 0.5}
    },
    "status": "SUCCESS"
}

VALID_COMMAND_MSG = {
    "type": "command.control.v1",
    "source": "Manager",
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
    """Prueba que un mensaje que cumple el esquema es aceptado."""
    assert validate_message(VALID_MSG_BASE.copy()) is True

def test_invalid_missing_required_field_fail():
    """Prueba que el mensaje falla si falta un campo OBLIGATORIO (ej: 'target')."""
    invalid_msg = VALID_MSG_BASE.copy()
    del invalid_msg["target"]
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)

def test_invalid_type_in_payload_fail():
    """Prueba que el mensaje falla si el tipo de dato en el payload es incorrecto."""
    invalid_msg = VALID_MSG_BASE.copy()
    # 'cobblestone' debe ser entero, no string
    invalid_msg["payload"] = {"cobblestone": "diez", "dirt": 20} 
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)

def test_valid_map_message_pass():
    """Prueba que el mensaje de mapa específico es aceptado."""
    assert validate_message(VALID_MAP_MSG.copy()) is True

def test_invalid_map_message_missing_elevation_map_fail():
    """Prueba que el mensaje de mapa falla si falta el campo 'elevation_map'."""
    invalid_msg = VALID_MAP_MSG.copy()
    del invalid_msg["payload"]["elevation_map"]
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)
        
def test_valid_command_message_pass():
    """Prueba que el mensaje de comando es aceptado."""
    assert validate_message(VALID_COMMAND_MSG.copy()) is True

def test_invalid_command_message_invalid_source_fail():
    """Prueba que el mensaje de comando falla si la fuente no es 'Manager'."""
    invalid_msg = VALID_COMMAND_MSG.copy()
    invalid_msg["source"] = "ExplorerBot" # Solo el Manager debe enviar comandos.control.v1
    with pytest.raises(ValidationError):
        validate_message(invalid_msg)