# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla (Adaptada para minería de Superficie: Dirt).
    Se ha eliminado la lógica de búsqueda de 'wood' por requerimiento del usuario.
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 
        self.search_x = 0
        self.search_z = 0
        self.WOOD_BLOCK_ID = block.WOOD.id
        self.LEAVES_BLOCK_ID = block.LEAVES.id

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # 1. Lógica de Movimiento Horizontal (Común)
        self.search_x += 1
        if self.search_x > self.max_x:
             self.search_x = 0
             self.search_z += 1
        
        # Uso de coordenadas enteras para el target
        x_target, z_target = int(position.x) + 1, int(position.z) + 1
        position.x, position.z = x_target, z_target
        
        # Obtener la altura real de la superficie (para alineación y minado)
        current_surface_y = self.mc.getHeight(x_target, z_target)
        # La posición Y de la estrategia (y el marcador) se fija en la superficie
        position.y = current_surface_y 

        # --- Lógica de Minería Adaptativa ---
        
        # Solo se prioriza la búsqueda de 'dirt', ya que 'wood' ha sido eliminado de los requisitos.
        if 'dirt' in requirements and requirements['dirt'] > 0:
            self.logger.debug("Estrategia: Grid/Superficie (Buscando DIRT).")
            
            # 2. Minar solo la capa superior de césped/tierra.
            # current_surface_y es el bloque de césped sobre el que está "caminando".
            mine_pos = Vec3(x_target, current_surface_y, z_target)
            await mine_block_callback(mine_pos)
            await asyncio.sleep(0.2)
                
        else:
            self.logger.debug("Estrategia: Grid/General. (Minado en área cúbica por defecto).")
            
            # Comportamiento Grid por defecto (minar 3 capas)
            volume = 3
            for i in range(volume):
                mine_pos = Vec3(x_target, current_surface_y - i, z_target)
                await mine_block_callback(mine_pos)
                await asyncio.sleep(0.2) 
        
        await asyncio.sleep(0.1)