# -*- coding: utf-8 -*-
import logging
import time
import asyncio
from abc import ABC, abstractmethod
from enum import Enum, auto
# NUEVAS IMPORTACIONES PARA VISUALIZACIÓN
from mcpi import block 
from mcpi.vec3 import Vec3

# Importaciones para Checkpointing
import json
import os
from functools import wraps # Importación para el decorador

# La configuración de logging se gestiona de forma centralizada en main.py

# --- DECORADOR DE PROGRAMACIÓN FUNCIONAL (Requisito 175) ---
def log_execution_time(logger_instance, method_name):
    """
    Decorador que mide y loguea el tiempo de ejecución de una corrutina.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = await func(self, *args, **kwargs)
                return result
            finally:
                end_time = time.perf_counter()
                elapsed = (end_time - start_time) * 1000 # en milisegundos
                logger_instance.debug(
                    f"FUNCTIONAL: {self.agent_id}.{method_name} ejecutado en {elapsed:.2f}ms"
                )
        return wrapper
    return decorator
# -------------------------------------------------------------

class AgentState(Enum):
    """
    Estados unificados de la Máquina de Estados Finita (FSM) para todos los agentes.
    """
    IDLE = auto()      # Esperando un comando
    RUNNING = auto()   # Ejecutando activamente su tarea
    PAUSED = auto()    # Temporalmente detenido, escucha mensajes pero no actúa
    WAITING = auto()   # Bloqueado por lógica interna (ej: falta materiales)
    STOPPED = auto()   # Estado FINAL. El ciclo termina y el agente se apaga.
    ERROR = auto()     # Estado FINAL por fallo.

class BaseAgent(ABC):
    """
    Clase base para todos los agentes (ExplorerBot, MinerBot, BuilderBot).
    Implementa la FSM unificada y el ciclo Perceive-Decide-Act.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        self.agent_id = agent_id
        self.mc = mc_connection  # Conexión a Minecraft
        self.broker = message_broker # Referencia al MessageBroker

        # FSM
        self._state = AgentState.IDLE
        self.logger = logging.getLogger(f"Agent.{self.agent_id}")
        
        # Checkpointing y Contexto 
        self.context = {} 
        self.checkpoint_file = os.path.join('checkpoints', f'{self.agent_id}_state.json')
        
        # Intentar cargar el estado si existe
        self._load_checkpoint()

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
        
        # Si el estado no cambia, no hacemos nada (evita spam de logs)
        if prev_state == new_state:
            return

        # Lógica de liberación de locks (Requerimiento de Sincronización)
        if new_state in (AgentState.STOPPED, AgentState.ERROR):
            self.release_locks()
            self._clear_marker() # Nuevo: Borrar marcador al detenerse/fallar
            
        # Transición
        self._state = new_state
        
        # Logging estructurado del cambio de estado
        self.logger.info(f"TRANSITION: {prev_state.name} -> {new_state.name}")

    # --- Métodos de Visualización ---
    def _set_marker_properties(self, block_id, data):
        """Establece las propiedades del bloque marcador (ID y Data)."""
        self.marker_block_id = block_id
        self.marker_block_data = data
        
    def _update_marker(self, new_pos: Vec3):
        """Mueve y actualiza el bloque marcador del agente."""
        
        # --- FIX ANTI-LAG: Si la posición es la misma, no hacer nada ---
        if (int(self.marker_position.x) == int(new_pos.x) and 
            int(self.marker_position.y) == int(new_pos.y) and 
            int(self.marker_position.z) == int(new_pos.z)):
            return
        # ---------------------------------------------------------------

        try:
            # Borrar antiguo
            old_x, old_y, old_z = int(self.marker_position.x), int(self.marker_position.y), int(self.marker_position.z)
            self.mc.setBlock(old_x, old_y, old_z, block.AIR.id)
            
            # Actualizar posición
            self.marker_position.x = new_pos.x
            self.marker_position.y = new_pos.y
            self.marker_position.z = new_pos.z
            
            # Colocar nuevo
            new_x, new_y, new_z = int(new_pos.x), int(new_pos.y), int(new_pos.z)
            self.mc.setBlock(new_x, new_y, new_z, self.marker_block_id, self.marker_block_data)
        except Exception:
             pass
            
    def _clear_marker(self):
        """Borra el bloque marcador de su posición actual."""
        try:
            x, y, z = int(self.marker_position.x), int(self.marker_position.y), int(self.marker_position.z)
            self.mc.setBlock(x, y, z, block.AIR.id)
        except Exception:
             pass

    # --- Métodos del Ciclo Perceive-Decide-Act (PDP) ---

    @abstractmethod
    @log_execution_time(logging.getLogger(f"Agent.{{agent_id}}"), "perceive")
    async def perceive(self):
        """Observa el entorno y procesa mensajes."""
        pass

    @abstractmethod
    @log_execution_time(logging.getLogger(f"Agent.{{agent_id}}"), "decide")
    async def decide(self):
        """Determina la siguiente acción."""
        pass

    @abstractmethod
    @log_execution_time(logging.getLogger(f"Agent.{{agent_id}}"), "act")
    async def act(self):
        """Ejecuta la acción."""
        pass
    
    # --- Bucle de Ejecución Concurrente (CORREGIDO PARA PAUSA) ---

    async def run_cycle(self):
        """
        Bucle principal. NO SE BLOQUEA EN PAUSA, solo salta decide/act.
        Esto permite recibir el comando RESUME o STOP mientras está pausado.
        """
        # Intentar cargar el estado (ej: si venimos de un STOP anterior)
        # El estado inicial se establece en __init__, lo mantenemos así.
        
        self.logger.info("Ciclo de ejecución iniciado.")

        # El bucle se mantiene vivo mientras no sea un estado terminal
        while self.state not in (AgentState.STOPPED, AgentState.ERROR):
            try:
                # 1. PERCEIVE: Siempre se ejecuta para leer mensajes (Start, Pause, Resume, Stop)
                await self.perceive()

                # 2. DECIDE & ACT: Solo se ejecutan si el agente está trabajando activamente
                if self.state == AgentState.RUNNING: 
                    await self.decide()
                    # Si act es muy largo (como ExplorerBot), debe usar await sleep para no bloquear
                    await self.act() 
                
                # Pausa para no saturar la CPU. CRÍTICO para el procesamiento de mensajes.
                await asyncio.sleep(0.1) 

            except Exception as e:
                self.logger.error(f"Error fatal en el ciclo: {e}", exc_info=True)
                self.state = AgentState.ERROR
                break

        self.logger.info(f"Ciclo de ejecución terminado ({self.state.name}).")


    # --- Control de Ciclo de Vida (Manejo de Comandos) ---

    def handle_pause(self):
        """Maneja el comando 'pause'."""
        # Solo pausamos si estamos corriendo o esperando
        if self.state in (AgentState.RUNNING, AgentState.WAITING):
            self._save_checkpoint()
            self.state = AgentState.PAUSED
            # self.mc.postToChat(f"[{self.agent_id}] PAUSADO.") # El Manager hace el postToChat

    def handle_resume(self):
        """Maneja el comando 'resume'."""
        if self.state == AgentState.PAUSED:
            self._load_checkpoint()
            # Al reanudar, siempre debe volver a RUNNING. El método 'decide' se encargará de reevaluar.
            self.state = AgentState.RUNNING 
            # self.mc.postToChat(f"[{self.agent_id}] REANUDADO.") # El Manager hace el postToChat

    def handle_stop(self):
        """Maneja el comando 'stop'."""
        # Stop es prioritario, funciona desde cualquier estado
        self._save_checkpoint()
        self.state = AgentState.STOPPED 
        # self.mc.postToChat(f"[{self.agent_id}] DETENIDO (Fin del proceso).") # El Manager hace el postToChat
        self.logger.info(f"{self.agent_id} deteniendo operaciones.")

    # --- Métodos de Checkpointing y Sincronización (Implementación de Serialización) ---

    def _save_checkpoint(self):
        """Guarda el contexto actual y el estado en un archivo JSON."""
        # Asegurarse de que el directorio exista
        os.makedirs('checkpoints', exist_ok=True)
        
        # 1. Preparar el estado completo
        # Clonamos el contexto y añadimos el estado y la posición del marcador
        state_to_save = {
            "state": self._state.name,
            "marker_position": (self.marker_position.x, self.marker_position.y, self.marker_position.z) if hasattr(self, 'marker_position') else (0, 70, 0),
            "context": self.context # El contexto debe contener datos serializables (str, int, dict, list)
        }
        
        try:
            with open(self.checkpoint_file, 'w') as f:
                json.dump(state_to_save, f, indent=4)
            self.logger.info(f"Checkpoint guardado en: {self.checkpoint_file}")
        except Exception as e:
            self.logger.error(f"Error al guardar checkpoint: {e}")

    def _load_checkpoint(self):
        """Carga el estado y el contexto desde un archivo JSON, si existe."""
        if not os.path.exists(self.checkpoint_file):
            return

        try:
            with open(self.checkpoint_file, 'r') as f:
                state_loaded = json.load(f)
            
            # 1. Restaurar el estado y el contexto
            loaded_state_name = state_loaded.get("state", "IDLE")
            
            # --- FIX CRÍTICO APLICADO AQUÍ ---
            # Si el estado cargado NO es un estado terminal (STOPPED/ERROR), 
            # lo reseteamos a IDLE para evitar ejecuciones automáticas al reiniciar el Manager.
            if loaded_state_name not in ["STOPPED", "ERROR"]:
                self._state = AgentState.IDLE
                self.logger.info(f"Checkpoint cargado: Estado anterior era {loaded_state_name}, forzado a IDLE.")
            else:
                 self._state = AgentState[loaded_state_name]
                 self.logger.info(f"Checkpoint cargado. Estado: {self._state.name}")
            # ----------------------------------

            self.context = state_loaded.get("context", {})

            # 2. Restaurar la posición del marcador
            mx, my, mz = state_loaded.get("marker_position", (0, 70, 0))
            self.marker_position = Vec3(mx, my, mz)

            # Limpiamos el archivo después de cargarlo para que el próximo inicio sea limpio, 
            # a menos que se quiera persistir el estado entre ejecuciones.
            
        except Exception as e:
            self.logger.error(f"Error al cargar checkpoint: {e}. Reiniciando estado a IDLE.")
            self._state = AgentState.IDLE
            self.context = {}

    def release_locks(self):
        self.logger.info("Locks liberados.")
        # Se necesita un método de liberación de locks específico para MinerBot
        # La propiedad 'state' del BaseAgent llama a este método genérico.
        # MinerBot ya sobrescribe esto en su propia clase.