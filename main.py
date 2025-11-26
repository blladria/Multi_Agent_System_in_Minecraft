# main.py
# -*- coding: utf-8 -*-
import asyncio
import logging

# Importar los componentes centrales
from core.agent_manager import AgentManager
from core.message_broker import MessageBroker

# Configuración de Logging para todo el sistema
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def main():
    """Función principal asíncrona que inicia el sistema."""
    broker = MessageBroker()
    manager = AgentManager(broker)

    # El manager se encarga de conectar a Minecraft, descubrir y lanzar a los agentes
    await manager.start_system()

    # Mantener el bucle de eventos corriendo para que los agentes funcionen
    # Esto puede ser reemplazado por un bucle que espera un comando de parada seguro
    while manager.is_running:
        await asyncio.sleep(1)

if __name__ == "__main__":
    # asyncio.run es necesario para iniciar el bucle de eventos asíncrono
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("main").info("Sistema detenido por el usuario.")
    except Exception as e:
        logging.getLogger("main").error(f"Error fatal en el sistema: {e}")