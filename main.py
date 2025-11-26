# -*- coding: utf-8 -*-
import asyncio
import logging
import sys
import os

# Asegúrate de que los directorios 'agents' y 'core' sean paquetes para Python
# Esto es esencial para que la reflexión funcione correctamente
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importar los componentes centrales (que a su vez importan el resto)
from core.agent_manager import AgentManager
from core.message_broker import MessageBroker

# Configuración de Logging Estructurado (Requisito del Enunciado)
# Asegúrate de que todos los logs se escriban en la consola para la prueba
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

async def main():
    """
    Función principal asíncrona que inicializa el MessageBroker y el AgentManager,
    y lanza el sistema multi-agente completo.
    """
    logger.info("Sistema de Agentes de Minecraft (TAP) inicializándose...")
    
    # Inicializar el Broker y el Manager
    broker = MessageBroker()
    manager = AgentManager(broker)
    
    # El Manager se conecta a Minecraft, descubre agentes (Reflexión) y lanza sus tareas
    await manager.start_system()
    
    # Mantener el bucle de eventos corriendo. 
    # En un sistema real, este bucle esperaría a que todos los agentes terminen o a un comando de parada.
    try:
        while manager.is_running:
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info("Bucle principal de asyncio cancelado (Stop del sistema).")
    
    finally:
        # Se puede añadir la lógica de cierre seguro aquí si fuera necesario
        pass

if __name__ == "__main__":
    # asyncio.run es necesario para iniciar el bucle de eventos asíncrono
    try:
        logger.info("Iniciando asyncio.run...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Sistema detenido por el usuario (Ctrl+C). Terminando tareas...")
    except Exception as e:
        logger.error(f"Error fatal inesperado en el sistema: {e}")