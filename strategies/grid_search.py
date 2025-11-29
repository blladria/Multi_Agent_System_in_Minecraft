# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla (Adaptada para minería de Superficie: Dirt/Grass).
    CORRECCIÓN: La posición se calcula con offsets desde un punto inicial fijo para
    garantizar que se mine un área definida en lugar de moverse linealmente.
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 
        self.search_x = 0
        self.search_z = 0
        self.start_x = None  # ANCLA: Posición X de inicio de la cuadrícula
        self.start_z = None  # ANCLA: Posición Z de inicio de la cuadrícula
        self.WOOD_BLOCK_ID = block.WOOD.id
        self.LEAVES_BLOCK_ID = block.LEAVES.id

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # 0. Anclaje de la posición inicial (solo en la primera ejecución)
        if self.start_x is None:
            self.start_x = int(position.x)
            self.start_z = int(position.z)

        # 1. Lógica de Movimiento Horizontal (Actualiza contadores)
        self.search_x += 1
        if self.search_x > self.max_x:
             self.search_x = 0
             self.search_z += 1
        
        # 2. Calcular la posición objetivo (Usando ancla + offsets)
        x_target = self.start_x + self.search_x
        z_target = self.start_z + self.search_z
        
        # 3. Obtener la altura real de la superficie en la nueva coordenada
        current_surface_y = self.mc.getHeight(x_target, z_target)
        
        # Mutar la posición del agente para reflejar el movimiento del escaneo (y mover el marcador)
        position.x = x_target
        position.z = z_target
        position.y = current_surface_y # <-- Esta es la altura de la superficie

        # --- Lógica de Minería Adaptativa ---
        
        # Solo se prioriza la búsqueda de 'dirt'.
        if 'dirt' in requirements and requirements['dirt'] > 0:
            self.logger.debug(f"Estrategia: Grid/Superficie (Buscando DIRT) en ({x_target}, {current_surface_y}, {z_target}).")
            
            # 4. Minar la capa superior de césped/tierra.
            mine_pos = Vec3(x_target, current_surface_y, z_target)
            
            # El callback de minería ya verifica si el bloque es DIRT/GRASS (3/2) y lo consume.
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