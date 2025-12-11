# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Awaitable
from core.json_validator import validate_message
from jsonschema import ValidationError as JsonSchemaValidationError

# Configuración del logger para el Broker
logger = logging.getLogger("MessageBroker")

class MessageBroker:
    """
    Clase que gestiona la comunicación asíncrona entre agentes mediante colas.
    Asegura la validación de mensajes y el logging persistente.
    """
    def __init__(self):
        # Almacena las colas de mensajes de cada agente.
        # { 'AgentID': asyncio.Queue }
        self._agent_queues: Dict[str, asyncio.Queue] = {}
        logger.info("Message Broker inicializado.")

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """
        Registra a un agente en el broker y le asigna una cola de entrada.
        
        :param agent_id: El identificador único del agente (ej: 'MinerBot').
        :return: La cola de mensajes asignada al agente.
        """
        if agent_id not in self._agent_queues:
            # Una cola asíncrona es el mecanismo de comunicación no bloqueante 
            self._agent_queues[agent_id] = asyncio.Queue()
            logger.info(f"Agente {agent_id} suscrito y cola creada.")
        return self._agent_queues[agent_id]

    async def publish(self, message: Dict[str, Any]):
        """
        Publica un mensaje a su agente destinatario ('target').
        
        :param message: El diccionario de mensaje JSON estructurado.
        """
        target_id = message.get("target")
        message_type = message.get("type", "unknown")
        source_id = message.get("source", "system")
        
        # 1. Validación de mensajes (Requisito obligatorio)
        try:
            validate_message(message)
        except JsonSchemaValidationError as e:
            logger.error(f"PUBLICACIÓN RECHAZADA: Mensaje no válido de {source_id} a {target_id}. Tipo: {message_type}. Error: {e.message}")
            # El broker detiene la publicación de mensajes inválidos
            return 
        except Exception as e:
            logger.error(f"PUBLICACIÓN RECHAZADA: Error interno al validar mensaje: {e}")
            return

        # 2. Encolamiento y Logging 
        
        # El campo 'timestamp' debe ser reciente o añadido si falta (aunque se valida arriba)
        if 'timestamp' not in message:
             message['timestamp'] = datetime.utcnow().isoformat() + 'Z'

        if target_id in self._agent_queues:
            try:
                # Pone el mensaje en la cola del agente sin bloquear 
                await self._agent_queues[target_id].put(message)
                
                # Logging persistente de mensaje enviado 
                logger.info(f"PUBLICADO {message_type} de {source_id} a {target_id}. Contexto: {message.get('context', {})}")
                
            except Exception as e:
                logger.error(f"Error al encolar mensaje para {target_id}: {e}")
        else:
            logger.warning(f"Agente destino {target_id} no está suscrito. Mensaje descartado: {message_type}")

    async def consume_queue(self, agent_id: str) -> Dict[str, Any]:
        """
        Método que el agente usa para esperar y recibir el siguiente mensaje.
        Es una corrutina que espera de forma no bloqueante.
        
        :param agent_id: El agente que intenta consumir.
        :return: El siguiente mensaje de su cola.
        """
        if agent_id not in self._agent_queues:
            raise ValueError(f"El agente {agent_id} no está suscrito al broker.")
        
        # Espera de forma no bloqueante por un mensaje
        message = await self._agent_queues[agent_id].get()
        
        # Indica que el mensaje ha sido procesado por el consumidor
        self._agent_queues[agent_id].task_done()
        
        # Logging de mensaje recibido 
        logger.info(f"RECIBIDO {message.get('type')} por {agent_id}. Origen: {message.get('source')}")
        
        return message

    def has_messages(self, agent_id: str) -> bool:
        """Verifica si un agente tiene mensajes pendientes en su cola."""
        if agent_id in self._agent_queues:
            return not self._agent_queues[agent_id].empty()
        return False