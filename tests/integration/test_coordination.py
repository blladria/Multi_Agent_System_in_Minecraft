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

# --- FIXTURES y MOCKS (Mantener el código actual) ---
@pytest.fixture
def mock_mc():
    mc = MagicMock()
    mc.getHeight.return_value = 65 
    mc.postToChat.return_value = None
    return mc

@pytest.fixture
def setup_coordination_system(mock_mc):
    broker = MessageBroker()
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    return broker, explorer, builder, miner

# --- PRUEBA PRINCIPAL CORREGIDA CON DIAGNÓSTICO ---

@pytest.mark.asyncio
async def test_full_workflow_coordination(setup_coordination_system):
    """
    Prueba el ciclo completo de coordinación: Explorer -> Builder -> Miner -> Builder.
    """
    broker, explorer, builder, miner = setup_coordination_system
    
    agent_tasks = {
        'explorer': asyncio.create_task(explorer.run_cycle()),
        'builder': asyncio.create_task(builder.run_cycle()),
        'miner': asyncio.create_task(miner.run_cycle()),
    }
    
    await asyncio.sleep(0.5) # Buffer de inicio

    # --- FASE 1: Exploración (Explorer -> Builder) ---
    
    start_command = {
        "type": "command.control.v1",
        "source": "Manager",
        "target": "ExplorerBot",
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "payload": {"command_name": "start", "parameters": {"args": ["x=10", "z=10", "range=20"]}},
        "status": "PENDING",
    }
    await broker.publish(start_command)
    
    # Dejar tiempo para que ExplorerBot complete su escaneo (3s) y publique map.v1.
    await asyncio.sleep(4.5) 

    print("\n--- INICIO VERIFICACION FASE 1 ---")
    print(f"Builder State (ANTES BOM): {builder.state.name}") # Diagnóstico 1
    
    # Verificación 1.1: BuilderBot debe recibir el mapa y pasar a WAITING.
    assert builder.terrain_data is not None
    assert builder.state == AgentState.WAITING
    
    # --- FASE 2/3: Minería y Suministro (Miner -> Builder) ---

    # El MinerBot debe estar en RUNNING (minando)
    await asyncio.sleep(0.5) 
    print(f"Miner State (CHECK RUNNING): {miner.state.name}") # Diagnóstico 2
    assert miner.requirements != {}
    assert miner.state == AgentState.RUNNING 

    # Permitir que el MinerBot minero corra por tiempo suficiente para cumplir requisitos.
    time_to_mine = 40 
    await asyncio.sleep(time_to_mine) 
    
    # Verificación 3.1: MinerBot debe haber cumplido requisitos y pasado a IDLE.
    assert miner.get_total_volume() >= 96 
    await asyncio.sleep(0.1) # Buffer
    assert miner.state == AgentState.IDLE 

    # --- FASE 4: Construcción (Builder se activa) ---
    
    # BuilderBot debe recibir el último inventory.v1 y pasar de WAITING a RUNNING (Construcción)
    await asyncio.sleep(1.5) # Tiempo suficiente para procesar el inventory.v1 FINAL

    # Verificación 4.1: El BuilderBot debe empezar a construir.
    assert builder.state == AgentState.RUNNING
    assert builder.is_building is True
    
    # Limpieza
    for task in agent_tasks.values():
        task.cancel()
    await asyncio.gather(*agent_tasks.values(), return_exceptions=True)
    
    print("\n--- PRUEBA DE COORDINACION ASINCRONA EXITOSA ---")