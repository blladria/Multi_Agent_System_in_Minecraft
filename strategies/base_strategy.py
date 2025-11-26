# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable
from mcpi.vec3 import Vec3
import logging

class BaseMiningStrategy(ABC):
    """
    Clase abstracta base para todas las estrategias de minería.
    Define el contrato (execute) para el Patrón Estrategia.
    """
    def __init__(self, mc_connection, logger: logging.Logger):
        """Inicializa la estrategia con las dependencias de MC y logging."""
        self.mc = mc_connection
        self.logger = logger

    @abstractmethod
    async def execute(self, 
                      requirements: Dict[str, int], 
                      inventory: Dict[str, int], 
                      position: Vec3, 
                      simulate_extraction: Callable):
        """
        Ejecuta un ciclo de minería.

        :param requirements: Dict con los materiales requeridos.
        :param inventory: Dict con los materiales actuales (se modifica in-place).
        :param position: Objeto Vec3 de la posición del minero (se modifica in-place).
        :param simulate_extraction: Función asíncrona del MinerBot para la extracción.
        """
        pass