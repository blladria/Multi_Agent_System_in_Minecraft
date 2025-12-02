# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical (Quarry).
    Excava una columna hacia abajo hasta la roca madre, luego se mueve y repite.
    Ideal para Cobblestone y Stone.
    """
    MIN_SAFE_Y = 5   # No bajar más allá de esto (Bedrock)
    RESTART_Y = 65   # Altura segura de reinicio si falla la lectura

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        self.logger.debug(f"VerticalSearch en ({position.x}, {position.y}, {position.z})")

        # 1. Intentar minar el bloque actual y el de abajo (velocidad x2)
        # Minamos en la posición actual
        await mine_block_callback(position)
        
        # 2. Descender
        if position.y > self.MIN_SAFE_Y:
            position.y -= 1
        else:
            # 3. Si tocamos fondo, nos movemos a la siguiente columna
            self.logger.info("Fondo alcanzado. Iniciando nueva columna.")
            position.x += 1
            
            # Reiniciar altura a la superficie
            try:
                # Obtenemos la altura del nuevo punto X
                surface_y = self.mc.getHeight(int(position.x), int(position.z))
                # Nos ponemos un poco bajo tierra para no minar aire (y-1)
                position.y = surface_y - 1 
            except:
                position.y = self.RESTART_Y
                
        # Pequeña pausa para no saturar
        await asyncio.sleep(0.2)