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
from datetime import timezone
import logging
from core.agent_manager import setup_system_logging 

# --- UTILS ---
async def debug_state_wait(agent, expected_state: AgentState, max_wait_seconds: float):
    start_time = asyncio.get_event_loop().time()
    while agent.state != expected_state and (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
        await asyncio.sleep(0.1) 
    return agent.state

# --- FIXTURES ---
@pytest.fixture
def mock_mc():
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    mock_player = MagicMock()
    mock_player.getTilePos.return_value = Vec3(50, 70, 50) 
    mc.player = mock_player
    return mc

@pytest.fixture
def setup_coordination_system(mock_mc):
    setup_system_logging(log_file_name='logsTests.log') 
    broker = MessageBroker()
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    yield broker, explorer, builder, miner
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()

# --- TEST 1: REFUGIO SIMPLE (CASO NORMAL) ---
@pytest.mark.asyncio
async def test_workflow_simple_shelter(setup_coordination_system):
    """Prueba la construcción del Refugio Simple (Suelo normal).
    BOM ACTUALIZADO: 24 Cobblestone (casa "más currada" de solo piedra).
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # BOM CORREGIDO: 24 Cobblestone (Calculado por BuilderBot con la plantilla robusta)
    expected_bom = {"cobblestone": 24}
    target_zone = {"x": 20, "z": 20} 
    
    map_message = {
        "type": "map.v1", 
        "source": "ExplorerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {
            "exploration_area": "size 30", "elevation_map": [64.0],
            "optimal_zone": {"center": target_zone},
            "suggested_template": "simple_shelter", # FORZAMOS LA SUGERENCIA
            "terrain_variance": 1.5
        },
        "context": {"target_zone": target_zone}, "status": "SUCCESS"
    }
    
    agent_tasks = [asyncio.create_task(a.run_cycle()) for a in [explorer, builder, miner]]
    await asyncio.sleep(0.1) 
    await broker.publish(map_message)

    # Verificar BOM calculado
    await debug_state_wait(builder, AgentState.WAITING, 2.0)
    assert builder.required_bom == expected_bom 
    
    # Simular minería
    miner.inventory = {"cobblestone": 50, "dirt": 50} # Sobrado
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 100},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    await broker.publish(inv_msg)
    
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    assert builder.state == AgentState.IDLE
    
    for t in agent_tasks: t.cancel()

# --- TEST 2: TORRE DE VIGILANCIA (CASO MONTAÑOSO) ---
@pytest.mark.asyncio
async def test_workflow_watch_tower(setup_coordination_system):
    """Prueba que si el terreno es irregular, se elige la Torre.
    BOM CORREGIDO: 35 Cobblestone.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # BOM CORREGIDO: 35 Cobblestone
    expected_bom = {"cobblestone": 35}
    target_zone = {"x": 100, "z": 100} 
    
    map_message = {
        "type": "map.v1", 
        "source": "ExplorerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {
            "exploration_area": "size 30", "elevation_map": [64.0, 70.0],
            "optimal_zone": {"center": target_zone},
            "suggested_template": "watch_tower", # SUGERENCIA DE TORRE
            "terrain_variance": 5.0 # Alta varianza
        },
        "context": {"target_zone": target_zone}, "status": "SUCCESS"
    }
    
    agent_tasks = [asyncio.create_task(a.run_cycle()) for a in [explorer, builder, miner]]
    await asyncio.sleep(0.1) 
    await broker.publish(map_message)

    await debug_state_wait(builder, AgentState.WAITING, 2.0)
    
    # ASSERT CLAVE: Verifica que el Builder calculó 35 de piedra
    assert builder.required_bom == expected_bom 
    
    # Completar ciclo
    miner.inventory = {"cobblestone": 40}
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 40},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    await broker.publish(inv_msg)
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    
    for t in agent_tasks: t.cancel()

# --- TEST 3: BÚNKER (CASO PLANO) ---
@pytest.mark.asyncio
async def test_workflow_storage_bunker(setup_coordination_system):
    """Prueba que si el terreno es plano, se elige el Búnker.
    BOM CORREGIDO: 32 Cobblestone, 22 Dirt.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # Cantidades esperadas para la nueva estructura
    expected_bom = {"cobblestone": 32, "dirt": 22}
    target_zone = {"x": -50, "z": -50} 
    
    map_message = {
        "type": "map.v1", 
        "source": "ExplorerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {
            "exploration_area": "size 30", "elevation_map": [64.0, 64.0],
            "optimal_zone": {"center": target_zone},
            "suggested_template": "storage_bunker", # SUGERENCIA DE BÚNKER
            "terrain_variance": 0.1 # Muy baja varianza
        },
        "context": {"target_zone": target_zone}, "status": "SUCCESS"
    }
    
    agent_tasks = [asyncio.create_task(a.run_cycle()) for a in [explorer, builder, miner]]
    await asyncio.sleep(0.1) 
    await broker.publish(map_message)

    await debug_state_wait(builder, AgentState.WAITING, 2.0)
    
    # ASSERT CLAVE
    assert builder.required_bom == expected_bom 
    
    miner.inventory = {"cobblestone": 35, "dirt": 25}
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 60},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    await broker.publish(inv_msg)
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    
    for t in agent_tasks: t.cancel()