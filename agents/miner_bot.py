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
    "wood_planks": block.WOOD_PLANKS.id, # Añadido
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id, 
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id, # Añadido
    "door_wood": block.DOOR_WOOD.id,   # Añadido
    "dirt": block.DIRT.id
}

class MinerBot(BaseAgent):
    """
    Agente responsable de la extracción y colección de materiales (Patrón Estrategia).
    (Uso de Programación Funcional en la agregación de inventario).
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        # Inicializa el inventario con todos los materiales del MAPA
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        # MODIFICACION: Intentar iniciar cerca del jugador para visibilidad, con fallback.
        try:
            player_pos = self.mc.player.getTilePos()
            # Iniciar la minería 10 bloques al lado (x+10, z+10) del jugador, 
            # 5 bloques por debajo para empezar a excavar en la tierra.
            self.mining_position: Vec3 = Vec3(player_pos.x + 10, player_pos.y - 5, player_pos.z + 10)
        except Exception:
            # Fallback para mocks o si el jugador no está conectado (usar posición visible)
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
        
        # VISUALIZACIÓN: Marcador Amarillo (Lana Amarilla = data 4)
        self._set_marker_properties(block.WOOL.id, 4)

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

    # --- Lógica de Extracción REAL (CORREGIDA) ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        """
        Rompe el bloque en la posición dada en MC (animación visual) y actualiza el inventario
        solo si se extrajo un material útil, LIMITANDO la recolección a los requisitos.
        """
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        # 1. Obtener el tipo de bloque actual
        try:
            current_block_id = self.mc.getBlock(x, y, z)
        except Exception as e:
            self.logger.error(f"Error al obtener bloque en MC ({x}, {y}, {z}): {e}")
            return False

        if current_block_id == block.AIR.id:
            self.logger.debug(f"Posición ({x}, {y}, {z}) ya es aire. Minería ignorada.")
            return False

        # 2. Mapear ID a Material Relevante
        material_found = None
        for name, id in MATERIAL_MAP.items():
            # Buscamos solo materiales REQUERIDOS
            if id == current_block_id and name in self.requirements:
                 material_found = name
                 break
        
        # 3. Romper el Bloque en Minecraft
        try:
            # Esta línea rompe el bloque y proporciona la animación visual.
            self.mc.setBlock(x, y, z, block.AIR.id)
            self.logger.debug(f"BLOQUE ROTO en ({x}, {y}, {z}). ID: {current_block_id}")
            
            # 4. Actualizar Inventario (LÓGICA DE DETENCIÓN CRÍTICA)
            if material_found:
                required_qty = self.requirements.get(material_found, 0)
                current_qty = self.inventory.get(material_found, 0)

                # **SOLO INCREMENTAR SI AÚN NO SE HA ALCANZADO LA CANTIDAD REQUERIDA**
                if required_qty > 0 and current_qty < required_qty:
                    self.inventory[material_found] = current_qty + 1
                    self.logger.info(f"EXTRAÍDO 1 de {material_found}. Total: {self.inventory[material_found]}/{required_qty}")
                else:
                    # El material fue encontrado pero ya se cumplió el requisito. Se desecha el bloque extra.
                    self.logger.debug(f"Material {material_found} ya cumplido ({current_qty}/{required_qty}). Bloque desechado.")
            else:
                # El bloque no es un material requerido. Se rompe y desecha (esto elimina el over-mining de 'dirt').
                self.logger.debug(f"Bloque minado ID:{current_block_id} no es material requerido ({list(self.requirements.keys())}). Bloque desechado.")
                
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
                self.logger.info("Decidiendo: Requisitos completados. Ejecutando acciones finales y transición a IDLE.")
                
                await self._complete_mining_cycle() 
                
                self.state = AgentState.IDLE 
            elif not self.mining_sector_locked:
                self.logger.info("Decidiendo: Adquiriendo lock de sector de mineria.")
                self.mining_sector_locked = True
                self.logger.info("Lock de sector adquirido. Minando...")

    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            
            # VISUALIZACIÓN: Mover el marcador a la posición de minería actual
            self._update_marker(self.mining_position) 
            
            # Ejecuta la estrategia de minería (Patrón Strategy)
            # Pasamos la nueva función _mine_current_block como callable
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position,
                # NUEVO CALLBACK: La estrategia llamará a esta función para romper bloques
                mine_block_callback=self._mine_current_block 
            )
            
            await self._publish_inventory_update(status="PENDING")
            
    # --- Control y Sincronización ---
    def release_locks(self):
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock de sector de minería liberado.")
            
    async def _complete_mining_cycle(self):
        """Acciones de finalización: publica el inventario final y libera locks."""
        # 1. Publicar el mensaje de éxito 
        await self._publish_inventory_update(status="SUCCESS")
        # 2. Liberar el lock de sector 
        self.release_locks()


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