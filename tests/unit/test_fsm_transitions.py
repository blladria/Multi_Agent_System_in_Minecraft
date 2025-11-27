# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from agents.base_agent import BaseAgent, AgentState, asyncio

# NUEVA IMPORTACIÓN PARA LOGGING EN TESTS UNITARIOS
from core.agent_manager import setup_system_logging 

# --- MOCK: Clase Agente Mínima para Pruebas ---
# Creamos una clase concreta que hereda de BaseAgent para poder instanciarla.

class MockAgent(BaseAgent):
    """Agente concreto mínimo para pruebas unitarias de la FSM."""
    async def perceive(self):
        # Simula la percepción
        pass

    async def decide(self):
        # Simula la decisión
        pass

    async def act(self):
        # Simula la acción
        pass

    # No usamos super().__init__ aquí, llamamos directamente al constructor de BaseAgent

# --- FIXTURE de Inicialización ---

@pytest.fixture
def base_agent_instance():
    """Fixture que crea una instancia de MockAgent con dependencias simuladas."""
    
    # LLAMADA CRÍTICA: Configura el logging para tests unitarios
    setup_system_logging(log_file_name='logsTests.log')

    mc_mock = MagicMock()        # Simula la conexión a Minecraft
    broker_mock = MagicMock()    # Simula el MessageBroker
    
    # Crea una instancia usando el constructor de la clase mock.
    agent = MockAgent(agent_id="TestAgent", mc_connection=mc_mock, message_broker=broker_mock)
    
    # Sobrescribe el método de log de locks para verificar que se llama
    agent.release_locks = MagicMock()
    
    return agent

# --- Casos de Prueba de la FSM ---

def test_initial_state(base_agent_instance):
    """Prueba que el estado inicial del agente es IDLE."""
    assert base_agent_instance.state == AgentState.IDLE

def test_transition_to_running(base_agent_instance):
    """Prueba la transición básica de IDLE a RUNNING."""
    base_agent_instance.state = AgentState.RUNNING
    assert base_agent_instance.state == AgentState.RUNNING

def test_handle_pause_transition(base_agent_instance):
    """
    Prueba el comando pause: RUNNING -> PAUSED, 
    y que la bandera de ejecución (is_running) se limpia.
    """
    # 1. Preparación: debe estar en RUNNING para pausar
    base_agent_instance.state = AgentState.RUNNING
    
    # 2. Acción
    base_agent_instance.handle_pause()
    
    # 3. Verificación
    assert base_agent_instance.state == AgentState.PAUSED
    assert base_agent_instance.is_running.is_set() is False # Debe bloquear la ejecución

def test_handle_resume_transition(base_agent_instance):
    """Prueba el comando resume: PAUSED -> RUNNING."""
    # 1. Preparación: Forzar a PAUSED
    base_agent_instance.state = AgentState.PAUSED
    
    # 2. Acción
    base_agent_instance.handle_resume()
    
    # 3. Verificación
    assert base_agent_instance.state == AgentState.RUNNING
    assert base_agent_instance.is_running.is_set() is True # Debe permitir la ejecución

def test_handle_stop_releases_locks(base_agent_instance):
    """Prueba que el comando 'stop' llama a release_locks y entra en STOPPED."""
    
    # 1. Preparación
    base_agent_instance.state = AgentState.RUNNING
    
    # 2. Acción
    base_agent_instance.handle_stop()
    
    # 3. Verificación
    assert base_agent_instance.state == AgentState.STOPPED
    # Verifica que el método de liberación de locks fue llamado
    base_agent_instance.release_locks.assert_called_once()
    
def test_error_state_releases_locks(base_agent_instance):
    """Prueba que el estado ERROR llama a release_locks."""
    
    # 1. Acción
    base_agent_instance.state = AgentState.ERROR
    
    # 2. Verificación
    assert base_agent_instance.state == AgentState.ERROR
    # Verifica que el método de liberación de locks fue llamado
    base_agent_instance.release_locks.assert_called_once()