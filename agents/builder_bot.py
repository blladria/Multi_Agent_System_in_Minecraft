# -*- coding: utf-8 -*-
import asyncio
import logging
from functools import reduce  # NECESARIO PARA PROGRAMACIÓN FUNCIONAL
from typing import Dict, Any, Tuple, List
from agents.base_agent import BaseAgent, AgentState
from mcpi import block
from mcpi.vec3 import Vec3
from datetime import datetime, timezone

# --- 1. MAPEO DE MATERIALES (Solo Primitivos) ---
MATERIAL_MAP = {
    "cobblestone": block.COBBLESTONE.id, 
    "dirt": block.DIRT.id,               
    "air": block.AIR.id
}

# --- 2. DEFINICIÓN DE PLANTILLAS (TEMPLATES) ---

TEMPLATE_SHELTER = [
    # Suelo (y=0)
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'),
    
    # Paredes (y=1)
    (0,1,0,'cobblestone'), (1,1,0,'air'),         (2,1,0,'cobblestone'), 
    (0,1,1,'cobblestone'), (1,1,1,'air'),         (2,1,1,'cobblestone'), 
    (0,1,2,'cobblestone'), (1,1,2,'cobblestone'), (2,1,2,'cobblestone'),
    
    # Techo (y=2)
    (0,2,0,'cobblestone'), (1,2,0,'air'),         (2,2,0,'cobblestone'), 
    (0,2,1,'cobblestone'), (1,2,1,'cobblestone'), (2,2,1,'cobblestone'),
    (0,2,2,'cobblestone'), (1,2,2,'cobblestone'), (2,2,2,'cobblestone'),
]

TEMPLATE_TOWER = [
    # Base Sólida 3x3 (y=0)
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'),
    
    # Nivel 1 (Paredes) - y=1
    (0,1,0,'cobblestone'), (1,1,0,'air'),         (2,1,0,'cobblestone'), 
    (0,1,1,'cobblestone'),                         (2,1,1,'cobblestone'),
    (0,1,2,'cobblestone'), (1,1,2,'cobblestone'), (2,1,2,'cobblestone'),
    (1,1,1,'air'), 
    
    # Nivel 2 (Paredes) - y=2
    (0,2,0,'cobblestone'), (1,2,0,'air'),         (2,2,0,'cobblestone'), 
    (0,2,1,'cobblestone'),                         (2,2,1,'cobblestone'),
    (0,2,2,'cobblestone'), (1,2,2,'cobblestone'), (2,2,2,'cobblestone'),

    # Nivel 3 (Paredes) - y=3
    (0,3,0,'cobblestone'), (1,3,0,'cobblestone'), (2,3,0,'cobblestone'),
    (0,3,1,'cobblestone'),                         (2,3,1,'cobblestone'),
    (0,3,2,'cobblestone'), (1,3,2,'cobblestone'), (2,3,2,'cobblestone'),
    
    # Nivel 4 (Almenas) - y=4
    (0,4,0,'cobblestone'), (1,4,0,'air'),         (2,4,0,'cobblestone'),
    (0,4,1,'air'),         (1,4,1,'air'),         (2,4,1,'air'), 
    (0,4,2,'cobblestone'), (1,4,2,'air'),         (2,4,2,'cobblestone'),
]

TEMPLATE_BUNKER = [
    # Base 4x4 (Cobblestone) - y=0
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'), (3,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'), (3,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'), (3,0,2,'cobblestone'),
    (0,0,3,'cobblestone'), (1,0,3,'cobblestone'), (2,0,3,'cobblestone'), (3,0,3,'cobblestone'),

    # Nivel 1 (Paredes de Tierra) - y=1
    (0,1,0,'dirt'), (1,1,0,'air'), (2,1,0,'dirt'), (3,1,0,'dirt'), 
    (0,1,1,'dirt'),                                 (3,1,1,'dirt'),
    (0,1,2,'dirt'),                                 (3,1,2,'dirt'),
    (0,1,3,'dirt'), (1,1,3,'dirt'), (2,1,3,'dirt'), (3,1,3,'dirt'),

    # Nivel 2 (Paredes de Tierra) - y=2
    (0,2,0,'dirt'), (1,2,0,'air'), (2,2,0,'dirt'), (3,2,0,'dirt'), 
    (0,2,1,'dirt'),                                 (3,2,1,'dirt'),
    (0,2,2,'dirt'),                                 (3,2,2,'dirt'),
    (0,2,3,'dirt'), (1,2,3,'dirt'), (2,2,3,'dirt'), (3,2,3,'dirt'),

    # Nivel 3 (Techo Sólido Piedra) - y=3
    (0,3,0,'cobblestone'), (1,3,0,'cobblestone'), (2,3,0,'cobblestone'), (3,3,0,'cobblestone'),
    (0,3,1,'cobblestone'), (1,3,1,'cobblestone'), (2,3,1,'cobblestone'), (3,3,1,'cobblestone'),
    (0,3,2,'cobblestone'), (1,3,2,'cobblestone'), (2,3,2,'cobblestone'), (3,3,2,'cobblestone'),
    (0,3,3,'cobblestone'), (1,3,3,'cobblestone'), (2,3,3,'cobblestone'), (3,3,3,'cobblestone'),
]

BUILDING_TEMPLATES = {
    "simple_shelter": TEMPLATE_SHELTER,
    "watch_tower": TEMPLATE_TOWER,
    "storage_bunker": TEMPLATE_BUNKER
}

class BuilderBot(BaseAgent):
    """
    Agente BuilderBot:
    Refactorizado para cumplir estrictamente con paradigmas funcionales (Map, Filter, Reduce).
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)

        self.required_bom: Dict[str, int] = {}
        self.current_inventory: Dict[str, int] = {}
        self.target_zone: Dict[str, int] = {}
        self.is_building = False 
        
        # --- GESTIÓN DE PLANTILLAS ---
        self.current_template_name = "simple_shelter" # Default
        self.current_design = BUILDING_TEMPLATES[self.current_template_name]
        
        # NUEVO: Bandera para saber si el usuario ha forzado una plantilla
        self.manual_override = False 
        
        self._set_marker_properties(block.WOOL.id, 5)

    # --- Lógica de Inventario (Funcional) ---

    def _check_inventory(self) -> bool:
        """Verifica si tenemos todos los materiales necesarios usando filter."""
        if not self.required_bom:
            return False
        
        # FUNCIONAL: Filtramos los materiales que NO cumplen el requisito
        insufficient_materials = list(filter(
            lambda item: self.current_inventory.get(item[0], 0) < item[1],
            self.required_bom.items()
        ))
        
        # Si la lista de insuficientes está vacía, tenemos todo
        return len(insufficient_materials) == 0
                   
    def _calculate_bom_for_structure(self) -> Dict[str, int]:
        """Calcula el BOM usando reduce."""
        return self._reduce_design_to_bom(self.current_design)
        
    def _calculate_bom_for_specific_design(self, design_list) -> Dict[str, int]:
        """Calcula el BOM para una lista dada usando reduce."""
        return self._reduce_design_to_bom(design_list)

    def _reduce_design_to_bom(self, design_list) -> Dict[str, int]:
        """Helper funcional puro para reducir una lista de bloques a un diccionario de conteo."""
        def bom_reducer(acc, block_tuple):
            material_key = block_tuple[3]
            if material_key != 'air':
                acc[material_key] = acc.get(material_key, 0) + 1
            return acc
            
        # FUNCIONAL: Uso de reduce
        bom = reduce(bom_reducer, design_list, {})
        self.logger.info(f"BOM calculado (funcional): {bom}")
        return bom

    # --- CICLO DE VIDA ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if not self.target_zone:
                self.logger.info("Esperando zona de construccion (Mapa o Jugador).")
                self.state = AgentState.WAITING 
            elif not self._check_inventory():
                self.logger.info(f"Esperando materiales para '{self.current_template_name}'.")
                self.state = AgentState.WAITING 
            else:
                self.logger.info("Materiales listos y zona definida. Iniciando construccion.")
                self.is_building = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.is_building and self.target_zone:
            
            center_x = self.target_zone.get('x', 0)
            center_z = self.target_zone.get('z', 0)
            
            try:
                y_surface = self.mc.getHeight(center_x, center_z)
                self._update_marker(Vec3(center_x, y_surface + 5, center_z))
            except Exception: pass
            
            self._clear_marker()
            
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            if self.state not in (AgentState.PAUSED, AgentState.ERROR):
                self.is_building = False
                self.required_bom = {} 
                self.state = AgentState.IDLE
                self.manual_override = False # Resetear override al terminar
                await self._publish_build_complete()
                self._clear_marker() 
            else:
                 self.logger.warning("Construccion interrumpida.")

    async def _build_structure(self, center_pos: Vec3):
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        try:
             start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception:
             start_y_surface = 65
        
        # FUNCIONAL: Uso de map para obtener coordenadas X y Z
        x_coords = list(map(lambda b: b[0], self.current_design))
        z_coords = list(map(lambda b: b[2], self.current_design))
        
        max_x = max(x_coords)
        max_z = max(z_coords)
        
        x_base = center_x - (max_x // 2)
        z_base = center_z - (max_z // 2)
        y_base = start_y_surface 
        
        self.logger.info(f"Construyendo '{self.current_template_name}' en base: ({x_base}, {y_base}, {z_base})")

        for dx, dy, dz, material_key in self.current_design:
            
            if self.state in (AgentState.PAUSED, AgentState.STOPPED):
                return 
            
            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            block_id = block.AIR.id
            if material_key != 'air':
                if self.current_inventory.get(material_key, 0) > 0:
                    block_id = MATERIAL_MAP.get(material_key, block.COBBLESTONE.id)
                else:
                    self.logger.error(f"Material '{material_key}' agotado a mitad de obra! Pasando a WAITING.")
                    self.mc.postToChat(f"[Builder] Material '{material_key}' agotado. Pausando construccion. Estado: WAITING.")
                    self.is_building = False
                    self.state = AgentState.WAITING 
                    return
            
            try:
                self.mc.setBlock(final_x, final_y, final_z, block_id)
                
                if block_id != block.AIR.id:
                    self.current_inventory[material_key] -= 1
                
                await asyncio.sleep(0.05) 

            except Exception as e:
                self.logger.error(f"Error poniendo bloque: {e}")
                self.mc.postToChat(f"[Builder] ERROR fatal al construir. Estado: ERROR.")
                self.is_building = False
                self.state = AgentState.ERROR
                return

        self.logger.info(f"Construccion de '{self.current_template_name}' finalizada con exito.")

    async def _publish_status(self):
        """Genera y envía un mensaje de estado detallado usando map y filter."""
        
        req_bom_str = []
        is_ready = True
        
        if self.required_bom:
            # FUNCIONAL: Map para crear las strings de estado
            req_bom_str = list(map(
                lambda item: f"{self.current_inventory.get(item[0], 0)}/{item[1]} {item[0]}",
                self.required_bom.items()
            ))
            
            # FUNCIONAL: Filter para chequear si hay insuficientes
            insufficient = list(filter(
                lambda item: self.current_inventory.get(item[0], 0) < item[1],
                self.required_bom.items()
            ))
            is_ready = len(insufficient) == 0
        
        req_status = "LISTO" if is_ready and self.required_bom else "PENDIENTE"
        req_str = ", ".join(req_bom_str) if req_bom_str else "Ninguno"

        zone_str = f"({self.target_zone.get('x', '?')}, {self.target_zone.get('z', '?')})"
        build_status = "SI" if self.is_building else "NO"
        
        override_str = " (MANUAL)" if self.manual_override else ""

        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | Plantilla: {self.current_template_name.upper()}{override_str} | "
            f"Zona: {zone_str}\n"
            f"  > Requisitos ({req_status}): {req_str}\n"
            f"  > Construyendo: {build_status}"
        )
        
        self.logger.info(f"Comando 'status' recibido. Reportando: {self.state.name}")
        try: self.mc.postToChat(status_message)
        except Exception: pass


    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            params = payload.get("parameters", {})
            args = params.get('args', [])

            if command == 'build':
                try:
                    player_pos = self.mc.player.getTilePos()
                    self.target_zone = {"x": player_pos.x, "z": player_pos.z}
                    self.logger.info(f"Comando 'build' manual. Zona establecida en jugador: {self.target_zone}")
                except Exception as e:
                    self.logger.warning(f"No se pudo obtener la posición del jugador: {e}")
                    if not self.target_zone:
                         self.mc.postToChat("[Builder] Error: No tengo mapa y no puedo localizarte.")
                         return

                self.state = AgentState.RUNNING
                
                if self._check_inventory():
                    self.is_building = True
                    self.mc.postToChat(f"[Builder] Iniciando construccion de '{self.current_template_name}' en tu posicion.")
                else:
                    self.mc.postToChat(f"[Builder] Recibido 'build', pero faltan materiales. Esperando... Usa '/miner fulfill'.")
                    self.state = AgentState.WAITING
            
            elif command == 'plan':
                if len(args) >= 2 and args[0] == 'set':
                    template_name = args[1].lower()
                    if template_name in BUILDING_TEMPLATES:
                        self.current_template_name = template_name
                        self.current_design = BUILDING_TEMPLATES[template_name]
                        
                        # CORRECCIÓN: Activamos el override manual
                        self.manual_override = True 
                        
                        self.required_bom = self._calculate_bom_for_structure()
                        
                        await self._publish_requirements_to_miner(status="ACKNOWLEDGED")
                        
                        # FUNCIONAL: Map para formatear salida
                        req_str = ", ".join(map(lambda item: f"{item[1]} {item[0]}", self.required_bom.items()))
                        
                        self.logger.info(f"Plan fijado: {template_name}. BOM: {req_str}")
                        self.mc.postToChat(f"[Builder] Plan fijado MANUALMENTE a '{template_name}'. Requisitos: {req_str}. Listo para '/miner fulfill'.")

                    else:
                        self.mc.postToChat(f"[Builder] No conozco la plantilla '{template_name}'.")
                
                elif len(args) >= 1 and args[0] == 'list':
                     self.mc.postToChat("[Builder] Plantillas disponibles:")
                     for name, design in BUILDING_TEMPLATES.items():
                         bom = self._calculate_bom_for_specific_design(design)
                         # FUNCIONAL: Map para formatear salida
                         bom_str = ", ".join(map(lambda item: f"{item[1]} {item[0]}", bom.items()))
                         self.mc.postToChat(f" - {name}: [{bom_str}]")
            
            elif command == 'pause': 
                self.handle_pause()
                self.mc.postToChat(f"[Builder] Pausado.")
                
            elif command == 'resume': 
                self.handle_resume()
                self.mc.postToChat(f"[Builder] Reanudado.")

            elif command == 'stop': 
                self.handle_stop()
                self.mc.postToChat(f"[Builder] Detenido.")
                self._clear_marker()

            elif command == 'bom':
                 self.required_bom = self._calculate_bom_for_structure()
                 req_str = ", ".join(map(lambda item: f"{item[1]} {item[0]}", self.required_bom.items()))
                 if self.required_bom:
                    await self._publish_requirements_to_miner(status="ACKNOWLEDGED")
                    self.mc.postToChat(f"[Builder] BOM actual: {req_str}")
                 else:
                     self.mc.postToChat(f"[Builder] La plantilla actual no requiere materiales.")

            elif command == 'status':
                await self._publish_status()

        elif msg_type == "map.v1":
            context = message.get("context", {})
            optimal_zone_center = payload.get("optimal_zone", {}).get("center", {})

            if context.get("target_zone"):
                 self.target_zone = context["target_zone"]
            elif optimal_zone_center:
                 self.target_zone = optimal_zone_center

            suggested = payload.get("suggested_template")
            
            # CORRECCIÓN: Solo aceptamos la sugerencia si NO hay override manual
            if not self.manual_override:
                if suggested and suggested in BUILDING_TEMPLATES:
                    self.current_template_name = suggested
                    self.current_design = BUILDING_TEMPLATES[suggested]
                    self.mc.postToChat(f"[Builder] Acepto sugerencia del Explorer: '{suggested}'.")
            else:
                 self.mc.postToChat(f"[Builder] Ignoro sugerencia del Explorer ('{suggested}') porque hay plan manual: '{self.current_template_name}'.")
            
            self.required_bom = self._calculate_bom_for_structure() 
            if self.required_bom:
                await self._publish_requirements_to_miner(status="PENDING")
            
            if self._check_inventory():
                 self.state = AgentState.RUNNING
            else:
                 self.state = AgentState.WAITING

        elif msg_type == "inventory.v1":
            new_inventory = payload.get("collected_materials", {})
            self.current_inventory.update(new_inventory)
            self.logger.info(f"Inventario actualizado.")
            
            if self.state == AgentState.WAITING and self._check_inventory():
                if self.target_zone:
                    self.state = AgentState.RUNNING
                    self.is_building = True
                    self.mc.postToChat(f"[Builder] Materiales recibidos. Iniciando construccion.")
                else:
                    self.mc.postToChat(f"[Builder] Materiales recibidos. Usa '/builder build' para construir aqui.")
                
    async def _publish_requirements_to_miner(self, status: str = "PENDING"):
        requirements_message = {
            "type": "materials.requirements.v1",
            "source": self.agent_id,
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": self.required_bom,
            "status": status, 
            "context": {"target_zone": self.target_zone}
        }
        await self.broker.publish(requirements_message)
        self.logger.info(f"Enviando BOM a MinerBot (Estado: {status}): {self.required_bom}")
    
    async def _publish_build_complete(self):
        build_message = {
            "type": "build.status.v1",
            "source": self.agent_id,
            "target": "Manager",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {"status": "SUCCESS", "location": self.target_zone},
            "status": "SUCCESS"
        }
        await self.broker.publish(build_message)
        self.mc.postToChat(f"[Builder] Construccion de '{self.current_template_name}' finalizada.")