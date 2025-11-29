# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla (Adaptada para minería de Superficie: Dirt/Grass).
    CORRECCIÓN: Se ancla la posición Y de minería a un nivel fijo para asegurar
    la extracción horizontal de la capa superficial (Grass/Dirt).
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 
        self.search_x = 0
        self.search_z = 0
        self.start_x = None  # ANCLA: Posición X de inicio de la cuadrícula
        self.start_z = None  # ANCLA: Posición Z de inicio de la cuadrícula
        self.mining_y_level = None # NEW: Fixed Y level for horizontal mining
        self.WOOD_BLOCK_ID = block.WOOD.id
        self.LEAVES_BLOCK_ID = block.LEAVES.id

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # 0. Anclaje de la posición inicial y el nivel Y de minería.
        if self.start_x is None:
            self.start_x = int(position.x)
            self.start_z = int(position.z)
            # Fija el nivel Y para la minería a la altura de la superficie inicial - 1 (para asegurar DIRT).
            initial_surface_y = self.mc.getHeight(self.start_x, self.start_z)
            self.mining_y_level = initial_surface_y - 1
            # Para evitar minar en el aire, si la superficie es baja, minar el bloque de la superficie.
            if self.mining_y_level < 1: self.mining_y_level = initial_surface_y
            
            self.logger.info(f"GridSearch anclado a la posición inicial ({self.start_x}, {self.start_z}) y minando en Y={self.mining_y_level}")

        # 1. Lógica de Movimiento Horizontal (Actualiza contadores)
        self.search_x += 1
        if self.search_x > self.max_x:
             self.search_x = 0
             self.search_z += 1
        
        # 2. Calcular la posición objetivo (Usando ancla + offsets)
        x_target = self.start_x + self.search_x
        z_target = self.start_z + self.search_z
        
        # 3. La posición Y del agente (marcador) sigue la altura real de la superficie
        # (Necesario para que el marcador sea visible)
        marker_y = self.mc.getHeight(x_target, z_target)
        position.x = x_target
        position.z = z_target
        position.y = marker_y 

        # --- Lógica de Minería Adaptativa ---
        
        # Solo se prioriza la búsqueda de 'dirt'.
        if 'dirt' in requirements and requirements['dirt'] > 0:
            self.logger.debug(f"Estrategia: Grid/Superficie (Mina horizontal) en ({x_target}, {self.mining_y_level}, {z_target}).")
            
            # 4. Minar DOS bloques en la misma columna para capturar GRASS y DIRT
            mine_pos_1 = Vec3(x_target, self.mining_y_level + 1, z_target) # La capa de arriba (Grass/Dirt)
            mine_pos_2 = Vec3(x_target, self.mining_y_level, z_target)     # La capa de minería principal (Dirt/Stone)

            await mine_block_callback(mine_pos_1)
            await mine_block_callback(mine_pos_2) 
            
            await asyncio.sleep(0.2)
                
        else:
            self.logger.debug("Estrategia: Grid/General. (Minado en área cúbica por defecto).")
            
            # Comportamiento Grid por defecto (minar 3 capas)
            current_surface_y = self.mc.getHeight(x_target, z_target)
            volume = 3
            for i in range(volume):
                mine_pos = Vec3(x_target, current_surface_y - i, z_target)
                await mine_block_callback(mine_pos)
                await asyncio.sleep(0.2) 
        
        await asyncio.sleep(0.1)