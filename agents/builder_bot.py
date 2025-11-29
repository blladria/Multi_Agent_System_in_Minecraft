# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any
from agents.base_agent import BaseAgent, AgentState
from mcpi import block
from mcpi.vec3 import Vec3

# Diccionario de plantillas de construcción simuladas
BUILDING_TEMPLATES = {
    "shelter_basic": {
        # Materiales OBTENIBLES: Piedra y Tierra. (Actualizado: No usa wood)
        "materials": {"stone": 30, "dirt": 60}, 
        "size": (5, 3, 5), # (x, y, z)
        "description": "Un refugio simple de 5x3x5 hecho de piedra y tierra."
    },
    "house_basic": {
        # Se reemplazan wood_planks, stone, glass_pane, door_wood por stone y dirt
        "materials": {"stone": 60, "dirt": 60}, 
        "size": (5, 6, 5), # (x, y, z)
        "description": "Una casa basica de 5x6x5 con techo y puerta (solo materiales basicos: piedra y tierra)"
    },
    "tower_watch": {
        # Reemplazar wood por stone
        "materials": {"dirt": 128, "stone": 16},
        "size": (3, 10, 3),
        "description": "Una torre de vigilancia de 3x10x3 de tierra y piedra"
    },
    # --- PLANTILLA DE PRUEBA (CONSTRUCCIÓN SÓLIDA DE PIEDRA/TIERRA) ---
    "test_mining": {
        "materials": {"stone": 50, "dirt": 50}, 
        "size": (5, 5, 5),
        "description": "Plan de prueba para minar 50 Stone (Vertical) y 50 Dirt (Grid)."
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
        # CAMBIO: Usar la cabaña simple (shelter_basic) por defecto
        self.current_plan: Dict[str, Any] = BUILDING_TEMPLATES["shelter_basic"] 
        self.required_bom: Dict[str, int] = {}
        self.current_inventory: Dict[str, int] = {}
        self.construction_position: Vec3 = None
        
        self.build_step = 0
        self.is_planning = False
        self.is_building = False
        
        # VISUALIZACIÓN: Marcador Rojo (Lana Roja = data 14)
        # LLAMADA ELIMINADA: La deshabilitamos para evitar interferencias
        # self._set_marker_properties(block.WOOL.id, 14) 

    # --- Sobreescritura de Métodos de Visualización (Deshabilitados) ---
    def _set_marker_properties(self, block_id, data):
        """Sobreescrito: Deshabilita la configuración del marcador para BuilderBot."""
        pass
        
    def _update_marker(self, new_pos: Vec3):
        """Sobreescrito: Deshabilita el movimiento del marcador para BuilderBot."""
        pass
            
    def _clear_marker(self):
        """Sobreescrito: Deshabilita la limpieza del marcador para BuilderBot."""
        pass
    # ----------------------------------------------------------------

    async def perceive(self):
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
                
                build_finished = await self._execute_build_step()
                
                # LLAMADA ELIMINADA: Se ha quitado el movimiento del marcador para evitar errores de construcción.
                # if self.construction_position:
                #     current_y_pos = self.construction_position.clone()
                #     current_y_pos.y += self.build_step - 1 
                #     self._update_marker(current_y_pos) 
                
                # CAMBIO: Usar el valor de retorno para terminar la construcción
                if build_finished:
                    self.logger.info("CONSTRUCCION FINALIZADA.")
                    self.is_building = False
                    self.build_step = 0
                    self.state = AgentState.IDLE
                    # La limpieza del marcador ahora está anulada en el método _clear_marker.
                    # self._clear_marker() 
                    
                    # CORRECCIÓN (5): Evitar reconstrucción. Limpiar datos de posición/mapa.
                    self.construction_position = None
                    self.terrain_data = {} 
                    
                # Simula el tiempo de construcción entre capas
                await asyncio.sleep(0.5)
        
        elif self.state in (AgentState.IDLE, AgentState.WAITING):
            # LLAMADA ELIMINADA: La limpieza del marcador ahora está anulada.
            # self._clear_marker() 
            pass

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
        """
        Publica el mensaje materials.requirements.v1 a MinerBot, incluyendo
        las coordenadas de la zona de trabajo.
        """
        
        # OBTENEMOS LAS COORDENADAS PARA INCLUIRLAS EN EL CONTEXTO
        target_zone_data = self.terrain_data.get("optimal_zone", {}).get("center", {})
        
        bom_message = {
            "type": "materials.requirements.v1",
            "source": self.agent_id,
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": self.required_bom,
            "status": "PENDING",
            "context": {
                "plan_name": self.current_plan["description"],
                # --- AÑADIDO: COORDENADAS DE LA ZONA OPTIMA ---
                "target_zone": target_zone_data 
            }
        }
        await self.broker.publish(bom_message)
        self.logger.info(f"BOM publicado a MinerBot. Materiales requeridos: {self.required_bom}")

    async def _execute_build_step(self) -> bool:
        """
        Coloca una capa de bloques en Minecraft, ciclando el material usado por capa
        y consumiéndolo del inventario.
        
        Retorna True si la construcción ha finalizado.
        """
        size_x, size_y, size_z = self.current_plan["size"]
        
        if self.build_step >= size_y:
            return True # Construcción terminada
            
        # 1. Preparación de Posición
        if not self.construction_position:
            # Inicializa la posición de construcción si no está definida
            zone = self.terrain_data.get('optimal_zone', {}).get('center', {})
            # Asume que 'y_avg' es la altura de la base (highest solid block).
            x_start, y_start, z_start = zone.get('x', 0), zone.get('y_avg', 0), zone.get('z', 0)
            
            # Para centrar la estructura, ajustamos x0 y z0 restando la mitad del tamaño.
            center_x, center_z = int(x_start), int(z_start)
            x0 = center_x - size_x // 2
            z0 = center_z - size_z // 2
            
            # FIX 1: La base (piso) debe comenzar al menos 1 bloque *encima* del bloque de tierra más alto.
            self.construction_position = Vec3(x0, int(y_start) + 1, z0) 
            
            self.logger.info(f"Base de construccion en: ({x0}, {self.construction_position.y}, {z0}). Altura base: {y_start}")
        
        # --- DEFINICIÓN DE BOUNDS FUERA DEL BLOQUE IF PARA EVITAR UnboundLocalError ---
        
        x0 = int(self.construction_position.x)
        y_base = int(self.construction_position.y)
        z0 = int(self.construction_position.z)
        current_y = y_base + self.build_step
        
        x1 = x0 + size_x - 1
        z1 = z0 + size_z - 1
        
        # NEW: Asegurar que el área esté limpia, desde el suelo hacia arriba, SOLO EN EL PRIMER STEP
        if self.build_step == 0:
            # y_start ahora es el nivel del suelo (y_base - 1)
            clear_y0 = y_base - 1 
            clear_y1 = y_base + size_y + 2 # Limpiar hasta dos bloques por encima del techo
            # FIX: x1 y z1 ya están definidos aquí, resolviendo el UnboundLocalError.
            self.mc.setBlocks(x0, clear_y0, z0, x1, clear_y1, z1, block.AIR.id)
            self.logger.debug(f"Despejando área de construccion de Y={clear_y0} a Y={clear_y1}")

        # 2. Lógica de Materiales por defecto
        required_materials_keys = list(self.current_plan["materials"].keys())
        
        # Obtener material por defecto para la capa. Si falla, usa el primer material del BOM.
        material_key_lower = required_materials_keys[self.build_step % len(required_materials_keys)]
        
        # Lógica de mapeo para obtener el ID de bloque
        # Ahora solo se espera 'stone' (ID 1) o 'dirt' (ID 3)
        mat_id = block.DIRT.id 
        if material_key_lower == 'wood':
             mat_id = block.WOOD.id # ID 17 (Log de madera sin refinar)
        elif material_key_lower == 'dirt':
             mat_id = block.DIRT.id # ID 3
        elif material_key_lower == 'stone':
             mat_id = block.STONE.id # ID 1
        
        blocks_to_place = 0
        
        
        # --- Lógica de Construcción de la Casa (House_basic 5x6x5) ---
        
        if self.current_plan["description"].startswith("Una casa basica"):
            
            # CAPA 0: Piso (Ahora de STONE)
            if self.build_step == 0:
                material_key_lower = "stone"
                mat_id = block.STONE.id # ID 1
                blocks_to_place = size_x * size_z # 25
                self.mc.setBlocks(x0, current_y, z0, x1, current_y, z1, mat_id)
                self.logger.info(f"Construyendo: Piso ({blocks_to_place} bloques de {material_key_lower}).")

            # CAPAS 1 a 4: Paredes, Ventanas y Puerta. (Hollow Interior)
            elif 1 <= self.build_step <= 4:
                material_key_lower = "dirt"
                mat_id = block.DIRT.id # ID 3
                
                blocks_in_layer = size_x * size_z
                blocks_inner = (size_x-2) * (size_z-2) 
                blocks_to_place = blocks_in_layer - blocks_inner # 16 bloques para un 5x5
                
                # 1. Colocar las paredes exteriores (cuboide hueco)
                self.mc.setBlocks(x0, current_y, z0, x1, current_y, z1, mat_id)
                
                # 2. Vaciar el interior (CORRECCIÓN: Asegura que el interior esté vacío)
                self.mc.setBlocks(x0 + 1, current_y, z0 + 1, x1 - 1, current_y, z1 - 1, block.AIR.id)
                
                # 3. Inserciones: Puerta y Ventana (Se usa AIR para huecos)
                mid_x = x0 + size_x // 2 
                mid_z = z0 + size_z // 2 
                
                # Puerta: Capas 1 y 2, en el centro de la pared X=x0 (mirando hacia el este)
                if self.build_step == 1: # Parte inferior de la puerta
                    door_pos_x = x0
                    door_pos_z = mid_z 
                    # Colocamos el bloque de AIRE.
                    self.mc.setBlock(door_pos_x, current_y, door_pos_z, block.AIR.id)
                    # El material se sigue consumiendo (simulado) pero el bloque puesto es aire.
                    material_key_lower = "dirt" 
                    self.logger.debug(f"Colocando hueco de puerta en ({door_pos_x}, {current_y}, {door_pos_z}).")

                # Ventana: Capa 3, en el centro de la pared X=x1 (opuesta a la puerta)
                if self.build_step == 3:
                    window_pos_x = x1
                    window_pos_z = mid_z
                    self.mc.setBlock(window_pos_x, current_y, window_pos_z, block.AIR.id) # Reemplazado por AIR
                    material_key_lower = "dirt" 
                    self.logger.debug(f"Colocando hueco de ventana en ({window_pos_x}, {current_y}, {window_pos_z}).")

                # Si es Capa 2, simplemente se asegura de que el hueco de la puerta esté libre de ladrillos
                if self.build_step == 2:
                    door_pos_x = x0
                    door_pos_z = mid_z 
                    self.mc.setBlock(door_pos_x, current_y, door_pos_z, block.AIR.id)
                    
                # Para evitar errores de consumo negativo, restablecemos el material a consumir
                blocks_to_place = 16 


            # CAPA 5: Techo (Ahora de STONE)
            elif self.build_step == 5:
                material_key_lower = "stone"
                mat_id = block.STONE.id # ID 1
                blocks_to_place = size_x * size_z # 25
                self.mc.setBlocks(x0, current_y, z0, x1, current_y, z1, mat_id)
                self.logger.info(f"Construyendo: Techo ({blocks_to_place} bloques de {material_key_lower}).")
            
            else: # Fallback para otras capas de la casa
                 material_key_lower = "dirt"
                 mat_id = block.DIRT.id
                 blocks_to_place = (size_x * 2) + (size_z * 2) - 4 # Perímetro
                 self.mc.setBlocks(x0, current_y, z0, x1, current_y, z0, mat_id) # Pared Z=z0
                 self.mc.setBlocks(x0, current_y, z1, x1, current_y, z1, mat_id) # Pared Z=z1
                 self.mc.setBlocks(x0, current_y, z0, x0, current_y, z1, mat_id) # Pared X=x0
                 self.mc.setBlocks(x1, current_y, z0, x1, current_y, z1, mat_id) # Pared X=x1
        
        # --- Lógica de Construcción de SHELTER, TOWER y TEST (Perímetro/Cuboide simple) ---
        elif self.current_plan["description"].startswith("Un refugio simple") or \
             self.current_plan["description"].startswith("Una torre de vigilancia") or \
             self.current_plan["description"].startswith("Plan de prueba"): # <-- Tu plan de prueba usa esta lógica
            
            # Se usa el material por defecto para la capa (ciclado entre dirt y stone, en tu caso)
            
            if material_key_lower == 'wood':
                 mat_id = block.WOOD.id
            elif material_key_lower == 'stone':
                 mat_id = block.STONE.id
            else:
                 mat_id = block.DIRT.id
            
            blocks_to_place = size_x * size_z # Bloques por defecto para una capa sólida
            
            # Construir cuboide sólido para la capa actual (IGNORA PUERTAS/VENTANAS)
            self.mc.setBlocks(x0, current_y, z0, x1, current_y, z1, mat_id)
            self.logger.info(f"Construyendo: Capa genérica ({blocks_to_place} bloques de {material_key_lower}).")

        # --- Lógica de Consumo (Común) ---
        
        # Consumir el material del inventario (SIMULACIÓN DE USO)
        if self.current_inventory.get(material_key_lower, 0) >= blocks_to_place:
            # Consumir del inventario
            self.current_inventory[material_key_lower] = self.current_inventory.get(material_key_lower, 0) - blocks_to_place
            self.logger.debug(f"Consumidos {blocks_to_place} de {material_key_lower}. Restante: {self.current_inventory[material_key_lower]}")
        else:
             # Si falta material, simplemente lo registramos y usamos el material virtual para terminar.
             self.logger.warning(f"Fallo de construccion simulada: {material_key_lower} insuficiente. Quedan {self.current_inventory.get(material_key_lower, 0)}. Usando el material de todos modos para terminar la estructura.")

        self.logger.info(f"Construyendo capa {self.build_step + 1}/{size_y} en Y={current_y}. ({blocks_to_place} bloques)")
        self.build_step += 1
        
        return False # No ha terminado

    # --- Manejo de Mensajes (incluye la corrección de no reconstruir) ---
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Procesa los mensajes de control y de datos recibidos."""
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'plan':
                self._parse_plan_command(payload.get("parameters", {}))
                
            elif command == 'build':
                # Al iniciar una construcción, si ya hay datos de terreno, forzamos a recalcular la posición de inicio.
                if self.terrain_data:
                    self.construction_position = None
                    
                if self._check_materials_sufficient():
                     self.state = AgentState.RUNNING # Puede iniciar la construcción
                else:
                     self.state = AgentState.WAITING # No puede iniciar, debe esperar los materiales
                     self.logger.warning("No se puede iniciar la construccion: Materiales insuficientes.")
            
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
        
        elif msg_type == "map.v1":
            # CORRECCIÓN (5): Se acepta el mapa solo si no hay data o si se está IDLE para empezar un nuevo ciclo.
            if self.terrain_data and self.state != AgentState.IDLE:
                self.logger.warning("Mapa recibido, pero ya hay datos de terreno y el agente está ocupado. Ignorando para evitar re-planificación forzada.")
                return

            self.terrain_data = payload
            # Transicionar a RUNNING al recibir el mapa
            if self.state == AgentState.IDLE or self.state == AgentState.WAITING:
                self.is_planning = True 
                self.state = AgentState.RUNNING
                self.logger.info("Datos de mapa recibidos. Iniciando planificación.")

        elif msg_type == "inventory.v1":
            # Actualiza el inventario local con los datos del MinerBot
            self.current_inventory = payload.get("collected_materials", {})
            self.logger.info("Inventario actualizado.")

            # **LÓGICA DE SINCRONIZACIÓN:** Si el MinerBot envió el mensaje de FINALIZACIÓN (SUCCESS) y estamos 
            # esperando materiales, forzamos la reevaluación y la transición a RUNNING 
            if self.state == AgentState.WAITING and message.get("status") == "SUCCESS":
                 if self._check_materials_sufficient():
                    self.logger.info("Materiales suficientes. Forzando transición a RUNNING para empezar construcción.")
                    self.is_building = True
                    self.state = AgentState.RUNNING

    def _parse_plan_command(self, params: Dict[str, Any]):
        """Parsea el comando '/builder plan set <template>'."""
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'set' and args[1] in BUILDING_TEMPLATES:
            self.current_plan = BUILDING_TEMPLATES[args[1]]
            self.logger.info(f"Plan de construccion cambiado a: {self.current_plan['description']}")
            # Limpiar datos para forzar un nuevo ciclo de mapa/plan si se cambia el plan
            self.terrain_data = {} 
            self.construction_position = None
            self.build_step = 0
        else:
            self.mc.postToChat("ERROR: /builder plan set <template> invalido.")