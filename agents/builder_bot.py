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

def _generate_complex_shelter():
    """
    Genera un refugio de 5x5x4.
    - Accesible: Puerta frontal (aire).
    - Habitable: Interior hueco.
    - Materiales: Suelo piedra, techo tierra, paredes mixtas.
    """
    structure = []
    width, height, depth = 5, 4, 5
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                mat = 'air'
                
                # Suelo (y=0) de piedra
                if y == 0:
                    mat = 'cobblestone'
                # Techo (última capa) de tierra
                elif y == height - 1:
                    mat = 'dirt'
                # Paredes (Perímetro)
                elif x == 0 or x == width - 1 or z == 0 or z == depth - 1:
                    # Ventanas (aire) en el centro de las paredes a altura 2
                    if y == 2 and (1 < x < width-2 or 1 < z < depth-2):
                        mat = 'air'
                    # Esquinas de piedra para soporte visual
                    elif (x == 0 or x == width-1) and (z == 0 or z == depth-1):
                        mat = 'cobblestone'
                    # Resto de paredes de tierra compactada
                    else:
                        mat = 'dirt'
                
                # Puerta (aire) en el frente (z=0), centrada
                # Altura y=1 y y=2 para que el jugador quepa
                if z == 0 and x == 2 and y in [1, 2]:
                    mat = 'air'

                if mat != 'air':
                    structure.append((x, y, z, mat))
    return structure

def _generate_chess_tower():
    """
    Genera una torre de vigilancia alta (3x3 base).
    - Accesible: Puerta en la base.
    - Habitable: Interior hueco (chimenea vertical).
    - Patrón: Ajedrezado de piedra y tierra.
    """
    structure = []
    height = 10
    width = 3
    depth = 3
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                # Hueco interior (x=1, z=1) para poder estar dentro o subir (si hubiera escaleras)
                if x == 1 and z == 1:
                    continue
                
                mat = 'air'
                
                # Almenas en la cima (y=9)
                if y == height - 1:
                    # Solo esquinas y centros de lados (patrón almena)
                    if (x + z) % 2 == 0: 
                        mat = 'cobblestone'
                else:
                    # Patrón de ajedrez en las paredes sólidas
                    if (x + y + z) % 2 == 0:
                        mat = 'cobblestone'
                    else:
                        mat = 'dirt'
                
                # Puerta en la base (z=0, x=1) para entrar a la torre
                if z == 0 and x == 1 and y in [1, 2]:
                    mat = 'air'
                
                if mat != 'air':
                    structure.append((x, y, z, mat))
    return structure

def _generate_reinforced_bunker():
    """
    Genera un búnker ancho (7x7).
    - Accesible: Entrada lateral tipo túnel.
    - Habitable: Gran espacio interior.
    - Seguridad: Paredes dobles (Piedra fuera, Tierra dentro).
    """
    structure = []
    width = 7
    depth = 7
    height = 4 # Bajo y robusto
    
    for y in range(height):
        for x in range(width):
            for z in range(depth):
                mat = 'air'
                
                # Suelo y Techo blindados (Piedra completa)
                if y == 0 or y == height - 1:
                    mat = 'cobblestone'
                else:
                    # Pared Exterior (Piedra)
                    if x == 0 or x == width - 1 or z == 0 or z == depth - 1:
                        mat = 'cobblestone'
                    # Pared Interior (Tierra) - Recubrimiento térmico
                    elif x == 1 or x == width - 2 or z == 1 or z == depth - 2:
                        mat = 'dirt'
                    # El centro (x e z entre 2 y 4) queda vacío (aire)
                
                # Entrada (Puerta) en el frente
                if z == 0 and x == 3 and y in [1, 2]:
                    mat = 'air'
                    # Limpiar también la capa interior de tierra para pasar
                    # No necesitamos poner aire explícito en la lista, simplemente no agregamos bloque
                    pass 

                # Si es la coordenada de la puerta interior (z=1), tampoco ponemos bloque
                if z == 1 and x == 3 and y in [1, 2]:
                    mat = 'air'

                if mat != 'air':
                    structure.append((x, y, z, mat))
    return structure

# Generación de las listas finales al iniciar el módulo
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
        
        # Bandera para saber si el usuario ha forzado una plantilla manualmente
        self.manual_override = False 
        
        self._set_marker_properties(block.WOOL.id, 5)

    # --- Lógica de Inventario (Funcional) ---

    def _check_inventory(self) -> bool:
        """Verifica si tenemos todos los materiales necesarios usando filter."""
        if not self.required_bom:
            return False
        
        # FUNCIONAL: Filtramos los materiales que NO cumplen el requisito (tengo < necesito)
        insufficient_materials = list(filter(
            lambda item: self.current_inventory.get(item[0], 0) < item[1],
            self.required_bom.items()
        ))
        
        # Si la lista de insuficientes está vacía, tenemos todo
        return len(insufficient_materials) == 0
                   
    def _calculate_bom_for_structure(self) -> Dict[str, int]:
        """Calcula el BOM usando reduce sobre el diseño actual."""
        return self._reduce_design_to_bom(self.current_design)
        
    def _calculate_bom_for_specific_design(self, design_list) -> Dict[str, int]:
        """Calcula el BOM para una lista de diseño dada usando reduce."""
        return self._reduce_design_to_bom(design_list)

    def _reduce_design_to_bom(self, design_list) -> Dict[str, int]:
        """Helper funcional puro para reducir una lista de bloques a un diccionario de conteo."""
        def bom_reducer(acc, block_tuple):
            # block_tuple es (x, y, z, material_key)
            material_key = block_tuple[3]
            if material_key != 'air':
                acc[material_key] = acc.get(material_key, 0) + 1
            return acc
            
        # FUNCIONAL: Uso de reduce para acumular conteos
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
            
            # Marcador visual de inicio
            try:
                y_surface = self.mc.getHeight(center_x, center_z)
                self._update_marker(Vec3(center_x, y_surface + 5, center_z))
            except Exception: pass
            
            self._clear_marker()
            
            # Ejecutar construcción bloque a bloque
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            # Si terminamos y no nos pausaron/pararon a medias
            if self.state not in (AgentState.PAUSED, AgentState.STOPPED, AgentState.ERROR):
                self.is_building = False
                self.required_bom = {} 
                self.state = AgentState.IDLE
                self.manual_override = False # Resetear override al terminar con éxito
                await self._publish_build_complete()
                self._clear_marker() 
            else:
                 self.logger.warning("Construccion interrumpida o pausada.")

    async def _build_structure(self, center_pos: Vec3):
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        try:
             start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception:
             start_y_surface = 65
        
        # Centrar la estructura: Calculamos offsets máximos
        # FUNCIONAL: Uso de map para obtener listas de coordenadas X y Z
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
        
        self.logger.info(f"Construyendo '{self.current_template_name}' en base: ({x_base}, {y_base}, {z_base})")

        for dx, dy, dz, material_key in self.current_design:
            
            # Chequeo de estado en cada bloque para permitir pausa/stop inmediato
            if self.state in (AgentState.PAUSED, AgentState.STOPPED, AgentState.ERROR):
                return 
            
            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            block_id = block.AIR.id
            if material_key != 'air':
                # Verificar inventario antes de poner cada bloque
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
                
                # Descontar del inventario solo si no es aire
                if block_id != block.AIR.id:
                    self.current_inventory[material_key] -= 1
                
                # Pequeño delay para simular proceso de construcción y no saturar servidor
                await asyncio.sleep(0.05) 

            except Exception as e:
                self.logger.error(f"Error poniendo bloque en ({final_x},{final_y},{final_z}): {e}")
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
            # FUNCIONAL: Map para crear las strings de estado "cantidad/total material"
            req_bom_str = list(map(
                lambda item: f"{self.current_inventory.get(item[0], 0)}/{item[1]} {item[0]}",
                self.required_bom.items()
            ))
            
            # FUNCIONAL: Filter para chequear si hay materiales insuficientes
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
                # Construcción manual en la posición del jugador
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
                # Cambio de plan manual
                if len(args) >= 2 and args[0] == 'set':
                    template_name = args[1].lower()
                    if template_name in BUILDING_TEMPLATES:
                        self.current_template_name = template_name
                        self.current_design = BUILDING_TEMPLATES[template_name]
                        
                        # IMPORTANTE: Activamos el override manual para que Explorer no lo cambie
                        self.manual_override = True 
                        
                        self.required_bom = self._calculate_bom_for_structure()
                        
                        # Notificar al minero los nuevos requisitos
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

            # Actualizar zona objetivo
            if context.get("target_zone"):
                 self.target_zone = context["target_zone"]
            elif optimal_zone_center:
                 self.target_zone = optimal_zone_center

            suggested = payload.get("suggested_template")
            
            # LÓGICA DE DECISIÓN: Solo aceptamos la sugerencia si NO hay override manual
            if not self.manual_override:
                if suggested and suggested in BUILDING_TEMPLATES:
                    self.current_template_name = suggested
                    self.current_design = BUILDING_TEMPLATES[suggested]
                    self.mc.postToChat(f"[Builder] Acepto sugerencia del Explorer: '{suggested}'.")
            else:
                 self.mc.postToChat(f"[Builder] Ignoro sugerencia del Explorer ('{suggested}') porque hay plan manual: '{self.current_template_name}'.")
            
            # Recalcular BOM y enviarlo
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
            
            # Si estábamos esperando materiales, verificamos si ya podemos construir
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