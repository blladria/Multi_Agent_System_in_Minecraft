# -*- coding: utf-8 -*-
"""
Este módulo verifica la robustez del sistema ante condiciones de carrera y transiciones de estado.
Se centra en dos comportamientos críticos:
1. Seguridad de Hilos/Recursos: Que el MinerBot libere el "Lock" del sector al detenerse.
2. Lógica de Dependencia: Que el BuilderBot sepa esperar (WAITING) si no tiene materiales.
"""
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
import logging

# Importamos la función de configuración de logging desde AgentManager
from core.agent_manager import setup_system_logging

# --- FIXTURES y MOCKS ---

@pytest.fixture
def mock_mc():
    """
    Aquí creo un Minecraft de mentira (Mock).
    Como no quiero abrir el juego cada vez que paso los tests, engaño a los bots
    para que crean que están conectados.
    """
    mc = MagicMock()
    mc.getHeight.return_value = 65 # Les digo que el suelo está a altura 65
    mc.postToChat.return_value = None # Si escriben en el chat, no pasa nada
    
    # El minero hace sumas con la posición.
    # Si le paso números normales falla, así que le paso un objeto Vec3 (coordenadas 3D).
    mock_player = MagicMock()
    mock_player.getTilePos.return_value = Vec3(50, 70, 50) 
    mc.player = mock_player
    
    # Hago que poner bloques no haga nada para evitar errores durante la ejecución de las estrategias
    mc.setBlock.return_value = None
    mc.setBlocks.return_value = None

    # Hago que el juego diga que siempre hay piedra (ID 1) cuando el bot mira un bloque.
    # Si le digo que hay aire (0), el bot se ralla y no mina.
    mc.getBlock.return_value = 1 

    return mc

@pytest.fixture
def setup_synchronization_agents(mock_mc):
    """
    Esta función prepara el terreno antes de cada test.
    Crea al Broker (especie de cartero) y a los tres bots, pero todavía no los enciende.
    """
    # Guardo los logs en un archivo aparte para no ensuciar la consola
    setup_system_logging(log_file_name='logsTests.log')
    
    broker = MessageBroker()
    
    # # Creo a mis tres bots y les paso el Minecraft falso y el cartero
    explorer = ExplorerBot("ExplorerBot", mock_mc, broker)
    builder = BuilderBot("BuilderBot", mock_mc, broker)
    miner = MinerBot("MinerBot", mock_mc, broker)
    
    # Los apunto a la lista de correo para que reciban mensajes
    broker.subscribe("ExplorerBot")
    broker.subscribe("BuilderBot")
    broker.subscribe("MinerBot")
    
    # Entrego las herramientas al test y espero a que termine
    yield broker, explorer, builder, miner

# --- LIMPIEZA ---
    # Esto se ejecuta cuando acaba el test.
    # Me aseguro de guardar todo lo que quedó pendiente en el archivo de logs.    
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()

# --- PRUEBAS DE SINCRONIZACIÓN Y LOCKING ---

@pytest.mark.asyncio
async def test_miner_lock_release_on_stop(setup_synchronization_agents):
    """
    Prueba para ver si el Minero es educado.
    Si le digo STOP, tiene que soltar el 'candado' (lock) de la zona de minería
    para que otros puedan usarla.
    """
    broker, _, _, miner = setup_synchronization_agents
    agent_tasks = {}

    try:
        # 1. Enciendo al minero en segundo plano (como un hilo aparte)        
        agent_tasks['miner'] = asyncio.create_task(miner.run_cycle())
        
        # Espera para que el ciclo de run_cycle se inicie (y MinerBot esté en IDLE)
        await asyncio.sleep(0.5) 
        
        # 2. Le fuerzo a trabajar
        # Poner requisitos y forzar la transición a RUNNING
        miner.requirements = {"dirt": 100} # Usamos 'dirt' que siempre se mina/simula
        miner.state = AgentState.RUNNING

        # 3. Espero un rato (1.5s)
        # Esto es importante: necesito darle tiempo al bot para que 'piense',
        # vea que le falta tierra y ponga el candado en la zona.
        await asyncio.sleep(1.5)
        
        # Ha puesto el candado? Debería ser True.
        assert miner.mining_sector_locked is True
        
        # 4. Acción: Enviar comando de STOP
        stop_command = {
            "type": "command.control.v1",
            "source": "Manager",
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {"command_name": "stop"},
            "status": "PENDING",
        }
        await broker.publish(stop_command)
        
        # Le doy un segundo para que lea el mensaje y reaccione
        await asyncio.sleep(1.0) 
        
        # 5. EXAMEN FINAL
        # ¿Se ha parado?
        assert miner.state == AgentState.STOPPED
        # ¿Ha liberado el lock?
        # Si esto falla, es que el minero se ha quedado bloqueando la zona aunque no trabaje.
        assert miner.mining_sector_locked is False

    finally:
        # Limpieza: Si el test falla o acaba, apago al minero a la fuerza para que no se quede colgado.
        for task in agent_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*agent_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_builder_waits_for_materials(setup_synchronization_agents):
    """
    Prueba para el Constructor.
    Si le digo "Construye" pero no tiene materiales, no debería ponerse a construir aire.
    Debería quedarse esperando (WAITING).
    """
    broker, _, builder, _ = setup_synchronization_agents
    agent_tasks = {}

    try:
        # 1. Enciendo al constructor
        agent_tasks['builder'] = asyncio.create_task(builder.run_cycle())
        await asyncio.sleep(0.5) # Tiempo de calentamiento

        # 2. Le pongo una trampa
        # Le digo que necesita 50 de madera, pero solo tiene 5 en la mochila.        
        builder.required_bom = {"wood": 50, "dirt": 10}
        builder.current_inventory = {"wood": 5} # Insuficiente
        
        # 3. Le ordeno construir
        build_command = {
            "type": "command.control.v1",
            "source": "Manager",
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {"command_name": "build"},
            "status": "PENDING",
        }
        await broker.publish(build_command)
        
        # Le doy un segundo para que haga sus cuentas
        await asyncio.sleep(1.0) 
        
        # 4. Verificación Final
        # BuilderBot debe recibir el comando y transicionar de IDLE a WAITING
        assert builder.state == AgentState.WAITING 
        assert builder.is_building is False

    finally:
        # Apago todo al salir
        for task in agent_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*agent_tasks.values(), return_exceptions=True)