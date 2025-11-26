# -*- coding: utf-8 -*-
import pytest
import asyncio
from unittest.mock import MagicMock
from datetime import datetime
from agents.base_agent import AgentState
from core.message_broker import MessageBroker
from agents.explorer_bot import ExplorerBot
from agents.builder_bot import BuilderBot
from agents.miner_bot import MinerBot
from mcpi.vec3 import Vec3

# NOTA: Estas pruebas requieren que los ciclos de los agentes se lancen para que 
# la lógica de perceive/decide/act se ejecute.

# --- FIXTURES y MOCKS ---

@pytest.fixture
def mock_mc():
    """Mock de la conexión de Minecraft, esencial para los métodos de los agentes."""
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    return mc

@pytest.fixture
async def setup_synchronization_agents(mock_mc):
    """
    Configura el sistema y lanza los ciclos de los agentes como tareas.
    """
    broker = MessageBroker()
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    
    # Suscribir manualmente al broker
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    
    # Iniciar los ciclos de los agentes (sin esperar a que terminen)
    asyncio.create_task(explorer.run_cycle())
    asyncio.create_task(builder.run_cycle())
    asyncio.create_task(miner.run_cycle())
    
    # Dar un pequeño tiempo para que los agentes inicien sus ciclos a RUNNING
    await asyncio.sleep(0.01)

    return broker, explorer, builder, miner

# --- PRUEBAS DE SINCRONIZACIÓN Y LOCKING ---

@pytest.mark.asyncio
async def test_miner_lock_release_on_stop(setup_synchronization_agents):
    """
    Verifica que MinerBot libera su lock de sector al recibir el comando 'stop'.
    (Requisito: liberar locks en estados STOPPED/ERROR).
    """
    broker, _, _, miner = setup_synchronization_agents
    
    # 1. Preparación: Poner al Miner en RUNNING para que adquiera el lock simulado
    miner.requirements = {"stone": 100} # Necesario para que decida minar
    miner.state = AgentState.RUNNING
    
    # Darle tiempo al ciclo para que Miner ejecute decide() y adquiera el lock
    await asyncio.sleep(0.01)
    
    # Verificación 1.1: El lock debe estar adquirido
    assert miner.mining_sector_locked is True
    
    # 2. Acción: Enviar comando de STOP (esto llama a handle_stop)
    stop_command = {
        "type": "command.control.v1",
        "source": "Manager",
        "target": "MinerBot",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "payload": {"command_name": "stop"},
        "status": "PENDING",
    }
    await broker.publish(stop_command)
    
    # Dar tiempo para que el agente procese el mensaje y haga la transición
    await asyncio.sleep(0.05) 
    
    # 3. Verificación Final
    assert miner.state == AgentState.STOPPED
    # Verificación CRÍTICA: El lock debe haberse liberado (release_locks debe ser llamado)
    assert miner.mining_sector_locked is False

@pytest.mark.asyncio
async def test_builder_waits_for_materials(setup_synchronization_agents):
    """
    Verifica que BuilderBot entra en estado WAITING si recibe un comando 'build'
    pero no tiene los materiales necesarios.
    """
    broker, _, builder, _ = setup_synchronization_agents
    
    # 1. Preparación: Definir requisitos (BOM) y un inventario vacío/insuficiente
    builder.required_bom = {"WOOD_PLANKS": 50, "STONE": 10}
    builder.current_inventory = {"WOOD_PLANKS": 5} # Insuficiente para construir

    # 2. Acción: Simular el comando /builder build
    build_command = {
        "type": "command.control.v1",
        "source": "Manager",
        "target": "BuilderBot",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "payload": {"command_name": "build"},
        "status": "PENDING",
    }
    await broker.publish(build_command)
    
    # Dar tiempo para que el BuilderBot procese el mensaje
    await asyncio.sleep(0.05) 
    
    # 3. Verificación Final
    # BuilderBot debe verificar el inventario en _handle_message y pasar a WAITING
    assert builder.state == AgentState.WAITING 
    assert builder.is_building is False