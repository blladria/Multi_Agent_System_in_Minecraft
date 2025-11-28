# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical: Simula una perforación hacia abajo.
    Ahora utiliza un callback para romper bloques reales.
    """
    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        """
        Mueve la posición Y hacia abajo y rompe 'volume' bloques.
        """
        self.logger.debug("Estrategia activa: Búsqueda Vertical (hacia abajo).")

        # El volumen/rate de minería es 3 bloques/ciclo.
        volume = 3
        y_initial = position.y
        
        # 1. Intentar minar 3 bloques en la posición actual antes de moverse.
        for i in range(volume):
            x, y, z = position.x, position.y, position.z
            
            # 2. Minar en la posición y actualizar inventario (callback real)
            block_mined = await mine_block_callback(position)
            
            # 3. Si no minamos nada (aire), nos movemos hacia abajo.
            if not block_mined:
                 position.y -= 1 
                 self.logger.debug(f"No hay bloque en ({x}, {y}, {z}). Moviendo posición Y a {position.y}.")
            
            # Esperamos un tiempo por bloque minado/intentado minar
            await asyncio.sleep(0.3) 
        
        # 4. Asegurar que nos movemos un poco hacia abajo si no lo hicimos en el loop
        if volume > 0 and y_initial == position.y:
             position.y -= 1 
             self.logger.debug(f"Ciclo finalizado. Moviendo posición Y a {position.y}.")
             
        # Simular el tiempo de minería restante.
        await asyncio.sleep(0.1)