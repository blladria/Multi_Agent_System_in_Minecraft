# -*- coding: utf-8 -*-
import asyncio
import logging
from typing import Dict, Any, Tuple
from agents.base_agent import BaseAgent, AgentState
from mcpi import block
from mcpi.vec3 import Vec3
from datetime import datetime, timezone

# --- MAPEO DE BLOQUES Y DISEÑO DE LA "Simple Shelter" (DIRT/COBBLESTONE ONLY) ---

# Mapeo de material (texto) a ID de bloque (Minecraft)
MATERIAL_MAP = {
    "wood": block.WOOD.id, 
    "wood_planks": block.WOOD_PLANKS.id,
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id, # Ahora es el material principal para el BuilderBot
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id,
    "door_wood": block.DOOR_WOOD.id,
    "dirt": block.DIRT.id
}

# Diseño de la "Simple Shelter": 3x3x4 (dx, dy, dz, material_key)
# Materiales: Cobblestone y Dirt. (El piso (y=0) se coloca sobre el bloque de superficie).

SIMPLE_SHELTER_DESIGN = [
    # Capa Y=0 (Piso): 3x3 Cobblestone
    (0, 0, 0, 'cobblestone'), (1, 0, 0, 'cobblestone'), (2, 0, 0, 'cobblestone'),
    (0, 0, 1, 'cobblestone'), (1, 0, 1, 'cobblestone'), (2, 0, 1, 'cobblestone'),
    (0, 0, 2, 'cobblestone'), (1, 0, 2, 'cobblestone'), (2, 0, 2, 'cobblestone'),
    
    # Capa Y=1 (Paredes - Dirt con Puerta)
    (0, 1, 0, 'dirt'), (1, 1, 0, 'dirt'), (2, 1, 0, 'dirt'),
    (0, 1, 1, 'dirt'),                       (2, 1, 1, 'dirt'),
    (0, 1, 2, 'dirt'), (1, 1, 2, 'dirt'), (2, 1, 2, 'dirt'),
    (1, 1, 1, 'air'), # Apertura de la puerta (Usamos AIR para dejar el hueco)
    
    # Capa Y=2 (Paredes - Cobblestone con hueco central - Simula ventana/altura)
    (0, 2, 0, 'cobblestone'), (1, 2, 0, 'cobblestone'), (2, 2, 0, 'cobblestone'),
    (0, 2, 1, 'cobblestone'),                       (2, 2, 1, 'cobblestone'),
    (0, 2, 2, 'cobblestone'), (1, 2, 2, 'cobblestone'), (2, 2, 2, 'cobblestone'),
    (1, 2, 1, 'air'), # Hueco interior
    
    # Capa Y=3 (Techo final - Cobblestone)
    (0, 3, 0, 'cobblestone'), (1, 3, 0, 'cobblestone'), (2, 3, 0, 'cobblestone'),
    (0, 3, 1, 'cobblestone'), (1, 3, 1, 'cobblestone'), (2, 3, 1, 'cobblestone'),
    (0, 3, 2, 'cobblestone'), (1, 3, 2, 'cobblestone'), (2, 3, 2, 'cobblestone'),
]


class BuilderBot(BaseAgent):
    """
    Agente responsable de la construcción de estructuras.
    Sincronización: espera a que MinerBot cumpla el BoM.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)

        # FIX: Inicialización del atributo terrain_data para compatibilidad con tests.
        self.terrain_data: Dict[str, Any] = {}
        
        self.required_bom: Dict[str, int] = {}
        self.current_inventory: Dict[str, int] = {}
        self.target_zone: Dict[str, int] = {}
        self.is_building = False # Indica que la acción de ACT está en curso
        
        # Marcador Verde (Lana Verde Lima = data 5)
        self._set_marker_properties(block.WOOL.id, 5)

    # --- Lógica Específica del Agente ---

    def _check_inventory(self) -> bool:
        """Verifica si el inventario actual cumple con el BoM requerido."""
        if not self.required_bom:
            return False
        return all(self.current_inventory.get(material, 0) >= required_qty 
                   for material, required_qty in self.required_bom.items())
                   
    # --- Cálculo del BOM (Responsabilidad del BuilderBot) ---
    def _calculate_bom_for_structure(self) -> Dict[str, int]:
        """
        Calcula el Bill of Materials (BoM) total necesario para construir
        la estructura Simple Shelter.
        """
        bom = {}
        for _, _, _, material_key in SIMPLE_SHELTER_DESIGN:
            if material_key != 'air':
                # Utilizamos una expresión funcional simple para contar:
                bom[material_key] = bom.get(material_key, 0) + 1
        
        self.logger.info(f"BOM calculado para Simple Shelter (Cobblestone/Dirt): {bom}")
        return bom
    # ---------------------------------------------------------------------

    # --- Ciclo Perceive-Decide-Act ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if not self.target_zone:
                self.logger.info("Esperando mapa del ExplorerBot.")
                # Si falta el mapa, forzamos a WAITING
                self.state = AgentState.WAITING 
            elif not self._check_inventory():
                self.logger.info("Esperando materiales del MinerBot.")
                self.state = AgentState.WAITING # Esperar materiales
            else:
                 # Todo listo: iniciar/continuar construcción
                self.logger.info("Materiales listos y zona definida. Iniciando construcción.")
                self.is_building = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.is_building and self.target_zone:
            
            # Obtener la posición central (X, Z) del área a construir
            center_x = self.target_zone.get('x', 0)
            center_z = self.target_zone.get('z', 0)
            
            # Usamos una Y de visualización (encima de la superficie)
            try:
                y_surface = self.mc.getHeight(center_x, center_z)
                self._update_marker(Vec3(center_x, y_surface + 2, center_z))
            except Exception:
                pass # Ignorar error de visualización
            
            # 0. FIX: Limpiar el marcador ANTES de construir para que no quede la lana flotando
            self._clear_marker()
            
            # 1. Construir la estructura
            await self._build_structure(Vec3(center_x, 0, center_z)) 
            
            # 2. Finalizar la tarea
            if self.state != AgentState.PAUSED and self.state != AgentState.ERROR:
                self.is_building = False
                self.required_bom = {} # Limpiar BoM
                self.state = AgentState.IDLE
                await self._publish_build_complete()
                
                # Volver a colocar el marcador en IDLE para visibilidad
                try:
                    self._update_marker(Vec3(center_x, y_surface + 1, center_z))
                except Exception:
                    pass
            else:
                 self.logger.warning("Construcción interrumpida. Estado guardado.")


    async def _build_structure(self, center_pos: Vec3):
        """
        Construye la estructura "Simple Shelter" usando la posición central
        y asegurando que el piso esté a ras de la superficie (Ground Placement Fix).
        """
        center_x, center_z = int(center_pos.x), int(center_pos.z)
        
        try:
             # FIX 1: Obtener la altura de la superficie en el centro de la zona.
             # start_y_surface SERÁ LA BASE (Y=0) DEL PISO. Esto soluciona la flotación.
             start_y_surface = self.mc.getHeight(center_x, center_z) 
        except Exception:
             self.logger.warning("No se pudo obtener la altura de la superficie. Usando y=65.")
             start_y_surface = 65
        
        # El diseño se basa en un origen (x, y, z). La casa es de 3x3.
        # Para que el centro de la casa 3x3 esté en (center_x, center_z), 
        # el punto de inicio (x_base, z_base) debe ser el centro - 1.
        x_base = center_x - 1
        y_base = start_y_surface # FIX 2: La base del piso comienza en la superficie
        z_base = center_z - 1
        
        self.logger.info(f"Iniciando construcción de Simple Shelter en base: ({x_base}, {y_base}, {z_base})")

        # Construir bloque por bloque
        for dx, dy, dz, material_key in SIMPLE_SHELTER_DESIGN:
            
            # Comprobar el estado antes de cada bloque
            if self.state == AgentState.PAUSED or self.state == AgentState.STOPPED:
                self.logger.info("Construcción pausada/detenida por comando externo.")
                self._save_checkpoint() 
                return # Salir del bucle
            
            final_x = x_base + dx
            final_y = y_base + dy
            final_z = z_base + dz
            
            block_id = block.AIR.id # Por defecto es aire
            
            # 1. Definir el bloque o verificar si el material está disponible
            if material_key == 'air':
                 block_id = block.AIR.id
            elif material_key in self.current_inventory:
                if self.current_inventory.get(material_key, 0) > 0:
                    block_id = MATERIAL_MAP.get(material_key, block.COBBLESTONE.id) # Usar COBBLESTONE como fallback
                else:
                    # CRÍTICO: Si no hay material, volvemos a WAITING.
                    self.logger.error(f"Fallo de construcción: Material '{material_key}' agotado. Transicionando a WAITING.")
                    self.is_building = False
                    self.state = AgentState.WAITING 
                    return
            else:
                 # Si el material no es aire y no está en el inventario (pero se necesita), asumimos un fallback
                 block_id = MATERIAL_MAP.get(material_key, block.COBBLESTONE.id)
            
            try:
                # Colocar el bloque en Minecraft
                self.mc.setBlock(final_x, final_y, final_z, block_id)
                
                # Solo consumir si no es aire
                if block_id != block.AIR.id:
                    self.current_inventory[material_key] -= 1 # Consumir el material
                
                # Pausa asíncrona para no bloquear el bucle de eventos
                await asyncio.sleep(0.01) # Pausa mínima para permitir el procesamiento de mensajes
                
            except Exception as e:
                self.logger.error(f"Error al construir bloque en MC: {e}")
                self.is_building = False
                self.state = AgentState.ERROR
                return

        self.logger.info("Construcción finalizada con éxito.")

    # --- Manejo de Mensajes (Resto de métodos sin cambio) ---

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'build':
                # Si recibe 'build', intenta pasar a RUNNING (si tiene mapa/materiales)
                self.state = AgentState.RUNNING
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()

        elif msg_type == "map.v1": # FIX: Cambiado a map.v1
            context = message.get("context", {})

            # Recibe el mapa y la zona objetivo del ExplorerBot
            # Usamos el campo 'optimal_zone.center' del payload para la posición central, si existe
            optimal_zone_center = payload.get("optimal_zone", {}).get("center", {})

            # 1. Extraer la zona objetivo
            if context.get("target_zone"):
                 self.target_zone = context["target_zone"]
            elif optimal_zone_center:
                 self.target_zone = optimal_zone_center

            # 2. CALCULAR el BOM (Nueva Responsabilidad)
            self.required_bom = self._calculate_bom_for_structure() 
            
            # 3. Publicar requisitos al MinerBot inmediatamente (BuilderBot -> MinerBot)
            if self.required_bom:
                await self._publish_requirements_to_miner()
            
            # 4. TRANSICIÓN CONTROLADA (FIX para el bucle infinito)
            # Después de publicar el requerimiento, el BuilderBot sabe que debe esperar materiales.
            # Solo transiciona a RUNNING si ya tiene los materiales (lo cual es improbable aquí).
            if self._check_inventory():
                 self.state = AgentState.RUNNING
            else:
                 self.state = AgentState.WAITING # Esperar la respuesta del MinerBot/materiales
            
            self.logger.info(f"Mapa recibido. Zona objetivo: {self.target_zone}. BOM calculado: {self.required_bom}. Estado: {self.state.name}")


        elif msg_type == "inventory.v1":
            # Actualiza el inventario local con los datos del MinerBot
            new_inventory = payload.get("collected_materials", {})
            self.current_inventory.update(new_inventory)
            self.logger.info(f"Inventario actualizado. Vol: {payload.get('total_volume')}")
            
            # Si estaba esperando materiales, reanuda la decisión
            if self.state == AgentState.WAITING:
                self.state = AgentState.RUNNING
                
    # --- Comunicación Externa ---
    
    async def _publish_requirements_to_miner(self):
        """Publica el BOM (Bill of Materials) como un mensaje de requerimientos al MinerBot."""
        requirements_message = {
            "type": "materials.requirements.v1",
            "source": self.agent_id,
            "target": "MinerBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": self.required_bom, # El payload son los requisitos
            "status": "PENDING",
            "context": {"target_zone": self.target_zone} # Incluir la zona de trabajo para el minero
        }
        await self.broker.publish(requirements_message)
        self.logger.info(f"Requisitos (BOM) publicados a MinerBot: {self.required_bom}")
    
    async def _publish_build_complete(self):
        """Notifica al sistema que la construcción ha finalizado."""
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