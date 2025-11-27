# -*- coding: utf-8 -*-
import asyncio
import logging
import inspect
import sys
import os
import logging.handlers # Nueva importación
from datetime import datetime
import pkgutil # Nueva importación
from mcpi.minecraft import Minecraft
from core.message_broker import MessageBroker
from agents.base_agent import BaseAgent, AgentState 

# Configuración del logger para el Manager
logger = logging.getLogger("AgentManager")

# --- Función de Configuración de Logging (Exportada para Tests) ---
def setup_system_logging(log_file_name: str = 'system.log'):
    """
    Configura el sistema de logging con handlers para archivo y consola.
    Permite especificar un nombre de archivo para logs separados (e.g., para tests).
    """
    
    # 1. Asegúrate de que el directorio 'logs' exista
    LOG_DIR = 'logs'
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # Evita re-añadir handlers si ya están configurados 
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        return

    # 2. Formato de Logging Estructurado
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(LOG_FORMAT)

    # 3. Handler para Archivo (Persistencia)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, log_file_name),
        maxBytes=10 * 1024 * 1024, # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 4. Handler para Consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 5. Configuración del Logger Raíz
    root_logger.setLevel(logging.DEBUG) 
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.getLogger("LoggingSetup").info(f"Configuracion de logging inicializada. Archivo: {log_file_name}")

# --- CLASE DE AYUDA PARA LA REFLEXIÓN ---
class AgentDiscovery:
    """Clase estática para el descubrimiento reflexivo de agentes."""
    
    @staticmethod
    def discover_agents(package_name: str = 'agents') -> list[type[BaseAgent]]:
        """
        Escanea un paquete (directorio) dado y devuelve todas las clases que heredan de BaseAgent.
        Esto implementa la Programación Reflexiva.
        """
        discovered_agents = []
        try:
            # Importa dinámicamente el paquete 'agents'
            package = __import__(package_name)
            
            # Recorre todos los submódulos dentro del paquete
            for _, name, is_pkg in pkgutil.walk_packages(package.__path__):
                if not is_pkg:
                    try:
                        # Importa el módulo completo (e.g., agents.explorer_bot)
                        module = __import__(f"{package_name}.{name}", fromlist=[name])
                        
                        # Inspecciona los miembros del módulo en busca de clases de agentes
                        for item_name, item_obj in inspect.getmembers(module, inspect.isclass):
                            # Verifica si hereda de BaseAgent pero no es la BaseAgent misma
                            if (issubclass(item_obj, BaseAgent) and 
                                item_obj is not BaseAgent and 
                                item_obj.__module__.startswith(package_name)):
                                
                                discovered_agents.append(item_obj)
                                logger.info(f"Descubierto agente: {item_name} de {name}")
                                
                    except ImportError as e:
                        logger.error(f"Error al importar módulo {name}: {e}")

        except Exception as e:
            logger.error(f"Error fatal durante el descubrimiento de agentes: {e}")
            
        return discovered_agents


# --- CLASE PRINCIPAL: AGENT MANAGER ---

class AgentManager:
    """
    Orquesta el sistema, gestiona el ciclo de vida de los agentes y procesa comandos de chat.
    """
    def __init__(self, broker: MessageBroker):
        # LLAMADA CRÍTICA: Configuración para el archivo de log principal
        setup_system_logging(log_file_name='system.log') 
        
        self.broker = broker
        # Nota: La conexión a MC ahora usa el método initialize_minecraft para logging
        self.mc = None 
        self.agents: dict[str, BaseAgent] = {}
        self.agent_tasks: dict[str, asyncio.Task] = {}
        self.is_running = False
        logger.info("Agent Manager inicializado.")

    def initialize_minecraft(self):
        """Conecta a Minecraft y envía un mensaje de estado."""
        try:
            # Intenta conectarse al servidor (debe estar iniciado en localhost:4711)
            self.mc = Minecraft.create()
            self.mc.postToChat("Manager: Conexion establecida. Iniciando agentes...")
            logger.info("Conexion con Minecraft API exitosa.")
            return True
        except Exception as e:
            logger.error(f"Fallo al conectar con Minecraft. Asegurese de que el servidor este activo. Error: {e}")
            return False
            
    async def start_system(self):
        """Descubre agentes y lanza sus ciclos de ejecución asíncrona."""
        if not self.initialize_minecraft():
            return

        AgentClasses = AgentDiscovery.discover_agents()
        if not AgentClasses:
            logger.warning("No se encontraron clases de agentes para iniciar.")
            return

        # Inicializa e suscribe cada agente
        for AgentClass in AgentClasses:
            agent_id = AgentClass.__name__
            
            # 1. Instancia el agente (asumiendo que su __init__ toma ID, mc y broker)
            agent_instance = AgentClass(agent_id, self.mc, self.broker)
            self.agents[agent_id] = agent_instance
            
            # 2. Suscribe la cola del agente al broker
            self.broker.subscribe(agent_id)
            
            # 3. Lanza el ciclo de ejecución como una tarea asíncrona
            task = asyncio.create_task(agent_instance.run_cycle(), name=agent_id)
            self.agent_tasks[agent_id] = task
            logger.info(f"Tarea '{agent_id}' lanzada de forma asincrona.")

        self.is_running = True
        logger.info("Sistema Multi-Agente completamente lanzado.")
        
        # Inicia el monitoreo de comandos de chat
        await self._chat_command_monitor()
        
    async def _chat_command_monitor(self):
        """Monitorea el chat de Minecraft para comandos de usuario."""
        
        # Limpia los eventos de chat previos
        self.mc.events.clearAll()
        logger.info("Monitoreo de comandos de chat iniciado.")
        
        while self.is_running:
            try:
                # pollChatPosts es una llamada que lee los comandos del chat
                posts = self.mc.events.pollChatPosts()
                
                for post in posts:
                    # Convierte el post (ej: '/agent status') a un mensaje JSON interno
                    await self._process_chat_command(post.entityId, post.message)
                    
                await asyncio.sleep(0.5) # Pausa breve para ceder el control

            except Exception as e:
                logger.error(f"Error en el monitoreo de chat: {e}")
                await asyncio.sleep(5)

    async def _process_chat_command(self, entity_id, raw_message: str):
        """Convierte comandos de chat en mensajes de control JSON usando if/elif/else."""
        
        raw_message = raw_message.strip()
        if not raw_message.startswith('/'):
            return # Ignora mensajes que no son comandos

        # Lógica de parseo simple (ej: /agent status -> ['agent', 'status'])
        parts = raw_message.lstrip('/').split()
        command_root = parts[0] # Ej: 'agent' o 'miner'

        # 1. Comando general del Manager (ej: /agent status)
        if command_root == 'agent' and len(parts) > 1:
            subcommand = parts[1].lower()
            
            if subcommand == 'status':
                self.mc.postToChat(f"STATUS: {self._get_system_status()}")
            elif subcommand == 'stop':
                # Implementación pendiente de stop general
                self.mc.postToChat("Manager: Comando 'stop' en desarrollo.")
            elif subcommand == 'help':
                self.mc.postToChat("Manager: Comandos disponibles: /agent status, /<AgentName> <comando>")
            
        # 2. Comando dirigido a un Agente específico (ej: /miner start)
        elif command_root.capitalize() + 'Bot' in self.agents:
            target_agent_id = command_root.capitalize() + 'Bot' # Reconverte a formato ID (MinerBot)
            
            # Verifica que haya un sub-comando
            if len(parts) < 2:
                self.mc.postToChat(f"{target_agent_id}: Falta el sub-comando (start, pause, etc.).")
                return

            # Crea un mensaje de control JSON (command.control.v1)
            control_msg = {
                "type": "command.control.v1",
                "source": "Manager",
                "target": target_agent_id,
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "payload": {
                    "command_name": parts[1], # start, pause, resume, etc.
                    # Los parámetros se pasan como un diccionario simple de ejemplo
                    "parameters": {"args": parts[2:]}, 
                },
                "status": "PENDING",
            }
            # Envía el mensaje al agente a través del broker
            await self.broker.publish(control_msg)
            
        # 3. Comando no reconocido
        else:
            self.mc.postToChat(f"Comando '{raw_message}' no reconocido. Use /agent help.")
            
    def _get_system_status(self):
        """Recopila el estado de todos los agentes."""
        status = ", ".join([f"{name}: {agent.state.name}" for name, agent in self.agents.items()])
        return status or "Ningun agente activo."