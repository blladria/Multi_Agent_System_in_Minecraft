# -*- coding: utf-8 -*-
import asyncio
import logging
from functools import reduce
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

def _generate_complex_shelter():
    """Genera un refugio de 5x5x4."""
    structure = []
    width, height, depth = 5, 4, 5
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                mat = 'air'
                if y == 0: mat = 'cobblestone'
                elif y == height - 1: mat = 'dirt'
                elif x == 0 or x == width - 1 or z == 0 or z == depth - 1:
                    if y == 2 and (1 < x < width-2 or 1 < z < depth-2): mat = 'air'
                    elif (x == 0 or x == width-1) and (z == 0 or z == depth-1): mat = 'cobblestone'
                    else: mat = 'dirt'
                if z == 0 and x == 2 and y in [1, 2]: mat = 'air'
                if mat != 'air': structure.append((x, y, z, mat))
    return structure

def _generate_chess_tower():
    """Genera una torre de vigilancia alta (3x3 base)."""
    structure = []
    height, width, depth = 10, 3, 3
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                if x == 1 and z == 1: continue
                mat = 'air'
                if y == height - 1:
                    if (x + z) % 2 == 0: mat = 'cobblestone'
                else:
                    if (x + y + z) % 2 == 0: mat = 'cobblestone'
                    else: mat = 'dirt'
                if z == 0 and x == 1 and y in [1, 2]: mat = 'air'
                if mat != 'air': structure.append((x, y, z, mat))
    return structure

def _generate_reinforced_bunker():
    """Genera un búnker ancho (7x7)."""
    structure = []
    width, depth, height = 7, 7, 4
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                mat = 'air'
                if y == 0 or y == height - 1: mat = 'cobblestone'
                else:
                    if x == 0 or x == width - 1 or z == 0 or z == depth - 1: mat = 'cobblestone'
                    elif x == 1 or x == width - 2 or z == 1 or z == depth - 2: mat = 'dirt'
                if z == 0 and x == 3 and y in [1, 2]: mat = 'air'
                if z == 1 and x == 3 and y in [1, 2]: mat = 'air'
                if mat != 'air': structure.append((x, y, z, mat))
    return structure

TEMPLATE_SHELTER = _generate_complex_shelter()
TEMPLATE_TOWER = _generate_chess_tower()
TEMPLATE_BUNKER = _generate_reinforced_bunker()

BUILDING_TEMPLATES = {
    "simple_shelter": TEMPLATE_SHELTER,
    "watch_tower": TEMPLATE_TOWER,
    "storage_bunker": TEMPLATE_BUNKER
}

class BuilderBot(BaseAgent):
    """
    Agente BuilderBot:
    Encargado de la construcción de estructuras basadas en plantillas.
    Modificado para soportar interrupción y reanudación correcta.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)

        self.required_bom: Dict[str, int] = {}
        self.current_inventory: Dict[str, int] = {}
        self.target_zone: Dict[str, int] = {}
        self.is_building = False 
        
        # --- GESTIÓN DE PLANTILLAS ---
        self.current_template_name = "simple_shelter" 
        self.current_design = BUILDING_TEMPLATES[self.current_template_name]
        
        self.manual_override = False 
        self._set_marker_properties(block.WOOL.id, 5)

        # Índice para rastrear el progreso de la construcción
        self.build_progress_index = 0

    # --- Lógica de Inventario ---

    def _check_inventory(self) -> bool:
        if not self.required_bom: return False
        insufficient_materials = list(filter(
            lambda item: self.current_inventory.get(item[0], 0) < item[1],
            self.required_bom.items()
        ))
        return len(insufficient_materials) == 0
                   
    def _calculate_bom_for_structure(self) -> Dict[str, int]:
        return self._reduce_design_to_bom(self.current_design)
        
    def _calculate_bom_for_specific_design(self, design_list) -> Dict[str, int]:
        return self._reduce_design_to_bom(design_list)

    def _reduce_design_to_bom(self, design_list) -> Dict[str, int]:
        def bom_reducer(acc, block_tuple):
            material_key = block_tuple[3]
            if material_key != 'air':
                acc[material_key] = acc.get(material_key, 0) + 1
            return acc
        
        bom = reduce(bom_reducer, design_list, {})
        self.logger.info(f"BOM calculado (funcional): {bom}")
        return bom

    # --- CICLO DE VIDA ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        """
        Determina si debe construir o esperar.
        CORREGIDO: No bloquea el 'resume' si el inventario parcial es menor al BOM total.
        """
        if self.state == AgentState.RUNNING:
            # Recuperar progreso del contexto (para resume/crash recovery)
            if 'build_progress_index' in self.context:
                self.build_progress_index = self.context['build_progress_index']

            if not self.target_zone:
                self.logger.info("Esperando zona de construccion (Mapa o Jugador).")
                self.state = AgentState.WAITING 
            
            # CAMBIO IMPORTANTE AQUÍ:
            # Solo exigimos el inventario COMPLETO si NO estamos construyendo ya.
            # Si estamos 'is_building' (reanudando), confiamos en que 'act' gestione los bloques restantes.
            elif not self.is_building and not self._check_inventory():
                self.logger.info(f"Esperando materiales para '{self.current_template_name}'.")
                self.state = AgentState.WAITING 
            
            else:
                self.logger.info("Materiales listos (o obra en curso) y zona definida. Iniciando/Continuando.")
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
            
            # Guardar el estado actual antes de empezar
            self.context['build_progress_index'] = self.build_progress_index

            # Ejecutar construcción (bloque a bloque, interrumpible)
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            # Solo reseteamos si hemos terminado de verdad (Seguimos en RUNNING)
            if self.state == AgentState.RUNNING:
                self.is_building = False
                self.required_bom = {} 
                self.state = AgentState.IDLE
                self.manual_override = False 
                
                # Reseteamos el índice al terminar con éxito
                self.build_progress_index = 0
                self.context['build_progress_index'] = 0
                
                await self._publish_build_complete()
                self._clear_marker() 
            else:
                # Si estamos PAUSED o STOPPED, no hacemos nada, conservamos is_building = True
                self.logger.warning(f"Construccion interrumpida. Estado: {self.state.name}")

    async def _build_structure(self, center_pos: Vec3):
        """
        Construye la estructura permitiendo interrupciones inmediatas.
        """
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        try: start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception: start_y_surface = 65
        
        x_coords = list(map(lambda b: b[0], self.current_design))
        z_coords = list(map(lambda b: b[2], self.current_design))
        
        if not x_coords or not z_coords:
            self.logger.warning("Diseño vacío. Nada que construir.")
            return

        max_x = max(x_coords)
        max_z = max(z_coords)
        x_base = center_x - (max_x // 2)
        z_base = center_z - (max_z // 2)
        y_base = start_y_surface 
        
        self.logger.info(f"Construyendo '{self.current_template_name}'. Progreso: {self.build_progress_index}/{len(self.current_design)}")

        # Usamos enumerate para saber por qué bloque vamos
        for i, (dx, dy, dz, material_key) in enumerate(self.current_design):
            
            # Salto rápido: Si este bloque es anterior al índice guardado, saltar
            if i < self.build_progress_index:
                continue

            # CRÍTICO: Escuchar mensajes en cada iteración para detectar PAUSE/STOP
            await self.perceive()
            
            # Si el estado ha cambiado a PAUSED, STOPPED o ERROR, salimos inmediatamente
            if self.state != AgentState.RUNNING:
                self.logger.info(f"Construcción detenida en bloque {i} por estado {self.state.name}")
                return 

            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            block_id = block.AIR.id
            if material_key != 'air':
                # Chequeo granular: ¿Tengo ESTE material específico?
                if self.current_inventory.get(material_key, 0) > 0:
                    block_id = MATERIAL_MAP.get(material_key, block.COBBLESTONE.id)
                else:
                    self.logger.error(f"Material '{material_key}' agotado a mitad de obra! Pasando a WAITING.")
                    self.mc.postToChat(f"[Builder] Material '{material_key}' agotado. Pausando. Estado: WAITING.")
                    self.is_building = False
                    self.state = AgentState.WAITING 
                    return
            
            try:
                self.mc.setBlock(final_x, final_y, final_z, block_id)
                
                if block_id != block.AIR.id:
                    self.current_inventory[material_key] -= 1
                
                # Actualizamos el progreso Y EL CONTEXTO tras cada bloque
                self.build_progress_index = i + 1
                self.context['build_progress_index'] = self.build_progress_index
                
                await asyncio.sleep(0.05) 

            except Exception as e:
                self.logger.error(f"Error poniendo bloque: {e}")
                self.is_building = False
                self.state = AgentState.ERROR
                return

        self.logger.info(f"Construccion finalizada con exito.")

    async def _publish_status(self):
        req_bom_str = []
        is_ready = True
        
        if self.required_bom:
            req_bom_str = list(map(
                lambda item: f"{self.current_inventory.get(item[0], 0)}/{item[1]} {item[0]}",
                self.required_bom.items()
            ))
            # Insuficiente solo es relevante si NO estamos construyendo
            if not self.is_building:
                insufficient = list(filter(
                    lambda item: self.current_inventory.get(item[0], 0) < item[1],
                    self.required_bom.items()
                ))
                is_ready = len(insufficient) == 0
        
        req_status = "LISTO" if is_ready else "PENDIENTE"
        req_str = ", ".join(req_bom_str) if req_bom_str else "Ninguno"
        zone_str = f"({self.target_zone.get('x', '?')}, {self.target_zone.get('z', '?')})"
        build_status = "SI" if self.is_building else "NO"
        override_str = " (MANUAL)" if self.manual_override else ""
        
        # Progreso numérico
        total_blocks = len(self.current_design)
        progress_str = f"{self.build_progress_index}/{total_blocks}" if self.is_building else "N/A"

        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | Plantilla: {self.current_template_name.upper()}{override_str} | "
            f"Zona: {zone_str}\n"
            f"  > Requisitos ({req_status}): {req_str}\n"
            f"  > Construyendo: {build_status} | Progreso: {progress_str}"
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
                        self.manual_override = True 
                        self.required_bom = self._calculate_bom_for_structure()
                        
                        # Al cambiar de plan, reiniciamos el progreso
                        self.build_progress_index = 0
                        
                        await self._publish_requirements_to_miner(status="ACKNOWLEDGED")
                        req_str = ", ".join(map(lambda item: f"{item[1]} {item[0]}", self.required_bom.items()))
                        self.mc.postToChat(f"[Builder] Plan fijado MANUALMENTE a '{template_name}'. Requisitos: {req_str}. Listo para '/miner fulfill'.")
                    else:
                        self.mc.postToChat(f"[Builder] No conozco la plantilla '{template_name}'.")
                
                elif len(args) >= 1 and args[0] == 'list':
                     self.mc.postToChat("[Builder] Plantillas disponibles:")
                     for name, design in BUILDING_TEMPLATES.items():
                         bom = self._calculate_bom_for_specific_design(design)
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
            
            if not self.manual_override:
                if suggested and suggested in BUILDING_TEMPLATES:
                    self.current_template_name = suggested
                    self.current_design = BUILDING_TEMPLATES[suggested]
                    self.mc.postToChat(f"[Builder] Acepto sugerencia del Explorer: '{suggested}'.")
            else:
                 self.mc.postToChat(f"[Builder] Ignoro sugerencia del Explorer ('{suggested}') porque hay plan manual: '{self.current_template_name}'.")
            
            self.required_bom = self._calculate_bom_for_structure() 
            # Reiniciar índice si cambia el mapa/plan implícitamente
            self.build_progress_index = 0
            
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