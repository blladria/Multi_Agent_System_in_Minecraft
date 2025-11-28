# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical: Simula una perforación hacia abajo.
    Ahora utiliza un callback para romper bloques reales, asegurando que se rompen 3 bloques distintos.
    """
    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        """
        Mina 3 bloques directamente debajo del agente y luego mueve el agente 1 bloque hacia abajo.
        Esto simula un proceso de perforación (drilling).
        """
        self.logger.debug("Estrategia activa: Búsqueda Vertical (hacia abajo).")

        # El volumen/rate de minería es 3 bloques/ciclo.
        volume = 3
        
        # 1. Minar 3 bloques distintos debajo del agente
        for i in range(volume):
            # Clonar la posición del agente y calcular la posición del bloque a minar (y-1, y-2, y-3)
            mine_pos = position.clone()
            # Posición de minería es (Y - 1), (Y - 2), (Y - 3)
            mine_pos.y -= (i + 1)
            
            # Minar el bloque
            await mine_block_callback(mine_pos)
            
            # Esperamos un tiempo por bloque minado/intentado minar
            await asyncio.sleep(0.3) 
        
        # 2. Mover la posición del agente hacia abajo 1 bloque (para el siguiente ciclo)
        # Esto asegura que la perforación continúe hacia abajo, cumpliendo con la lógica original.
        position.y -= 1 
        self.logger.debug(f"Agente se mueve a Y={position.y} para el siguiente ciclo.")
             
        # 3. Simular el tiempo que toma minar
        await asyncio.sleep(0.1)