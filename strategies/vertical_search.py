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
    RESTART_Y = 65   # Altura de reinicio de fallback (solo si getHeight falla)
    
    # Paso horizontal: 11 bloques (salta 10) para el patrón de rejilla de pozos
    HORIZONTAL_STEP = 11

    def __init__(self, mc_connection, logger: logging.Logger):
        super().__init__(mc_connection, logger)
        self.cycle_counter = 0 

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
        
        self.logger.debug(f"VerticalSearch en ({position.x}, {position.y}, {position.z})")

        # 1. Minar 3 bloques: el actual y dos debajo (Y, Y-1, Y-2)
        for i in range(3):
            mine_pos = position.clone()
            mine_pos.y -= i
            
            await mine_block_callback(mine_pos)
            await asyncio.sleep(0.3) 
        
        # 2. Lógica de Movimiento: CRÍTICA
        if position.y > (self.MIN_SAFE_Y + 1): 
            # Si aún no toca fondo, nos movemos un bloque HACIA ABAJO para el siguiente ciclo.
            position.y -= 1 
            
            # Animación/Actualización del marcador (pequeño cambio en Z)
            position.z += 0.001 
            if position.z > 1.0: 
                position.z = 0.001

            self.logger.info(f"Agente desciende. Nueva Y interna: {position.y}")

        else:
            # Fondo alcanzado. Decidir si terminar el trabajo o saltar a la siguiente columna.
            
            if self._needs_more_mining(requirements, inventory):
                # Si todavía faltan materiales, salta a la siguiente columna.
                self.cycle_counter = 0 
                self.logger.warning(f"Fondo alcanzado. Iniciando nuevo pozo en X + {self.HORIZONTAL_STEP}.")
                
                # 1. Aumentamos X (El salto de 11 bloques)
                position.x += self.HORIZONTAL_STEP
                
                # 2. --- FIX CRÍTICO: RECALCULAR LA ALTURA REAL DE LA SUPERFICIE ---
                try:
                    # Usamos getHeight + 1 para empezar justo por encima de la superficie
                    new_surface_y = self.mc.getHeight(position.x, position.z) + 1
                    position.y = new_surface_y
                    
                    # NOTA: También es buena idea enviar este new_surface_y al MinerBot.surface_marker_y
                    # Aunque esa tarea se hace idealmente en MinerBot, aquí aseguramos que la posición de minería sea correcta.
                except Exception:
                    # Fallback si la conexión MC falla
                    position.y = self.RESTART_Y
                # -----------------------------------------------------------------
            
            else:
                 # Si ya cumplimos los requisitos, terminamos. No movemos X.
                 self.logger.info("Requisitos cumplidos. Finalizando estrategia VerticalSearch.")
                 # Establecemos Y a la altura de reinicio para que MinerBot.decide() lo maneje.
                 position.y = self.RESTART_Y
                 
        await asyncio.sleep(0.1)