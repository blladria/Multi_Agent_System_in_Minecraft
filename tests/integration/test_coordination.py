# -*- coding: utf-8 -*-
"""
Este módulo prueba la coordinación asíncrona entre tres agentes:
1. ExplorerBot: Escanea el terreno y envía mapas.
2. BuilderBot: Recibe mapas, calcula materiales (BOM) y construye.
3. MinerBot: Recibe solicitudes y provee inventario.
"""
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
    """
    Ayuda para pruebas asíncronas: Espera a que un agente alcance un estado específico.
    
    En lugar de usar un sleep fijo (que es lento y propenso a errores), esto hace 'polling'
    del estado cada 0.1s hasta que cambia o se acaba el tiempo.
    """
    start_time = asyncio.get_event_loop().time()
    while agent.state != expected_state and (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
        await asyncio.sleep(0.1) 
    return agent.state

# --- FIXTURES ---
@pytest.fixture
def mock_mc():
    """
    Crea un 'falso' objeto Minecraft (Mock).
    
    Esto permite ejecutar las pruebas sin tener el juego abierto ni un servidor corriendo.
    Simulamos las respuestas de la API (ej: altura del terreno, posición del jugador).
    """
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    mock_player = MagicMock()
    mock_player.getTilePos.return_value = Vec3(50, 70, 50) 
    mc.player = mock_player
    return mc

@pytest.fixture
def setup_coordination_system(mock_mc):
    """
    Configura el entorno de pruebas (Setup):
    1. Inicializa el sistema de logs.
    2. Crea el MessageBroker (el cerebro de comunicación).
    3. Instancia los 3 bots inyectándoles el Mock de Minecraft.
    4. Suscribe a los bots al Broker para que escuchen mensajes.
    """
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
    """
    Prueba de Integración: Construcción de Refugio Simple.
    
    Escenario:
    - Terreno con varianza normal (1.5).
    - El Builder debe solicitar exactamente 33 Cobblestone y 44 Dirt.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # BOM REAL: Calculado por el BuilderBot para la estructura de 5x5x4
    expected_bom = {"cobblestone": 33, "dirt": 44}
    target_zone = {"x": 20, "z": 20} 
    
    # 1. SIMULAR MENSAJE DEL EXPLORADOR
    # Creamos manualmente el mensaje que enviaría el ExplorerBot tras analizar el terreno
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
    
    # Arrancar los ciclos de vida de los agentes en background
    agent_tasks = [asyncio.create_task(a.run_cycle()) for a in [explorer, builder, miner]]
    await asyncio.sleep(0.1) 
    # Publicar evento: El Builder recibirá esto y calculará materiales
    await broker.publish(map_message)

    # 2. VERIFICACIÓN DE ESTADO INTERMEDIO
    # Esperamos a que el Builder procese el mapa y pase a estado WAITING (esperando materiales)
    await debug_state_wait(builder, AgentState.WAITING, 2.0)

    # ¿Calculó bien los materiales necesarios?
    assert builder.required_bom == expected_bom 
    
    # 3. SIMULAR RESPUESTA DEL MINERO
    # Simular minería (Aseguramos tener suficiente material para cubrir 33 Stone y 44 Dirt)
    miner.inventory = {"cobblestone": 50, "dirt": 50} 
    
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 100},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    # El Builder recibe los materiales -> Debería construir y volver a IDLE
    await broker.publish(inv_msg)
    
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    assert builder.state == AgentState.IDLE
    
    # Limpieza de tareas asíncronas
    for t in agent_tasks: t.cancel()

# --- TEST 2: TORRE DE VIGILANCIA (CASO MONTAÑOSO) ---
@pytest.mark.asyncio
async def test_workflow_watch_tower(setup_coordination_system):
    """
    Prueba que si el terreno es irregular, se elige la Torre.
    BOM actualizado a 39 Cobblestone y 35 Dirt.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # BOM REAL: 39 Cobblestone, 35 Dirt
    expected_bom = {"cobblestone": 39, "dirt": 35}
    target_zone = {"x": 100, "z": 100} 
    
    # Mensaje simulando terreno montañoso
    map_message = {
        "type": "map.v1", 
        "source": "ExplorerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {
            "exploration_area": "size 30", "elevation_map": [64.0, 70.0], # Diferencia de altura notable
            "optimal_zone": {"center": target_zone},
            "suggested_template": "watch_tower", 
            "terrain_variance": 5.0 # Alta varianza activa lógica de Torre
        },
        "context": {"target_zone": target_zone}, "status": "SUCCESS"
    }
    
    agent_tasks = [asyncio.create_task(a.run_cycle()) for a in [explorer, builder, miner]]
    await asyncio.sleep(0.1) 
    await broker.publish(map_message)

    # Verificamos que el Builder entra en espera de materiales
    await debug_state_wait(builder, AgentState.WAITING, 2.0)
    
    # Verifica que el Builder calculó correctamente
    assert builder.required_bom == expected_bom 
    
    # Simular entrega de materiales suficientes
    miner.inventory = {"cobblestone": 50, "dirt": 50}
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 100},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    await broker.publish(inv_msg)

    # Esperar fin de construcción
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    
    for t in agent_tasks: t.cancel()

# --- TEST 3: BÚNKER (CASO PLANO) ---
@pytest.mark.asyncio
async def test_workflow_storage_bunker(setup_coordination_system):
    """
    Prueba que si el terreno es plano, se elige el Búnker.
    BOM esperado: Alto coste en piedra (144) y poco en tierra (30).
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # BOM REAL: 144 Cobblestone, 30 Dirt
    expected_bom = {"cobblestone": 144, "dirt": 30}
    target_zone = {"x": -50, "z": -50} 
    
    # Mensaje simulando llanura perfecta
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
    
    # Verificar cálculo masivo de materiales
    assert builder.required_bom == expected_bom 
    
    # Inventario suficiente para 144 Stone y 30 Dirt
    miner.inventory = {"cobblestone": 200, "dirt": 50}
    inv_msg = {
        "type": "inventory.v1", "source": "MinerBot", "target": "BuilderBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"collected_materials": miner.inventory, "total_volume": 250},
        "status": "SUCCESS", "context": {"required_bom": expected_bom} 
    }
    await broker.publish(inv_msg)
    await debug_state_wait(builder, AgentState.IDLE, 5.0)
    
    for t in agent_tasks: t.cancel()