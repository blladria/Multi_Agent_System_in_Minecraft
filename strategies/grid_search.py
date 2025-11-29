# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla (Adaptada para minería de Superficie/Tala: Dirt y Wood).
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
        
        if 'wood' in requirements and requirements['wood'] > 0:
            self.logger.debug("Estrategia: Grid/Tala (Buscando WOOD).")
            
            # Buscamos la base del árbol 1 bloque por encima de la superficie.
            y_search_start = current_surface_y + 1 
            lowest_tree_y = -1
            
            # 2. Búsqueda: Determinar la Y más baja donde hay un bloque de árbol.
            # Rango de búsqueda vertical (e.g., hasta 20 bloques de altura).
            for dy in range(20): 
                y_check = y_search_start + dy
                
                try:
                    block_at_pos = self.mc.getBlock(x_target, y_check, z_target)
                except Exception:
                    break
                
                # Si encontramos el primer bloque de árbol (Wood o Leaves), esta es nuestra base.
                if block_at_pos == self.WOOD_BLOCK_ID or block_at_pos == self.LEAVES_BLOCK_ID:
                    lowest_tree_y = y_check 
                    break 
                
                # Si encontramos aire o un bloque que NO es aire ni árbol, detenemos la búsqueda.
                if block_at_pos != block.AIR.id:
                     lowest_tree_y = -1
                     break
            
            # Si se encontró la base del árbol...
            if lowest_tree_y != -1:
                self.logger.info(f"Árbol encontrado. Iniciando tala vertical desde Y={lowest_tree_y}.")
                
                # 3. Minar la columna, permitiendo huecos (aire)
                # Iteramos hasta una altura máxima para asegurar que se talan todas las hojas.
                for y_mine in range(lowest_tree_y, lowest_tree_y + 20): 
                    mine_pos = Vec3(x_target, y_mine, z_target)
                    
                    try:
                        block_to_mine_id = self.mc.getBlock(x_target, y_mine, z_target)
                    except Exception:
                        continue 

                    # Si es un bloque de árbol, lo minamos.
                    if block_to_mine_id == self.WOOD_BLOCK_ID or block_to_mine_id == self.LEAVES_BLOCK_ID:
                        await mine_block_callback(mine_pos)
                    
                    await asyncio.sleep(0.1) # Pausa breve entre picos
            else:
                 self.logger.debug("No se encontró madera. Continuando búsqueda horizontal.")
                 
        elif 'dirt' in requirements and requirements['dirt'] > 0:
            self.logger.debug("Estrategia: Grid/Superficie (Buscando DIRT).")
            
            # 2. Minar solo las 3 capas superiores (superficiales)
            volume = 3
            for i in range(volume):
                # Aseguramos minar desde la superficie hacia abajo
                mine_pos = Vec3(x_target, current_surface_y - i, z_target)
                await mine_block_callback(mine_pos)
                await asyncio.sleep(0.2)
                
        else:
            self.logger.debug("Estrategia: Grid/General. (Minado en área cúbica por defecto).")
            
            # Comportamiento Grid por defecto
            volume = 3
            for i in range(volume):
                mine_pos = Vec3(x_target, current_surface_y - i, z_target)
                await mine_block_callback(mine_pos)
                await asyncio.sleep(0.2) 
        
        await asyncio.sleep(0.1)