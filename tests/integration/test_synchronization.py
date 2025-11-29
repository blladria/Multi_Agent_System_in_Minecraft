# -*- coding: utf-8 -*-
import pytest
import asyncio
from unittest.mock import MagicMock
from datetime import datetime, timezone 
from agents.base_agent import AgentState
from core.message_broker import MessageBroker
from agents.explorer_bot import ExplorerBot
from agents.builder_bot import BuilderBot
from agents.miner_bot import MinerBot
from mcpi.vec3 import Vec3
import logging # AÑADIDO: Importar el módulo logging

# Importamos la función de configuración de logging desde AgentManager
from core.agent_manager import setup_system_logging

# --- FIXTURES y MOCKS (CORREGIDO) ---

@pytest.fixture
def mock_mc():
    """Mock de la conexión de Minecraft."""
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    
    # CORRECCIÓN CRÍTICA: Mockear mc.player.getTilePos() para devolver un Vec3 con enteros
    # Esto asegura que MinerBot.mining_position se inicialice con números.
    mock_player = MagicMock()
    mock_player.getTilePos.return_value = Vec3(50, 70, 50) 
    mc.player = mock_player
    
    # Mockear setBlock/setBlocks para evitar errores durante la ejecución de las estrategias
    mc.setBlock.return_value = None
    mc.setBlocks.return_value = None

    # Mockear getBlock para simular que hay un bloque genérico para minar (e.g., ID 1)
    # Esto asegura que _mine_current_block no falle.
    mc.getBlock.return_value = 1 

    return mc

@pytest.fixture
def setup_synchronization_agents(mock_mc):
    """
    Configura y devuelve el MessageBroker y las instancias de los tres agentes
    (sin iniciar sus ciclos asíncronos).
    """
    # LLAMADA CRÍTICA: Configura el logging para que use un archivo de test
    setup_system_logging(log_file_name='logsTests.log')
    
    broker = MessageBroker()
    
    # Instanciación de agentes con mocks
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    
    # Suscribir manualmente los agentes al broker
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    
    # FIX: Usar yield para que sea un generator fixture
    yield broker, explorer, builder, miner

    # Teardown: Forzar la escritura de los logs del buffer al finalizar el test
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()

# --- PRUEBAS DE SINCRONIZACIÓN Y LOCKING ---

@pytest.mark.asyncio
async def test_miner_lock_release_on_stop(setup_synchronization_agents):
    """
    Verifica que MinerBot libera su lock de sector al recibir el comando 'stop' 
    y entra en estado STOPPED (Aumento crítico de tiempo).
    """
    broker, _, _, miner = setup_synchronization_agents
    agent_tasks = {}

    try:
        # 1. Lanzar ciclos asíncronos de los agentes (Miner inicia en IDLE)
        agent_tasks['miner'] = asyncio.create_task(miner.run_cycle())
        
        # Espera para que el ciclo de run_cycle se inicie (y MinerBot esté en IDLE)
        await asyncio.sleep(0.5) 
        
        # Poner requisitos y forzar la transición a RUNNING
        miner.requirements = {"dirt": 100} # Usamos 'dirt' que siempre se mina/simula
        miner.state = AgentState.RUNNING

        # Dar tiempo para que el Miner ejecute decide() y adquiera el lock
        # y ejecute el primer ciclo de act()
        await asyncio.sleep(1.5) # Más tiempo para que complete una iteración de minería
        
        # Verificación 1.1: El lock debe estar adquirido después de decide() y antes de act()
        # La lógica de decide() pone el lock al ver que no está cumplido y no está lockeado
        assert miner.mining_sector_locked is True
        
        # 2. Acción: Enviar comando de STOP (esto llama a handle_stop)
        stop_command = {
            "type": "command.control.v1",
            "source": "Manager",
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {"command_name": "stop"},
            "status": "PENDING",
        }
        await broker.publish(stop_command)
        
        # Dar tiempo para que el agente procese el mensaje y haga la transición
        await asyncio.sleep(1.0) 
        
        # 3. Verificación Final
        assert miner.state == AgentState.STOPPED
        # Verificación CRÍTICA: El lock debe haberse liberado
        assert miner.mining_sector_locked is False

    finally:
        # Limpieza: Cancelar todas las tareas al finalizar la prueba
        for task in agent_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*agent_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_builder_waits_for_materials(setup_synchronization_agents):
    """
    Verifica que BuilderBot entra en estado WAITING si recibe un comando 'build'
    pero no tiene los materiales necesarios (Aumento crítico de tiempo).
    """
    broker, _, builder, _ = setup_synchronization_agents
    agent_tasks = {}

    try:
        # 1. Lanzar ciclos asíncronos (Builder inicia en IDLE)
        agent_tasks['builder'] = asyncio.create_task(builder.run_cycle())
        await asyncio.sleep(0.5) # Tiempo incrementado para inicialización

        # 2. Preparación: Definir requisitos y un inventario insuficiente
        builder.required_bom = {"wood": 50, "dirt": 10}
        builder.current_inventory = {"wood": 5} # Insuficiente
        
        # 3. Acción: Simular el comando /builder build
        build_command = {
            "type": "command.control.v1",
            "source": "Manager",
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {"command_name": "build"},
            "status": "PENDING",
        }
        await broker.publish(build_command)
        
        # Dar tiempo para que el BuilderBot procese el mensaje
        await asyncio.sleep(1.0) # TIEMPO SUFICIENTE (1.0s) para la transición a WAITING
        
        # 4. Verificación Final
        # BuilderBot debe recibir el comando y transicionar de IDLE a WAITING
        assert builder.state == AgentState.WAITING 
        assert builder.is_building is False

    finally:
        # Limpieza: Cancelar todas las tareas al finalizar la prueba
        for task in agent_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*agent_tasks.values(), return_exceptions=True)