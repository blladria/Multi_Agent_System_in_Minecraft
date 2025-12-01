# -*- coding: utf-8 -*-
import json
import jsonschema
from jsonschema import validate, ValidationError
import logging

# Configuración básica de logging
logger = logging.getLogger("JSONValidator")

# --- 1. Definición de Componentes Reutilizables ---

# Agentes participantes
AGENT_IDENTIFIERS = ["ExplorerBot", "MinerBot", "BuilderBot", "Manager"]

# Estados de los mensajes (SUCCESS es un estado requerido)
MESSAGE_STATUSES = ["SUCCESS", "ERROR", "PENDING", "ACKNOWLEDGMENT"]

# Esquema para la sección 'context' (metadatos opcionales, pero estructurados)
CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "state": {"type": "string", "enum": ["RUNNING", "PAUSED", "WAITING", "STOPPED"]},
        "correlation_id": {"type": "string"},
    },
    "additionalProperties": True,
}

# --- 2. Esquema Base (para todos los mensajes) ---

BASE_SCHEMA = {
    "type": "object",
    "properties": {
        # Campos Requeridos por el protocolo
        "type": {"type": "string", "description": "Categoría del mensaje (ej: inventory.v1)"},
        "source": {"type": "string", "enum": AGENT_IDENTIFIERS, "description": "Agente emisor"},
        "target": {"type": "string", "enum": AGENT_IDENTIFIERS, "description": "Agente receptor"},
        "timestamp": {"type": "string", "format": "date-time", "description": "Hora en formato ISO 8601 UTC"},
        "payload": {"type": "object", "description": "Datos estructurados relevantes al mensaje"},
        "status": {"type": "string", "enum": MESSAGE_STATUSES, "description": "Resultado del procesamiento del mensaje"},
        
        # Campo Opcional (metadatos)
        "context": CONTEXT_SCHEMA,
    },
    "required": ["type", "source", "target", "timestamp", "payload", "status"],
    "additionalProperties": False,
}

# --- 3. Esquemas de Payload Específicos ---

# 1. Mensaje de Materiales Requeridos (materials.requirements.v1)
MATERIALS_REQUIREMENTS_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        "type": {"const": "materials.requirements.v1"},
        "payload": {
            "type": "object",
            "patternProperties": {
                # Se espera un nombre de material (string) y una cantidad (integer)
                "^.*$": {"type": "integer", "minimum": 1}
            },
            # REQUISITO ACTUALIZADO: Ahora se requiere 'cobblestone' y 'dirt'
            "required": ["cobblestone", "dirt"], 
            "additionalProperties": True
        }
    })
})

# 2. Mensaje de Inventario / Progreso (inventory.v1)
INVENTORY_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        "type": {"const": "inventory.v1"},
        "payload": {
            "type": "object",
            "properties": {
                "collected_materials": {
                    "type": "object",
                    "patternProperties": {
                        "^.*$": {"type": "integer", "minimum": 0}
                    }
                },
                "total_volume": {"type": "number"},
            },
            "required": ["collected_materials"],
            "additionalProperties": True
        }
    })
})

# 3. Mensaje de Mapa / Terreno (map.v1)
MAP_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        "type": {"const": "map.v1"},
        "payload": {
            "type": "object",
            "properties": {
                "exploration_area": {"type": "string"}, # Coordenadas de la región explorada
                "elevation_map": {"type": "array", "items": {"type": "number"}}, # Mapa de elevación
                "optimal_zone": {"type": "object"}, # Zona plana identificada
            },
            "required": ["exploration_area", "elevation_map"],
            "additionalProperties": True
        }
    })
})

# 4. Mensaje de Control (Comandos internos o de Chat)
COMMAND_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        # Tipo que debe coincidir con el patrón command.algo.v1
        "type": {"pattern": "^command\\..*\\.v1$"},
        "source": {"const": "Manager"}, # Se asume que el Manager maneja la conversión de comandos
        "payload": {
            "type": "object",
            "properties": {
                # CORRECCIÓN CRÍTICA: Se añade 'status' al enum para que los comandos pasen la validación.
                "command_name": {"type": "string", "enum": ["pause", "resume", "stop", "update", "start", "build", "plan", "bom", "fulfill", "set", "status"]},
                "parameters": {"type": "object"}, # Parámetros del comando (ej: x, y, z)
            },
            "required": ["command_name"],
            "additionalProperties": True
        }
    })
})


# Diccionario final de esquemas para la función de validación
MESSAGE_SCHEMAS = {
    "materials.requirements.v1": MATERIALS_REQUIREMENTS_SCHEMA,
    "inventory.v1": INVENTORY_SCHEMA,
    "map.v1": MAP_SCHEMA,
    "command": COMMAND_SCHEMA,
}


# --- 4. Función de Validación Principal ---

def validate_message(message: dict) -> bool:
    """
    Valida un mensaje JSON contra su esquema predefinido basado en el campo 'type'.
    Si el mensaje es válido, devuelve True. Si es inválido, lanza ValidationError.
    """
    message_type = message.get("type", "unknown")
    
    # 1. Determinar el esquema a usar
    # Si es un comando, usa el esquema COMMAND_SCHEMA
    if message_type.startswith("command."):
        schema = MESSAGE_SCHEMAS["command"]
    elif message_type in MESSAGE_SCHEMAS:
        schema = MESSAGE_SCHEMAS[message_type]
    else:
        logger.warning(f"Tipo de mensaje '{message_type}' desconocido. Usando esquema BASE.")
        schema = BASE_SCHEMA
        
    # 2. Realizar la validación
    try:
        validate(instance=message, schema=schema)
        return True
    except ValidationError as e:
        logger.error(f"FALLO DE VALIDACIÓN: Mensaje JSON no cumple con el esquema '{message_type}'")
        logger.error(f"Error detallado: {e.message}")
        raise ValidationError(f"JSON Validation Error for type {message_type}: {e.message}")


# --- Bloque de Prueba (Opcional) ---

if __name__ == "__main__":
    
    # Mensaje VÁLIDO (ejemplo de requisitos)
    valid_msg = {
        "type": "materials.requirements.v1",
        "source": "BuilderBot",
        "target": "MinerBot",
        "timestamp": "2025-10-21T15:30:00Z",
        "payload": {
            "stone": 50,
            "dirt": 100,
        },
        "status": "PENDING",
        "context": {"task_id": "BOM-001"}
    }
    
    # Mensaje INVÁLIDO (falta el campo 'target', que es requerido)
    invalid_msg = {
        "type": "map.v1",
        "source": "ExplorerBot",
        "timestamp": "2025-10-21T15:30:00Z",
        "payload": {"exploration_area": "A1", "elevation_map": [10, 11, 10]},
        "status": "SUCCESS"
    }

    print("--- PRUEBAS DE VALIDACIÓN ---")
    try:
        if validate_message(valid_msg):
            print("Mensaje VÁLIDO aprobado.")

        print("\nIntentando validar mensaje INVÁLIDO...")
        validate_message(invalid_msg)
        
    except ValidationError as e:
        print(f"FALLO ESPERADO: {e}")
    except Exception as e:
        print(f"Error inesperado: {e}")