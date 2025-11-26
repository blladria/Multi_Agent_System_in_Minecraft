# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical: Simula una perforación hacia abajo.
    """
    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, simulate_extraction: Callable):
        """
        Mueve la posición Y hacia abajo y simula la extracción.
        """
        self.logger.debug("Estrategia activa: Búsqueda Vertical (hacia abajo).")

        # 1. Modificar la posición (Minar hacia abajo)
        position.y -= 1 
        
        # 2. Simular la extracción de materiales (pasa la lógica de simulación del bot)
        await simulate_extraction(requirements, inventory, volume=5)
        
        # 3. Simular el tiempo que toma minar
        await asyncio.sleep(1)