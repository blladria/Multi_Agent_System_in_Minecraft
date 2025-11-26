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
from datetime import timezone # Para corregir las warnings

# --- FIXTURES y MOCKS ---

@pytest.fixture
def mock_mc():
    """Mock de la conexión de Minecraft."""
    mc = MagicMock()
    # MOCK CRÍTICO: simular la altura del terreno para ExplorerBot (zona plana)
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    return mc

@pytest.fixture
def setup_coordination_system(mock_mc):
    """
    Configura y devuelve el MessageBroker y las instancias de los tres agentes.
    """
    broker = MessageBroker()
    
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    
    # Suscribir manualmente los agentes al broker
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    
    return broker, explorer, builder, miner

# --- PRUEBA PRINCIPAL ---

@pytest.mark.asyncio
async def test_full_workflow_coordination(setup_coordination_system):
    """
    Prueba el ciclo completo de coordinación: Explorer -> Builder -> Miner -> Builder.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    # 1. Ejecutar todos los agentes concurrentemente
    agent_tasks = {
        'explorer': asyncio.create_task(explorer.run_cycle()),
        'builder': asyncio.create_task(builder.run_cycle()),
        'miner': asyncio.create_task(miner.run_cycle()),
    }
    
    # Asegurar que el ciclo asíncrono se ha iniciado
    await asyncio.sleep(0.1) 
    
    # --- FASE 1: Exploración (Explorer -> Builder) ---
    
    # Simular el comando inicial que dispara la exploración
    start_command = {
        "type": "command.control.v1",
        "source": "Manager",
        "target": "ExplorerBot",
        # Corregir la generación de timestamp para evitar DeprecationWarning
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"command_name": "start", "parameters": {"args": ["x=10", "z=10", "range=20"]}},
        "status": "PENDING",
    }
    await broker.publish(start_command)
    
    # **AJUSTE CRÍTICO DE TIMING:** Dejar tiempo suficiente para que ExplorerBot
    # complete su escaneo de 3 segundos (en act) y publique map.v1.
    await asyncio.sleep(4.5) 

    # Verificación 1.1: BuilderBot debe recibir el mapa y pasar a planificar/WAITING
    assert builder.terrain_data is not None
    # El BuilderBot debe haber pasado de IDLE -> RUNNING (Planifica) -> ACT (Publica BOM) -> WAITING
    assert builder.state == AgentState.WAITING
    
    # --- FASE 2: Planificación y Demanda de Materiales (Builder -> Miner) ---

    # El MinerBot debe haber recibido el BOM del BuilderBot.
    await asyncio.sleep(0.1)
    assert miner.requirements != {}
    assert miner.requirements.get("WOOD_PLANKS") > 0
    assert miner.state == AgentState.RUNNING # Miner debe estar minando/trabajando

    # --- FASE 3: Minería y Suministro (Miner -> Builder) ---
    
    # **AJUSTE CRÍTICO DE TIMING:** Permitir que el MinerBot minero corra por tiempo suficiente.
    # El requisito es 96 bloques. El Miner extrae ~5-8 bloques/ciclo. 20 ciclos son insuficientes.
    time_to_mine = 30 # Permitir 30 segundos (más de 20 ciclos lentos)
    await asyncio.sleep(time_to_mine) 
    
    # Verificación 3.1: MinerBot debe haber cumplido requisitos (get_total_volume >= 96) 
    # y publicado SUCCESS, pasando a IDLE.
    assert miner.get_total_volume() >= 96
    assert miner.state == AgentState.IDLE 

    # --- FASE 4: Construcción (Builder se activa) ---
    
    # BuilderBot debe recibir el último inventory.v1 y pasar de WAITING a RUNNING (Construcción)
    await asyncio.sleep(0.5) # Pausa suficiente para el procesamiento del último mensaje

    # Verificación 4.1: El BuilderBot debe empezar a construir.
    assert builder.state == AgentState.RUNNING
    assert builder.is_building is True
    
    # Limpieza
    for task in agent_tasks.values():
        task.cancel()
    
    # Esperar que las tareas finalicen (limpieza del test)
    await asyncio.gather(*agent_tasks.values(), return_exceptions=True)
    
    print("\n--- PRUEBA DE COORDINACION ASINCRONA EXITOSA ---")