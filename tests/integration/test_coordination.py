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
from typing import Tuple

# --- FUNCIÓN DE UTILIDAD PARA SEGUIMIENTO ---

async def debug_state_wait(agent, expected_state: AgentState, max_wait_seconds: float):
    """
    Espera hasta que el agente alcance un estado específico o se agote el tiempo.
    Imprime el estado en cada ciclo para seguimiento.
    """
    start_time = asyncio.get_event_loop().time()
    
    # Imprime el estado inicial antes de la espera
    print(f"\n[DEBUG] Esperando que {agent.agent_id} transicione a {expected_state.name}...")
    
    while agent.state != expected_state and (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
        print(f"[DEBUG] {agent.agent_id} Estado actual: {agent.state.name}")
        # Pequeña pausa para permitir que el event loop procese la cola de mensajes
        await asyncio.sleep(0.1) 
    
    current_state = agent.state
    if current_state != expected_state:
        print(f"[DEBUG] ERROR: Tiempo agotado. {agent.agent_id} se quedo en {current_state.name}.")
    else:
        print(f"[DEBUG] ÉXITO: {agent.agent_id} alcanzó el estado {expected_state.name}.")
        
    return current_state


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

# --- PRUEBA PRINCIPAL ---

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
    
    await asyncio.sleep(0.1) 
    
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
    
    # 1.1 Espera a que ExplorerBot complete su trabajo y el BuilderBot transicione
    await asyncio.sleep(6.0) 
    
    # DEBUG: Comprobación de estado antes de la aserción crítica
    await debug_state_wait(builder, AgentState.WAITING, 0.5)

    # Verificación 1.1: BuilderBot debe recibir el mapa y pasar a WAITING.
    assert builder.terrain_data is not None
    assert builder.state == AgentState.WAITING
    
    # --- FASE 2/3: Minería y Suministro (Miner -> Builder) ---

    # El MinerBot debe estar en RUNNING (minando)
    await asyncio.sleep(0.5) 
    assert miner.requirements != {}
    assert miner.state == AgentState.RUNNING 

    # Permitir que el MinerBot minero corra por tiempo suficiente para cumplir requisitos.
    time_to_mine = 40 
    await asyncio.sleep(time_to_mine) 
    
    # Verificación 3.1: MinerBot debe haber cumplido requisitos y pasado a IDLE.
    await debug_state_wait(miner, AgentState.IDLE, 0.5)
    
    assert miner.get_total_volume() >= 96 
    assert miner.state == AgentState.IDLE 

    # --- FASE 4: Construcción (Builder se activa) ---
    
    # Verificación 4.1: El BuilderBot debe empezar a construir.
    await debug_state_wait(builder, AgentState.RUNNING, 5.0)
    
    assert builder.state == AgentState.RUNNING
    assert builder.is_building is True
    
    # Limpieza
    for task in agent_tasks.values():
        task.cancel()
    await asyncio.gather(*agent_tasks.values(), return_exceptions=True)
    
    print("\n--- PRUEBA DE COORDINACION ASINCRONA EXITOSA ---")