# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from functools import reduce  
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block


from core.agent_manager import AgentDiscovery 
from strategies.base_strategy import BaseMiningStrategy 


from strategies.vertical_search import VerticalSearchStrategy 

# Mapeo de materiales
MATERIAL_MAP = {
    "wood": block.WOOD.id, 
    "wood_planks": block.WOOD_PLANKS.id,
    "stone": block.STONE.id, 
    "cobblestone": block.COBBLESTONE.id,
    "diamond_ore": block.DIAMOND_ORE.id,
    "glass": block.GLASS.id,
    "glass_pane": block.GLASS_PANE.id,
    "dirt": block.DIRT.id,
    "sand": block.SAND.id,
    "sandstone": block.SANDSTONE.id,
    "gravel": block.GRAVEL.id
}

class MinerBot(BaseAgent):
    """
    Agente MinerBot: Extrae recursos usando estrategias adaptativas.
Utiliza paradigmas funcionales para gestión de inventario y selección de objetivos.    """
    # Constante para definir el tamaño de la región que bloquea
    SECTOR_SIZE = 10 
    
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        # Posición de trabajo
        self.mining_position: Vec3 = Vec3(10, 65, 10)
        self.mining_sector_locked = False 
        self.locked_sector_id: str = "" 
        
        self.remote_locks: Dict[str, str] = {}
        self._mining_offset: int = 0
        self.surface_marker_y = 66 
        
        self.inventory_publish_counter = 0 
        self.publish_frequency = 5 
        
        # Estrategias Disponibles: DESCUBRIMIENTO DINÁMICO (Reflection)
        self.strategy_classes: Dict[str, Type[BaseMiningStrategy]] = AgentDiscovery.discover_strategies()
        
        self.current_strategy_name = "vertical" 
        InitialStrategy = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
        self.current_strategy_instance = InitialStrategy(self.mc, self.logger)
        
        self.manual_strategy_active = False
        
        self.logger.info(f"MinerBot: Estrategias descubiertas: {list(self.strategy_classes.keys())}. Inicial: {self.current_strategy_name}")
        self._set_marker_properties(block.WOOL.id, 4)

    def get_total_volume(self) -> int:
        # Uso de reduce para sumar valores
        return reduce(lambda acc, qty: acc + qty, self.inventory.values(), 0)

    def _check_requirements_fulfilled(self) -> bool:
        if not self.requirements: return False
        
        # Uso de filter para encontrar materiales pendientes
        pending_items = list(filter(
            lambda item: item[1] > self.inventory.get(item[0], 0),
            self.requirements.items()
        ))

        # Return True si la lista de pendientes está vacía
        return len(pending_items) == 0

    # --- LÓGICA DE EXTRACCIÓN FÍSICA ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        try:
            block_id = self.mc.getBlock(x, y, z)
        except: return False

        if block_id == block.AIR.id:
            return False

        # Identificar qué material obtenemos
        material_dropped = None
        
        # Lógica imperativa simple para mapeos directos
        if block_id in [block.GRASS.id, block.DIRT.id]:
            material_dropped = "dirt" 
        elif block_id in [block.STONE.id, block.COBBLESTONE.id, block.MOSS_STONE.id]:
            material_dropped = "cobblestone"
        elif block_id == block.SAND.id:
            material_dropped = "sand"
        elif block_id == block.SANDSTONE.id:
            material_dropped = "sandstone"
        elif block_id == block.GRAVEL.id:
            material_dropped = "gravel"
        elif block_id in [block.WOOD.id, block.LEAVES.id]:
            material_dropped = "wood"
        else:
             # Búsqueda inversa usando filter y next
             found = next(
                 filter(lambda item: item[1] == block_id, MATERIAL_MAP.items()), 
                 None
             )
             if found:
                 material_dropped = found[0]
        
        # Verificar si lo necesitamos
        material_to_count = None
        if material_dropped and material_dropped in self.requirements:
            req = self.requirements.get(material_dropped, 0)
            curr = self.inventory.get(material_dropped, 0)
            if curr < req:
                material_to_count = material_dropped

        # Acción Física: Romper
        try:
            self.mc.setBlock(x, y, z, block.AIR.id)
            
            if material_to_count:
                self.inventory[material_to_count] += 1
                req = self.requirements[material_to_count]
                
                self.logger.info(f"MINADO: {material_to_count} ({self.inventory[material_to_count]}/{req})")
                self.mc.postToChat(f"[Miner] +1 {material_to_count.upper()} en ({x},{y},{z}). Progreso: {self.inventory[material_to_count]}/{req}.")
            
            return True
        except: return False


    # --- CICLO DE VIDA ---

    async def perceive(self):
        if self.broker.has_messages(self.agent_id):
            message = await self.broker.consume_queue(self.agent_id)
            await self._handle_message(message)

    async def decide(self):
        if self.state == AgentState.RUNNING:
            if self._check_requirements_fulfilled():
                await self._complete_mining_cycle() 
                self.state = AgentState.IDLE 
                return 

            await self._select_adaptive_strategy()
                 
            current_sector_id = self._calculate_sector_id(self.mining_position)
            
            if current_sector_id in self.remote_locks:
                self.logger.warning(f"Sector {current_sector_id} bloqueado por {self.remote_locks[current_sector_id]}. Reubicando...")
                self.mining_position.x += self.SECTOR_SIZE
                
                try:
                    self.mining_position.y = self.mc.getHeight(self.mining_position.x, self.mining_position.z) + 1
                    self.surface_marker_y = self.mining_position.y
                except Exception:
                    self.mining_position.y = 65
                    self.surface_marker_y = 66
                
                self.logger.info(f"Nueva posición de minería: ({int(self.mining_position.x)}, {int(self.mining_position.y)}, {int(self.mining_position.z)})")
                await asyncio.sleep(0.5) 
                return 
                 
            if not self.mining_sector_locked:
                await self._acquire_lock()
                    
    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            try:
                 x, z = int(self.mining_position.x), int(self.mining_position.z)
                 y_surf = self.surface_marker_y 
                 self._update_marker(Vec3(x, y_surf, z))
            except: pass
            
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position, 
                mine_block_callback=self._mine_current_block 
            )
            
            self.inventory_publish_counter += 1
            if self.inventory_publish_counter >= self.publish_frequency:
                 await self._publish_inventory_update(status="PENDING")
                 self.inventory_publish_counter = 0
            
    # --- UTILS DE LOCKING ---
    
    def _calculate_sector_id(self, pos: Vec3) -> str:
        x_sector = int(pos.x // self.SECTOR_SIZE) * self.SECTOR_SIZE
        z_sector = int(pos.z // self.SECTOR_SIZE) * self.SECTOR_SIZE
        return f"{x_sector}_{z_sector}"

    async def _acquire_lock(self):
        self.mining_sector_locked = True
        self.locked_sector_id = self._calculate_sector_id(self.mining_position)
        
        await self._publish_lock_update(message_type="lock.spatial.v1")
        self.logger.info(f"Lock adquirido: Sector {self.locked_sector_id}")

    def release_locks(self):
        if self.mining_sector_locked:
            asyncio.create_task(self._publish_lock_update(message_type="unlock.spatial.v1"))
            
            self.mining_sector_locked = False
            self.locked_sector_id = ""
            self.logger.info("Lock liberado.")
        
        super().release_locks() 
        
    async def _publish_lock_update(self, message_type: str):
        sector_id = self._calculate_sector_id(self.mining_position)
        
        lock_message = {
            "type": message_type,
            "source": self.agent_id,
            "target": "All", 
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "sector_id": sector_id,
                "x": self.mining_position.x,
                "z": self.mining_position.z,
                "size": self.SECTOR_SIZE,
            },
            "status": "SUCCESS",
            "context": {"locked_sector": sector_id}
        }
        await self.broker.publish(lock_message)
        self.logger.info(f"Publicado: {message_type} para sector {sector_id}")


    async def _complete_mining_cycle(self):
        await self._publish_inventory_update(status="SUCCESS")
        self.release_locks()
        self._mining_offset += 1 
        self.logger.info("Ciclo minería completado.")
        self.mc.postToChat(f"[Miner] Ciclo de mineria completado. Requisitos cubiertos.")
        self._clear_marker()
    
    # --- MÉTODOS DE MANEJO DE ESTADO Y COMANDOS ---

    def _reset_mining_task(self, reset_requirements: bool = True, reset_inventory: bool = True):
        if self.mining_sector_locked:
            self.release_locks() 
            
        if reset_requirements:
             self.requirements = {}
        
        if reset_inventory:
            self.inventory = {mat: 0 for mat in MATERIAL_MAP.keys()}
            
        self._mining_offset = 0 
        self.state = AgentState.IDLE
        self.mining_sector_locked = False
        self.locked_sector_id = ""
        self.inventory_publish_counter = 0 
        
        StrategyClass = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
        self.current_strategy_instance = StrategyClass(self.mc, self.logger)

        self.logger.info(f"Tarea de mineria reseteada. Req: {not reset_requirements}, Inv: {not reset_inventory}")

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})
        params = payload.get("parameters", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            
            if command == 'fulfill':
                 await asyncio.sleep(0.5) 

                 if not self.requirements:
                     self.logger.warning("INTENTO FALLIDO: /miner fulfill llamado sin BOM previo del BuilderBot.")
                     self.mc.postToChat("[Miner] ERROR: No he recibido la lista de materiales del Builder.")
                     self.mc.postToChat("[Miner] REQUISITO: Ejecuta '/builder bom' primero.")
                     return
                 
                 self._reset_mining_task(reset_requirements=False, reset_inventory=True) 
                 self._parse_start_params(params)
                 
                 self.manual_strategy_active = False 

                 req_str = ", ".join([f"{q} {m}" for m, q in self.requirements.items()])
                 self.logger.info(f"Comando 'fulfill' recibido: Leyendo BOM del Builder. Objetivo: {req_str}")
                 target_pos = f"({int(self.mining_position.x)}, {int(self.mining_position.z)})"
                 self.mc.postToChat(f"[Miner] Tarea: Recolectar BOM de BuilderBot. Requisitos: {req_str}. Estrategia: {self.current_strategy_name.upper()}. Iniciando en {target_pos}.")
                 
                 await self._select_adaptive_strategy()
                 if not self._check_requirements_fulfilled():
                     self.state = AgentState.RUNNING
                 else: self.state = AgentState.IDLE
                 
            elif command == 'start':
                self._reset_mining_task(reset_requirements=True, reset_inventory=True) 
                self._parse_start_params(params)
                
                self.manual_strategy_active = False 

                if not self.requirements:
                    self.requirements = {"dirt": 40, "cobblestone": 40} 
                    self.logger.info("Iniciando mineria manual con tarea por defecto: 40 Dirt y 40 Cobblestone.")
                
                pending_dirt_or_sand = self.requirements.get("dirt", 0) > 0 or self.requirements.get("sand", 0) > 0
                if self.requirements and pending_dirt_or_sand:
                     self.current_strategy_name = 'grid'
                     StrategyClass = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
                     self.current_strategy_instance = StrategyClass(self.mc, self.logger)
                
                target_pos = f"({int(self.mining_position.x)}, {int(self.mining_position.z)})"
                req_str = ", ".join([f"{q} {m}" for m, q in self.requirements.items()])
                
                if self.requirements:
                    await self._select_adaptive_strategy() 
                    strat_name = self.current_strategy_name.upper()
                    self.mc.postToChat(f"[Miner] Mineria manual iniciada. Objetivo: {req_str}. Estrategia Inicial: {strat_name}. Iniciando en {target_pos}.")
                    
                    if not self._check_requirements_fulfilled():
                        self.state = AgentState.RUNNING
                    else: self.state = AgentState.IDLE
                    
            elif command == 'set': 
                old_strategy_name = self.current_strategy_name
                self._parse_set_strategy(params)
                
                if self.current_strategy_name in self.strategy_classes:
                    self.mc.postToChat(f"[Miner] Estrategia cambiada de {old_strategy_name.upper()} a: {self.current_strategy_name.upper()}.")
                    
                    self.manual_strategy_active = True
                    self.logger.info(f"Modo de estrategia manual activado: {self.current_strategy_name}")
                    
                    if self.state == AgentState.RUNNING and old_strategy_name != self.current_strategy_name:
                         self._reset_mining_task(reset_requirements=False, reset_inventory=True) 
                         
                         self.state = AgentState.RUNNING 
                         self.logger.info("Tarea de minería reiniciada para aplicar la nueva estrategia.")

            elif command == 'pause':
                self.handle_pause()
                self.logger.info(f"Comando 'pause' recibido. Estado: PAUSED.")
                self.mc.postToChat(f"[Miner] Pausado. Estado: PAUSED.")
                
            elif command == 'resume':
                self.handle_resume()
                self.logger.info(f"Comando 'resume' recibido. Estado: RUNNING.")
                self.mc.postToChat(f"[Miner] Reanudado. Estado: RUNNING.")

            elif command == 'stop':
                self.handle_stop()
                self.logger.info(f"Comando 'stop' recibido. Mineria detenida.")
                self.mc.postToChat(f"[Miner] Detenido. Locks liberados. Estado: STOPPED.")
                self._clear_marker()

            elif command == 'status':
                await self._publish_status()

            
        elif msg_type == "materials.requirements.v1":
            new_requirements = payload.copy()
            
            if new_requirements:
                 self.requirements = new_requirements
                 self.inventory = {mat: 0 for mat in MATERIAL_MAP.keys()}
                 self.logger.info(f"Nuevos requisitos cargados: {self.requirements}")
            
            if message.get("status") == "PENDING":
                ctx_zone = message.get("context", {}).get("target_zone")
                if ctx_zone:
                    bx, bz = int(ctx_zone['x']), int(ctx_zone['z'])
                    offset_magnitude = 3 * self.SECTOR_SIZE
                    
                    self.mining_position.x = bx + offset_magnitude
                    self.mining_position.z = bz + offset_magnitude
                    
                    try:
                        self.mining_position.y = self.mc.getHeight(self.mining_position.x, self.mining_position.z) + 1
                        self.surface_marker_y = self.mining_position.y
                    except Exception:
                        self.mining_position.y = 65
                        self.surface_marker_y = 66
                    
                    NewStrategy = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
                    self.current_strategy_instance = NewStrategy(self.mc, self.logger)

                    self.logger.info(f"Minero desplazado a: ({self.mining_position.x}, {self.mining_position.z})")
                
                self.manual_strategy_active = False 
                await self._select_adaptive_strategy()
                
                if self.requirements and self.state not in (AgentState.STOPPED, AgentState.ERROR): 
                    if not self._check_requirements_fulfilled():
                        self.state = AgentState.RUNNING
                    else: 
                        self.state = AgentState.IDLE
                        self.mc.postToChat("[Miner] Requisitos de BOM ya cubiertos. IDLE.")
            else:
                 self.mc.postToChat(f"[Miner] Requisitos cargados (ACKNOWLEDGED). Use /miner fulfill para iniciar.")


        elif msg_type == "lock.spatial.v1":
            sector_id = payload.get("sector_id")
            source = message.get("source")
            
            if source != self.agent_id:
                self.remote_locks[sector_id] = source
                self.logger.warning(f"Sector {sector_id} BLOQUEADO por {source}. Agregado a lista remota.")
        
        elif msg_type == "unlock.spatial.v1":
             sector_id = payload.get("sector_id")
             source = message.get("source")
             if source != self.agent_id and sector_id in self.remote_locks:
                 del self.remote_locks[sector_id]
                 self.logger.warning(f"Sector {sector_id} LIBERADO por {source}. Eliminado de lista remota.")


    def _parse_start_params(self, params: Dict[str, Any]):
        args = params.get('args', [])
        nx, nz, ny = None, None, None
        for a in args:
            if 'x=' in a: nx = int(a.split('=')[1])
            if 'z=' in a: nz = int(a.split('=')[1])
            if 'y=' in a: ny = int(a.split('=')[1])
        
        if nx is None:
            try: 
                p = self.mc.player.getTilePos()
                nx, nz = p.x, p.z
            except: nx, nz = 0, 0
            
        self.mining_position.x = nx
        self.mining_position.z = nz

        if ny is not None:
             self.mining_position.y = ny
             self.surface_marker_y = ny 
        else:
            try: 
                 self.mining_position.y = self.mc.getHeight(nx, nz) + 1
                 self.surface_marker_y = self.mining_position.y
            except: 
                 self.mining_position.y = 65
                 self.surface_marker_y = 66

    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            strat = args[1].lower()
            if strat in self.strategy_classes:
                NewStrategy = self.strategy_classes[strat]
                self.current_strategy_instance = NewStrategy(self.mc, self.logger) 
                self.current_strategy_name = strat
                self.logger.info(f"Estrategia manual: {strat}")

    async def _select_adaptive_strategy(self):
        if not self.requirements: return 
        
        # Construir diccionario 'pending' usando filter y map
        pending_items = filter(
            lambda item: item[1] > self.inventory.get(item[0], 0),
            self.requirements.items()
        )
        # Transformar a diccionario con la cantidad restante
        pending = dict(map(
            lambda item: (item[0], item[1] - self.inventory.get(item[0], 0)),
            pending_items
        ))

        if not pending: return 

        if self.manual_strategy_active and self.current_strategy_name == 'vertical':
             needs_dirt_sand = pending.get("dirt", 0) > 0 or pending.get("sand", 0) > 0
             needs_stone = any(map(lambda mat: pending.get(mat, 0) > 0, ["cobblestone", "stone"]))
             
             if needs_dirt_sand and not needs_stone:
                 self.logger.info("Modo Manual 'Vertical' ineficaz (Piedra completa, falta Tierra). Pasando a Auto.")
                 self.manual_strategy_active = False 
                 self.mc.postToChat("[Miner] Auto-switching: Vertical -> Grid (Piedra completada).")

        if self.manual_strategy_active:
            return

        new_strat = self.current_strategy_name 

        # --- LÓGICA DE PRIORIDAD ESPECÍFICA (usando el diccionario filtrado) ---
        
        if pending.get("dirt", 0) > 0 or pending.get("sand", 0) > 0:
            new_strat = "grid" 
        
        elif any(map(lambda mat: pending.get(mat, 0) > 0, ["cobblestone", "stone"])):
            new_strat = "vertical" 
        
        elif any(map(lambda mat: pending.get(mat, 0) > 0, ["diamond_ore", "iron_ore", "gold_ore", "coal_ore", "redstone_ore"])):
            new_strat = "vein"
        
        elif any(map(lambda mat: pending.get(mat, 0) > 0, ["wood", "wood_planks", "glass", "glass_pane", "sandstone", "gravel"])):
            new_strat = "vertical" 

        if new_strat != self.current_strategy_name:
            self.current_strategy_name = new_strat
            NewStrategy = self.strategy_classes.get(new_strat, VerticalSearchStrategy)
            self.current_strategy_instance = NewStrategy(self.mc, self.logger)
            self.logger.info(f"Estrategia adaptativa cambiada a: {new_strat} (Por prioridad de materiales)")

    async def _publish_inventory_update(self, status: str):
        msg = {
            "type": "inventory.v1",
            "source": self.agent_id, "target": "BuilderBot",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "payload": {
                "collected_materials": self.inventory,
                "total_volume": self.get_total_volume()
            },
            "status": status,
            "context": {"required_bom": self.requirements}
        }
        await self.broker.publish(msg)

    async def _publish_status(self):
        # FUNCIONAL: Uso de filter para determinar pendientes
        pending_materials = list(filter(
            lambda item: item[1] > self.inventory.get(item[0], 0),
            self.requirements.items()
        ))
        
        if self.requirements:
            # Uso de filter y map para formatear cadenas
            required_items = filter(lambda item: item[1] > 0, self.requirements.items())
            req_str_parts = map(
                lambda item: f"{self.inventory.get(item[0], 0)}/{item[1]} {item[0]}",
                required_items
            )
            req_str = ", ".join(req_str_parts)
            
            if not pending_materials:
                 req_str = f"Completado: {req_str}"
        else:
            req_str = "Ninguno"

        # Uso de filter y map para inventario extra
        extra_inv_items = filter(
            lambda item: item[1] > 0 and item[0] not in self.requirements,
            self.inventory.items()
        )
        inv_str = ", ".join(map(lambda item: f"{item[1]} {item[0]}", extra_inv_items))
        
        lock_status = f"LOCKED (Sector: {self.locked_sector_id})" if self.mining_sector_locked else "UNLOCKED"
        remote_str = f"| Remoto: {len(self.remote_locks)} locks" if self.remote_locks else ""
        mining_pos = f"({int(self.mining_position.x)}, {int(self.mining_position.y)}, {int(self.mining_position.z)})"
        
        strat_mode = "MANUAL" if self.manual_strategy_active else "AUTO"
        
        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | Estrategia: {self.current_strategy_name.upper()} ({strat_mode}) | "
            f"Pos: {mining_pos} | Lock: {lock_status}{remote_str}\n"
            f"  > Progreso (Rec./Req.): {req_str}\n"
            f"  > Inventario Extra: {inv_str if inv_str else 'Vacio'}"
        )
        
        self.logger.info(f"Comando 'status' recibido. Reportando: {self.state.name}")
        try: self.mc.postToChat(status_message)
        except: pass