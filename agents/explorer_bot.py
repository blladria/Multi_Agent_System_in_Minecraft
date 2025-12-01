# -*- coding: utf-8 -*-
import asyncio
import logging
from typing import Dict, Any, Tuple
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block # Necesario para definir el marcador
from datetime import datetime, timezone

# Definición de materiales de interés (para el mapa)
EXPLORATION_BLOCKS = {
    block.DIRT.id: "dirt",
    block.GRASS.id: "dirt", 
    block.STONE.id: "stone",
    block.COBBLESTONE.id: "stone", # Cobblestone cuenta como stone para la minería profunda
    block.WATER.id: "water",
    block.LAVA.id: "lava",
    block.AIR.id: "air",
}

class ExplorerBot(BaseAgent):
    """
    Agente responsable de analizar el terreno circundante para identificar zonas óptimas
    y estables para la construcción (Uso de Programación Funcional en el análisis).
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        # FIX: Inicialización para Checkpointing
        self.exploration_size = 0
        self.exploration_position: Vec3 = Vec3(0, 0, 0)
        self.map_data: Dict[Tuple[int, int, int], str] = {}
        
        # VISUALIZACIÓN: Marcador Azul (Lana Azul = data 11)
        self._set_marker_properties(block.WOOL.id, 11)

    # --- Ciclo Perceive-Decide-Act ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        # La lógica de ExplorerBot es simple: solo tiene una tarea
        if self.state == AgentState.RUNNING and not self.map_data and self.exploration_size > 0:
            self.logger.info(f"Decidiendo iniciar exploración en {self.exploration_position} con tamaño {self.exploration_size}")
        elif self.state == AgentState.RUNNING and not self.map_data and self.exploration_size == 0:
             self.state = AgentState.IDLE # Si no hay parámetros para explorar

    async def act(self):
        if self.state == AgentState.RUNNING and self.exploration_size > 0:
            
            # El ACT es iniciar la exploración y esperar a que termine (o se pause)
            await self._explore_area(self.exploration_position, self.exploration_size)
            
            # Lógica post-exploración
            # Verificamos si el estado sigue siendo RUNNING (es decir, la exploración completó sin pausa o error)
            if self.state == AgentState.RUNNING:

                if self.map_data: # Caso 1: Éxito, encontró datos y debe publicar
                    await self._publish_map_data()
                    self.logger.info("Exploración finalizada con éxito. Mapa publicado.")
                else: 
                    # Caso 2: Finaliza el escaneo de la zona, pero no encontró datos.
                    self.logger.warning("Exploración finalizada. No se encontraron materiales/zonas para mapear.")
                
                # CRITICAL FIX: En ambos casos de finalización (con o sin datos), 
                # reiniciamos la tarea y volvemos a IDLE.
                self.exploration_size = 0
                self.map_data = {}
                self.state = AgentState.IDLE
                self._clear_marker()
            
            elif self.state == AgentState.PAUSED:
                self.logger.info("ACT terminó debido a una pausa. Esperando 'resume'.")
            
            elif self.state == AgentState.ERROR:
                self.logger.error("ACT terminó en ERROR.")
                
    # --- Checkpointing (Necesario para Pause/Resume) ---

    def _save_checkpoint(self):
        self.context["exploration_size"] = self.exploration_size
        self.context["map_data"] = self.map_data
        super()._save_checkpoint()

    def _load_checkpoint(self):
        self.exploration_size = self.context.get("exploration_size", 0)
        self.map_data = self.context.get("map_data", {})
        super()._load_checkpoint()

    # --- NUEVO: Método para obtener suelo sólido (ignora hierba/flores) ---
    def _get_solid_ground_y(self, x: int, z: int) -> int:
        """
        Obtiene la altura del suelo ignorando vegetación (hierba, flores, nieve).
        
        NOTA: mc.getHeight() devuelve el bloque sólido más alto. Este método
        lo refina buscando hacia abajo si se encuentran bloques no sólidos
        que confunden la superficie.
        """
        try:
            y = self.mc.getHeight(x, z)
        except Exception:
            return 65 # Fallback

        # Bloques que NO son suelo sólido para la construcción (tall grass, flores, nieve, hojas, etc.)
        NON_SOLID_BLOCKS = [
            block.AIR.id, block.SAPLING.id, block.LEAVES.id, block.COBWEB.id,
            block.GRASS_TALL.id, block.FLOWER_YELLOW.id, block.FLOWER_CYAN.id, 
            block.MUSHROOM_BROWN.id, block.MUSHROOM_RED.id, block.SNOW.id, 
            # Si hay dudas con Wood (17), se puede añadir, pero por defecto lo mantenemos como sólido.
        ]

        # Buscamos hacia abajo desde la altura reportada
        for _ in range(5): 
            block_id = self.mc.getBlock(x, y, z)
            if block_id not in NON_SOLID_BLOCKS:
                return y # Encontramos suelo firme
            y -= 1 # Bajamos un bloque
            if y < 1: return 1 # Límite inferior
            
        return y # Retorno por defecto si no encontramos nada

    # --- Lógica Específica del Agente ---
    
    async def _explore_area(self, start_pos: Vec3, size: int):
        """
        Explora un área con pausas asíncronas, permitiendo la pausa en tiempo real
        y mostrando el movimiento del marcador.
        """
        self.logger.info(f"Iniciando exploración de {size}x{size} bloques...")
        self.map_data = {}
        
        # Determinar el centro del área explorada
        target_center_x = int(start_pos.x + size // 2)
        target_center_z = int(start_pos.z + size // 2)
        
        # Guardar el centro del área en el contexto
        self.context["target_zone"] = {"x": target_center_x, "z": target_center_z}
        
        # Posición inicial (x, z) de la esquina superior-oeste
        x_start = int(start_pos.x)
        z_start = int(start_pos.z)

        # Mover el bot a la posición inicial (visual) antes de empezar
        try:
            # FIX: Usar _get_solid_ground_y en vez de getHeight
            y_surface_start = self._get_solid_ground_y(x_start, z_start)
            self.exploration_position = Vec3(x_start, y_surface_start + 1, z_start) # +1 para estar de pie
            self._update_marker(self.exploration_position) 
        except Exception:
             pass

        for x in range(x_start, x_start + size):
            for z in range(z_start, z_start + size):
                
                # --- FIX CRÍTICO: Verificación de pausa/stop ---
                if self.state != AgentState.RUNNING:
                    # Si es PAUSED, salimos inmediatamente. Si es STOPPED/ERROR, también.
                    self.logger.info(f"Exploración interrumpida, estado: {self.state.name}.")
                    return 

                # 1. Movimiento del marcador y pausa asíncrona
                try:
                    # FIX: Usar _get_solid_ground_y para la altura actual
                    y_surface = self._get_solid_ground_y(x, z)
                    
                    # Mover marcador (visualización de movimiento)
                    self.exploration_position = Vec3(x, y_surface + 1, z) 
                    self._update_marker(self.exploration_position)
                    
                    # Pausa ASÍNCRONA: Cede el control al event loop para procesar mensajes
                    await asyncio.sleep(0.01) # Muy corto para inmediatez en comandos
                    
                    # 2. Obtener bloques y registrarlos
                    for y in range(y_surface - 2, y_surface + 3): # Rango de 5 bloques alrededor de la superficie
                        block_id = self.mc.getBlock(x, y, z)
                        block_name = EXPLORATION_BLOCKS.get(block_id, "unknown")
                        
                        # Si el bloque es un material de interés (no aire/agua/lava/desconocido), lo registramos y pasamos al siguiente (x,z)
                        if block_name not in ("air", "water", "lava", "unknown"):
                             self.map_data[(x, y, z)] = block_name
                             break 
                        
                except Exception as e:
                    self.logger.error(f"Error en MC (getHeight/setBlock durante exploración): {e}")
                    await asyncio.sleep(0.1) # Pausa si hay error


    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            params = payload.get("parameters", {})
            args = params.get('args', [])

            if command == 'start':
                self._parse_start_params(params)
                self.map_data = {} # Resetear el mapa
                self.state = AgentState.RUNNING
            
            elif command == 'set':
                # Manejar /explorer set range <int>
                if len(args) >= 2 and args[0] == 'range':
                    try:
                        new_range = int(args[1])
                        self.exploration_size = new_range
                        self.logger.info(f"Rango de exploración actualizado a: {new_range}x{new_range}")
                        
                        # Publicar ACK/Update (Requisito opcional, pero buena práctica)
                        # Nota: En un sistema real, enviaríamos un 'update.status.v1'
                        
                    except ValueError:
                        self.logger.error(f"Valor de rango inválido: {args[1]}")
                
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': 
                self.handle_resume()
            elif command == 'stop': self.handle_stop()
            # El comando 'status' es gestionado por el Manager (en agent_manager.py), lo ignoramos aquí.

    def _parse_start_params(self, params: Dict[str, Any]):
        """Actualiza la posición inicial (esquina) y el tamaño del área a explorar."""
        args = params.get('args', [])
        
        # Valores por defecto
        # FIX: new_size debe leer la configuración actual si no se proporciona.
        new_size = self.exploration_size if self.exploration_size > 0 else 30 
        new_x, new_z = None, None
        
        # Lógica de parseo
        arg_map = {}
        for arg in args:
             if '=' in arg:
                 key, val = arg.split('=', 1)
                 arg_map[key] = val
        
        # 1. Leer tamaño y coordenadas desde los argumentos
        if 'range' in arg_map:
            try: new_size = int(arg_map['range'])
            except: pass
        if 'x' in arg_map:
            try: new_x = int(arg_map['x'])
            except: pass
        if 'z' in arg_map:
            try: new_z = int(arg_map['z'])
            except: pass


        # 2. Si faltan X/Z, usar posición del jugador
        if new_x is None or new_z is None:
            try:
                # Usamos la posición del jugador para anclar la exploración
                pos = self.mc.player.getTilePos()
                if new_x is None: new_x = pos.x
                if new_z is None: new_z = pos.z
                self.logger.info(f"Usando posición del jugador para START: ({new_x}, {new_z})")
            except Exception as e:
                self.logger.warning(f"No se pudo obtener posición jugador. Usando 0, 0. Error: {e}")
                if new_x is None: new_x = 0
                if new_z is None: new_z = 0

        # 3. Aplicar los valores (la posición de inicio es la esquina)
        self.exploration_size = new_size
        self.exploration_position.x = new_x
        self.exploration_position.z = new_z
        
        self.logger.info(f"Configuración de exploración: {new_size}x{new_size} desde ({new_x}, Z={new_z})")


    async def _publish_map_data(self):
        """Publica los datos del mapa y la ubicación recomendada al BuilderBot."""
        
        if not self.context.get("target_zone"):
             self.context["target_zone"] = {"x": int(self.exploration_position.x + self.exploration_size // 2),
                                            "z": int(self.exploration_position.z + self.exploration_size // 2)}
             
        # Simular cálculo de materiales: 50 Stone y 50 Dirt como requerimiento inicial
        required_materials = self._calculate_materials_needed()
        
        map_message = {
            "type": "map.v1", 
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                # Esta estructura cumple con el esquema map.v1 de core/json_validator.py
                "exploration_area": f"({self.exploration_position.x},{self.exploration_position.z}) size {self.exploration_size}",
                "elevation_map": [64.0],
                "optimal_zone": {"center": self.context["target_zone"], "variance": 1.0},
            },
            "context": {"required_bom": required_materials},
            "status": "SUCCESS"
        }
        await self.broker.publish(map_message)
        self.logger.info(f"Datos de mapa y zona objetivo publicado a BuilderBot. BOM solicitado: {required_materials}")
        
    def _calculate_materials_needed(self) -> Dict[str, int]:
        """
        Define el BoM inicial requerido por el BuilderBot (50 Stone, 50 Dirt).
        """
        # BOM para el Simple Shelter (solo piedra y tierra)
        bom = {
            "stone": 50,  
            "dirt": 50,   
        }
        return bom