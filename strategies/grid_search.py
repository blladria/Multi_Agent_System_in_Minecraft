# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class GridSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda en Rejilla (Grid Search).    
    Ideal para minería de superficie (Tierra, Arena) o limpieza de terreno.
    Recorre un área definida de forma sistemática (eje X luego eje Z).
    """
    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        self.max_x = 10 
        self.search_x = 0
        self.search_z = 0
        # Variables de anclaje para mantener la referencia relativa
        self.start_x = None  
        self.start_z = None 
        self.mining_y_level = None 

        self.WOOD_BLOCK_ID = block.WOOD.id
        self.LEAVES_BLOCK_ID = block.LEAVES.id

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        # 0. Inicialización y Anclaje
        # # Si es la primera ejecución, guardamos la posición inicial como referencia (0,0) de la rejilla     
        if self.start_x is None:    
            self.start_x = int(position.x)
            self.start_z = int(position.z)
            
            # Intentar obtener la altura inicial de forma segura
            try:
                initial_surface_y = self.mc.getHeight(self.start_x, self.start_z)
            except Exception as e:
                self.logger.warning(f"GridSearch: Error al obtener altura inicial. Usando fallback Y=65. Error: {e}")
                initial_surface_y = 65

            # Fija el nivel Y de minería a la altura de la superficie inicial - 1 (para asegurar DIRT).
            self.mining_y_level = initial_surface_y - 1
            # Para evitar minar en el aire, si la superficie es baja, minar el bloque de la superficie.
            if self.mining_y_level < 1: self.mining_y_level = initial_surface_y
            
            self.logger.info(f"GridSearch anclado a la posición inicial ({self.start_x}, {self.start_z}) y minando en Y={self.mining_y_level}")

        # 1. Lógica de Movimiento Horizontal (Actualiza contadores)
        # Avanzamos en X hasta el límite, luego reseteamos X y avanzamos en Z
        self.search_x += 1
        if self.search_x > self.max_x:
             self.search_x = 0
             self.search_z += 1
        
        # 2. Calcular la posición objetivo (Usando ancla + offsets)
        x_target = self.start_x + self.search_x
        z_target = self.start_z + self.search_z
        
        # 3. Actualizar la posición del agente (marcador)
        # Manejo de excepciones para evitar caídas del agente si falla la API de Minecraft        try:
            marker_y = self.mc.getHeight(x_target, z_target) + 1 # Altura de pie
        except Exception as e:
            # Si falla la conexión, no crasheamos el agente. Usamos la Y actual o un fallback.
            self.logger.warning(f"GridSearch: Fallo de conexión en getHeight({x_target}, {z_target}). Manteniendo Y. Error: {e}")
            marker_y = position.y # Mantenemos la altura actual para no teletransportarlo al vacío
        
        # Actualizamos el objeto de posición (paso por referencia)
        position.x = x_target
        position.z = z_target
        position.y = marker_y 

        # --- Lógica de Minería Adaptativa ---
        
        # Verificamos si aún necesitamos 'dirt' (tierra)
        dirt_needed = requirements.get('dirt', 0) - inventory.get('dirt', 0)
        
        if dirt_needed > 0:
            self.logger.debug(f"Estrategia: Grid/Superficie (Mina horizontal) en ({x_target}, {self.mining_y_level}, {z_target}).")
            
            # Minamos dos capas para asegurar la recolección:
            # 1. El bloque justo debajo de los pies (puede ser Grass)
            # 2. El bloque debajo de ese (generalmente Dirt)            
            mine_pos_top = Vec3(x_target, position.y - 1, z_target) 
            mine_pos_bottom = Vec3(x_target, position.y - 2, z_target) 

            # Minar la capa superior
            await mine_block_callback(mine_pos_top)
            # Minar la capa debajo
            await mine_block_callback(mine_pos_bottom) 
            
            await asyncio.sleep(0.2)
                
        else:
            # Si el material no es requerido, solo nos movemos
            self.logger.debug("Estrategia: Grid/General. (Material no requerido o completado).")
            # Si se acaba la tierra, simplemente avanza para terminar el ciclo y forzar la re-selección de estrategia.
            await asyncio.sleep(0.1)