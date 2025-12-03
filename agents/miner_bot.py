# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Type
from agents.base_agent import BaseAgent, AgentState
from mcpi.vec3 import Vec3
from mcpi import block

# NUEVAS IMPORTACIONES PARA REFLEXIÓN
from core.agent_manager import AgentDiscovery 
from strategies.base_strategy import BaseMiningStrategy # Solo necesitamos la clase base para el tipado

# IMPORTACIÓN DE FALLBACK: Necesaria para el caso de fallo de reflexión, 
# para no instanciar la clase abstracta BaseMiningStrategy.
# Esto garantiza que siempre se use una estrategia concreta.
from strategies.vertical_search import VerticalSearchStrategy 

# ELIMINADAS: Las importaciones de estrategias específicas (GridSearchStrategy, VeinSearchStrategy) 
# se han eliminado, ahora se descubren automáticamente.

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
    """
    # Constante para definir el tamaño de la región que bloquea (ej: 10x10)
    SECTOR_SIZE = 10 
    
    def __init__(self, agent_id: str, mc_connection, message_broker):
        super().__init__(agent_id, mc_connection, message_broker)
        
        self.requirements: Dict[str, int] = {}
        self.inventory: Dict[str, int] = {mat: 0 for mat in MATERIAL_MAP.keys()}
        
        # Posición de trabajo (se actualiza dinámicamente)
        self.mining_position: Vec3 = Vec3(10, 65, 10)
        self.mining_sector_locked = False 
        self.locked_sector_id: str = "" # Identificador del sector bloqueado (ej: 10_10)
        
        # Offset para no minar siempre en el mismo hueco
        self._mining_offset: int = 0
        
        # NEW: Almacena la altura Y fija del marcador visual en superficie
        self.surface_marker_y = 66 
        
        # Estrategias Disponibles: DESCUBRIMIENTO DINÁMICO (Reflection)
        self.strategy_classes: Dict[str, Type[BaseMiningStrategy]] = AgentDiscovery.discover_strategies()
        
        # Determinar estrategia inicial (usando 'vertical' como fallback de nombre)
        self.current_strategy_name = "vertical" 
        
        # Instanciar la estrategia (usando el tipo descubierto o VerticalSearchStrategy como fallback SEGURO)
        InitialStrategy = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
        self.current_strategy_instance = InitialStrategy(self.mc, self.logger)
        
        self.logger.info(f"MinerBot: Estrategias descubiertas: {list(self.strategy_classes.keys())}. Inicial: {self.current_strategy_name}")
        
        # Marcador Amarillo (Lana Amarilla = data 4)
        self._set_marker_properties(block.WOOL.id, 4)

    def get_total_volume(self) -> int:
        return sum(self.inventory.values())

    def _check_requirements_fulfilled(self) -> bool:
        if not self.requirements: return False
        return all(self.inventory.get(mat, 0) >= qty for mat, qty in self.requirements.items())

    # --- LÓGICA DE EXTRACCIÓN FÍSICA (No modificada) ---
    
    async def _mine_current_block(self, position: Vec3) -> bool:
        """
        Rompe el bloque en la posición dada y actualiza el inventario si es necesario.
        """
        x, y, z = int(position.x), int(position.y), int(position.z)
        
        try:
            block_id = self.mc.getBlock(x, y, z)
        except: return False

        if block_id == block.AIR.id:
            return False

        # Identificar qué material obtenemos (DROP LOGIC)
        material_dropped = None
        
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
             # Búsqueda inversa para Ores
             for name, bid in MATERIAL_MAP.items():
                 if bid == block_id: 
                      material_dropped = name
                      break
        
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
            else:
                 await self._select_adaptive_strategy()
                 if not self.mining_sector_locked:
                    # Nuevo: Adquirir el lock y notificar
                    await self._acquire_lock()
                    
    async def act(self):
        if self.state == AgentState.RUNNING and self.mining_sector_locked:
            
            # 1. FIX VISUALIZACIÓN: Marcador siempre en la posición de superficie *fija*
            try:
                 x, z = int(self.mining_position.x), int(self.mining_position.z)
                 # Usamos la altura fija self.surface_marker_y
                 y_surf = self.surface_marker_y 
                 # Pintamos el marcador en la superficie
                 self._update_marker(Vec3(x, y_surf, z))
            except: pass
            
            # 2. Ejecutar estrategia, que modificará la posición interna (Y)
            await self.current_strategy_instance.execute(
                requirements=self.requirements,
                inventory=self.inventory,
                position=self.mining_position, 
                mine_block_callback=self._mine_current_block 
            )
            
            # 3. Publicar progreso
            await self._publish_inventory_update(status="PENDING")
            
    # --- UTILS DE LOCKING ---
    
    def _calculate_sector_id(self, pos: Vec3) -> str:
        """Calcula el ID del sector basado en la posición (ej: 10_10 para 10-19 en X y Z)."""
        # Redondea hacia abajo al múltiplo más cercano del tamaño del sector
        x_sector = int(pos.x // self.SECTOR_SIZE) * self.SECTOR_SIZE
        z_sector = int(pos.z // self.SECTOR_SIZE) * self.SECTOR_SIZE
        return f"{x_sector}_{z_sector}"

    async def _acquire_lock(self):
        """Adquiere el lock y notifica al sistema."""
        self.mining_sector_locked = True
        self.locked_sector_id = self._calculate_sector_id(self.mining_position)
        
        # Publicar el mensaje de bloqueo
        await self._publish_lock_update(message_type="lock.spatial.v1")
        self.logger.info(f"Lock adquirido: Sector {self.locked_sector_id}")

    def release_locks(self):
        """
        SOBRESCRIBE EL MÉTODO DE BASEAGENT.
        Libera el lock localmente y notifica al sistema. (Llamado al entrar en STOPPED/ERROR).
        """
        if self.mining_sector_locked:
            # Llama a la lógica de notificación asíncrona (no bloqueante)
            # Como este método se llama desde el setter de 'state' (no asíncrono),
            # usamos asyncio.create_task para ejecutar la publicación.
            asyncio.create_task(self._publish_lock_update(message_type="unlock.spatial.v1"))
            
            self.mining_sector_locked = False
            self.locked_sector_id = ""
            self.logger.info("Lock liberado.")
        
        super().release_locks() 
        
    async def _publish_lock_update(self, message_type: str):
        """Publica el mensaje de bloqueo/desbloqueo al sistema (target: All)."""
        sector_id = self._calculate_sector_id(self.mining_position)
        
        lock_message = {
            "type": message_type,
            "source": self.agent_id,
            "target": "All", # Broadcast para que todos los MinerBots lo vean
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
        # Nuevo: Liberar el lock al completar el ciclo
        self.release_locks()
        self._mining_offset += 1 
        self.logger.info("Ciclo minería completado.")
        # --- MEJORA DE FEEDBACK ---
        self.mc.postToChat(f"[Miner]  Ciclo de minería completado. Requisitos cubiertos.")
        # --- FIN MEJORA ---
    
    # --- MÉTODO PARA REINICIAR LA TAREA (FIX RE-EJECUCIÓN) ---
    def _reset_mining_task(self):
        """Reinicia el inventario y requisitos para una nueva tarea manual."""
        # FIX: Asegurar que el lock se libera en el sistema al resetear
        if self.mining_sector_locked:
            self.release_locks() 
            
        self.requirements = {}
        self.inventory = {mat: 0 for mat in MATERIAL_MAP.keys()}
        self._mining_offset = 0 # Reiniciar offset para empezar desde la base
        self.state = AgentState.IDLE
        self.mining_sector_locked = False
        self.locked_sector_id = ""
        # Forzar la recreación de la instancia de la estrategia
        # Utiliza la clase descubierta dinámicamente o el fallback seguro
        NewStrategy = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
        self.current_strategy_instance = NewStrategy(self.mc, self.logger)

        self.logger.info("Tarea de minería reseteada para nueva ejecución.")
    # -----------------------------------------------------------

    async def _handle_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type.startswith("command."):
            command = payload.get("command_name")
            if command in ['start', 'fulfill']:
                
                # --- FIX RE-EJECUCIÓN: Resetear tarea al recibir start/fulfill ---
                self._reset_mining_task()
                
                self._parse_start_params(payload.get("parameters", {}))
                
                # --- FIX REQUISITO POR DEFECTO ---
                if command == 'start' and not self.requirements:
                    # Tarea por defecto: minar 100 de Cobblestone
                    self.requirements = {"cobblestone": 100} 
                    self.logger.info("Iniciando minería manual con tarea por defecto: 100 Cobblestone.")
                
                # --- MEJORA DE FEEDBACK (start/fulfill) ---
                target_pos = f"({int(self.mining_position.x)}, {int(self.mining_position.z)})"
                req_str = ", ".join([f"{q} {m}" for m, q in self.requirements.items()])
                
                self.mc.postToChat(f"[Miner] ⛏️ Minería iniciada en {target_pos}. Objetivo: {req_str}. Estrategia: {self.current_strategy_name.upper()}.")
                # --- FIN MEJORA ---
                
                # ------------------------------------
                
                await self._select_adaptive_strategy() 
                if not self._check_requirements_fulfilled():
                    self.state = AgentState.RUNNING
                else: self.state = AgentState.IDLE
            elif command == 'set': 
                self._parse_set_strategy(payload.get("parameters", {}))
                
                # --- MEJORA DE FEEDBACK (set strategy) ---
                if self.current_strategy_name in self.strategy_classes:
                    self.logger.info(f"Comando 'set strategy' recibido. Estrategia cambiada a: {self.current_strategy_name}.")
                    self.mc.postToChat(f"[Miner]  Estrategia cambiada a: {self.current_strategy_name.upper()}.")
                # --- FIN MEJORA ---

            elif command == 'pause':
                self.handle_pause()
                self.logger.info(f"Comando 'pause' recibido. Estado: PAUSED.")
                self.mc.postToChat(f"[Miner]  Pausado. Estado: PAUSED.")
                
            elif command == 'resume':
                self.handle_resume()
                self.logger.info(f"Comando 'resume' recibido. Estado: RUNNING.")
                self.mc.postToChat(f"[Miner]  Reanudado. Estado: RUNNING.")

            elif command == 'stop':
                self.handle_stop()
                self.logger.info(f"Comando 'stop' recibido. Minería detenida y locks liberados.")
                self.mc.postToChat(f"[Miner]  Detenido. Locks liberados. Estado: STOPPED.")
                self._clear_marker()

            elif command == 'status':
                await self._publish_status()

            
        elif msg_type == "materials.requirements.v1":
            # ... (Lógica de requisitos)
            self.requirements = payload.copy()
            self.logger.info(f"Nuevos requisitos recibidos: {self.requirements}")
            
            # FIX CRÍTICO: Resetear el inventario para forzar la minería.
            self.inventory = {mat: 0 for mat in MATERIAL_MAP.keys()}
            
            # Reposicionar minero según zona de construcción + offset
            ctx_zone = message.get("context", {}).get("target_zone")
            if ctx_zone:
                 bx, bz = int(ctx_zone['x']), int(ctx_zone['z'])
                 # El offset asegura que el minero se va a otro sector, lejos del BuilderBot
                 offset = 15 + (self._mining_offset * self.SECTOR_SIZE * 2) 
                 
                 self.mining_position.x = bx + offset
                 self.mining_position.z = bz + offset
                 
                 # --- NEW FIX: Set the initial mining and marker height once ---
                 try:
                     # Posiciona en la superficie + 1 para empezar a picar abajo
                     self.mining_position.y = self.mc.getHeight(self.mining_position.x, self.mining_position.z) + 1
                     # CACHE la altura del marcador en superficie
                     self.surface_marker_y = self.mining_position.y
                 except Exception:
                     self.mining_position.y = 65
                     self.surface_marker_y = 66
                 # ----------------------------------------------------------------
                 
                 # Reiniciar la instancia de estrategia
                 NewStrategy = self.strategy_classes.get(self.current_strategy_name, VerticalSearchStrategy)
                 self.current_strategy_instance = NewStrategy(self.mc, self.logger)

                 self.logger.info(f"Minero desplazado a: ({self.mining_position.x}, {self.mining_position.z})")
            
            await self._select_adaptive_strategy()
            
            if self.state in (AgentState.IDLE, AgentState.WAITING): 
                self.state = AgentState.RUNNING

        elif msg_type == "lock.spatial.v1":
            # Nuevo: Escuchar si OTROS MinerBots bloquean un sector
            sector_id = payload.get("sector_id")
            source = message.get("source")
            
            if source != self.agent_id:
                self.logger.warning(f"Sector {sector_id} BLOQUEADO por {source}.")
                # Lógica de reubicación compleja (opcional) iría aquí.
        
        elif msg_type == "unlock.spatial.v1":
             # Nuevo: Escuchar si OTROS MinerBots liberan un sector
             sector_id = payload.get("sector_id")
             source = message.get("source")
             if source != self.agent_id:
                 self.logger.warning(f"Sector {sector_id} LIBERADO por {source}.")


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

        # --- FIX: Usar ny si fue proporcionado, sino usar getHeight ---
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
        # ----------------------------------------------------------------

    def _parse_set_strategy(self, params: Dict[str, Any]):
        args = params.get('args', [])
        if len(args) >= 2 and args[0] == 'strategy':
            strat = args[1].lower()
            if strat in self.strategy_classes:
                # Recrear la instancia para resetear su estado interno
                NewStrategy = self.strategy_classes[strat]
                self.current_strategy_instance = NewStrategy(self.mc, self.logger)
                self.current_strategy_name = strat
                self.logger.info(f"Estrategia manual: {strat}")

    async def _select_adaptive_strategy(self):
        """Elige la mejor estrategia según lo que falte."""
        if not self.requirements: return 

        pending = {m: q - self.inventory.get(m, 0) for m, q in self.requirements.items() if q > self.inventory.get(m, 0)}
        if not pending: return 

        most_needed = max(pending, key=pending.get)
        new_strat = "vertical" # Default

        vein_mats = ("diamond_ore", "iron_ore", "gold_ore", "coal_ore", "redstone_ore")
        
        # Reglas de Selección:
        if pending.get("dirt", 0) > 0 or pending.get("sand", 0) > 0:
            new_strat = "grid" # Superficie para tierra/arena
        elif most_needed in vein_mats:
            new_strat = "vein" # Vetas para minerales valiosos
        elif most_needed in ("cobblestone", "stone", "sandstone", "gravel"):
            new_strat = "vertical" # Vertical para materiales masivos profundos
            
        if new_strat != self.current_strategy_name:
            self.current_strategy_name = new_strat
            # Recrear la instancia al cambiar de estrategia
            NewStrategy = self.strategy_classes.get(new_strat, VerticalSearchStrategy)
            self.current_strategy_instance = NewStrategy(self.mc, self.logger)
            self.logger.info(f"Estrategia cambiada a: {new_strat} (Objetivo: {most_needed})")

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
        # Muestra el estado actual, inventario y estrategia
        inv_str = ", ".join([f"{q} {m}" for m, q in self.inventory.items() if q > 0])
        req_str = ", ".join([f"{q} {m}" for m, q in self.requirements.items()])
        status_message = (
            f"[{self.agent_id}] Estado: {self.state.name} | "
            f"Estrategia: {self.current_strategy_name.upper()} | "
            f"Inventario: {inv_str if inv_str else 'Vacío'} | "
            f"Requisitos: {req_str if req_str else 'Ninguno'}"
        )
        self.logger.info(f"Comando 'status' recibido. Reportando: {self.state.name}")
        try: self.mc.postToChat(status_message)
        except: pass