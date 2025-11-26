# -*- coding: utf-8 -*-
import logging
import time
import asyncio
from abc import ABC, abstractmethod
from enum import Enum, auto

# Configuración básica del logging (se mejorará en main.py/core)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

class AgentState(Enum):
    """
    Estados unificados de la Máquina de Estados Finita (FSM) para todos los agentes.
    
    """
    IDLE = auto()      # Esperando un comando 
    RUNNING = auto()   # Ejecutando activamente su tarea 
    PAUSED = auto()    # Temporalmente detenido, con el contexto preservado 
    WAITING = auto()   # Bloqueado, esperando datos o recursos 
    STOPPED = auto()   # Terminado de forma segura con estado y datos persistidos
    ERROR = auto()     # Ocurrió un problema irrecuperable; el agente se detiene 

class BaseAgent(ABC):
    """
    Clase base para todos los agentes (ExplorerBot, MinerBot, BuilderBot).
    Implementa la FSM unificada y el ciclo Perceive-Decide-Act.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        self.agent_id = agent_id
        self.mc = mc_connection  # Conexión a Minecraft (obtenida de mcpi.Minecraft.create())
        self.broker = message_broker # Referencia al MessageBroker (core/message_broker.py)

        # FSM
        self._state = AgentState.IDLE
        self.logger = logging.getLogger(f"Agent.{self.agent_id}")
        
        # Checkpointing y Contexto 
        self.context = {} 

        self.is_running = asyncio.Event()
        self.is_running.set() # Empieza listo para correr (si se llama a run_cycle)


    @property
    def state(self) -> AgentState:
        return self._state

    @state.setter
    def state(self, new_state: AgentState):
        """Transición de estado atómica y logueada."""
        prev_state = self._state
        
        # Lógica de liberación de locks (Requerimiento de Sincronización) 
        if new_state in (AgentState.STOPPED, AgentState.ERROR):
            self.release_locks()
            
        # Transición
        self._state = new_state
        
        # Logging estructurado del cambio de estado 
        self.logger.info(f"TRANSITION: {prev_state.name} -> {new_state.name}")
        
        # Notificar a dependientes (se implementaría en el MessageBroker/Observer Pattern) 
        # self.broker.notify_dependents(self.agent_id, new_state)


    # --- Métodos del Ciclo Perceive-Decide-Act (PDP) ---

    @abstractmethod
    async def perceive(self):
        """
        Observa el entorno (Minecraft) y el MessageBroker.
        Actualiza el estado interno o el contexto del agente. 
        """
        pass

    @abstractmethod
    async def decide(self):
        """
        Determina la siguiente acción basándose en el estado interno y el contexto.
        Puede cambiar el estado (ej: a WAITING si faltan recursos). 
        """
        pass

    @abstractmethod
    async def act(self):
        """
        Ejecuta la acción decidida (ej: enviar un mensaje, mover el jugador, colocar un bloque). 
        """
        pass
    
    # --- Bucle de Ejecución Concurrente ---

    async def run_cycle(self):
        """Bucle principal de ejecución del agente. Usa asyncio para concurrencia."""
        self.state = AgentState.RUNNING  # Empieza en RUNNING
        self.logger.info("Ciclo de ejecución iniciado.")

        # Este bucle simula la operación continua del agente
        while self.state not in (AgentState.STOPPED, AgentState.ERROR):
            await self.is_running.wait() # Bloquea aquí si el agente está PAUSED
            
            try:
                # El ciclo se ejecuta solo en estado RUNNING
                if self.state == AgentState.RUNNING:
                    await self.perceive()
                    await self.decide()
                    await self.act()
                    
                # Espera breve para evitar el consumo excesivo de CPU
                # (y para que la corrutina ceda el control a otras tareas)
                await asyncio.sleep(0.1) 

            except Exception as e:
                self.logger.error(f"Error fatal en el ciclo: {e}", exc_info=True)
                self.state = AgentState.ERROR
                break

        self.logger.info(f"Ciclo de ejecución terminado ({self.state.name}).")


    # --- Control de Ciclo de Vida (Manejo de Comandos) ---

    def handle_pause(self):
        """Maneja el comando 'pause': detiene temporalmente la ejecución. """
        if self.state == AgentState.RUNNING:
            self.is_running.clear()
            self._save_checkpoint() # Preservar el contexto 
            self.state = AgentState.PAUSED

    def handle_resume(self):
        """Maneja el comando 'resume': restaura la ejecución."""
        if self.state == AgentState.PAUSED:
            self._load_checkpoint() # Restaurar contexto
            self.is_running.set()
            self.state = AgentState.RUNNING

    def handle_stop(self):
        """Maneja el comando 'stop': termina la operación de forma segura."""
        self.is_running.set() # Asegura que el ciclo pueda despertar y terminar
        self._save_checkpoint() # Persistir el estado final 
        self.state = AgentState.STOPPED

    # --- Métodos de Checkpointing y Sincronización ---

    def _save_checkpoint(self):
        """Serializa y almacena el estado y contexto para reanudación. """
        # Aquí iría la lógica de serialización a JSON o pickle del diccionario self.context
        self.logger.debug(f"Punto de control guardado. Contexto: {self.context}")

    def _load_checkpoint(self):
        """Carga el estado y contexto desde el último checkpoint. """
        # Aquí iría la lógica de deserialización
        self.logger.debug(f"Punto de control cargado. Contexto: {self.context}")

    def release_locks(self):
        """Libera todos los locks (ej. regiones de minería) al detenerse o fallar."""
        # La lógica real de locks se implementará en el AgentManager o un módulo de Sincronización
        self.logger.info("Locks y recursos espaciales liberados.")


# Nota: Las clases específicas de agente (ExplorerBot, etc.) heredarán de esta clase
# y deberán implementar los métodos abstractos (perceive, decide, act).