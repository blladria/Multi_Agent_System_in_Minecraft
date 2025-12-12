# -*- coding: utf-8 -*-
import asyncio
import logging
import statistics
from functools import reduce  
from typing import Dict, Any, Tuple, List
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block
from datetime import datetime, timezone

# --- DEFINICIÓN DE BLOQUES DE INTERÉS ---
EXPLORATION_BLOCKS = {
    block.DIRT.id: "dirt",
    block.GRASS.id: "dirt", 
    block.STONE.id: "stone",
    block.COBBLESTONE.id: "stone", 
    block.WATER.id: "water",
    block.LAVA.id: "lava",
    block.AIR.id: "air",
    block.SAND.id: "sand",
    block.GRAVEL.id: "gravel"
}

class ExplorerBot(BaseAgent):
    """
    Agente ExplorerBot:
    Encargado de escanear el terreno, calcular la varianza y sugerir plantillas
    utilizando paradigmas funcionales.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.exploration_size = 30 
        self.exploration_position: Vec3 = Vec3(0, 0, 0)
        
        self.map_data: Dict[Tuple[int, int, int], str] = {}
        
        self._set_marker_properties(block.WOOL.id, 11)

    # --- CICLO DE VIDA (Perceive - Decide - Act) ---
    
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING and not self.map_data and self.exploration_size > 0:
            self.logger.info(f"Decidiendo iniciar exploración en {self.exploration_position} con tamaño {self.exploration_size}")
        
        elif self.state == AgentState.RUNNING and not self.map_data and self.exploration_size == 0:
             self.state = AgentState.IDLE 

    async def act(self):
        if self.state == AgentState.RUNNING and self.exploration_size > 0:
            
            await self._explore_area(self.exploration_position, self.exploration_size)
            
            if self.state == AgentState.RUNNING:

                if self.map_data:
                    self.logger.info("Exploración física terminada. Procesando datos...")
                    await self._publish_map_data()
                else: 
                    self.logger.warning("Exploración finalizada sin datos. ¿Estaba el área vacía?")
                
                self.exploration_size = 0
                self.map_data = {}
                self.state = AgentState.IDLE
                self._clear_marker() 
            
            elif self.state == AgentState.PAUSED:
                self.logger.info("Exploración pausada. Esperando comando 'resume'.")
            
            elif self.state == AgentState.ERROR:
                self.logger.error("La exploración terminó con errores.")

    # --- INTELIGENCIA: ANÁLISIS ESTADÍSTICO DEL TERRENO (Funcional) ---

    def _calculate_terrain_variance(self) -> float:
        """
        Calcula la varianza de altura del terreno explorado.
        """
        # Filtrar solo puntos de superficie
        surface_items = filter(lambda item: item[1] == "surface", self.map_data.items())
        
        # Extraer solo la altura (y) de la clave (x, y, z)
        heights = list(map(lambda item: item[0][1], surface_items))
        
        if len(heights) < 2:
            return 0.0
            
        try:
            variance = statistics.variance(heights)
            return variance
        except Exception as e:
            self.logger.error(f"Error calculando varianza: {e}")
            return 0.0

    def _suggest_template_based_on_terrain(self, variance: float) -> str:
        if variance < 1.0:
            return "storage_bunker"
        elif variance < 3.0:
            return "simple_shelter"
        else:
            return "watch_tower"

    def _get_solid_ground_y(self, x: int, z: int) -> int:
        """
        Encuentra la altura Y real del suelo sólido.        
        """
        try:
            start_y = self.mc.getHeight(x, z)
        except Exception:
            return 65

        NON_SOLID_BLOCKS = [
            block.AIR.id, 
            block.SAPLING.id, 
            block.LEAVES.id, 
            block.COBWEB.id,
            block.GRASS_TALL.id, 
            block.FLOWER_YELLOW.id, 
            block.FLOWER_CYAN.id, 
            block.MUSHROOM_BROWN.id, 
            block.MUSHROOM_RED.id, 
            block.SNOW.id
        ]

        # Generar rango de alturas hacia abajo
        depths = range(start_y, start_y - 5, -1)
        
        # Obtener pares (y, block_id)
        blocks_data = map(lambda y: (y, self.mc.getBlock(x, y, z)), depths)
        
        # Filter para encontrar el primer bloque sólido
        # Usamos next() para obtener el primer elemento que cumpla la condición
        found_solid = next(
            filter(lambda data: data[1] not in NON_SOLID_BLOCKS, blocks_data),
            None
        )

        # Si encontramos uno, devolvemos su Y, si no, devolvemos start_y (fallback seguro)
        if found_solid:
            return found_solid[0]
        
        # Fallback de seguridad: evitar devolver None o caer bajo el mundo
        return max(start_y - 5, 1)

    async def _explore_area(self, start_pos: Vec3, size: int):
        self.logger.info(f"Comenzando barrido de terreno: {size}x{size} bloques.")
        self.map_data = {}
        
        target_center_x = int(start_pos.x + size // 2)
        target_center_z = int(start_pos.z + size // 2)
        
        self.context["target_zone"] = {"x": target_center_x, "z": target_center_z}
        
        x_start = int(start_pos.x)
        z_start = int(start_pos.z)

        try:
            y_start = self._get_solid_ground_y(x_start, z_start)
            self._update_marker(Vec3(x_start, y_start + 2, z_start)) 
        except Exception: pass

        step = 2
        for x in range(x_start, x_start + size, step):
            for z in range(z_start, z_start + size, step):
                
                if self.state != AgentState.RUNNING:
                    return 

                try:
                    y_surface = self._get_solid_ground_y(x, z)
                    
                    self.exploration_position = Vec3(x, y_surface + 1, z) 
                    self._update_marker(self.exploration_position)
                    
                    await self.perceive() 
                    await asyncio.sleep(0.001) 
                    
                    self.map_data[(x, y_surface, z)] = "surface"
                        
                except Exception as e:
                    self.logger.error(f"Error leyendo bloque en ({x},{z}): {e}")
                    await asyncio.sleep(0.1)


    async def _publish_map_data(self):
        if not self.context.get("target_zone"):
             self.context["target_zone"] = {"x": int(self.exploration_position.x), "z": int(self.exploration_position.z)}
        
        variance = self._calculate_terrain_variance()
        suggested_template = self._suggest_template_based_on_terrain(variance)
        
        self.logger.info(f"ANÁLISIS: Varianza={variance:.2f} -> Sugerencia={suggested_template}")
        
        self.mc.postToChat(f"[Explorer] Terreno analizado (Var: {variance:.1f}). Sugiero: {suggested_template}")

        map_message = {
            "type": "map.v1", 
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "exploration_area": f"size {self.exploration_size}",
                "elevation_map": [64.0], 
                "optimal_zone": {"center": self.context["target_zone"], "variance": variance},
                "suggested_template": suggested_template,
                "terrain_variance": variance
            },
            "context": {"target_zone": self.context["target_zone"]}, 
            "status": "SUCCESS"
        }
        
        await self.broker.publish(map_message)
        self.logger.info("Mensaje map.v1 enviado al BuilderBot.")


    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})
        args = payload.get("parameters", {}).get('args', [])

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            params = payload.get("parameters", {})
            
            if command == 'start':
                self._parse_start_params(params)
                self.map_data = {} 
                self.state = AgentState.RUNNING

                self.logger.info(f"Comando 'start' recibido. Iniciando exploración.")
                self.mc.postToChat(f"[Explorer] Exploración iniciada en ({int(self.exploration_position.x)}, {int(self.exploration_position.z)}), rango: {self.exploration_size}x{self.exploration_size}. Estado: RUNNING.")
            
            elif command == 'stop': 
                self.handle_stop()
                self.logger.info(f"Comando 'stop' recibido. Exploración detenida y estado guardado.")
                self.mc.postToChat(f"[Explorer] Exploración detenida. Estado: STOPPED.")
                self._clear_marker()

            elif command == 'set':
                # Procesamiento de argumentos 'key=value' con filter y map
                valid_args = filter(lambda a: '=' in a, args)
                split_args = map(lambda a: a.split('=', 1), valid_args)
                arg_map = dict(split_args)

                if 'range' in arg_map:
                    try: 
                        new_range = int(arg_map['range'])
                        
                        if new_range != self.exploration_size:
                            self.exploration_size = new_range
                            self.logger.info(f"Comando 'set range' recibido. Nuevo rango: {new_range}.")
                            self.mc.postToChat(f"[Explorer] Rango de exploración cambiado a: {new_range}x{new_range}.")
                        
                    except ValueError:
                        self.mc.postToChat(f"[Explorer] Error: El rango '{arg_map['range']}' debe ser un número entero.")
                    except Exception as e:
                         self.logger.error(f"Error al cambiar rango: {e}")
            
            elif command == 'status':
                await self._publish_status()
                
            elif command == 'pause':
                self.handle_pause()
                self.logger.info(f"Comando 'pause' recibido. Estado: PAUSED.")
                self.mc.postToChat(f"[Explorer]  Pausado. Estado: PAUSED.")
                
            elif command == 'resume':
                self.handle_resume()
                self.logger.info(f"Comando 'resume' recibido. Estado: RUNNING.")
                self.mc.postToChat(f"[Explorer]  Reanudado. Estado: RUNNING.")


    def _parse_start_params(self, params: Dict[str, Any]):
        """Lee coordenadas y rango usando filter y map."""
        args = params.get('args', [])
        new_size = self.exploration_size if self.exploration_size > 0 else 30 
        new_x, new_z = None, None
        
        # Creación de diccionario de argumentos con filter y map
        arg_map = dict(map(
            lambda a: a.split('=', 1),
            filter(lambda a: '=' in a, args)
        ))
        
        if 'range' in arg_map:
            try: new_size = int(arg_map['range'])
            except: pass
        if 'x' in arg_map:
            try: new_x = int(arg_map['x'])
            except: pass
        if 'z' in arg_map:
            try: new_z = int(arg_map['z'])
            except: pass

        if new_x is None or new_z is None:
            try:
                pos = self.mc.player.getTilePos()
                if new_x is None: new_x = pos.x
                if new_z is None: new_z = pos.z
            except Exception:
                if new_x is None: new_x = 0
                if new_z is None: new_z = 0

        self.exploration_size = new_size
        self.exploration_position.x = new_x
        self.exploration_position.z = new_z

    async def _publish_status(self):
        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | "
            f"Zona: ({int(self.exploration_position.x)}, {int(self.exploration_position.z)}) | "
            f"Tamaño: {self.exploration_size}x{self.exploration_size}"
        )
        self.logger.info(f"Comando 'status' recibido. Reportando: {self.state.name}")
        try: self.mc.postToChat(status_message)
        except: pass