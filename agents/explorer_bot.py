# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
# from mcpi import block 

class ExplorerBot(BaseAgent):
    """
    Agente responsable de analizar el terreno circundante para identificar zonas óptimas
    y estables para la construcción (Uso de Programación Funcional en el análisis).
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        self.exploration_params: Dict[str, Any] = {}
        self.map_data: Dict[str, Any] = {}
        self.target_position: Vec3 = None
        self.exploration_range = 30  # Rango por defecto
        self.is_exploring = False

    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING and not self.is_exploring and self.target_position:
            self.logger.info(f"Decidiendo iniciar exploracion en {self.target_position.x}, {self.target_position.z}")
            self.is_exploring = True
        elif self.state == AgentState.RUNNING and not self.target_position and not self.is_exploring:
            self.state = AgentState.IDLE

    async def act(self):
        if self.state == AgentState.RUNNING and self.is_exploring:
            self.logger.info(f"Act: Explorando area alrededor de ({self.target_position.x}, {self.target_position.z})...")
            
            await asyncio.sleep(2) 
            
            self.map_data = await self._scan_terrain()
            
            await self._publish_map_data()
            
            self.is_exploring = False
            self.target_position = None
            self.state = AgentState.IDLE

    # --- Manejo de Mensajes y Comandos (Omitido para brevedad) ---
    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        command = message.get("payload", {}).get("command_name")
        params = message.get("payload", {}).get("parameters", {})
        
        if msg_type.startswith("command."):
            if command == 'start':
                self._parse_start_command(params)
                self.state = AgentState.RUNNING
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
            elif command == 'set': self._parse_set_command(params)

    def _parse_start_command(self, params: Dict[str, Any]):
        try:
            args = params.get('args', []) 
            x = int(args[0].split('=')[1]) if len(args) > 0 and args[0].startswith('x=') else 0
            z = int(args[1].split('=')[1]) if len(args) > 1 and args[1].startswith('z=') else 0
            for arg in args:
                if arg.startswith('range='):
                    self.exploration_range = int(arg.split('=')[1])
                    
            self.target_position = Vec3(x, self.mc.getHeight(x, z), z)
            self.logger.info(f"Parametros de exploracion cargados: Centro=({x}, {z}), Rango={self.exploration_range}")
            
            if self.is_exploring:
                self.logger.warning("Exploracion activa. La nueva solicitud interrumpe el proceso.")
                self.is_exploring = False
                
        except Exception as e:
            self.logger.error(f"Error al parsear comando START para ExplorerBot: {e}")
            self.mc.postToChat(f"ERROR: /explorer start requiere x=<int> z=<int> validos. Error: {e}")

    def _parse_set_command(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'range':
            try:
                self.exploration_range = int(args[1])
                self.logger.info(f"Rango de exploracion actualizado a {self.exploration_range}")
            except ValueError:
                self.mc.postToChat("ERROR: /explorer set range requiere un valor entero.")

    # --- Lógica de Terreno (FUNCIONAL) ---

    async def _scan_terrain(self) -> Dict[str, Any]:
        """
        Escanea el terreno usando list comprehension y funciones agregadas 
        (map, min/max) para un análisis funcional de la varianza.
        """
        self.logger.info("Escaneando el terreno (ANALISIS FUNCIONAL)...")
        
        start_x, start_z = int(self.target_position.x), int(self.target_position.z)
        half_range = self.exploration_range // 2
        
        # --- APLICACIÓN FUNCIONAL (List Comprehension/Generators) ---
        
        # Generador que recorre todas las posiciones y obtiene la altura
        height_generator = (
            self.mc.getHeight(x, z)
            for x in range(start_x - half_range, start_x + half_range)
            for z in range(start_z - half_range, start_z + half_range)
        )
        # La conversión a lista permite el uso de min/max y cálculos posteriores
        heights = list(height_generator)
        
        # Análisis funcional de los datos recolectados
        min_height = min(heights)
        max_height = max(heights)

        # -------------------------------------------------------------

        variance = max_height - min_height
        
        optimal_zone = {
            "center": {"x": start_x, "z": start_z, "y_avg": (max_height + min_height) / 2},
            "size": self.exploration_range,
            "variance": variance
        }

        await asyncio.sleep(3) 

        return {
            "exploration_area": f"({start_x-half_range},{start_z-half_range}) a ({start_x+half_range},{start_z+half_range})",
            "optimal_zone": optimal_zone,
            "is_flat": variance <= 5 
        }

    async def _publish_map_data(self):
        map_payload = self.map_data
        
        map_message = {
            "type": "map.v1",
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "exploration_area": map_payload.get("exploration_area"),
                "elevation_map": [map_payload['optimal_zone']['y_avg']], 
                "optimal_zone": map_payload.get("optimal_zone"),
            },
            "status": "SUCCESS" if map_payload.get('is_flat') else "PENDING",
            "context": {"task_id": "EXP-" + datetime.now().strftime("%H%M%S")}
        }
        
        await self.broker.publish(map_message)
        self.logger.info(f"Datos de mapa (map.v1) publicados. Varianza: {map_payload['optimal_zone']['variance']}")