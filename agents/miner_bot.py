# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block

# Importar estrategias (asumimos que ya están corregidas)
from strategies.base_strategy import BaseMiningStrategy
from strategies.vertical_search import VerticalSearchStrategy
from strategies.grid_search import GridSearchStrategy
from strategies.vein_search import VeinSearchStrategy 

# Mapeo de materiales
MATERIAL_MAP = {
    "wood": block.WOOD.id, 
    "wood_planks": block.WOOD_PLANKS.id,
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id,
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id,
    "dirt": block.DIRT.id,
    "sand": block.SAND.id,
    "sandstone": block.SANDSTONE.id,
    "gravel": block.GRAVEL.id
}

class MinerBot(BaseAgent):
    """
    Agente MinerBot: Extrae recursos usando estrategias adaptativas.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        # Posición de trabajo (se actualiza dinámicamente)
        self.mining_position: Vec3 = Vec3(10, 65, 10)
        self.mining_sector_locked = False 
        
        # Offset para no minar siempre en el mismo hueco
        self._mining_offset: int = 0
        
        # Estrategias Disponibles
        self.strategy_classes: Dict[str, Type[BaseMiningStrategy]] = { 
            "vertical": VerticalSearchStrategy,
            "grid": GridSearchStrategy,
            "vein": VeinSearchStrategy,
        }
        self.current_strategy_name = "vertical" 
        self.current_strategy_instance = VerticalSearchStrategy(self.mc, self.logger)
        
        # Marcador Amarillo (Lana Amarilla = data 4)
        self._set_marker_properties(block.WOOL.id, 4)

    def get_total_volume(self) -> int:
        return sum(self.inventory.values())

    def _check_requirements_fulfilled(self) -> bool:
        if not self.requirements: return False
        return all(self.inventory.get(mat, 0) >= qty for mat, qty in self.requirements.items())

    # --- LÓGICA DE EXTRACCIÓN FÍSICA ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        """
        Rompe el bloque en la posición dada y actualiza el inventario si es necesario.
        """
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        try:
            block_id = self.mc.getBlock(x, y, z)
        except: return False

        if block_id == block.AIR.id:
            return False

        # Identificar qué material obtenemos (DROP LOGIC)
        material_dropped = None
        
        if block_id in [block.GRASS.id, block.DIRT.id]:
            material_dropped = "dirt" 
        elif block_id in [block.STONE.id, block.COBBLESTONE.id, block.MOSS_STONE.id]:
            material_dropped = "cobblestone"
        elif block_id == block.SAND.id:
            material_dropped = "sand"
        elif block_id == block.SANDSTONE.id:
            material_dropped = "sandstone"
        elif block_id == block.GRAVEL.id:
            material_dropped = "gravel"
        elif block_id in [block.WOOD.id, block.LEAVES.id]:
            material_dropped = "wood"
        else:
             # Búsqueda inversa para Ores
             for name, bid in MATERIAL_MAP.items():
                 if bid == block_id: 
                      material_dropped = name
                      break
        
        # Verificar si lo necesitamos
        material_to_count = None
        if material_dropped and material_dropped in self.requirements:
            req = self.requirements.get(material_dropped, 0)
            curr = self.inventory.get(material_dropped, 0)
            if curr < req:
                material_to_count = material_dropped

        # Acción Física: Romper
        try:
            self.mc.setBlock(x, y, z, block.AIR.id)
            
            if material_to_count:
                self.inventory[material_to_count] += 1
                req = self.requirements[material_to_count]
                self.logger.info(f"MINADO: {material_to_count} ({self.inventory[material_to_count]}/{req})")
            
            return True
        except: return False

    # --- CICLO DE VIDA ---

    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                await self._complete_mining_cycle() 
                self.state = AgentState.IDLE 
            else:
                 await self._select_adaptive_strategy()
                 if not self.mining_sector_locked:
                    self.mining_sector_locked = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            
            # 1. FIX VISUALIZACIÓN: Marcador siempre en superficie
            try:
                 x, z = int(self.mining_position.x), int(self.mining_position.z)
                 # Obtenemos la altura REAL de la superficie para pintar la lana
                 y_surf = self.mc.getHeight(x, z) + 1
                 # Pintamos el marcador en la superficie
                 self._update_marker(Vec3(x, y_surf, z))
            except: pass
            
            # 2. Ejecutar estrategia, que modificará la posición interna (Y)
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position, 
                mine_block_callback=self._mine_current_block 
            )
            
            # 3. Publicar progreso
            await self._publish_inventory_update(status="PENDING")
            
    # --- UTILS ---

    def release_locks(self):
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock liberado.")
            
    async def _complete_mining_cycle(self):
        await self._publish_inventory_update(status="SUCCESS")
        self.release_locks()
        self._mining_offset += 1 
        self.logger.info("Ciclo minería completado.")

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command in ['start', 'fulfill']:
                self._parse_start_params(payload.get("parameters", {}))
                await self._select_adaptive_strategy() 
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else: self.state = AgentState.IDLE
            elif command == 'set': self._parse_set_strategy(payload.get("parameters", {}))
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
            
        elif msg_type == "materials.requirements.v1":
            self.requirements = payload.copy()
            self.logger.info(f"Nuevos requisitos recibidos: {self.requirements}")
            
            # Reposicionar minero según zona de construcción + offset
            ctx_zone = message.get("context", {}).get("target_zone")
            if ctx_zone:
                 bx, bz = int(ctx_zone['x']), int(ctx_zone['z'])
                 offset = 15 + (self._mining_offset * 10) 
                 
                 self.mining_position.x = bx + offset
                 self.mining_position.z = bz + offset
                 try:
                     # Posiciona en la superficie para empezar a picar desde allí
                     self.mining_position.y = self.mc.getHeight(self.mining_position.x, self.mining_position.z) + 1
                 except: self.mining_position.y = 65
                 
                 # Reiniciar la instancia de estrategia
                 self.current_strategy_instance = self.strategy_classes[self.current_strategy_name](self.mc, self.logger)
                 self.logger.info(f"Minero desplazado a: ({self.mining_position.x}, {self.mining_position.z})")
            
            await self._select_adaptive_strategy()
            
            if self.state in (AgentState.IDLE, AgentState.WAITING): 
                self.state = AgentState.RUNNING

    def _parse_start_params(self, params: Dict[str, Any]):
        args = params.get('args', [])
        nx, nz = None, None
        for a in args:
            if 'x=' in a: nx = int(a.split('=')[1])
            if 'z=' in a: nz = int(a.split('=')[1])
        
        if nx is None:
            try: 
                p = self.mc.player.getTilePos()
                nx, nz = p.x, p.z
            except: nx, nz = 0, 0
            
        self.mining_position.x = nx
        self.mining_position.z = nz
        try: self.mining_position.y = self.mc.getHeight(nx, nz) + 1
        except: pass

    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            strat = args[1].lower()
            if strat in self.strategy_classes:
                self.current_strategy_instance = self.strategy_classes[strat](self.mc, self.logger)
                self.current_strategy_name = strat
                self.logger.info(f"Estrategia manual: {strat}")

    async def _select_adaptive_strategy(self):
        """Elige la mejor estrategia según lo que falte."""
        if not self.requirements: return 

        pending = {m: q - self.inventory.get(m, 0) for m, q in self.requirements.items() if q > self.inventory.get(m, 0)}
        if not pending: return 

        most_needed = max(pending, key=pending.get)
        new_strat = "vertical" # Default

        vein_mats = ("diamond_ore", "iron_ore", "gold_ore", "coal_ore", "redstone_ore")
        
        # Reglas de Selección:
        if pending.get("dirt", 0) > 0 or pending.get("sand", 0) > 0:
            new_strat = "grid" # Superficie para tierra/arena
        elif most_needed in vein_mats:
            new_strat = "vein" # Vetas para minerales valiosos
        elif most_needed in ("cobblestone", "stone", "sandstone", "gravel"):
            new_strat = "vertical" # Vertical para materiales masivos profundos
            
        if new_strat != self.current_strategy_name:
            self.current_strategy_name = new_strat
            self.current_strategy_instance = self.strategy_classes[new_strat](self.mc, self.logger)
            self.logger.info(f"Estrategia cambiada a: {new_strat} (Objetivo: {most_needed})")

    async def _publish_inventory_update(self, status: str):
        msg = {
            "type": "inventory.v1",
            "source": self.agent_id, "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "collected_materials": self.inventory,
                "total_volume": self.get_total_volume()
            },
            "status": status,
            "context": {"required_bom": self.requirements}
        }
        await self.broker.publish(msg)