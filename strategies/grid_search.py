# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla: Simula una exploración cubica en un plano XZ.
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, simulate_extraction: Callable):
        """
        Mueve la posición X y Z en patrón de rejilla y simula la extracción.
        """
        self.logger.debug("Estrategia activa: Búsqueda en Rejilla (área cúbica).")

        # 1. Modificar la posición (Mover en rejilla)
        position.x += 1
        if position.x > self.max_x:
             position.x = 0
             position.z += 1
        
        # 2. Simular la extracción de materiales
        # Ajustado el volumen a 3 bloques/ciclo para consistencia
        await simulate_extraction(requirements, inventory, volume=3)
        
        # 3. Simular el tiempo que toma minar
        await asyncio.sleep(0.7)