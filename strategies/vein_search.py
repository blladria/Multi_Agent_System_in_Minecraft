# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable, List, Set, Tuple
from mcpi.vec3 import Vec3
from mcpi import block
from .base_strategy import BaseMiningStrategy

class VeinSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda de Veta (Implementación Real BFS).
    Detecta un bloque de mineral requerido y recorre todos los bloques conectados
    del mismo tipo para extraer la veta completa.
    """
    
    # Offsets para los 6 vecinos (Arriba, Abajo, Norte, Sur, Este, Oeste)
    NEIGHBORS = [
        Vec3(0, 1, 0), Vec3(0, -1, 0), 
        Vec3(1, 0, 0), Vec3(-1, 0, 0), 
        Vec3(0, 0, 1), Vec3(0, 0, -1)
    ]
    
    # Límite de seguridad para evitar minar el mundo entero si la veta es enorme
    MAX_VEIN_SIZE = 50 

    def __init__(self, mc_connection, logger):
        super().__init__(mc_connection, logger)
        # Mapeo inverso simple para identificar IDs de interés basados en requisitos
        self.ore_map = {
            "diamond_ore": block.DIAMOND_ORE.id,
            "gold_ore": block.GOLD_ORE.id,
            "iron_ore": block.IRON_ORE.id,
            "coal_ore": block.COAL_ORE.id,
            "lapis_lazuli_ore": block.LAPIS_LAZULI_ORE.id,
            "redstone_ore": block.REDSTONE_ORE.id,
            "dirt": block.DIRT.id,
            "stone": block.STONE.id,
            "cobblestone": block.COBBLESTONE.id
        }

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        """
        Ejecuta la búsqueda de veta real.
        1. Escanea el entorno cercano.
        2. Si encuentra un mineral requerido, inicia BFS.
        """
        self.logger.debug("Estrategia activa: Búsqueda de Veta (Real BFS).")

        # 1. Identificar qué IDs estamos buscando según los requisitos pendientes
        target_ids = self._get_target_ids(requirements, inventory)
        
        if not target_ids:
            self.logger.info("VeinSearch: No hay minerales específicos requeridos pendientes.")
            await asyncio.sleep(1)
            return

        # 2. Escanear el área cercana (Radio 2 bloques) para encontrar un punto de inicio
        start_node = await self._scan_surroundings(position, target_ids)

        if start_node:
            block_id = self.mc.getBlock(start_node.x, start_node.y, start_node.z)
            self.logger.info(f"VeinSearch: ¡Veta encontrada! ID {block_id} en {start_node}")
            
            # 3. Iniciar Algoritmo de Inundación (Flood Fill / BFS)
            await self._mine_vein_bfs(start_node, block_id, mine_block_callback)
        else:
            # Si no encuentra nada cerca, se mueve aleatoriamente para buscar (Random Walk)
            self.logger.debug("VeinSearch: Nada cerca. Buscando...")
            await self._random_walk(position)

    def _get_target_ids(self, requirements: Dict[str, int], inventory: Dict[str, int]) -> List[int]:
        """Devuelve una lista de IDs de bloques que necesitamos minar."""
        targets = []
        for name, qty in requirements.items():
            current = inventory.get(name, 0)
            if current < qty and name in self.ore_map:
                targets.append(self.ore_map[name])
        return targets

    async def _scan_surroundings(self, center: Vec3, target_ids: List[int]) -> Vec3:
        """Escanea un cubo de 5x5x5 alrededor del agente."""
        radius = 2
        cx, cy, cz = int(center.x), int(center.y), int(center.z)
        
        # Prioridad: Escanear de abajo hacia arriba
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                for z in range(cz - radius, cz + radius + 1):
                    # Optimización: No llamar a MC si es aire (imposible saber sin getBlock, 
                    # pero asumimos que getBlock es rápido en local)
                    try:
                        b_id = self.mc.getBlock(x, y, z)
                        if b_id in target_ids:
                            return Vec3(x, y, z)
                    except:
                        pass
        return None

    async def _mine_vein_bfs(self, start_pos: Vec3, target_id: int, mine_callback: Callable):
        """
        Algoritmo BFS para minar todos los bloques conectados del mismo tipo.
        """
        # Cola para el BFS (FIFO)
        queue: List[Vec3] = [start_node_clone(start_pos)]
        # Conjunto de visitados para evitar ciclos (usamos tuplas x,y,z para hashing)
        visited: Set[Tuple[int, int, int]] = {(int(start_pos.x), int(start_pos.y), int(start_pos.z))}
        
        blocks_mined = 0

        while queue:
            # Si alcanzamos el límite de seguridad, paramos esta veta
            if blocks_mined >= self.MAX_VEIN_SIZE:
                self.logger.warning("VeinSearch: Veta demasiado grande, deteniendo por seguridad.")
                break

            # Sacar el siguiente bloque de la cola
            current_pos = queue.pop(0)

            # 1. MINAR EL BLOQUE ACTUAL
            # Movemos al agente "cerca" del bloque para realismo (opcional, visual)
            # await self._move_agent_visual(current_pos) 
            
            success = await mine_callback(current_pos)
            
            if success:
                blocks_mined += 1
                await asyncio.sleep(0.4) # Pequeño delay para ver la animación de minado
                
                # 2. BUSCAR VECINOS
                for offset in self.NEIGHBORS:
                    neighbor_pos = current_pos + offset
                    n_tuple = (int(neighbor_pos.x), int(neighbor_pos.y), int(neighbor_pos.z))
                    
                    if n_tuple not in visited:
                        try:
                            # Chequear si el vecino es del mismo tipo
                            n_id = self.mc.getBlock(neighbor_pos.x, neighbor_pos.y, neighbor_pos.z)
                            if n_id == target_id:
                                visited.add(n_tuple)
                                queue.append(neighbor_pos)
                        except Exception as e:
                            self.logger.error(f"Error leyendo vecino: {e}")

        self.logger.info(f"VeinSearch: Veta terminada. Total bloques extraídos: {blocks_mined}")

    async def _random_walk(self, position: Vec3):
        """Mueve al agente ligeramente si no encuentra nada, para expandir la búsqueda."""
        import random
        # Movimiento aleatorio pequeño en X o Z
        dx = random.choice([-1, 0, 1])
        dz = random.choice([-1, 0, 1])
        
        position.x += dx
        position.z += dz
        # Ajustar Y al suelo
        try:
            position.y = self.mc.getHeight(position.x, position.z) + 1
        except:
            pass
        await asyncio.sleep(0.5)

def start_node_clone(v: Vec3):
    return Vec3(v.x, v.y, v.z)