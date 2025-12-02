# -*- coding: utf-8 -*-
import logging # <-- FIX: Importado para resolver NameError
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
    RESTART_Y = 65   # Altura de reinicio en superficie

    def __init__(self, mc_connection, logger: logging.Logger):
        super().__init__(mc_connection, logger)
        # El contador ya no es necesario con el fix del float, pero se mantiene si se usa en otra parte.
        self.cycle_counter = 0 

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
            
            # --- FIX ANIMACIÓN REFORZADO: Forzar cambio visual flotante ---
            # Sumar un valor flotante a Z asegura que el BaseAgent detecte un cambio
            # de posición, obligando a actualizar el marcador sin cambiar la coordenada entera de minado.
            position.z += 0.001 
            if position.z > 1.0: # Evitar que el número flotante crezca indefinidamente
                position.z = 0.001
            # ----------------------------------------------------------------

            self.logger.info(f"Agente desciende. Nueva Y interna: {position.y}")

        else:
            # Desplazamiento Horizontal (Nueva columna)
            self.cycle_counter = 0 
            self.logger.warning("Fondo alcanzado. Iniciando nueva columna.")
            
            position.x += 1
            
            # Reiniciar altura a la superficie (Usando la altura real del nuevo punto X)
            try:
                surface_y = self.mc.getHeight(int(position.x), int(position.z))
                # Nos ponemos en la superficie + 1 para empezar a picar abajo
                position.y = surface_y + 1 
            except Exception:
                 position.y = self.RESTART_Y
            
            self.logger.info(f"Nuevo pozo iniciado en: ({position.x}, {position.y}, {position.z})")
             
        await asyncio.sleep(0.1)