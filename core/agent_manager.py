# -*- coding: utf-8 -*-
import asyncio
import logging
import inspect
import sys
import os
import logging.handlers
from datetime import datetime
import pkgutil
from typing import Dict, Type 
from mcpi.minecraft import Minecraft
from core.message_broker import MessageBroker
from agents.base_agent import BaseAgent, AgentState 
from strategies.base_strategy import BaseMiningStrategy 

# Configuración del logger global
logger = logging.getLogger("AgentManagerGlobal")

# --- Función de Configuración de Logging ---
def setup_system_logging(log_file_name: str = 'system.log'):
    """Configura el sistema de logging."""
    LOG_DIR = 'logs'
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    root_logger = logging.getLogger()
    
    handlers_to_remove = []
    for h in root_logger.handlers:
        if isinstance(h, (logging.handlers.RotatingFileHandler, logging.FileHandler, logging.StreamHandler)):
            h.close() 
            handlers_to_remove.append(h)
    for h in handlers_to_remove:
        root_logger.removeHandler(h)

    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, log_file_name), maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root_logger.setLevel(logging.DEBUG) 
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.getLogger("LoggingSetup").info(f"Logging configurado en: {log_file_name}")

# --- CLASE DE AYUDA PARA LA REFLEXIÓN ---

class AgentDiscovery:
    
    @staticmethod
    def _discover_classes(package_name: str, base_class: Type) -> list[Type]:
        """Método genérico para descubrir subclases de una clase base en un paquete."""
        discovered_classes = []
        try:
            package = __import__(package_name)
            for _, name, is_pkg in pkgutil.walk_packages(package.__path__):
                if not is_pkg:
                    try:
                        module = __import__(f"{package_name}.{name}", fromlist=[name])
                        for item_name, item_obj in inspect.getmembers(module, inspect.isclass):
                            if (issubclass(item_obj, base_class) and 
                                item_obj is not base_class and 
                                item_obj.__module__.startswith(package_name)):
                                discovered_classes.append(item_obj)
                                logging.getLogger("ClassDiscovery").info(f"Descubierta clase {base_class.__name__} en {package_name}: {item_name}")
                    except ImportError as e:
                        logging.getLogger("ClassDiscovery").error(f"Error importando {name}: {e}")
        except Exception as e:
            logging.getLogger("ClassDiscovery").error(f"Error fatal discovery: {e}")
        return discovered_classes

    @staticmethod
    def discover_agents(package_name: str = 'agents') -> list[type[BaseAgent]]:
        """Descubre todas las clases de Agente."""
        return AgentDiscovery._discover_classes(package_name, BaseAgent)

    @staticmethod
    def discover_strategies(package_name: str = 'strategies') -> dict[str, type[BaseMiningStrategy]]:
        """Descubre todas las clases de Estrategia y las mapea por nombre clave para MinerBot."""
        strategy_classes = AgentDiscovery._discover_classes(package_name, BaseMiningStrategy)
        
        # CORRECCIÓN: Limpieza de nombre agresiva para coincidir con comandos ('grid', 'vertical')
        strategies_map = {}
        for cls in strategy_classes:
            # Ejemplo: GridSearchStrategy -> "grid"
            # 1. replace('SearchStrategy', '') -> "Grid"
            # 2. replace('Strategy', '') -> (backup por si acaso)
            # 3. lower() -> "grid"
            clean_name = cls.__name__.replace('SearchStrategy', '').replace('Strategy', '').lower()
            strategies_map[clean_name] = cls
            
        return strategies_map

# --- CLASE PRINCIPAL: AGENT MANAGER ---

class AgentManager:
    """Orquesta el sistema y gestiona el ciclo de vida."""
    def __init__(self, broker: MessageBroker):
        setup_system_logging(log_file_name='system.log') 
        self.broker = broker
        self.mc = None 
        self.agents: dict[str, BaseAgent] = {}
        self.agent_tasks: dict[str, asyncio.Task] = {}
        self.is_running = False
        
        self.logger = logging.getLogger("AgentManager")
        self.logger.info("Agent Manager inicializado.")

    def initialize_minecraft(self):
        try:
            self.mc = Minecraft.create()
            self.mc.postToChat("Manager: Sistema iniciado.")
            self.logger.info("Conexion con Minecraft API exitosa.")
            return True
        except Exception as e:
            self.logger.error(f"Fallo conexion MC: {e}")
            return False
            
    async def start_system(self):
        if not self.initialize_minecraft():
            return

        AgentClasses = AgentDiscovery.discover_agents()
        if not AgentClasses:
            self.logger.warning("No se encontraron agentes.")
            return

        for AgentClass in AgentClasses:
            agent_id = AgentClass.__name__
            agent_instance = AgentClass(agent_id, self.mc, self.broker)
            self.agents[agent_id] = agent_instance
            self.broker.subscribe(agent_id)
            
            task = asyncio.create_task(agent_instance.run_cycle(), name=agent_id)
            self.agent_tasks[agent_id] = task
            self.logger.info(f"Agente '{agent_id}' iniciado.")

        self.is_running = True
        self.logger.info("Sistema corriendo. Esperando comandos...")
        await self._chat_command_monitor()
        
    async def _chat_command_monitor(self):
        self.mc.events.clearAll()
        self.logger.info("Monitor de chat activo.")
        
        while self.is_running:
            try:
                posts = self.mc.events.pollChatPosts()
                for post in posts:
                    await self._process_chat_command(post.entityId, post.message)
                await asyncio.sleep(0.5) 
            except Exception as e:
                self.logger.error(f"Error monitor chat: {e}")
                await asyncio.sleep(5)

    async def _broadcast_control_command(self, command_name: str):
        self.logger.info(f"Broadcasting comando: {command_name}")
        self.mc.postToChat(f"Manager: Ejecutando '{command_name.upper()}' global.")
        
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        for agent_id in self.agents.keys():
            control_msg = {
                "type": "command.control.v1",
                "source": "Manager",
                "target": agent_id,
                "timestamp": timestamp,
                "payload": {
                    "command_name": command_name, 
                    "parameters": {}, 
                },
                "status": "PENDING",
            }
            await self.broker.publish(control_msg)

    async def _process_chat_command(self, entity_id, raw_message: str):
        command_string = raw_message.strip().lstrip('/')
        if not command_string: return
            
        parts = command_string.split()
        if not parts: return
            
        command_root = parts[0] # Ej: 'agent', 'miner', 'explorer'
        
        arg_map = {}
        for arg in parts[2:]:
            if '=' in arg:
                key, val = arg.split('=', 1)
                arg_map[key] = val

        if command_root == 'agent' and len(parts) > 1:
            subcommand = parts[1].lower()
            
            if subcommand == 'status':
                status_msg = " | ".join([f"{name}: {a.state.name}" for name, a in self.agents.items()])
                self.mc.postToChat(f"ESTADO: {status_msg}")
            elif subcommand == 'stop': await self._broadcast_control_command("stop")
            elif subcommand == 'pause': await self._broadcast_control_command("pause")
            elif subcommand == 'resume': await self._broadcast_control_command("resume")
            elif subcommand == 'help':
                self.mc.postToChat("Manager: agent [status|pause|resume|stop]")
                self.mc.postToChat("Agentes: <Nombre> <comando> (ej: explorer start x=10 z=10)")
        
        elif command_root == 'workflow' and len(parts) > 1 and parts[1].lower() == 'run':
            await self._execute_workflow_run(arg_map)
            
        elif command_root.capitalize() + 'Bot' in self.agents:
            target_agent_id = command_root.capitalize() + 'Bot'
            if len(parts) < 2:
                self.mc.postToChat(f"Faltan argumentos para {target_agent_id}")
                return

            control_msg = {
                "type": "command.control.v1",
                "source": "Manager",
                "target": target_agent_id,
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "payload": {
                    "command_name": parts[1], 
                    "parameters": {"args": parts[2:]}, 
                },
                "status": "PENDING",
            }
            await self.broker.publish(control_msg)
            
    async def _execute_workflow_run(self, arg_map: Dict[str, str]):
        self.logger.info(f"Iniciando workflow run con parámetros: {arg_map}")
        self.mc.postToChat("Manager: Iniciando Workflow Run (Exploración -> Minería -> Construcción).")
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        if 'template' in arg_map and 'BuilderBot' in self.agents:
            template_name = arg_map['template']
            plan_msg = {
                "type": "command.control.v1", "source": "Manager", "target": "BuilderBot", "timestamp": timestamp,
                "payload": {"command_name": "plan", "parameters": {"args": ["set", template_name]}},
                "status": "PENDING",
            }
            await self.broker.publish(plan_msg)
            self.logger.info(f"Configurado BuilderBot con plantilla: {template_name}")
            
        miner_args = []
        if 'miner.strategy' in arg_map and 'MinerBot' in self.agents:
            strategy = arg_map['miner.strategy']
            strat_msg = {
                "type": "command.control.v1", "source": "Manager", "target": "MinerBot", "timestamp": timestamp,
                "payload": {"command_name": "set", "parameters": {"args": ["strategy", strategy]}},
                "status": "PENDING",
            }
            await self.broker.publish(strat_msg)
            self.logger.info(f"Configurado MinerBot con estrategia: {strategy}")

        if 'miner.x' in arg_map: miner_args.append(f"x={arg_map['miner.x']}")
        if 'miner.y' in arg_map: miner_args.append(f"y={arg_map['miner.y']}")
        if 'miner.z' in arg_map: miner_args.append(f"z={arg_map['miner.z']}")
        
        if miner_args:
             miner_start_msg = {
                "type": "command.control.v1", "source": "Manager", "target": "MinerBot", "timestamp": timestamp,
                "payload": {"command_name": "start", "parameters": {"args": miner_args}},
                "status": "PENDING",
            }
             await self.broker.publish(miner_start_msg)
             self.logger.info("MinerBot posicionado.")

        if 'ExplorerBot' in self.agents:
            explorer_args = []
            if 'x' in arg_map: explorer_args.append(f"x={arg_map['x']}")
            if 'z' in arg_map: explorer_args.append(f"z={arg_map['z']}")
            if 'range' in arg_map: explorer_args.append(f"range={arg_map['range']}")
            
            explorer_start_msg = {
                "type": "command.control.v1", "source": "Manager", "target": "ExplorerBot", "timestamp": timestamp,
                "payload": {"command_name": "start", "parameters": {"args": explorer_args}},
                "status": "PENDING",
            }
            await self.broker.publish(explorer_start_msg)
            self.logger.info(f"ExplorerBot iniciado con args: {explorer_args}")
        else:
            self.mc.postToChat("Manager: ERROR - ExplorerBot no encontrado.")

    def _get_system_status(self):
        return {name: agent.state.name for name, agent in self.agents.items()}