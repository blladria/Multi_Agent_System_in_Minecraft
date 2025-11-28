# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla: Simula una exploración cubica en un plano XZ.
    Ahora utiliza un callback para romper bloques reales.
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        """
        Mueve la posición X y Z en patrón de rejilla y rompe 3 bloques de profundidad.
        """
        self.logger.debug("Estrategia activa: Búsqueda en Rejilla (área cúbica).")
        volume = 3
        
        # 1. Modificar la posición (Mover en rejilla en XZ)
        position.x += 1
        if position.x > self.max_x:
             position.x = 0
             position.z += 1
        
        # 2. Romper 'volume' bloques en la nueva posición XZ (simulando 3 bloques de profundidad)
        for i in range(volume):
            # Clonar posición temporal para minar ligeramente debajo
            temp_pos = position.clone()
            
            # Intentar minar en Y (hacia abajo)
            temp_pos.y -= i 
            
            # Llamada al callback para romper el bloque y actualizar inventario
            await mine_block_callback(temp_pos)
            
            # Esperar un tiempo por bloque minado/intentado minar
            await asyncio.sleep(0.2) 
        
        # 3. Simular el tiempo que toma minar
        await asyncio.sleep(0.1)