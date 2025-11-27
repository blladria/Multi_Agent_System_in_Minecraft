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

# Importamos la función de configuración de logging desde AgentManager
from core.agent_manager import setup_system_logging

# --- FIXTURES y MOCKS (Mantener el código actual) ---

@pytest.fixture
def mock_mc():
    """Mock de la conexión de Minecraft."""
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    return mc

@pytest.fixture
def setup_synchronization_agents(mock_mc):
    """
    Configura y devuelve el MessageBroker y las instancias de los tres agentes
    (sin iniciar sus ciclos asíncronos).
    """
    # LLAMADA CRÍTICA: Configura el logging para que use un archivo de test único
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
    
    return broker, explorer, builder, miner

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
        
        await asyncio.sleep(0.5) # Aumentar el buffer de inicio
        
        # Poner requisitos y forzar la transición a RUNNING
        miner.requirements = {"stone": 100}
        miner.state = AgentState.RUNNING

        # Dar tiempo para que el Miner ejecute decide() y adquiera el lock
        await asyncio.sleep(1.0) # Más tiempo para adquirir el lock
        
        # Verificación 1.1: El lock debe estar adquirido
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
        await asyncio.sleep(1.5) # TIEMPO MÁS SEGURO (1.5s) para la transición a STOPPED
        
        # 3. Verificación Final
        assert miner.state == AgentState.STOPPED
        # Verificación CRÍTICA: El lock debe haberse liberado
        assert miner.mining_sector_locked is False

    finally:
        # Limpieza: Cancelar todas las tareas al finalizar la prueba
        for task in agent_tasks.values():
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
        builder.required_bom = {"WOOD_PLANKS": 50, "STONE": 10}
        builder.current_inventory = {"WOOD_PLANKS": 5} # Insuficiente
        
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
            task.cancel()
        await asyncio.gather(*agent_tasks.values(), return_exceptions=True)