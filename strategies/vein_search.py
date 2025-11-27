# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VeinSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda de Veta: Detecta un clúster de material y lo mina
    recursivamente para maximizar el rendimiento.
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.vein_search_count = 0 
        self.vein_material = "diamond_ore" # Material objetivo de alto valor

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, simulate_extraction: Callable):
        """
        Simula la minería recursiva en un punto fijo (la veta).
        """
        self.logger.debug(f"Estrategia activa: Búsqueda de Veta ({self.vein_material}).")

        # 1. Simular la extracción de material de alto valor (simula encontrar la veta)
        # Ajustado el volumen a 5 (rendimiento superior por veta)
        volume = 5 
        
        # Simular que los requisitos se extienden al material de la veta si se necesita
        if self.vein_material in requirements:
            await simulate_extraction(requirements, inventory, volume=volume)
        else:
            # Simular la extracción en la veta y guardarlo en el inventario
            # (aunque no esté en los requisitos actuales)
            await simulate_extraction({self.vein_material: 999}, inventory, volume=volume)
            
        # 2. Simular el movimiento (ligeramente) y el tiempo que toma minar
        # Solo movemos la posición simulada ligeramente para que se vea que no es estática
        position.x += 0.1
        self.vein_search_count += 1
        
        await asyncio.sleep(2)
        
        self.logger.debug(f"Veta minada {self.vein_search_count} veces. Rendimiento: {volume}")