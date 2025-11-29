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
        self.LEAVES_BLOCK_ID = block.LEAVES.id # Añadido para mejor detección

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # 1. Lógica de Movimiento Horizontal (Común)
        self.search_x += 1
        if self.search_x > self.max_x:
             self.search_x = 0
             self.search_z += 1
        
        position.x += 1
        position.z += 1
        x_target, z_target = int(position.x), int(position.z)
        
        # Obtener la altura real de la superficie
        current_surface_y = self.mc.getHeight(x_target, z_target)
        # CORRECCIÓN MARCADOR: La posición base es el bloque sólido superior.
        position.y = current_surface_y 

        # --- Lógica de Minería Adaptativa ---
        
        if 'wood' in requirements and requirements['wood'] > 0:
            self.logger.debug("Estrategia: Grid/Tala (Buscando WOOD).")
            
            y_check_start = current_surface_y
            is_tree_found = False
            y_trunk_base = y_check_start
            
            # 2. Búsqueda vertical de troncos (simulación de detección de árbol)
            for dy in range(15): 
                y_check = y_check_start + dy
                
                try:
                    block_at_pos = self.mc.getBlock(x_target, y_check, z_target)
                except Exception:
                    break

                # El tronco puede empezar justo por encima de la tierra (y_check_start)
                if block_at_pos == self.WOOD_BLOCK_ID:
                    is_tree_found = True
                    y_trunk_base = y_check 
                    break 

            if is_tree_found:
                self.logger.info(f"Árbol encontrado. Iniciando tala vertical desde Y={y_trunk_base}.")
                
                # 3. Tala la columna desde la base hacia arriba
                for y_mine in range(y_trunk_base, y_trunk_base + 15):
                    mine_pos = Vec3(x_target, y_mine, z_target)
                    
                    try:
                        # CORRECCIÓN PICADO: Detener la tala inmediatamente si se golpea el aire
                        if self.mc.getBlock(x_target, y_mine, z_target) == block.AIR.id:
                             break 
                    except Exception:
                        break # Salir si está fuera de los límites del mundo

                    await mine_block_callback(mine_pos)
                    await asyncio.sleep(0.1)
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
            
            # Comportamiento Grid por defecto (minar 3 bloques de profundidad)
            volume = 3
            for i in range(volume):
                temp_pos = position.clone()
                temp_pos.y -= i 
                await mine_block_callback(temp_pos)
                await asyncio.sleep(0.2) 
        
        await asyncio.sleep(0.1)