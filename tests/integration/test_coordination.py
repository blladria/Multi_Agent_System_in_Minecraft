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

# NOTA: Los tests de integración requieren que las clases de Agente estén importadas
#       y que implementen correctamente el método _handle_message para procesar los mensajes.

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
    
    # NOTA: Los Agentes se instancian directamente, ya que la Reflexión se prueba en AgentManager.
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
    await asyncio.sleep(0.01) 
    
    # --- FASE 1: Exploración (Explorer -> Builder) ---
    
    # Simular el comando inicial que dispara la exploración
    start_command = {
        "type": "command.control.v1",
        "source": "Manager",
        "target": "ExplorerBot",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "payload": {"command_name": "start", "parameters": {"args": ["x=10", "z=10", "range=20"]}},
        "status": "PENDING",
    }
    await broker.publish(start_command)
    
    # Dejar tiempo para que ExplorerBot perciba, decida, escanee (act) y publique map.v1
    # Necesita unos 3-4 segundos reales de sleep, pero en el test usamos un avance de ciclo
    await asyncio.sleep(4.0) 

    # Verificación 1.1: BuilderBot debe recibir el mapa y pasar a planificar/WAITING
    assert builder.terrain_data is not None
    assert builder.state == AgentState.WAITING
    
    # --- FASE 2: Planificación y Demanda de Materiales (Builder -> Miner) ---

    # El BuilderBot debe haber publicado un mensaje materials.requirements.v1
    # Verificamos que MinerBot haya recibido y actualizado sus requisitos
    await asyncio.sleep(0.01)
    assert miner.requirements != {}
    assert miner.requirements.get("WOOD_PLANKS") > 0
    assert miner.state == AgentState.RUNNING # Miner debe estar minando/trabajando

    # --- FASE 3: Minería y Suministro (Miner -> Builder) ---
    
    # La minería es lenta. Dejamos que el MinerBot minero corra por un tiempo suficiente.
    # El MinerBot publica 'inventory.v1' periódicamente, y pasará a IDLE solo cuando cumpla el requisito.
    
    # El BuilderBot requiere 64 WOOD_PLANKS y 32 STONE.
    # Las estrategias extraen ~5-8 bloques/ciclo. Necesitará varios ciclos.
    time_to_mine = 20 # Simular 20 ciclos de minería (tiempo real de test)
    await asyncio.sleep(time_to_mine) 
    
    # Verificación 3.1: MinerBot debe haber cumplido requisitos y publicado SUCCESS
    assert miner.get_total_volume() >= 96 # (64+32)
    assert miner.state == AgentState.IDLE 

    # --- FASE 4: Construcción (Builder se activa) ---
    
    # BuilderBot debe haber recibido el último inventory.v1 y debe pasar de WAITING a RUNNING
    # y comenzar la construcción.
    await asyncio.sleep(0.1) # Pequeña pausa para que el BuilderBot procese el último mensaje

    # Verificación 4.1: El BuilderBot debe empezar a construir.
    assert builder.state == AgentState.RUNNING
    assert builder.is_building is True
    
    # Limpieza
    for task in agent_tasks.values():
        task.cancel()
    
    # Esperar que las tareas finalicen (limpieza del test)
    await asyncio.gather(*agent_tasks.values(), return_exceptions=True)
    
    print("\n--- PRUEBA DE COORDINACION ASINCRONA EXITOSA ---")