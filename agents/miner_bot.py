# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block

# Importar las clases de estrategia (Patrón Estrategia)
from strategies.base_strategy import BaseMiningStrategy
from strategies.vertical_search import VerticalSearchStrategy
from strategies.grid_search import GridSearchStrategy
from strategies.vein_search import VeinSearchStrategy 

# Diccionario de materiales para simulación (material: ID de bloque MC)
MATERIAL_MAP = {
    "wood": block.WOOD.id, 
    "wood_planks": block.WOOD_PLANKS.id,
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id, 
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id,
    "door_wood": block.DOOR_WOOD.id,
    "dirt": block.DIRT.id
}

class MinerBot(BaseAgent):
    """
    Agente responsable de la extracción y colección de materiales (Patrón Estrategia).
    Implementa selección de estrategia adaptativa basada en requisitos.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        try:
            player_pos = self.mc.player.getTilePos()
            self.mining_position: Vec3 = Vec3(player_pos.x + 10, 60, player_pos.z + 10)
        except Exception:
            self.mining_position: Vec3 = Vec3(10, 60, 10)
            
        self.mining_sector_locked = False 
        
        # Registro de estrategias
        self.strategy_classes: Dict[str, Type[BaseMiningStrategy]] = { 
            "vertical": VerticalSearchStrategy,
            "grid": GridSearchStrategy,
            "vein": VeinSearchStrategy,
        }
        self.current_strategy_name = "vertical" 
        self.current_strategy_instance: BaseMiningStrategy = VerticalSearchStrategy(
            self.mc, 
            self.logger
        )
        
        self._set_marker_properties(block.WOOL.id, 4)

    # --- Lógica de Programación Funcional (Agregación) ---
    
    def get_total_volume(self) -> int:
        return sum(self.inventory.values())

    def _check_requirements_fulfilled(self) -> bool:
        if not self.requirements:
            return False
        return all(self.inventory.get(material, 0) >= required_qty 
                   for material, required_qty in self.requirements.items())

    # --- Lógica de Extracción REAL (CORREGIDA) ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        """
        Rompe el bloque y actualiza el inventario, aplicando la limitación estricta de requisitos.
        """
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        try:
            current_block_id = self.mc.getBlock(x, y, z)
        except Exception as e:
            self.logger.error(f"Error al obtener bloque en MC ({x}, {y}, {z}): {e}")
            return False

        if current_block_id == block.AIR.id:
            return False

        # 1. Identificar material requerido
        material_found = None
        for name, id in MATERIAL_MAP.items():
            if id == current_block_id and name in self.requirements:
                 material_found = name
                 break
        
        # 2. Romper el Bloque en Minecraft
        try:
            self.mc.setBlock(x, y, z, block.AIR.id)
            
            # 3. Actualizar Inventario (LÓGICA DE DETENCIÓN CRÍTICA)
            if material_found:
                required_qty = self.requirements.get(material_found, 0)
                current_qty = self.inventory.get(material_found, 0)

                if required_qty > 0 and current_qty < required_qty:
                    self.inventory[material_found] = current_qty + 1
                    self.logger.info(f"EXTRAÍDO 1 de {material_found}. Total: {self.inventory[material_found]}/{required_qty}")
                else:
                    self.logger.debug(f"Material {material_found} ya cumplido o no requerido. Bloque desechado.")
            else:
                self.logger.debug(f"Bloque minado ID:{current_block_id} no es material requerido. Bloque desechado.")
                
            return True
        except Exception as e:
            self.logger.error(f"Error al romper bloque en MC: {e}")
            return False

    # --- Ciclo Perceive-Decide-Act ---
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                await self._complete_mining_cycle() 
                self.state = AgentState.IDLE 
            elif not self.mining_sector_locked:
                self.mining_sector_locked = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            self._update_marker(self.mining_position) 
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position,
                mine_block_callback=self._mine_current_block 
            )
            await self._publish_inventory_update(status="PENDING")
            
    # --- Control y Sincronización ---
    def release_locks(self):
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock de sector de minería liberado.")
            
    async def _complete_mining_cycle(self):
        await self._publish_inventory_update(status="SUCCESS")
        self.release_locks()


    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'start' or command == 'fulfill':
                await self._select_adaptive_strategy() 
                
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else:
                    self.state = AgentState.IDLE
            elif command == 'set': self._parse_set_strategy(payload.get("parameters", {}))
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
            
        elif msg_type == "materials.requirements.v1":
            self.requirements = payload
            self.logger.info(f"Requisitos de materiales recibidos: {self.requirements}")
            
            await self._select_adaptive_strategy()
            
            if self.state == AgentState.IDLE: 
                self.state = AgentState.RUNNING


    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            new_strategy_name = args[1].lower()
            if new_strategy_name in self.strategy_classes:
                StrategyClass = self.strategy_classes[new_strategy_name]
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
                self.logger.info(f"Estrategia de mineria cambiada manualmente a: {new_strategy_name}")
            else:
                self.mc.postToChat(f"ERROR: Estrategia '{new_strategy_name}' no reconocida.")


    async def _select_adaptive_strategy(self):
        """
        Selecciona la estrategia de minería más adecuada basada en el material más requerido.
        Usa Grid para superficie (Wood/Dirt) y Vertical/Vein para profundidad.
        """
        if not self.requirements:
            new_strategy_name = "vertical" 
        
        # 1. Determinar el material principal (ignorando los ya cumplidos)
        remaining_requirements = {mat: qty - self.inventory.get(mat, 0) 
                                  for mat, qty in self.requirements.items() if qty > self.inventory.get(mat, 0)}
        
        if not remaining_requirements:
            return # Todo cumplido.

        most_needed_material = max(remaining_requirements, key=remaining_requirements.get)

        # 2. Asignación de Estrategia
        if "wood" in remaining_requirements or "dirt" in remaining_requirements:
            # Grid Search para minería de superficie (Tala y Tierra)
            new_strategy_name = "grid"
        elif most_needed_material in ("diamond_ore", "iron_ore", "gold_ore", "lapis_lazuli_ore", "redstone_ore"):
             # Vein Search para minerales concentrados
             new_strategy_name = "vein"
        elif most_needed_material in ("stone", "cobblestone"):
            # Vertical Search para minería profunda (Piedra)
            new_strategy_name = "vertical"
        else:
            new_strategy_name = "vertical" 

        
        # 3. Aplicar la estrategia solo si es diferente
        if new_strategy_name != self.current_strategy_name:
            if new_strategy_name in self.strategy_classes:
                StrategyClass = self.strategy_classes[new_strategy_name]
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
                self.logger.info(f"Estrategia de mineria adaptada a: {new_strategy_name}")
            else:
                self.logger.error(f"Estrategia adaptativa '{new_strategy_name}' no encontrada. Usando vertical.")
                self.current_strategy_instance = VerticalSearchStrategy(self.mc, self.logger)
                self.current_strategy_name = "vertical"

    async def _publish_inventory_update(self, status: str):
        total_volume = self.get_total_volume() 
        inventory_message = {
            "type": "inventory.v1",
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "collected_materials": self.inventory,
                "total_volume": total_volume
            },
            "status": status,
            "context": {"required_bom": self.requirements}
        }
        await self.broker.publish(inventory_message)
        self.logger.info(f"Inventario ({status}) publicado. Volumen total: {total_volume}")