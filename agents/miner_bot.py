# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3

# Importar las clases de estrategia (se asume que ya están creadas)
from strategies.base_strategy import BaseMiningStrategy
from strategies.vertical_search import VerticalSearchStrategy
from strategies.grid_search import GridSearchStrategy
from strategies.vein_search import VeinSearchStrategy 

# Diccionario de materiales para simulación (material: ID de bloque MC)
MATERIAL_MAP = {
    "wood": 17,
    "stone": 1,
    "cobblestone": 4,
    "diamond_ore": 56,
    "glass": 20
}

class MinerBot(BaseAgent):
    """
    Agente responsable de la extracción y colección de materiales (Patrón Estrategia).
    (Uso de Programación Funcional en la agregación de inventario).
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        self.mining_position: Vec3 = Vec3(0, 60, 0)
        self.mining_sector_locked = False 
        
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

    # --- Lógica de Programación Funcional (Agregación) ---
    
    def get_total_volume(self) -> int:
        """
        Calcula el volumen total minado. 
        Aplica un patrón funcional (sum()/reduce) para la agregación del inventario.
        """
        # --- APLICACIÓN FUNCIONAL (sum/reduce) ---
        return sum(self.inventory.values())
        # -----------------------------------------

    def _check_requirements_fulfilled(self) -> bool:
        """Verifica si el inventario actual satisface los requisitos del BuilderBot (Uso funcional)."""
        if not self.requirements:
            return False
        # Uso de Programación Funcional: all() junto con un generador (equivalente a filter/map)
        return all(self.inventory.get(material, 0) >= required_qty 
                   for material, required_qty in self.requirements.items())

    async def _simulate_extraction(self, requirements: Dict[str, int], inventory: Dict[str, int], volume: int):
        blocks_extracted = 0
        for material, required_qty in requirements.items():
            if inventory[material] < required_qty:
                qty_to_mine = min(volume - blocks_extracted, required_qty - inventory[material])
                if qty_to_mine > 0:
                    inventory[material] += qty_to_mine
                    blocks_extracted += qty_to_mine
                    self.logger.debug(f"Extraidos {qty_to_mine} de {material}. Total: {inventory[material]}")
        if volume > blocks_extracted:
            inventory["stone"] += (volume - blocks_extracted)

    # --- Ciclo Perceive-Decide-Act (ACT Omitido para brevedad) ---
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                self.logger.info("Decidiendo: Requisitos completados. Publicando inventario final.")
                self.state = AgentState.IDLE 
            elif not self.mining_sector_locked:
                self.logger.info("Decidiendo: Adquiriendo lock de sector de mineria.")
                self.mining_sector_locked = True
                self.logger.info("Lock de sector adquirido. Minando...")

    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position,
                simulate_extraction=self._simulate_extraction
            )
            await self._publish_inventory_update(status="PENDING")
            
        elif self.state == AgentState.IDLE and self._check_requirements_fulfilled():
            await self._publish_inventory_update(status="SUCCESS")
            self.release_locks()
            self.state = AgentState.IDLE

    # --- Control y Sincronización (Omitido para brevedad) ---
    def release_locks(self):
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock de sector de minería liberado.")

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'start' or command == 'fulfill':
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else:
                    self.state = AgentState.IDLE
                    self.mc.postToChat(f"{self.agent_id}: Requisitos ya cumplidos.")
            elif command == 'set': self._parse_set_strategy(payload.get("parameters", {}))
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
        elif msg_type == "materials.requirements.v1":
            self.requirements = payload
            self.logger.info(f"Requisitos de materiales recibidos: {self.requirements}")
            if self.state == AgentState.IDLE: self.state = AgentState.RUNNING

    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            new_strategy_name = args[1].lower()
            if new_strategy_name in self.strategy_classes:
                StrategyClass = self.strategy_classes[new_strategy_name]
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
                self.logger.info(f"Estrategia de mineria cambiada a: {new_strategy_name}")
            else:
                self.mc.postToChat(f"ERROR: Estrategia '{new_strategy_name}' no reconocida.")

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