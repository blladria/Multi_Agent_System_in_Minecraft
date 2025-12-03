# -*- coding: utf-8 -*-
import asyncio
import logging
from typing import Dict, Any, Tuple, List
from agents.base_agent import BaseAgent, AgentState
from mcpi import block
from mcpi.vec3 import Vec3
from datetime import datetime, timezone

# --- 1. MAPEO DE MATERIALES (Solo Primitivos) ---
# Limitado a lo que el MinerBot puede extraer directamente.
MATERIAL_MAP = {
    "cobblestone": block.COBBLESTONE.id, # Se obtiene minando piedra
    "dirt": block.DIRT.id,               # Se obtiene minando tierra
    "air": block.AIR.id
}

# --- 2. DEFINICIÓN DE PLANTILLAS (TEMPLATES) ---

# Diseño 1: Refugio Simple (3x3 - Muros de Cobblestone)
# Muros y suelo son Cobblestone (BOM: 24 Cobble, 0 Dirt). Puerta de 2 bloques.
TEMPLATE_SHELTER = [
    # Suelo (y=0)
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'),
    
    # Paredes (y=1) - Muros de Cobblestone
    (0,1,0,'cobblestone'), (1,1,0,'air'),         (2,1,0,'cobblestone'), # ENTRADA INFERIOR
    (0,1,1,'cobblestone'), (1,1,1,'air'),         (2,1,1,'cobblestone'), # Interior space
    (0,1,2,'cobblestone'), (1,1,2,'cobblestone'), (2,1,2,'cobblestone'),
    
    # Techo (y=2)
    (0,2,0,'cobblestone'), (1,2,0,'air'),         (2,2,0,'cobblestone'), # ENTRADA SUPERIOR
    (0,2,1,'cobblestone'), (1,2,1,'cobblestone'), (2,2,1,'cobblestone'),
    (0,2,2,'cobblestone'), (1,2,2,'cobblestone'), (2,2,2,'cobblestone'),
]

# Diseño 2: Torre de Vigilancia (100% Cobblestone) - 3x3
# Puerta de 2 bloques de alto en (1, y, 0)
TEMPLATE_TOWER = [
    # Base Sólida 3x3 (y=0)
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'),
    
    # Nivel 1 (Paredes) - y=1
    (0,1,0,'cobblestone'), (1,1,0,'air'),         (2,1,0,'cobblestone'), # ENTRADA INFERIOR (1,1,0)
    (0,1,1,'cobblestone'),                         (2,1,1,'cobblestone'),
    (0,1,2,'cobblestone'), (1,1,2,'cobblestone'), (2,1,2,'cobblestone'),
    (1,1,1,'air'), # Interior core access (Keep as air)
    
    # Nivel 2 (Paredes) - y=2
    (0,2,0,'cobblestone'), (1,2,0,'air'),         (2,2,0,'cobblestone'), # ENTRADA SUPERIOR (1,2,0)
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

# Diseño 3: Búnker de Almacenamiento (Walls: Dirt, Roof: Cobblestone) - 4x4
# Puerta de 2 bloques de alto en (1, y, 0)
TEMPLATE_BUNKER = [
    # Base 4x4 (Cobblestone) - y=0
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'), (3,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'), (3,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'), (3,0,2,'cobblestone'),
    (0,0,3,'cobblestone'), (1,0,3,'cobblestone'), (2,0,3,'cobblestone'), (3,0,3,'cobblestone'),

    # Nivel 1 (Paredes de Tierra) - y=1
    (0,1,0,'dirt'), (1,1,0,'air'), (2,1,0,'dirt'), (3,1,0,'dirt'), # ENTRADA INFERIOR
    (0,1,1,'dirt'),                                 (3,1,1,'dirt'),
    (0,1,2,'dirt'),                                 (3,1,2,'dirt'),
    (0,1,3,'dirt'), (1,1,3,'dirt'), (2,1,3,'dirt'), (3,1,3,'dirt'),

    # Nivel 2 (Paredes de Tierra) - y=2
    (0,2,0,'dirt'), (1,2,0,'air'), (2,2,0,'dirt'), (3,2,0,'dirt'), # ENTRADA SUPERIOR
    (0,2,1,'dirt'),                                 (3,2,1,'dirt'),
    (0,2,2,'dirt'),                                 (3,2,2,'dirt'),
    (0,2,3,'dirt'), (1,2,3,'dirt'), (2,2,3,'dirt'), (3,2,3,'dirt'),

    # Nivel 3 (Techo Sólido Piedra) - y=3
    (0,3,0,'cobblestone'), (1,3,0,'cobblestone'), (2,3,0,'cobblestone'), (3,3,0,'cobblestone'),
    (0,3,1,'cobblestone'), (1,3,1,'cobblestone'), (2,3,1,'cobblestone'), (3,3,1,'cobblestone'),
    (0,3,2,'cobblestone'), (1,3,2,'cobblestone'), (2,3,2,'cobblestone'), (3,3,2,'cobblestone'),
    (0,3,3,'cobblestone'), (1,3,3,'cobblestone'), (2,3,3,'cobblestone'), (3,3,3,'cobblestone'),
]

# Registro de Plantillas
BUILDING_TEMPLATES = {
    "simple_shelter": TEMPLATE_SHELTER,
    "watch_tower": TEMPLATE_TOWER,
    "storage_bunker": TEMPLATE_BUNKER
}

class BuilderBot(BaseAgent):
    """
    Agente BuilderBot:
    1. Recibe sugerencias del ExplorerBot.
    2. Calcula materiales necesarios (BOM).
    3. Construye la estructura bloque a bloque.
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
        
        # Marcador Verde (Lana Verde Lima = data 5)
        self._set_marker_properties(block.WOOL.id, 5)

    # --- Lógica de Inventario ---

    def _check_inventory(self) -> bool:
        """Verifica si tenemos todos los materiales necesarios."""
        if not self.required_bom:
            return False
        return all(self.current_inventory.get(material, 0) >= required_qty 
                   for material, required_qty in self.required_bom.items())
                   
    def _calculate_bom_for_structure(self) -> Dict[str, int]:
        """Calcula el BOM (Bill of Materials) basado en la plantilla ACTIVA."""
        bom = {}
        # Recorremos el diseño actual contando bloques
        for _, _, _, material_key in self.current_design:
            if material_key != 'air':
                bom[material_key] = bom.get(material_key, 0) + 1
        
        self.logger.info(f"BOM calculado para '{self.current_template_name}': {bom}")
        return bom

    # --- CICLO DE VIDA ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if not self.target_zone:
                self.logger.info("Esperando mapa del ExplorerBot.")
                self.state = AgentState.WAITING 
            elif not self._check_inventory():
                self.logger.info(f"Esperando materiales para '{self.current_template_name}'.")
                self.state = AgentState.WAITING 
            else:
                self.logger.info("Materiales listos y zona definida. Iniciando construcción.")
                self.is_building = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.is_building and self.target_zone:
            
            center_x = self.target_zone.get('x', 0)
            center_z = self.target_zone.get('z', 0)
            
            # Poner el marcador verde bien alto para avisar que vamos a construir
            try:
                y_surface = self.mc.getHeight(center_x, center_z)
                self._update_marker(Vec3(center_x, y_surface + 5, center_z))
            except Exception: pass
            
            # Quitamos marcador para no estorbar en la construcción
            self._clear_marker()
            
            # --- CONSTRUCCIÓN REAL ---
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            # Post-construcción
            if self.state not in (AgentState.PAUSED, AgentState.ERROR):
                self.is_building = False
                self.required_bom = {} 
                self.state = AgentState.IDLE
                await self._publish_build_complete()
                
                # --- FIX: Desaparecer el marcador del BuilderBot ---
                self._clear_marker() 
                # ----------------------------------------------------
            else:
                 self.logger.warning("Construcción interrumpida.")

    async def _build_structure(self, center_pos: Vec3):
        """Itera sobre la lista de bloques de la plantilla y los coloca en el mundo."""
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        try:
             start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception:
             start_y_surface = 65
        
        # Calcular el desplazamiento para centrar la estructura
        max_x = max([b[0] for b in self.current_design])
        max_z = max([b[2] for b in self.current_design])
        
        x_base = center_x - (max_x // 2)
        z_base = center_z - (max_z // 2)
        y_base = start_y_surface 
        
        self.logger.info(f"Construyendo '{self.current_template_name}' en base: ({x_base}, {y_base}, {z_base})")

        for dx, dy, dz, material_key in self.current_design:
            
            # Chequeo de seguridad por si nos pausan
            if self.state in (AgentState.PAUSED, AgentState.STOPPED):
                return 
            
            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            # Determinar ID del bloque
            block_id = block.AIR.id
            if material_key != 'air':
                if self.current_inventory.get(material_key, 0) > 0:
                    # Obtenemos el ID de Minecraft desde nuestro mapa
                    block_id = MATERIAL_MAP.get(material_key, block.COBBLESTONE.id)
                else:
                    self.logger.error(f"¡Material '{material_key}' agotado a mitad de obra! Pasando a WAITING.")
                    self.mc.postToChat(f"[Builder]  Material '{material_key}' agotado. Pausando construcción. Estado: WAITING.") # Nuevo mensaje de alerta
                    self.is_building = False
                    self.state = AgentState.WAITING 
                    return
            
            try:
                self.mc.setBlock(final_x, final_y, final_z, block_id)
                
                # Descontar del inventario
                if block_id != block.AIR.id:
                    self.current_inventory[material_key] -= 1
                
                # Pequeña pausa para ver la animación de construcción
                await asyncio.sleep(0.05) 

            except Exception as e:
                self.logger.error(f"Error poniendo bloque: {e}")
                self.mc.postToChat(f"[Builder]  ERROR fatal al construir. Estado: ERROR.") # Nuevo mensaje de error
                self.is_building = False
                self.state = AgentState.ERROR
                return

        self.logger.info(f"Construcción de '{self.current_template_name}' finalizada con éxito.")

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            params = payload.get("parameters", {})
            args = params.get('args', [])

            if command == 'build':
                # --- MEJORA DE FEEDBACK ---
                if self.state == AgentState.WAITING:
                     self.mc.postToChat(f"[Builder]  Recibido 'build', esperando materiales. Estado: WAITING.")
                self.state = AgentState.RUNNING
                self.logger.info(f"Comando 'build' recibido. Iniciando ciclo de construcción.")
                self.mc.postToChat(f"[Builder]  Iniciando construcción de '{self.current_template_name}'.")
                # --- FIN MEJORA ---
            
            # --- COMANDO MANUAL DE CAMBIO DE PLAN ---
            elif command == 'plan':
                if len(args) >= 2 and args[0] == 'set':
                    template_name = args[1].lower()
                    if template_name in BUILDING_TEMPLATES:
                        self.current_template_name = template_name
                        self.current_design = BUILDING_TEMPLATES[template_name]
                        self.required_bom = {} 
                        
                        # --- MEJORA DE FEEDBACK ---
                        self.logger.info(f"Comando 'plan set' recibido. Plantilla cambiada a: {template_name}")
                        self.mc.postToChat(f"[Builder]  Plantilla cambiada a: '{template_name}'. Calculando BOM...")
                        # --- FIN MEJORA ---
                        
                        # Si ya tenemos zona, actualizar BOM al instante
                        if self.target_zone:
                            self.required_bom = self._calculate_bom_for_structure()
                            await self._publish_requirements_to_miner()
                    else:
                        self.mc.postToChat(f"[Builder]  No conozco la plantilla '{template_name}'.")
                elif len(args) >= 1 and args[0] == 'list':
                     self.mc.postToChat(f"[Builder] Plantillas disponibles: {list(BUILDING_TEMPLATES.keys())}")
            
            elif command == 'pause': 
                self.handle_pause()
                self.logger.info(f"Comando 'pause' recibido. Estado: PAUSED.")
                self.mc.postToChat(f"[Builder]  Pausado. Estado: PAUSED.")
                
            elif command == 'resume': 
                self.handle_resume()
                self.logger.info(f"Comando 'resume' recibido. Estado: RUNNING.")
                self.mc.postToChat(f"[Builder]  Reanudado. Estado: RUNNING.")

            elif command == 'stop': 
                self.handle_stop()
                self.logger.info(f"Comando 'stop' recibido. Construcción detenida.")
                self.mc.postToChat(f"[Builder]  Detenido. Estado: STOPPED.")
                self._clear_marker()

            elif command == 'bom':
                 if self.required_bom:
                    await self._publish_requirements_to_miner()
                    # --- MEJORA DE FEEDBACK ---
                    req_str = ", ".join([f"{q} {m}" for m, q in self.required_bom.items()])
                    self.logger.info(f"Comando 'bom' recibido. Reenviando BOM: {req_str}")
                    self.mc.postToChat(f"[Builder]  BOM reenviado. Requisitos: {req_str}")
                    # --- FIN MEJORA ---


        elif msg_type == "map.v1":
            # --- RECEPCIÓN DEL MAPA Y DECISIÓN AUTOMÁTICA ---
            context = message.get("context", {})
            optimal_zone_center = payload.get("optimal_zone", {}).get("center", {})

            if context.get("target_zone"):
                 self.target_zone = context["target_zone"]
            elif optimal_zone_center:
                 self.target_zone = optimal_zone_center

            # Leer sugerencia del Explorer
            suggested = payload.get("suggested_template")
            terrain_var = payload.get("terrain_variance", 0.0)
            
            if suggested and suggested in BUILDING_TEMPLATES:
                self.current_template_name = suggested
                self.current_design = BUILDING_TEMPLATES[suggested]
                self.logger.info(f"Aceptando sugerencia del Explorer: {suggested} (Var: {terrain_var:.2f})")
                self.mc.postToChat(f"[Builder]  Acepto sugerencia: '{suggested}'.")
            
            # Calcular BOM y pedir materiales
            self.required_bom = self._calculate_bom_for_structure() 
            if self.required_bom:
                await self._publish_requirements_to_miner()
            
            # Decidir si empezamos o esperamos
            if self._check_inventory():
                 self.state = AgentState.RUNNING
            else:
                 self.state = AgentState.WAITING

        elif msg_type == "inventory.v1":
            # Actualización de materiales desde el MinerBot
            new_inventory = payload.get("collected_materials", {})
            self.current_inventory.update(new_inventory)
            self.logger.info(f"Inventario actualizado. Vol: {payload.get('total_volume')}")
            
            if self.state == AgentState.WAITING and self._check_inventory():
                self.state = AgentState.RUNNING
                self.mc.postToChat(f"[Builder]  Materiales recibidos. Iniciando construcción. Estado: RUNNING.")
                
    async def _publish_requirements_to_miner(self):
        requirements_message = {
            "type": "materials.requirements.v1",
            "source": self.agent_id,
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": self.required_bom,
            "status": "PENDING",
            "context": {"target_zone": self.target_zone}
        }
        await self.broker.publish(requirements_message)
        self.logger.info(f"Enviando BOM a MinerBot: {self.required_bom}")
    
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
        self.logger.info("Construcción completada publicada.")
        self.mc.postToChat(f"[Builder]  Construcción de '{self.current_template_name}' finalizada con éxito.")