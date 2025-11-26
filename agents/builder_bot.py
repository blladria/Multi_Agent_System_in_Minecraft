# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any
from agents.base_agent import BaseAgent, AgentState
from mcpi import block # Necesario para la construcción
from mcpi.vec3 import Vec3

# Diccionario de plantillas de construcción simuladas
BUILDING_TEMPLATES = {
    "shelter_basic": {
        "materials": {"WOOD_PLANKS": 64, "STONE": 32, "GLASS": 4},
        "size": (5, 3, 5), # (x, y, z)
        "description": "Un refugio simple de 5x3x5"
    },
    "tower_watch": {
        "materials": {"COBBLESTONE": 128, "WOOD": 16, "LADDER": 8},
        "size": (3, 10, 3),
        "description": "Una torre de vigilancia de 3x10x3"
    }
}

class BuilderBot(BaseAgent):
    """
    Agente responsable de construir estructuras basándose en los datos del ExplorerBot
    y los materiales suministrados por el MinerBot.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.terrain_data: Dict[str, Any] = {}
        self.current_plan: Dict[str, Any] = BUILDING_TEMPLATES["shelter_basic"]
        self.required_bom: Dict[str, int] = {}
        self.current_inventory: Dict[str, int] = {}
        self.construction_position: Vec3 = None
        
        self.build_step = 0
        self.is_planning = False
        self.is_building = False

    async def perceive(self):
        """
        Escucha mensajes (map.v1, inventory.v1, comandos) y actualiza su estado.
        """
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        """
        Decide la siguiente acción: Planificar, esperar materiales o construir.
        """
        if self.state == AgentState.RUNNING and self.is_building:
            # Continuar la construcción (la acción se ejecuta en act)
            return

        if self.state == AgentState.WAITING:
            # Verificar si los materiales son suficientes (comparando BOM con inventario)
            if self._check_materials_sufficient():
                self.logger.info("Decidiendo: Materiales recibidos. Iniciando construccion.")
                self.is_building = True
                self.state = AgentState.RUNNING
            else:
                # Si no es suficiente, permanece en WAITING.
                return

        if self.state == AgentState.RUNNING and self.terrain_data and not self.is_planning:
            # Recibió mapa y necesita planificar el BOM
            self.logger.info("Decidiendo: Mapa recibido. Calculando BOM...")
            self.is_planning = True
            # El estado se mantiene en RUNNING para ejecutar el ACT

    async def act(self):
        """
        Ejecuta la planificación, publica el BOM, o ejecuta la construcción.
        """
        if self.state == AgentState.RUNNING:
            
            if self.is_planning:
                # Acción 1: Calcular y Publicar BOM
                self.required_bom = self._calculate_bom(self.current_plan)
                await self._publish_materials_requirements()
                
                # TRANSICIÓN CRÍTICA DE FLUJO: Pasar a WAITING para esperar al MinerBot
                self.is_planning = False
                self.state = AgentState.WAITING
                
            elif self.is_building:
                # Acción 2: Construir
                await self._execute_build_step()
                if self.build_step >= self.current_plan["size"][1]: # 'size'[1] es la altura
                    self.logger.info("CONSTRUCCION FINALIZADA.")
                    self.is_building = False
                    self.build_step = 0
                    self.state = AgentState.IDLE
                    
                # Simula el tiempo de construcción entre capas
                await asyncio.sleep(0.5)

    # --- Lógica de Comunicación y Planificación ---

    def _calculate_bom(self, plan: Dict[str, Any]) -> Dict[str, int]:
        """Calcula la Lista de Materiales para el plan actual."""
        self.logger.info(f"Calculando BOM para '{plan['description']}'.")
        return plan["materials"]

    def _check_materials_sufficient(self) -> bool:
        """Verifica si el inventario actual cumple con el BOM requerido."""
        if not self.required_bom:
            return False
            
        is_sufficient = True
        for material, required_qty in self.required_bom.items():
            current_qty = self.current_inventory.get(material, 0)
            if current_qty < required_qty:
                is_sufficient = False
                break
        
        self.logger.info(f"Estado de materiales: Requeridos={self.required_bom}, Actual={self.current_inventory}")
        return is_sufficient

    async def _publish_materials_requirements(self):
        """Publica el mensaje materials.requirements.v1 a MinerBot."""
        bom_message = {
            "type": "materials.requirements.v1",
            "source": self.agent_id,
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": self.required_bom,
            "status": "PENDING",
            "context": {"plan_name": self.current_plan["description"]}
        }
        await self.broker.publish(bom_message)
        self.logger.info(f"BOM publicado a MinerBot. Materiales requeridos: {self.required_bom}")

    async def _execute_build_step(self):
        """Coloca una capa de bloques en Minecraft."""
        if not self.construction_position:
            zone = self.terrain_data.get('optimal_zone', {}).get('center', {})
            x, y, z = zone.get('x', 0), zone.get('y_avg', 0), zone.get('z', 0)
            self.construction_position = Vec3(int(x), int(y) + 1, int(z)) 
        
        current_y = int(self.construction_position.y) + self.build_step
        size_x, size_y, size_z = self.current_plan["size"]
        
        # Simulación: Construye el contorno de un rectángulo en la capa actual
        mat_id = getattr(block, list(self.required_bom.keys())[0], block.STONE).id

        # Coloca bloques en las 4 esquinas de la capa
        self.mc.setBlock(self.construction_position.x, current_y, self.construction_position.z, mat_id)
        self.mc.setBlock(self.construction_position.x + size_x, current_y, self.construction_position.z, mat_id)
        self.mc.setBlock(self.construction_position.x, current_y, self.construction_position.z + size_z, mat_id)
        self.mc.setBlock(self.construction_position.x + size_x, current_y, self.construction_position.z + size_z, mat_id)
        
        self.logger.info(f"Construyendo capa {self.build_step + 1}/{size_y} en Y={current_y}.")
        self.build_step += 1

    # --- Manejo de Mensajes (CORREGIDO) ---
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Procesa los mensajes de control y de datos recibidos."""
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'plan':
                self._parse_plan_command(payload.get("parameters", {}))
                
            elif command == 'build':
                # Verifica si puede empezar a construir O si debe esperar
                if self._check_materials_sufficient():
                     self.state = AgentState.RUNNING # Puede iniciar la construcción
                else:
                     self.state = AgentState.WAITING # No puede iniciar, debe esperar los materiales
                     self.logger.warning("No se puede iniciar la construccion: Materiales insuficientes.")
            
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop() 
        
        elif msg_type == "map.v1":
            self.terrain_data = payload
            # CORRECCIÓN: Transicionar a RUNNING al recibir el mapa
            if self.state == AgentState.IDLE:
                self.is_planning = True 
                self.state = AgentState.RUNNING
                self.logger.info("Datos de mapa recibidos. Iniciando planificación.")

        elif msg_type == "inventory.v1":
            # Actualiza el inventario local con los datos del MinerBot
            self.current_inventory = payload.get("collected_materials", {})
            # El estado WAITING será reevaluado en el siguiente ciclo DECIDE
            self.logger.info("Inventario actualizado.")

    def _parse_plan_command(self, params: Dict[str, Any]):
        """Parsea el comando '/builder plan set <template>'."""
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'set' and args[1] in BUILDING_TEMPLATES:
            self.current_plan = BUILDING_TEMPLATES[args[1]]
            self.logger.info(f"Plan de construccion cambiado a: {self.current_plan['description']}")
            self.terrain_data = {} 
        else:
            self.mc.postToChat("ERROR: /builder plan set <template> invalido.")