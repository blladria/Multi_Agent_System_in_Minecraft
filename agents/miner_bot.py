# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block

# Importar las clases de estrategia (Patrón Estrategia)
from strategies.base_strategy import BaseMiningStrategy
from strategies.vertical_search import VerticalSearchStrategy
from strategies.grid_search import GridSearchStrategy
from strategies.vein_search import VeinSearchStrategy 

# Diccionario de materiales para simulación (material: ID de bloque MC)
MATERIAL_MAP = {
    "wood": block.WOOD.id, 
    "wood_planks": block.WOOD_PLANKS.id,
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id, # COBBLESTONE es clave para la construcción
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id,
    "door_wood": block.DOOR_WOOD.id,
    "dirt": block.DIRT.id
}

class MinerBot(BaseAgent):
    """
    Agente responsable de la extracción y colección de materiales (Patrón Estrategia).
    Implementa selección de estrategia adaptativa basada en requisitos.
    """
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        # Inicializa el inventario con las claves de materiales que espera manejar
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        # --- POSICIÓN INICIAL DE TRABAJO PREDETERMINADA (Y visible) ---
        self.mining_position: Vec3 = Vec3(10, 65, 10)
        # ---------------------------------------------
            
        self.mining_sector_locked = False 
        
        # --- NUEVOS CAMPOS PARA EL DESPLAZAMIENTO DE MINERÍA ---
        # Ancla base del BuilderBot (donde se quiere construir)
        self._base_build_anchor: Vec3 = Vec3(0, 0, 0)
        # Contador de ciclos de minería completados (usado para desplazar el nuevo pozo)
        self._mining_offset: int = 0
        # --------------------------------------------------------
        
        # Registro de estrategias
        self.strategy_classes: Dict[str, Type[BaseMiningStrategy]] = { 
            "vertical": VerticalSearchStrategy,
            "grid": GridSearchStrategy,
            "vein": VeinSearchStrategy,
        }
        self.current_strategy_name = "vertical" 
        self.current_strategy_instance: BaseMiningStrategy = VerticalSearchStrategy(
            self.mc, 
            self.logger
        )
        
        # Marcador Amarillo (Lana Amarilla = data 4)
        self._set_marker_properties(block.WOOL.id, 4)

    # --- Lógica de Programación Funcional (Agregación) ---
    
    def get_total_volume(self) -> int:
        return sum(self.inventory.values())

    def _check_requirements_fulfilled(self) -> bool:
        if not self.requirements:
            return False
        return all(self.inventory.get(material, 0) >= required_qty 
                   for material, required_qty in self.requirements.items())

    # --- Lógica de Extracción REAL (CORREGIDA) ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        """
        Rompe el bloque y actualiza el inventario, aplicando la limitación estricta de requisitos.
        """
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        try:
            current_block_id = self.mc.getBlock(x, y, z)
        except Exception as e:
            self.logger.error(f"Error al obtener bloque en MC ({x}, {y}, {z}): {e}")
            return False

        if current_block_id == block.AIR.id:
            return False

        # 1. Simular qué material se extrae (DROP logic)
        material_dropped = None
        
        if current_block_id in [block.GRASS.id, block.DIRT.id]:
            material_dropped = "dirt" 
        elif current_block_id == block.STONE.id:
            # FIX CRÍTICO: Minar STONE (ID 1) siempre produce COBBLESTONE (ID 4)
            material_dropped = "cobblestone"
        elif current_block_id == block.COBBLESTONE.id:
            material_dropped = "cobblestone"
        elif current_block_id in [block.WOOD.id, block.LEAVES.id]:
            material_dropped = "wood"
        
        # Para minerales (ej. DIAMOND_ORE), asumimos que el ID del bloque es el nombre del material para la veta
        for name, id in MATERIAL_MAP.items():
            if id == current_block_id and name not in ["dirt", "cobblestone", "wood"]:
                material_dropped = name
                break
        
        
        # 2. Verificar si el material extraído es un REQUISITO PENDIENTE
        material_to_count = None
        if material_dropped and material_dropped in self.requirements:
            required_qty = self.requirements.get(material_dropped, 0)
            current_qty = self.inventory.get(material_dropped, 0)

            if current_qty < required_qty:
                material_to_count = material_dropped
                
        # 3. Romper el Bloque en Minecraft
        try:
            self.mc.setBlock(x, y, z, block.AIR.id)
            
            # 4. Actualizar Inventario (LÓGICA DE DETENCIÓN CRÍTICA)
            if material_to_count:
                # El material_to_count ya pasó el filtro de ser un requisito y estar pendiente
                self.inventory[material_to_count] = self.inventory.get(material_to_count, 0) + 1
                required_qty = self.requirements.get(material_to_count, 0) # Re-obtener la cantidad
                self.logger.info(f"EXTRAÍDO 1 de {material_to_count}. Total: {self.inventory[material_to_count]}/{required_qty}")
            else:
                self.logger.debug(f"Bloque minado ID:{current_block_id}. Material '{material_dropped}' no requerido o completado. Bloque desechado.")
                
            return True
        except Exception as e:
            self.logger.error(f"Error al romper bloque en MC: {e}")
            return False

    # --- Ciclo Perceive-Decide-Act ---
    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                await self._complete_mining_cycle() 
                self.state = AgentState.IDLE 
            else:
                 # FIX CRÍTICO: Re-evaluar estrategia CADA ciclo si aún se está minando.
                 await self._select_adaptive_strategy()
                 
                 if not self.mining_sector_locked:
                    self.mining_sector_locked = True

    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            
            # 1. Usamos el X/Z de la posición de minería (el pozo actual).
            x_working = int(self.mining_position.x)
            z_working = int(self.mining_position.z)
            
            # 2. Obtenemos la altura real de la superficie para la visualización.
            try:
                 # getHeight devuelve el bloque sólido más alto. Se suma 1 para que el marcador esté por encima.
                 display_y = self.mc.getHeight(x_working, z_working) + 1
            except Exception:
                 # Fallback si falla getHeight o conexión a MC.
                 display_y = 70 
                 
            # 3. Actualizamos el marcador en la posición visible de la superficie.
            marker_position_visible = Vec3(x_working, display_y, z_working)
            self._update_marker(marker_position_visible) 
            
            # Continúa con la ejecución de la estrategia
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position, # Mantenemos la posición interna (con Y profunda) para la lógica de la estrategia.
                mine_block_callback=self._mine_current_block 
            )
            await self._publish_inventory_update(status="PENDING")
            
    # --- Control y Sincronización ---
    def release_locks(self):
        if self.mining_sector_locked:
            self.mining_sector_locked = False
            self.logger.info("Lock de sector de minería liberado.")
            
    async def _complete_mining_cycle(self):
        await self._publish_inventory_update(status="SUCCESS")
        self.release_locks()
        
        # LÓGICA DE MOVIMIENTO MULTIPLE: Incrementa el offset después de completar un ciclo de suministro
        self._mining_offset += 1
        self.logger.info(f"Ciclo de minería completado. Offset incrementado a {self._mining_offset}.")


    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command == 'start' or command == 'fulfill':
                
                params = payload.get("parameters", {})
                self._parse_start_params(params)
                
                await self._select_adaptive_strategy() 
                
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else:
                    self.state = AgentState.IDLE
            elif command == 'set': self._parse_set_strategy(payload.get("parameters", {}))
            elif command == 'pause': self.handle_pause()
            elif command == 'resume': self.handle_resume()
            elif command == 'stop': self.handle_stop()
            
        elif msg_type == "materials.requirements.v1":
            
            self.requirements = payload.copy()
            self.logger.info(f"Requisitos de materiales recibidos: {self.requirements}")
            
            # --- MODIFICACION CLAVE: APLICAR DESPLAZAMIENTO A LA POSICIÓN DE MINERÍA ---
            target_zone = message.get("context", {}).get("target_zone")
            if target_zone and all(key in target_zone for key in ['x', 'z']):
                 
                 base_x = int(target_zone['x'])
                 base_z = int(target_zone['z'])
                 
                 # 1. Almacenar el ancla original (sólo para referencia, se puede omitir si no se necesita)
                 self._base_build_anchor = Vec3(base_x, 0, base_z)
                 
                 # 2. Calcular el desplazamiento (10 bloques por cada ciclo de minería previo completado)
                 offset = self._mining_offset * 10
                 
                 # 3. Aplicar las coordenadas desplazadas
                 self.mining_position.x = base_x + offset
                 self.mining_position.z = base_z + offset
                 
                 try:
                     y_surface = self.mc.getHeight(self.mining_position.x, self.mining_position.z)
                     self.mining_position.y = y_surface + 1 
                 except Exception:
                     self.mining_position.y = 65 
                     
                 # 4. Reiniciar la estrategia para que use la nueva posición (esto es crucial)
                 self.current_strategy_instance.__init__(self.mc, self.logger)
                 
                 self.logger.info(f"Posicion de mineria reajustada. Base: ({base_x}, {base_z}). Nuevo Inicio (Offset={offset}): ({self.mining_position.x}, {self.mining_position.y}, {self.mining_position.z})")
            # -------------------------------------------------------------
            
            await self._select_adaptive_strategy()
            
            if self.state in (AgentState.IDLE, AgentState.WAITING): 
                self.state = AgentState.RUNNING


    # --- NUEVO MÉTODO: Parsea parámetros o usa la posición del jugador ---
    def _parse_start_params(self, params: Dict[str, Any]):
        """Actualiza la posición de minería basada en argumentos o posición del jugador."""
        args = params.get('args', [])
        new_x, new_z = None, None
        
        # 1. Intentar leer del comando
        for arg in args:
            if arg.startswith('x='):
                try: new_x = int(arg.split('=')[1])
                except: pass
            elif arg.startswith('z='):
                try: new_z = int(arg.split('=')[1])
                except: pass

        # 2. Si falta alguno, usar posición del jugador
        if new_x is None or new_z is None:
            try:
                pos = self.mc.player.getTilePos()
                if new_x is None: new_x = pos.x
                if new_z is None: new_z = pos.z
                self.logger.info(f"Usando posición del jugador: {new_x}, {new_z}")
            except Exception as e:
                self.logger.warning(f"No se pudo obtener posición jugador: {e}")
                if new_x is None: new_x = self.mining_position.x
                if new_z is None: new_z = self.mining_position.z

        # 3. Aplicar
        self.mining_position.x = new_x
        self.mining_position.z = new_z
        try:
            self.mining_position.y = self.mc.getHeight(new_x, new_z) + 1
        except:
            pass # Mantener altura anterior si falla

        # Reiniciar instancia de estrategia para que tome la nueva posición como ancla
        StrategyClass = self.strategy_classes.get(self.current_strategy_name)
        if StrategyClass:
            self.current_strategy_instance = StrategyClass(self.mc, self.logger)


    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            new_strategy_name = args[1].lower()
            if new_strategy_name in self.strategy_classes:
                StrategyClass = self.strategy_classes[new_strategy_name]
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
                self.logger.info(f"Estrategia de mineria cambiada manualmente a: {new_strategy_name}")
            else:
                self.mc.postToChat(f"ERROR: Estrategia '{new_strategy_name}' no reconocida.")


    async def _select_adaptive_strategy(self):
        """
        Selecciona la estrategia de minería más adecuada basada en el material más requerido.
        Ajustado para priorizar la minería de superficie (Grid) para la tierra (Dirt).
        """
        if not self.requirements:
            new_strategy_name = "vertical" 
            if new_strategy_name != self.current_strategy_name:
                StrategyClass = self.strategy_classes[new_strategy_name]
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
            return 

        # 1. Determinar el material pendiente (ignorando los ya cumplidos)
        remaining_requirements = {mat: qty - self.inventory.get(mat, 0) 
                                  for mat, qty in self.requirements.items() if qty > self.inventory.get(mat, 0)}
        
        if not remaining_requirements:
            return 

        most_needed_material = max(remaining_requirements, key=remaining_requirements.get)
        
        # --- LÓGICA DE PRIORIDAD ESTRATÉGICA (FIX para el usuario) ---

        # Lista de materiales de alto valor (siempre priorizan Vein)
        vein_materials = ("diamond_ore", "iron_ore", "gold_ore", "lapis_lazuli_ore", "redstone_ore")
        
        # 2.1. REGLA 1: Priorizar Tierra (Dirt) con GridSearch (minería superficial)
        # Esto asegura que la tierra se recolecte primero, rompiendo el bloqueo.
        if remaining_requirements.get("dirt", 0) > 0:
            new_strategy_name = "grid"
            self.logger.info("Prioridad Estratégica: DIRT pendiente. Forzando GridSearch (Superficie).")
        
        # 2.2. REGLA 2: Minería de Veta (Alto Valor)
        elif most_needed_material in vein_materials:
            new_strategy_name = "vein"
            self.logger.info("Prioridad Estratégica: Mineral de Alto Valor pendiente. Forzando VeinSearch.")
            
        # 2.3. REGLA 3: Minería Profunda (Cobblestone/Stone) con VerticalSearch
        elif most_needed_material in ("cobblestone", "stone"):
            new_strategy_name = "vertical"
            self.logger.info("Prioridad Estratégica: Cobblestone/Stone pendiente. Forzando VerticalSearch (Profundo).")
            
        # 2.4. Fallback (Si se pide un material que no es dirt, cobble o vein_material)
        else:
             new_strategy_name = "vertical"
             self.logger.info(f"Prioridad Estratégica: Material '{most_needed_material}' pendiente. Usando VerticalSearch por defecto.")
        
        # --- FIN LÓGICA DE PRIORIDAD ESTRATÉGICA ---
        
        # 3. Aplicar la estrategia solo si es diferente
        if new_strategy_name != self.current_strategy_name:
            if new_strategy_name in self.strategy_classes:
                StrategyClass = self.strategy_classes[new_strategy_name]
                # Se reinicia la instancia para que use la nueva posición desplazada como ancla
                self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                self.current_strategy_name = new_strategy_name
                self.logger.info(f"Estrategia de mineria adaptada a: {new_strategy_name}")
                
                # Si se cambia a GRID, se reinician los anclajes internos para que la estrategia GridSearch se base en la nueva posición desplazada
                if new_strategy_name == "grid":
                     self.current_strategy_instance.start_x = None 
                     self.current_strategy_instance.start_z = None
                     self.current_strategy_instance.mining_y_level = None
                     self.logger.info("Estrategia GridSearch iniciada en la posición actual.")
                     
            else:
                self.logger.error(f"Estrategia adaptativa '{new_strategy_name}' no encontrada. Usando vertical.")
                self.current_strategy_instance = VerticalSearchStrategy(self.mc, self.logger)
                self.current_strategy_name = "vertical"

    async def _publish_inventory_update(self, status: str):
        total_volume = self.get_total_volume() 
        inventory_message = {
            "type": "inventory.v1",
            "source": self.agent_id,
            "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "collected_materials": self.inventory,
                "total_volume": total_volume
            },
            "status": status,
            "context": {"required_bom": self.requirements}
        }
        await self.broker.publish(inventory_message)
        self.logger.info(f"Inventario ({status}) publicado. Volumen total: {total_volume}")