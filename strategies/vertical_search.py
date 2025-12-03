# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical (Quarry).
    Excava una columna hacia abajo.
    """
    MIN_SAFE_Y = 5   # No bajar más allá de esto (Bedrock)
    RESTART_Y = 65   # Altura de reinicio de fallback
    
    # FIX CRÍTICO: Cambiamos el paso horizontal a 1 para ir al bloque ADYACENTE.
    HORIZONTAL_STEP = 1

    def __init__(self, mc_connection, logger: logging.Logger):
        super().__init__(mc_connection, logger)
        self.cycle_counter = 0 
        self.is_finished = False 
        # NUEVO: Contador para agrupar minería. En cada execute(), minará 5 bloques.
        self.blocks_per_step = 5 

    # --- FUNCIÓN DE AYUDA PARA CHECKEO DE REQUISITOS ---
    def _needs_more_mining(self, requirements: Dict[str, int], inventory: Dict[str, int]) -> bool:
        """Verifica si todavía faltan materiales por obtener."""
        if not requirements:
            # Si no hay requisitos definidos, seguimos minando el objetivo por defecto (100 Cobblestone)
            return inventory.get("cobblestone", 0) < 100 
        
        # Comprueba si algún requisito NO está cumplido
        return any(inventory.get(mat, 0) < qty for mat, qty in requirements.items())
    # ----------------------------------------------------
    
    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        
        if self.is_finished:
             await asyncio.sleep(0.1)
             return
             
        self.logger.debug(f"VerticalSearch en ({position.x}, {position.y}, {position.z})")

        blocks_mined_in_step = 0
        
        # Bucle optimizado: Minar varios bloques antes de ceder el control
        while blocks_mined_in_step < self.blocks_per_step and position.y > self.MIN_SAFE_Y:
            
            # 1. Minar el bloque actual
            mine_pos = position.clone() 
            # Ya no necesitamos minar 3 a la vez, el MinerBot está en Y+1, mina Y-1 (suelo)
            # Para la estrategia vertical, minamos en la posición actual de Y
            
            await mine_block_callback(mine_pos)
            blocks_mined_in_step += 1
            
            # CRÍTICO: Descender inmediatamente en Y (minando un bloque por ciclo de descenso)
            position.y -= 1 
            
            # Pequeña pausa de CPU, no de I/O de MC. Permite al MinerBot leer mensajes en el `perceive`
            await asyncio.sleep(0.01) 
            
        # Logging de descenso solo al terminar el ciclo agrupado
        self.logger.info(f"Agente desciende. Nueva Y interna: {position.y}. Bloques: {blocks_mined_in_step}")
        
        # 2. Lógica de Movimiento (Comprobar si se alcanzó el fondo)
        if position.y <= self.MIN_SAFE_Y:
            self.logger.warning(f"Fondo alcanzado. Finalizando pozo en ({position.x}, {position.z}).")

            if self._needs_more_mining(requirements, inventory):
                
                # 1. Aumentamos X en 1 para ir al bloque adyacente (X+1)
                position.x = int(position.x) + self.HORIZONTAL_STEP
                position.z = int(position.z)
                
                # 2. Recalculamos Y (para empezar en la superficie del nuevo X)
                try:
                    # El MinerBot se encargará de re-lockear/reubicar
                    new_surface_y = self.mc.getHeight(position.x, position.z) + 1
                    position.y = new_surface_y
                except Exception:
                    position.y = self.RESTART_Y
                
                self.logger.info(f"Iniciando nuevo pozo en ({position.x}, {position.z}). Y inicial: {position.y}")

            else:
                 # Requisitos cumplidos
                 self.logger.info("Requisitos cumplidos. Finalizando estrategia VerticalSearch.")
                 self.is_finished = True 
                 position.y = self.RESTART_Y
                 
        await asyncio.sleep(0.5) # Pausa más larga al terminar el ciclo de minado.