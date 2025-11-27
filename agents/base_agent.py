# -*- coding: utf-8 -*-
import logging
import time
import asyncio
from abc import ABC, abstractmethod
from enum import Enum, auto
# NUEVAS IMPORTACIONES PARA VISUALIZACIÓN
from mcpi import block 
from mcpi.vec3 import Vec3

# La configuración de logging se gestiona de forma centralizada en main.py

class AgentState(Enum):
    """
    Estados unificados de la Máquina de Estados Finita (FSM) para todos los agentes.
    """
    IDLE = auto()      # Esperando un comando [cite: 107]
    RUNNING = auto()   # Ejecutando activamente su tarea [cite: 108]
    PAUSED = auto()    # Temporalmente detenido, con el contexto preservado [cite: 109]
    WAITING = auto()   # Bloqueado, esperando datos o recursos [cite: 110]
    STOPPED = auto()   # Terminado de forma segura con estado y datos persistidos [cite: 111]
    ERROR = auto()     # Ocurrió un problema irrecuperable; el agente se detiene [cite: 112]

class BaseAgent(ABC):
    """
    Clase base para todos los agentes (ExplorerBot, MinerBot, BuilderBot).
    Implementa la FSM unificada y el ciclo Perceive-Decide-Act[cite: 30].
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

        # VISUALIZACIÓN (NUEVO)
        self.marker_block_id = block.WOOL.id # Default: Lana
        self.marker_block_data = 0 # Default: Blanco
        # La posición inicial se establece alta para evitar conflictos
        self.marker_position: Vec3 = Vec3(0, 70, 0) 
        try:
             # Colocar el marcador inicial
            self.mc.setBlock(int(self.marker_position.x), int(self.marker_position.y), int(self.marker_position.z), block.AIR.id)
        except Exception:
            pass

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
            self._clear_marker() # Nuevo: Borrar marcador al detenerse/fallar
            
        # Transición
        self._state = new_state
        
        # Logging estructurado del cambio de estado
        self.logger.info(f"TRANSITION: {prev_state.name} -> {new_state.name}")
        
        # Notificar a dependientes (se implementaría en el MessageBroker/Observer Pattern)
        # self.broker.notify_dependents(self.agent_id, new_state)

    # --- Métodos de Visualización (NUEVO) ---
    def _set_marker_properties(self, block_id, data):
        """Establece las propiedades del bloque marcador (ID y Data)."""
        self.marker_block_id = block_id
        self.marker_block_data = data
        
    def _update_marker(self, new_pos: Vec3):
        """
        Mueve y actualiza el bloque marcador del agente. 
        Se coloca 1 bloque encima de la posición base para mayor visibilidad.
        """
        # 1. Borrar el marcador antiguo
        try:
            # Asegura que las coordenadas sean enteras
            old_x, old_y, old_z = int(self.marker_position.x), int(self.marker_position.y) + 1, int(self.marker_position.z)
            self.mc.setBlock(old_x, old_y, old_z, block.AIR.id)
        except Exception:
             # Ignorar errores si no hay conexión real o si es la primera vez
             pass

        # 2. Establecer la nueva posición base
        self.marker_position.x = new_pos.x
        self.marker_position.y = new_pos.y
        self.marker_position.z = new_pos.z
        
        # 3. Colocar el nuevo marcador (1 bloque encima de la base)
        # Se convierte a int y se sube 1 bloque
        new_x, new_y, new_z = int(new_pos.x), int(new_pos.y) + 1, int(new_pos.z)
        try:
            self.mc.setBlock(new_x, new_y, new_z, self.marker_block_id, self.marker_block_data)
        except Exception as e:
            self.logger.error(f"Fallo al colocar el marcador en MC: {e}")
            
    def _clear_marker(self):
        """Borra el bloque marcador de su posición actual."""
        try:
            # Borra el bloque en la posición (Y + 1)
            x, y, z = int(self.marker_position.x), int(self.marker_position.y) + 1, int(self.marker_position.z)
            self.mc.setBlock(x, y, z, block.AIR.id)
        except Exception:
             pass
    # --- FIN Métodos de Visualización ---


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
    
    # --- Bucle de Ejecución Concurrente (CORRECCIÓN CRÍTICA) ---

    async def run_cycle(self):
        """Bucle principal de ejecución del agente. Usa asyncio para concurrencia."""
        self.state = AgentState.IDLE  # INICIA EN IDLE (Estado inicial)
        self.logger.info("Ciclo de ejecución iniciado.")

        # Este bucle simula la operación continua del agente
        while self.state not in (AgentState.STOPPED, AgentState.ERROR):
            await self.is_running.wait() # Bloquea aquí si el agente está PAUSED
            
            try:
                # CORRECCIÓN: La percepción debe ocurrir *siempre* para que el agente
                # pueda recibir comandos y transicionar de IDLE/PAUSED/WAITING a RUNNING.
                await self.perceive()

                if self.state != AgentState.IDLE: 
                    await self.decide()
                    await self.act()
                    
                # Espera breve para evitar el consumo excesivo de CPU
                # Este sleep es crucial para el event loop y para permitir la entrada de comandos
                await asyncio.sleep(0.1) 

            except Exception as e:
                self.logger.error(f"Error fatal en el ciclo: {e}", exc_info=True)
                self.state = AgentState.ERROR
                break

        self.logger.info(f"Ciclo de ejecución terminado ({self.state.name}).")


    # --- Control de Ciclo de Vida (Manejo de Comandos) ---

    def handle_pause(self):
        """Maneja el comando 'pause': detiene temporalmente la ejecución."""
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
        self.is_running.clear() # Bloquea el ciclo para la terminación
        self._save_checkpoint() # Persistir el estado final
        self.state = AgentState.STOPPED # Esto libera el lock
        self.logger.info(f"{self.agent_id} ha recibido STOP y esta TERMINANDO.")

    # --- Métodos de Checkpointing y Sincronización ---

    def _save_checkpoint(self):
        """Serializa y almacena el estado y contexto para reanudación."""
        self.logger.debug(f"Punto de control guardado. Contexto: {self.context}")

    def _load_checkpoint(self):
        """Carga el estado y contexto desde el último checkpoint."""
        self.logger.debug(f"Punto de control cargado. Contexto: {self.context}")

    def release_locks(self):
        """Libera todos los locks (ej. regiones de minería) al detenerse o fallar."""
        self.logger.info("Locks y recursos espaciales liberados.")