# -*- coding: utf-8 -*-
import asyncio
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
from .base_strategy import BaseMiningStrategy

class VerticalSearchStrategy(BaseMiningStrategy):
    """
    Estrategia de Búsqueda Vertical: Simula una perforación hacia abajo.
    Si se alcanza el límite de Bedrock, se desplaza horizontalmente para iniciar
    un nuevo pozo vertical.
    """
    # Profundidad mínima segura (ej: Y=5, para evitar la capa de Bedrock en Y=0/1)
    MIN_SAFE_Y = 5 
    # Altura para reiniciar la perforación vertical (cerca de la superficie).
    RESTART_Y = 60

    async def execute(self, requirements: Dict[str, int], inventory: Dict[str, int], position: Vec3, mine_block_callback: Callable):
        """
        Mina 3 bloques directamente debajo del agente y luego mueve el agente 1 bloque hacia abajo.
        Si alcanza MIN_SAFE_Y, se mueve 1 bloque en X y reinicia la altura Y para empezar un nuevo pozo.
        """
        self.logger.debug("Estrategia activa: Búsqueda Vertical (hacia abajo).")

        # El volumen/rate de minería es 3 bloques/ciclo.
        volume = 3
        
        # 1. Minar 3 bloques distintos debajo del agente
        for i in range(volume):
            # Clonar la posición del agente y calcular la posición del bloque a minar (Y - 1, Y - 2, Y - 3)
            mine_pos = position.clone()
            mine_pos.y -= (i + 1)
            
            # Llamada al callback para romper el bloque y actualizar inventario
            await mine_block_callback(mine_pos)
            
            # Esperamos un tiempo por bloque minado/intentado minar
            await asyncio.sleep(0.3) 
        
        # 2. Lógica de Movimiento: Vertical o Horizontal (si se toca fondo)
        if position.y > self.MIN_SAFE_Y:
            # Movimiento vertical: Descender 1 bloque para el siguiente ciclo
            position.y -= 1 
            self.logger.debug(f"Agente se mueve a Y={position.y} para el siguiente ciclo.")
        else:
            # **LÓGICA DE DESPLAZAMIENTO HORIZONTAL:** Toca fondo, inicia un nuevo pozo.
            self.logger.warning(f"Se alcanzó la profundidad máxima ({self.MIN_SAFE_Y}). Desplazando 1 bloque en X para nuevo pozo.")
            
            # Moverse 1 bloque en X (ajuste horizontal)
            position.x += 1
            
            # Reiniciar la posición Y para empezar un nuevo pozo vertical
            position.y = self.RESTART_Y
            
            self.logger.info(f"Iniciando nuevo pozo. Nueva posicion de inicio: ({position.x}, {position.y}, {position.z})")
             
        # 3. Simular el tiempo que toma minar
        await asyncio.sleep(0.1)