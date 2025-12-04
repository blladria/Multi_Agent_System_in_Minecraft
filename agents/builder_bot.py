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
TEMPLATE_SHELTER = [
    # Suelo (y=0)
    (0,0,0,'cobblestone'), (1,0,0,'cobblestone'), (2,0,0,'cobblestone'),
    (0,0,1,'cobblestone'), (1,0,1,'cobblestone'), (2,0,1,'cobblestone'),
    (0,0,2,'cobblestone'), (1,0,2,'cobblestone'), (2,0,2,'cobblestone'),
    
    # Paredes (y=1)
    (0,1,0,'cobblestone'), (1,1,0,'air'),         (2,1,0,'cobblestone'), # ENTRADA
    (0,1,1,'cobblestone'), (1,1,1,'air'),         (2,1,1,'cobblestone'), 
    (0,1,2,'cobblestone'), (1,1,2,'cobblestone'), (2,1,2,'cobblestone'),
    
    # Techo (y=2)
    (0,2,0,'cobblestone'), (1,2,0,'air'),         (2,2,0,'cobblestone'), # ENTRADA SUPERIOR
    (0,2,1,'cobblestone'), (1,2,1,'cobblestone'), (2,2,1,'cobblestone'),
    (0,2,2,'cobblestone'), (1,2,2,'cobblestone'), (2,2,2,'cobblestone'),
]

# Diseño 2: Torre de Vigilancia (100% Cobblestone) - 3x3
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

# Diseño 3: Búnker de Almacenamiento (Walls: Dirt, Roof: Cobblestone) - 4x4
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

# Registro de Plantillas
BUILDING_TEMPLATES = {
    "simple_shelter": TEMPLATE_SHELTER,
    "watch_tower": TEMPLATE_TOWER,
    "storage_bunker": TEMPLATE_BUNKER
}

class BuilderBot(BaseAgent):
    """
    Agente BuilderBot:
    1. Recibe sugerencias del ExplorerBot o comandos manuales.
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
            # Si no hay BOM definido, asumimos que no necesitamos nada (o no estamos listos)
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
        
    def _calculate_bom_for_specific_design(self, design_list) -> Dict[str, int]:
        """Calcula el BOM para una lista de diseño dada (usado en 'plan list')."""
        bom = {}
        for _, _, _, material_key in design_list:
            if material_key != 'air':
                bom[material_key] = bom.get(material_key, 0) + 1
        return bom

    # --- CICLO DE VIDA ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if not self.target_zone:
                # Si estamos corriendo pero no hay zona, esperamos
                self.logger.info("Esperando zona de construccion (Mapa o Jugador).")
                self.state = AgentState.WAITING 
            elif not self._check_inventory():
                # Si tenemos zona pero no materiales
                self.logger.info(f"Esperando materiales para '{self.current_template_name}'.")
                self.state = AgentState.WAITING 
            else:
                # Tenemos todo
                self.logger.info("Materiales listos y zona definida. Iniciando construccion.")
                self.is_building = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.is_building and self.target_zone:
            
            center_x = self.target_zone.get('x', 0)
            center_z = self.target_zone.get('z', 0)
            
            # Marcador visual de inicio
            try:
                y_surface = self.mc.getHeight(center_x, center_z)
                self._update_marker(Vec3(center_x, y_surface + 5, center_z))
            except Exception: pass
            
            # Quitamos marcador para no estorbar
            self._clear_marker()
            
            # --- CONSTRUCCIÓN REAL ---
            # Se pasa y=0 relativo, _build_structure calcula la altura real
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            # Post-construccion
            if self.state not in (AgentState.PAUSED, AgentState.ERROR):
                self.is_building = False
                self.required_bom = {} # Limpiamos BOM al terminar
                self.state = AgentState.IDLE
                await self._publish_build_complete()
                self._clear_marker() 
            else:
                 self.logger.warning("Construccion interrumpida.")

    async def _build_structure(self, center_pos: Vec3):
        """Itera sobre la lista de bloques de la plantilla y los coloca en el mundo."""
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        # Encontrar la altura del suelo en el centro
        try:
             start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception:
             start_y_surface = 65
        
        # Calcular el desplazamiento para centrar la estructura (la coordenada dada será el centro)
        max_x = max([b[0] for b in self.current_design])
        max_z = max([b[2] for b in self.current_design])
        
        x_base = center_x - (max_x // 2)
        z_base = center_z - (max_z // 2)
        y_base = start_y_surface # Construimos A RAS DE SUELO sobre la altura detectada
        
        self.logger.info(f"Construyendo '{self.current_template_name}' en base: ({x_base}, {y_base}, {z_base})")

        for dx, dy, dz, material_key in self.current_design:
            
            if self.state in (AgentState.PAUSED, AgentState.STOPPED):
                return 
            
            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            block_id = block.AIR.id
            if material_key != 'air':
                # Consumir material
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
        """Genera y envía un mensaje de estado detallado al chat del juego."""
        
        req_bom_str = []
        is_ready = True
        if self.required_bom:
            for material, required_qty in self.required_bom.items():
                current_qty = self.current_inventory.get(material, 0)
                req_bom_str.append(f"{current_qty}/{required_qty} {material}")
                if current_qty < required_qty:
                    is_ready = False
        
        req_status = "LISTO" if is_ready and self.required_bom else "PENDIENTE"
        req_str = ", ".join(req_bom_str) if req_bom_str else "Ninguno"

        zone_str = f"({self.target_zone.get('x', '?')}, {self.target_zone.get('z', '?')})"
        build_status = "SI" if self.is_building else "NO"
        
        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | Plantilla: {self.current_template_name.upper()} | "
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
                # --- CAMBIO IMPORTANTE: Construir donde está el jugador si no hay zona ---
                
                # 1. Intentar obtener posición del jugador
                try:
                    player_pos = self.mc.player.getTilePos()
                    # Actualizamos la zona objetivo a la posición del jugador
                    self.target_zone = {"x": player_pos.x, "z": player_pos.z}
                    self.logger.info(f"Comando 'build' manual. Zona establecida en jugador: {self.target_zone}")
                except Exception as e:
                    self.logger.warning(f"No se pudo obtener la posición del jugador: {e}")
                    if not self.target_zone:
                         self.mc.postToChat("[Builder] Error: No tengo mapa y no puedo localizarte.")
                         return

                # 2. Verificar inventario y cambiar estado
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
                        
                        # --- CAMBIO: CALCULAR BOM Y PUBLICAR INMEDIATAMENTE ---
                        self.required_bom = self._calculate_bom_for_structure()
                        
                        # Publicamos con estado ACKNOWLEDGED para que el MinerBot lo guarde
                        await self._publish_requirements_to_miner(status="ACKNOWLEDGED")
                        
                        req_str = ", ".join([f"{q} {m}" for m, q in self.required_bom.items()])
                        self.logger.info(f"Plan fijado: {template_name}. BOM: {req_str}")
                        self.mc.postToChat(f"[Builder] Plan fijado a '{template_name}'. Requisitos: {req_str}. Listo para '/miner fulfill'.")
                        # ------------------------------------------------------

                    else:
                        self.mc.postToChat(f"[Builder] No conozco la plantilla '{template_name}'.")
                
                elif len(args) >= 1 and args[0] == 'list':
                     # --- CAMBIO: MOSTRAR MATERIALES EN LA LISTA ---
                     self.mc.postToChat("[Builder] Plantillas disponibles:")
                     for name, design in BUILDING_TEMPLATES.items():
                         bom = self._calculate_bom_for_specific_design(design)
                         bom_str = ", ".join([f"{q} {m}" for m, q in bom.items()])
                         self.mc.postToChat(f" - {name}: [{bom_str}]")
                     # -----------------------------------------------
            
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
                 # Comando manual para visualizar BOM (ahora es redundante con plan set, pero útil)
                 self.required_bom = self._calculate_bom_for_structure()
                 req_str = ", ".join([f"{q} {m}" for m, q in self.required_bom.items()])
                 if self.required_bom:
                    await self._publish_requirements_to_miner(status="ACKNOWLEDGED")
                    self.mc.postToChat(f"[Builder] BOM actual: {req_str}")
                 else:
                     self.mc.postToChat(f"[Builder] La plantilla actual no requiere materiales.")

            elif command == 'status':
                await self._publish_status()

        elif msg_type == "map.v1":
            # Flujo automático con Explorer
            context = message.get("context", {})
            optimal_zone_center = payload.get("optimal_zone", {}).get("center", {})

            if context.get("target_zone"):
                 self.target_zone = context["target_zone"]
            elif optimal_zone_center:
                 self.target_zone = optimal_zone_center

            suggested = payload.get("suggested_template")
            if suggested and suggested in BUILDING_TEMPLATES:
                self.current_template_name = suggested
                self.current_design = BUILDING_TEMPLATES[suggested]
                self.mc.postToChat(f"[Builder] Acepto sugerencia del Explorer: '{suggested}'.")
            
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
                # Si estábamos esperando materiales y ya los tenemos:
                # 1. Si tenemos zona, arrancamos.
                # 2. Si no tenemos zona (caso manual), nos quedamos en WAITING/IDLE hasta el 'builder build'.
                if self.target_zone:
                    self.state = AgentState.RUNNING
                    self.is_building = True
                    self.mc.postToChat(f"[Builder] Materiales recibidos. Iniciando construccion.")
                else:
                    self.mc.postToChat(f"[Builder] Materiales recibidos. Usa '/builder build' para construir aqui.")
                
    async def _publish_requirements_to_miner(self, status: str = "PENDING"):
        """
        Publica los requisitos.
        status: "PENDING" (inicia minería auto), "ACKNOWLEDGED" (carga requisitos para fulfill manual).
        """
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