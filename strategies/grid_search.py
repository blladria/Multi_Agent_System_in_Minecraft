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
        # La posición base es el bloque sólido superior.
        position.y = current_surface_y 

        # --- Lógica de Minería Adaptativa ---
        
        if 'wood' in requirements and requirements['wood'] > 0:
            self.logger.debug("Estrategia: Grid/Tala (Buscando WOOD).")
            
            # CORRECCIÓN: Empezamos a buscar 1 bloque por encima de la superficie.
            y_check_start = current_surface_y + 1 
            is_tree_found = False
            
            # Inicializamos la base con la altura de inicio, para que capture la Y más baja.
            lowest_tree_y = y_check_start 
            highest_tree_y = y_check_start
            
            # 2. Búsqueda vertical de troncos y hojas
            for dy in range(15): # Busca 15 bloques hacia arriba
                y_check = y_check_start + dy
                
                try:
                    block_at_pos = self.mc.getBlock(x_target, y_check, z_target)
                except Exception:
                    break
                
                # Si encontramos un bloque de ARBOL (madera o hojas)
                if block_at_pos == self.WOOD_BLOCK_ID or block_at_pos == self.LEAVES_BLOCK_ID:
                    if not is_tree_found:
                        lowest_tree_y = y_check # Captura la Y más baja del árbol
                    highest_tree_y = y_check # Captura la Y más alta del árbol
                    is_tree_found = True
                
                # Si encontramos aire y ya habíamos encontrado parte del árbol (hojas o tronco), es el final de la estructura.
                elif block_at_pos == block.AIR.id and is_tree_found:
                    break 
                
                # Si encontramos aire antes de encontrar árbol, no hay árbol.
                elif block_at_pos == block.AIR.id and not is_tree_found:
                    break
            
            if is_tree_found:
                # 3. Minar el árbol completo desde la base hasta el tope encontrado (+3 de margen para hojas superiores)
                self.logger.info(f"Árbol encontrado. Iniciando tala vertical de Y={lowest_tree_y} a Y={highest_tree_y}.")
                
                for y_mine in range(lowest_tree_y, highest_tree_y + 3): 
                    mine_pos = Vec3(x_target, y_mine, z_target)
                    
                    try:
                        block_to_mine_id = self.mc.getBlock(x_target, y_mine, z_target)
                    except Exception:
                        continue 

                    # Solo llamamos al callback si es un bloque de madera o hojas.
                    # El bucle continua incluso si encuentra aire (rompe a través del follaje).
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