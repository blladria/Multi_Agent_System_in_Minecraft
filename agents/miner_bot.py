# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Callable
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3

# Diccionario de materiales para simulación (material: ID de bloque MC)
MATERIAL_MAP = {
    "wood": 17,
    "stone": 1,
    "cobblestone": 4,
    "diamond_ore": 56
}

# --- Estrategias de Minería (Programación Reflexiva en el diseño del Manager) ---
# Aquí se definen las funciones/métodos que representan las estrategias.

class MinerBot(BaseAgent):
    """
    Agente responsable de la extracción y colección de materiales.
    Soporta múltiples estrategias de minería.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        self.current_strategy_name = "vertical"
        self.current_strategy_func: Callable = self._vertical_search # Estrategia inicial
        self.mining_position: Vec3 = Vec3(0, 60, 0)
        self.mining_sector_locked = False # Simulación de bloqueo espacial
        
        # Mapa de estrategias disponibles (Reflexivo, usando el nombre del método)
        self.strategy_map = {
            "vertical": self._vertical_search,
            "grid": self._grid_search,
            # "vein": self._vein_search # Se implementaría después
        }

    # --- Ciclo Perceive-Decide-Act ---

    async def perceive(self):
        """
        Escucha el MessageBroker, principalmente para 'materials.requirements.v1' 
        y comandos de control.
        """
        # Consume mensajes de la cola de forma no bloqueante
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        """
        Determina si los requisitos están completos o si debe continuar minando.
        """
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                self.logger.info("Decidiendo: Requisitos completados. Publicando inventario final.")
                # Cambia a IDLE para forzar la acción de publicar el inventario final
                self.state = AgentState.IDLE 
            elif not self.mining_sector_locked:
                self.logger.info("Decidiendo: Adquiriendo lock de sector de mineria.")
                # En un sistema real, aquí intentaría adquirir un lock global (x, z)
                self.mining_sector_locked = True
                self.logger.info("Lock de sector adquirido. Minando...")

    async def act(self):
        """
        Ejecuta la estrategia de minería actual o publica el inventario final.
        """
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            # Ejecuta la función de estrategia seleccionada (Strategy Pattern)
            await self.current_strategy_func()
            
            # Publica el progreso periódicamente
            await self._publish_inventory_update(status="PENDING")
            
        elif self.state == AgentState.IDLE and self._check_requirements_fulfilled():
            # Si se acaba de cumplir el requisito, publica el mensaje final
            await self._publish_inventory_update(status="SUCCESS")
            
            # Libera el lock y vuelve a IDLE (para esperar el siguiente BOM)
            self.release_locks()
            self.state = AgentState.IDLE

    # --- Implementación de Estrategias de Minería ---

    async def _vertical_search(self):
        """Simula la minería vertical (hacia abajo)."""
        self.logger.debug("Estrategia: Ejecutando Búsqueda Vertical.")
        
        # Simula la minería de un bloque
        self.mining_position.y -= 1
        
        # Simula la extracción de materiales necesarios
        await self._simulate_extraction(volume=5)
        
        # Simula el tiempo que toma minar
        await asyncio.sleep(1)

    async def _grid_search(self):
        """Simula la minería en patrón de rejilla (área cúbica)."""
        self.logger.debug("Estrategia: Ejecutando Búsqueda en Rejilla.")
        
        # Simula moverse lateralmente y extraer
        self.mining_position.x += 1
        if self.mining_position.x > 10:
             self.mining_position.x = 0
             self.mining_position.z += 1
             
        await self._simulate_extraction(volume=8)
        
        await asyncio.sleep(0.7)

    async def _simulate_extraction(self, volume: int):
        """Simula la extracción de N bloques, priorizando los requeridos."""
        
        blocks_extracted = 0
        
        # Prioriza los materiales que se necesitan
        for material, required_qty in self.requirements.items():
            if self.inventory[material] < required_qty:
                qty_to_mine = min(volume - blocks_extracted, required_qty - self.inventory[material])
                
                if qty_to_mine > 0:
                    self.inventory[material] += qty_to_mine
                    blocks_extracted += qty_to_mine
                    self.logger.debug(f"Extraidos {qty_to_mine} de {material}. Total: {self.inventory[material]}")
                    
        # Si aún queda volumen, se extrae piedra (simulación de descarte)
        if volume > blocks_extracted:
            self.inventory["stone"] += (volume - blocks_extracted)

    # --- Control y Sincronización ---

    def release_locks(self):
        """Libera el lock de sector cuando el agente finaliza o falla."""
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock de sector de minería liberado.")

    def _check_requirements_fulfilled(self) -> bool:
        """Verifica si el inventario actual satisface los requisitos del BuilderBot."""
        if not self.requirements:
            return False
            
        for material, required_qty in self.requirements.items():
            if self.inventory.get(material, 0) < required_qty:
                return False
        return True

    # --- Manejo de Mensajes (Usa if/elif/else) ---
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Procesa mensajes de control (command.*.v1) y de requisitos (materials.requirements.v1)."""
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            
            if command == 'start' or command == 'fulfill':
                # Inicia el ciclo de minería para cumplir los requisitos
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else:
                    self.state = AgentState.IDLE
                    self.mc.postToChat(f"{self.agent_id}: Requisitos ya cumplidos.")
                    
            elif command == 'set':
                self._parse_set_strategy(payload.get("parameters", {}))
            
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
            
        elif msg_type == "materials.requirements.v1":
            # Recibe el Bill of Materials (BOM) del BuilderBot
            self.requirements = payload
            self.logger.info(f"Requisitos de materiales recibidos: {self.requirements}")
            
            # Si estaba IDLE, debe empezar a minar (pasar a RUNNING en el siguiente decide)
            if self.state == AgentState.IDLE:
                 self.state = AgentState.RUNNING


    def _parse_set_strategy(self, params: Dict[str, Any]):
        """Parsea el comando '/miner set strategy <vertical|grid|vein>'."""
        args = params.get('args', [])
        
        if len(args) >= 2 and args[0] == 'strategy':
            new_strategy = args[1].lower()
            if new_strategy in self.strategy_map:
                self.current_strategy_name = new_strategy
                self.current_strategy_func = self.strategy_map[new_strategy]
                self.logger.info(f"Estrategia de mineria cambiada a: {new_strategy}")
            else:
                self.mc.postToChat(f"ERROR: Estrategia '{new_strategy}' no reconocida.")

    # --- Publicación de Inventario ---

    async def _publish_inventory_update(self, status: str):
        """Publica el mensaje inventory.v1 al BuilderBot."""
        
        # Calcula el volumen total simulado
        total_volume = sum(self.inventory.values())

        inventory_message = {
            "type": "inventory.v1",
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "payload": {
                "collected_materials": self.inventory,
                "total_volume": total_volume
            },
            "status": status,
            "context": {"required_bom": self.requirements}
        }
        
        await self.broker.publish(inventory_message)
        self.logger.info(f"Inventario ({status}) publicado. Volumen total: {total_volume}")