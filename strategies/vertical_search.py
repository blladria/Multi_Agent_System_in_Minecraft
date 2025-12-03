# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical (Quarry).
    Excava una columna hacia abajo.
    """
    MIN_SAFE_Y = 5   # No bajar más allá de esto (Bedrock)
    RESTART_Y = 65   # Altura de reinicio de fallback
    
    # FIX CRÍTICO: Cambiamos el paso horizontal a 1 para ir al bloque ADYACENTE.
    HORIZONTAL_STEP = 1

    def __init__(self, mc_connection, logger: logging.Logger):
        super().__init__(mc_connection, logger)
        self.cycle_counter = 0 
        self.is_finished = False # Nuevo flag para indicar al MinerBot que debe re-evaluar

    # --- FUNCIÓN DE AYUDA PARA CHECKEO DE REQUISITOS ---
    def _needs_more_mining(self, requirements: Dict[str, int], inventory: Dict[str, int]) -> bool:
        """Verifica si todavía faltan materiales por obtener."""
        if not requirements:
            # Si no hay requisitos definidos, seguimos minando el objetivo por defecto (100 Cobblestone)
            return inventory.get("cobblestone", 0) < 100 
        
        # Comprueba si algún requisito NO está cumplido
        return any(inventory.get(mat, 0) < qty for mat, qty in requirements.items())
    # ----------------------------------------------------
    
    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # Si ya hemos indicado que terminamos, no hacemos nada.
        if self.is_finished:
             await asyncio.sleep(0.1)
             return
             
        self.logger.debug(f"VerticalSearch en ({position.x}, {position.y}, {position.z})")

        # 1. Minar 3 bloques: el actual y dos debajo (Y, Y-1, Y-2)
        for i in range(3):
            # Clonamos para asegurar que la posición de minado es estable
            mine_pos = position.clone() 
            mine_pos.y -= i
            
            await mine_block_callback(mine_pos)
            await asyncio.sleep(0.3) 
        
        # 2. Lógica de Movimiento: CRÍTICA
        if position.y > (self.MIN_SAFE_Y + 1): 
            # Continuar descendiendo en el pozo actual (solo movemos Y)
            position.y -= 1 
            
            # Aseguramos X y Z como enteros estables (sin el hack de float)
            position.x = int(position.x)
            position.z = int(position.z)

            self.logger.info(f"Agente desciende. Nueva Y interna: {position.y}")

        else:
            # Fondo alcanzado. Decidir si terminar el trabajo o saltar a la siguiente columna.
            
            if self._needs_more_mining(requirements, inventory):
                self.cycle_counter = 0 
                self.logger.warning(f"Fondo alcanzado. Iniciando nuevo pozo en X + {self.HORIZONTAL_STEP}.")
                
                # 1. Aumentamos X en 1 para ir al bloque adyacente (X+1)
                position.x = int(position.x) + self.HORIZONTAL_STEP
                position.z = int(position.z)
                
                # 2. Recalculamos Y (FIX de altura, para empezar en la superficie del nuevo X)
                try:
                    # El MinerBot se encargará de re-lockear/reubicar
                    new_surface_y = self.mc.getHeight(position.x, position.z) + 1
                    position.y = new_surface_y
                except Exception:
                    position.y = self.RESTART_Y
            
            else:
                 # Si ya cumplimos los requisitos, terminamos. No movemos X.
                 self.logger.info("Requisitos cumplidos. Finalizando estrategia VerticalSearch.")
                 # Establecemos el flag para que MinerBot pase a IDLE
                 self.is_finished = True 
                 position.y = self.RESTART_Y
                 
        await asyncio.sleep(0.1)