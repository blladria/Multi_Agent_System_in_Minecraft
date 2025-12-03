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
        "locked_sector": {"type": "string", "description": "Coordenadas del sector bloqueado."}, # Nuevo
    },
    "additionalProperties": True,
}

# --- 2. Esquema Base (para todos los mensajes) ---

BASE_SCHEMA = {
    "type": "object",
    "properties": {
        # Campos Requeridos por el protocolo
        "type": {"type": "string", "description": "Categoría del mensaje (ej: inventory.v1)"},
        # Añadir "All" como target para broadcasts [cite: 160]
        "source": {"type": "string", "enum": AGENT_IDENTIFIERS, "description": "Agente emisor"},
        "target": {"type": "string", "enum": AGENT_IDENTIFIERS + ["All"], "description": "Agente receptor (o 'All')"}, 
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
                # REGLA: Todos los materiales listados deben ser enteros >= 1
                "^.*$": {"type": "integer", "minimum": 1}
            },
            # FIX CRÍTICO: Eliminamos 'required: ["cobblestone", "dirt"]'
            "required": [], 
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
                # Estos campos (sugerencia y varianza) se añaden en el ExplorerBot
                "suggested_template": {"type": "string"},
                "terrain_variance": {"type": "number"}
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
        "source": {"const": "Manager"}, 
        "payload": {
            "type": "object",
            "properties": {
                "command_name": {"type": "string", "enum": ["pause", "resume", "stop", "update", "start", "build", "plan", "bom", "fulfill", "set", "status"]},
                "parameters": {"type": "object"}, 
            },
            "required": ["command_name"],
            "additionalProperties": True
        }
    })
})

# 5. Mensaje de Estado de Construcción (build.status.v1)
BUILD_STATUS_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        "type": {"const": "build.status.v1"},
        "payload": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["SUCCESS", "ERROR", "PENDING"]},
                "location": {"type": "object"},
            },
            "required": ["status"],
            "additionalProperties": True
        }
    })
})

# 6. Nuevo: Esquema para Bloqueo/Liberación Espacial (lock.spatial.v1 / unlock.spatial.v1) [cite: 170]
SPATIAL_LOCK_SCHEMA = dict(BASE_SCHEMA, **{
    "properties": dict(BASE_SCHEMA['properties'], **{
        "type": {"enum": ["lock.spatial.v1", "unlock.spatial.v1"]},
        "target": {"const": "All"}, # Siempre broadcast
        "source": {"const": "MinerBot"}, # Solo el MinerBot puede bloquear sectores de minería
        "payload": {
            "type": "object",
            "properties": {
                "sector_id": {"type": "string", "description": "Identificador único de la zona (ej: X_Z)"},
                "x": {"type": "number"},
                "z": {"type": "number"},
                "size": {"type": "number"},
            },
            "required": ["sector_id", "x", "z", "size"],
            "additionalProperties": False
        },
        "status": {"const": "SUCCESS"}
    })
})


# Diccionario final de esquemas para la función de validación
MESSAGE_SCHEMAS = {
    "materials.requirements.v1": MATERIALS_REQUIREMENTS_SCHEMA,
    "inventory.v1": INVENTORY_SCHEMA,
    "map.v1": MAP_SCHEMA,
    "command": COMMAND_SCHEMA,
    "build.status.v1": BUILD_STATUS_SCHEMA,
    "lock.spatial.v1": SPATIAL_LOCK_SCHEMA,      # Nuevo
    "unlock.spatial.v1": SPATIAL_LOCK_SCHEMA     # Nuevo
}


# --- 4. Función de Validación Principal ---

def validate_message(message: dict) -> bool:
    """
    Valida un mensaje JSON contra su esquema predefinido basado en el campo 'type'.
    """
    message_type = message.get("type", "unknown")
    
    # 1. Determinar el esquema a usar
    if message_type.startswith("command."):
        schema = MESSAGE_SCHEMAS["command"]
    # Manejar los nuevos tipos de bloqueo/desbloqueo
    elif message_type in ["lock.spatial.v1", "unlock.spatial.v1"]:
         schema = MESSAGE_SCHEMAS[message_type]
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