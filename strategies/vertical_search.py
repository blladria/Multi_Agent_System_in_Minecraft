# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical (Para minería profunda de piedra/minerales).
    Implementa el movimiento a Y=surface cuando se alcanza el límite de Bedrock (Y=5).
    """
    MIN_SAFE_Y = 5 
    RESTART_Y = 65 

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        self.logger.debug("Estrategia activa: Búsqueda Vertical (Profunda).")

        volume = 3
        
        # 1. Minar 3 bloques: el actual y dos debajo (Y, Y-1, Y-2)
        for i in range(volume):
            mine_pos = position.clone()
            mine_pos.y -= i 
            
            await mine_block_callback(mine_pos)
            await asyncio.sleep(0.3) 
        
        # 2. Lógica de Movimiento: Vertical o Horizontal (si se toca fondo)
        if position.y > self.MIN_SAFE_Y:
            position.y -= 1 
            self.logger.debug(f"Agente se mueve a Y={position.y} para el siguiente ciclo.")
        else:
            # Desplazamiento Horizontal al tocar fondo
            self.logger.warning(f"Se alcanzó la profundidad máxima ({self.MIN_SAFE_Y}). Desplazando 1 bloque en X para nuevo pozo.")
            
            position.x += 1
            
            # CORRECCIÓN: Obtener la altura real de la superficie para el nuevo pozo
            try:
                new_y = self.mc.getHeight(int(position.x), int(position.z))
                # Asegura que la nueva Y sea al menos 65 si getHeight falla o devuelve algo bajo
                position.y = max(new_y, self.RESTART_Y)
            except Exception:
                 position.y = self.RESTART_Y
            
            self.logger.info(f"Iniciando nuevo pozo. Nueva posicion de inicio: ({position.x}, {position.y}, {position.z})")
             
        await asyncio.sleep(0.1)