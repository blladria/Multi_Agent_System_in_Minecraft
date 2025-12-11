# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from agents.base_agent import BaseAgent, AgentState, asyncio

# Importamos lo del diario de logs para ver qué pasa si algo falla
from core.agent_manager import setup_system_logging 

# --- EL AGENTE DE MENTIRA (MOCK) ---
# Como 'BaseAgent' es una plantilla (clase abstracta), no puedo usarla directamente.
# Así que me invento este 'MockAgent' vacío solo para poder hacer las pruebas.

class MockAgent(BaseAgent):
    """
    Agente 'tonto' para pruebas.
    No hace nada (pass), solo sirve para ver si cambia bien de estado (FSM).
    """
    async def perceive(self):
        # Hace que mira, pero no ve nada
        pass

    async def decide(self):
        # Hace que piensa, pero no decide nada
        pass

    async def act(self):
        # Hace que actúa, pero no se mueve
        pass

# No llamo a super().__init__ aquí, uso el de la clase padre directamente abajo.

# --- PREPARANDO EL LABORATORIO (FIXTURE) ---

@pytest.fixture
def base_agent_instance():
    """
    Esta función prepara un agente nuevo antes de cada test.
    Es como resetear la consola.
    """
    
    # Configuro los logs en un fichero aparte para no ensuciar
    setup_system_logging(log_file_name='logsTests.log')

    mc_mock = MagicMock()        # Simula la conexión a Minecraft
    broker_mock = MagicMock()    # Simula el MessageBroker
    
    # Aquí nace el agente de prueba
    agent = MockAgent(agent_id="TestAgent", mc_connection=mc_mock, message_broker=broker_mock)
    
    # Sobrescribe el método de log de locks para verificar que se llama
    agent.release_locks = MagicMock()
    
    return agent

# --- LOS EXÁMENES (TESTS DE ESTADOS) ---

def test_initial_state(base_agent_instance):
    """
    Prueba 1: ¿Nace el agente dormido?
    El estado inicial debería ser IDLE (Quieto).
    """
    assert base_agent_instance.state == AgentState.IDLE

def test_transition_to_running(base_agent_instance):
    """
    Prueba 2: ¿Puedo despertarlo?
    Si le cambio el estado a RUNNING, se debe quedar así.
    """
    base_agent_instance.state = AgentState.RUNNING
    assert base_agent_instance.state == AgentState.RUNNING

def test_handle_pause_transition(base_agent_instance):
    """
    Prueba 3: El botón de PAUSA.
    Si está corriendo y le doy a pausa, debe quedarse quieto (PAUSED).
    """
    # 1. Preparación: debe estar en RUNNING para pausar
    base_agent_instance.state = AgentState.RUNNING
    
    # 2. Acción: Le doy al botón de pausa
    base_agent_instance.handle_pause()
    
    # 3. Verificación: ¿Se ha parado?
    assert base_agent_instance.state == AgentState.PAUSED

def test_handle_resume_transition(base_agent_instance):
    """
    Prueba 4: El botón de PLAY (Reanudar).
    Si está pausado y le doy a reanudar, debe volver a correr.
    """
    # 1. Preparación: Forzar a PAUSED
    base_agent_instance.state = AgentState.PAUSED
    
    # 2. Acción: Le doy a reanudar
    base_agent_instance.handle_resume()
    
    # 3. Verificación: ¿Vuelve a estar RUNNING?
    assert base_agent_instance.state == AgentState.RUNNING

def test_handle_stop_releases_locks(base_agent_instance):
    """
    Prueba 5: Apagado y Limpieza.
    Si lo apago (STOP), tiene que soltar cualquier recurso bloqueado (locks).
    """
    
    # 1. Preparación: El agente está corriendo felizmente
    base_agent_instance.state = AgentState.RUNNING
    
    # 2. Acción: Le mando parar del todo
    base_agent_instance.handle_stop()
    
    # 3. Verificación
    # A) ¿Está parado?
    assert base_agent_instance.state == AgentState.STOPPED
    # B) Verifica que el método de liberación de locks fue llamado
    base_agent_instance.release_locks.assert_called_once()
    
def test_error_state_releases_locks(base_agent_instance):
    """
    Prueba 6: En caso de emergencia (ERROR).
    Si el agente crashea y entra en estado ERROR, también debe soltar los locks
    para no dejar el sistema colgado.
    """
    
    # 1. Acción: Simulo un error fatal cambiando el estado directamente
    base_agent_instance.state = AgentState.ERROR
    
    # 2. Verificación
    assert base_agent_instance.state == AgentState.ERROR
    # Compruebo que, aunque haya fallado, haya intentado limpiar antes de morir.
    base_agent_instance.release_locks.assert_called_once()