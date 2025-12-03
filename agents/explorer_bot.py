# -*- coding: utf-8 -*-
import asyncio
import logging
import statistics
from typing import Dict, Any, Tuple, List
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block
from datetime import datetime, timezone

# --- DEFINICIÓN DE BLOQUES DE INTERÉS ---
# Estos son los bloques que el explorador sabe reconocer.
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
    1. Explora un área cuadrada definida.
    2. Genera un mapa de elevación.
    3. Analiza la varianza del terreno para sugerir la mejor construcción.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        # Configuración inicial por defecto
        self.exploration_size = 30 
        self.exploration_position: Vec3 = Vec3(0, 0, 0)
        
        # Aquí guardaremos los datos del terreno: {(x,y,z): "tipo_bloque"}
        self.map_data: Dict[Tuple[int, int, int], str] = {}
        
        # VISUALIZACIÓN: Marcador Azul (Lana Azul = data 11)
        # Esto ayuda a ver dónde está el "ojo" del explorador en el juego.
        self._set_marker_properties(block.WOOL.id, 11)

    # --- CICLO DE VIDA (Perceive - Decide - Act) ---
    
    async def perceive(self):
        """Lee mensajes del sistema (comandos de inicio, parada, etc)."""
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        """Toma decisiones basadas en su estado actual."""
        # Si está en RUNNING pero no tiene datos, decide que debe empezar a explorar.
        if self.state == AgentState.RUNNING and not self.map_data and self.exploration_size > 0:
            self.logger.info(f"Decidiendo iniciar exploración en {self.exploration_position} con tamaño {self.exploration_size}")
        
        # Si ya terminó (RUNNING pero sin tarea), pasa a IDLE.
        elif self.state == AgentState.RUNNING and not self.map_data and self.exploration_size == 0:
             self.state = AgentState.IDLE 

    async def act(self):
        """Ejecuta la acción principal: Explorar el terreno."""
        if self.state == AgentState.RUNNING and self.exploration_size > 0:
            
            # --- ACCIÓN PRINCIPAL: ESCANEAR EL ÁREA ---
            # Esta función toma tiempo porque mueve el cursor por el mundo.
            await self._explore_area(self.exploration_position, self.exploration_size)
            
            # --- POST-ACCIÓN: ANALIZAR Y PUBLICAR ---
            # Si seguimos en RUNNING (no nos pararon a mitad), publicamos resultados.
            if self.state == AgentState.RUNNING:

                if self.map_data:
                    self.logger.info("Exploración física terminada. Procesando datos...")
                    await self._publish_map_data()
                else: 
                    self.logger.warning("Exploración finalizada sin datos. ¿Estaba el área vacía?")
                
                # Limpieza y reseteo
                self.exploration_size = 0
                self.map_data = {}
                self.state = AgentState.IDLE
                self._clear_marker() # Quitamos el marcador azul
            
            elif self.state == AgentState.PAUSED:
                self.logger.info("Exploración pausada. Esperando comando 'resume'.")
            
            elif self.state == AgentState.ERROR:
                self.logger.error("La exploración terminó con errores.")

    # --- INTELIGENCIA: ANÁLISIS ESTADÍSTICO DEL TERRENO ---

    def _calculate_terrain_variance(self) -> float:
        """
        Calcula qué tan 'irregular' es el terreno usando la varianza estadística de las alturas.
        Retorna: Un número float (0.0 = perfectamente plano, >10.0 = muy montañoso).
        """
        # Filtramos solo los puntos que representan la superficie del suelo
        heights = [y for (x, y, z), mat in self.map_data.items() if mat == "surface"]
        
        # Necesitamos al menos 2 puntos para calcular varianza
        if len(heights) < 2:
            return 0.0
            
        try:
            # La librería 'statistics' hace el cálculo matemático duro por nosotros
            variance = statistics.variance(heights)
            return variance
        except Exception as e:
            self.logger.error(f"Error calculando varianza: {e}")
            return 0.0

    def _suggest_template_based_on_terrain(self, variance: float) -> str:
        """
        Reglas lógicas para elegir la construcción:
        
        1. Si Varianza < 1.0: El terreno es muy plano (ideal para cimientos grandes).
           -> Sugerencia: "storage_bunker" (ocupa 4x4).
           
        2. Si Varianza < 3.0: El terreno tiene pequeñas irregularidades (normal).
           -> Sugerencia: "simple_shelter" (ocupa 3x3, estándar).
           
        3. Si Varianza >= 3.0: El terreno es caótico o montañoso.
           -> Sugerencia: "watch_tower" (ocupa poco espacio 3x3 y es vertical).
        """
        if variance < 1.0:
            return "storage_bunker"
        elif variance < 3.0:
            return "simple_shelter"
        else:
            return "watch_tower"

    # --- HERRAMIENTAS DE MINECRAFT ---

    def _get_solid_ground_y(self, x: int, z: int) -> int:
        """
        Encuentra la altura Y real del suelo sólido.
        Ignora bloques 'blandos' como flores, nieve, hojas o hierba alta.
        """
        try:
            # mc.getHeight nos da el bloque más alto (incluyendo árboles o flores)
            y = self.mc.getHeight(x, z)
        except Exception:
            return 65 # Altura por defecto si falla la API

        # Lista de bloques que NO consideramos suelo firme
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

        # Buscamos hacia abajo hasta 5 bloques para encontrar tierra firme
        for _ in range(5): 
            block_id = self.mc.getBlock(x, y, z)
            if block_id not in NON_SOLID_BLOCKS:
                return y # Encontramos suelo
            y -= 1
            if y < 1: return 1 # No bajar del fondo del mundo
            
        return y

    async def _explore_area(self, start_pos: Vec3, size: int):
        """
        Recorre el área definida (cuadrada) registrando la altura del suelo.
        Mueve visualmente un bloque marcador.
        """
        self.logger.info(f"Comenzando barrido de terreno: {size}x{size} bloques.")
        self.map_data = {}
        
        # Calcular el centro para que el Builder sepa dónde construir
        target_center_x = int(start_pos.x + size // 2)
        target_center_z = int(start_pos.z + size // 2)
        
        # Guardamos la zona objetivo en el contexto
        self.context["target_zone"] = {"x": target_center_x, "z": target_center_z}
        
        x_start = int(start_pos.x)
        z_start = int(start_pos.z)

        # Colocar marcador inicial
        try:
            y_start = self._get_solid_ground_y(x_start, z_start)
            self._update_marker(Vec3(x_start, y_start + 2, z_start)) 
        except Exception: pass

        # BUCLE DE ESCANEO
        # Usamos un 'step' de 2 (saltar un bloque) para hacerlo más rápido en la demo.
        step = 2
        for x in range(x_start, x_start + size, step):
            for z in range(z_start, z_start + size, step):
                
                # Chequeo de seguridad: Si nos pausan o paran, salimos del bucle
                if self.state != AgentState.RUNNING:
                    return 

                try:
                    # 1. Obtener altura del suelo
                    y_surface = self._get_solid_ground_y(x, z)
                    
                    # 2. Mover el marcador visual (El bloque azul)
                    self.exploration_position = Vec3(x, y_surface + 1, z) 
                    self._update_marker(self.exploration_position)
                    
                    # 3. Importante: ceder control con await para leer mensajes entrantes
                    await self.perceive() 
                    await asyncio.sleep(0.001) # Pausa mínima para no bloquear el servidor
                    
                    # 4. Guardar dato
                    self.map_data[(x, y_surface, z)] = "surface"
                        
                except Exception as e:
                    self.logger.error(f"Error leyendo bloque en ({x},{z}): {e}")
                    await asyncio.sleep(0.1)


    async def _publish_map_data(self):
        """
        Empaqueta los resultados, toma la decisión inteligente y se la envía al BuilderBot.
        """
        # Asegurarnos de que tenemos una zona objetivo definida
        if not self.context.get("target_zone"):
             self.context["target_zone"] = {"x": int(self.exploration_position.x), "z": int(self.exploration_position.z)}
        
        # 1. Ejecutar la lógica de IA (Varianza + Sugerencia)
        variance = self._calculate_terrain_variance()
        suggested_template = self._suggest_template_based_on_terrain(variance)
        
        self.logger.info(f"ANÁLISIS: Varianza={variance:.2f} -> Sugerencia={suggested_template}")
        
        # 2. Mensaje al Chat del juego (Feedback al usuario)
        self.mc.postToChat(f"[Explorer] Terreno analizado (Var: {variance:.1f}). Sugiero: {suggested_template}")

        # 3. Construir mensaje JSON
        map_message = {
            "type": "map.v1", 
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "exploration_area": f"size {self.exploration_size}",
                "elevation_map": [64.0], # Dato simbólico requerido por el esquema
                "optimal_zone": {"center": self.context["target_zone"], "variance": variance},
                
                # --- AQUÍ VA LA INTELIGENCIA ---
                "suggested_template": suggested_template,
                "terrain_variance": variance
            },
            "context": {"target_zone": self.context["target_zone"]}, 
            "status": "SUCCESS"
        }
        
        # 4. Enviar
        await self.broker.publish(map_message)
        self.logger.info("Mensaje map.v1 enviado al BuilderBot.")


    async def _handle_message(self, message: Dict[str, Any]):
        """Maneja los comandos entrantes."""
        msg_type = message.get("type")
        payload = message.get("payload", {})
        args = payload.get("parameters", {}).get('args', [])

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            params = payload.get("parameters", {})
            
            if command == 'start':
                
                # Se mantiene la lógica de start/parse (ya funciona bien)
                self._parse_start_params(params)
                self.map_data = {} # Resetear memoria anterior
                self.state = AgentState.RUNNING

                # --- MEJORA DE FEEDBACK ---
                self.logger.info(f"Comando 'start' recibido. Iniciando exploración.")
                self.mc.postToChat(f"[Explorer] 🗺️ Exploración iniciada en ({int(self.exploration_position.x)}, {int(self.exploration_position.z)}), rango: {self.exploration_size}x{self.exploration_size}. Estado: RUNNING.")
                # --- FIN MEJORA ---
            
            elif command == 'stop': 
                self.handle_stop()
                # --- MEJORA DE FEEDBACK ---
                self.logger.info(f"Comando 'stop' recibido. Exploración detenida y estado guardado.")
                self.mc.postToChat(f"[Explorer] 🛑 Exploración detenida. Estado: STOPPED.")
                self._clear_marker() # Aseguramos que el marcador desaparezca
                # --- FIN MEJORA ---

            
            elif command == 'set':
                # Permite cambiar el tamaño: /explorer set range=<int>
                arg_map = {}
                for arg in args:
                    if '=' in arg:
                        key, val = arg.split('=', 1)
                        arg_map[key] = val
                if 'range' in arg_map:
                    try: 
                        new_range = int(arg_map['range'])
                        
                        # FIX: Confirmación de cambio de rango
                        if new_range != self.exploration_size:
                            self.exploration_size = new_range
                            
                            # --- MEJORA DE FEEDBACK ---
                            self.logger.info(f"Comando 'set range' recibido. Nuevo rango: {new_range}.")
                            self.mc.postToChat(f"[Explorer] 📏 Rango de exploración cambiado a: {new_range}x{new_range}.")
                            # --- FIN MEJORA ---
                        
                    except ValueError:
                        self.mc.postToChat(f"[Explorer] ❌ Error: El rango '{arg_map['range']}' debe ser un número entero.")
                    except Exception as e:
                         self.logger.error(f"Error al cambiar rango: {e}")
            
            elif command == 'status':
                await self._publish_status()
                
            elif command == 'pause':
                self.handle_pause()
                self.logger.info(f"Comando 'pause' recibido. Estado: PAUSED.")
                self.mc.postToChat(f"[Explorer] ⏸️ Pausado. Estado: PAUSED.")
                
            elif command == 'resume':
                self.handle_resume()
                self.logger.info(f"Comando 'resume' recibido. Estado: RUNNING.")
                self.mc.postToChat(f"[Explorer] ▶️ Reanudado. Estado: RUNNING.")


    def _parse_start_params(self, params: Dict[str, Any]):
        """Lee coordenadas y rango del comando de inicio."""
        args = params.get('args', [])
        # new_size conserva el valor actual/por defecto (30) si no se especifica
        new_size = self.exploration_size if self.exploration_size > 0 else 30 
        new_x, new_z = None, None
        
        arg_map = {}
        for arg in args:
             if '=' in arg:
                 key, val = arg.split('=', 1)
                 arg_map[key] = val
        
        if 'range' in arg_map:
            try: new_size = int(arg_map['range'])
            except: pass
        if 'x' in arg_map:
            try: new_x = int(arg_map['x'])
            except: pass
        if 'z' in arg_map:
            try: new_z = int(arg_map['z'])
            except: pass

        # Si no dan coordenadas, usamos la posición del jugador
        if new_x is None or new_z is None:
            try:
                pos = self.mc.player.getTilePos()
                if new_x is None: new_x = pos.x
                if new_z is None: new_z = pos.z
            except Exception:
                # Fallback al origen del mundo
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
        # --- MEJORA DE FEEDBACK ---
        self.logger.info(f"Comando 'status' recibido. Reportando: {self.state.name}")
        # --- FIN MEJORA ---
        try: self.mc.postToChat(status_message)
        except: pass