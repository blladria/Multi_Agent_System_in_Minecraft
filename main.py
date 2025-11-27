# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers # Importación necesaria para RotatingFileHandler
import sys
import os

# --- INICIO: CONFIGURACIÓN AVANZADA DE LOGGING (Persistencia y Consola) ---

# 1. Asegúrate de que el directorio 'logs' exista
LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 2. Formato de Logging Estructurado (Requisito del Enunciado)
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
formatter = logging.Formatter(LOG_FORMAT)

# 3. Handler para Archivo (Persistencia)
# Usa RotatingFileHandler para guardar logs en ./logs/system.log
file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'system.log'),
    maxBytes=10 * 1024 * 1024, # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG) # Captura todo (DEBUG y superior) en el archivo

# 4. Handler para Consola (Visualización en tiempo real)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO) # Muestra solo INFO y superior en consola

# 5. Configuración del Logger Raíz para aplicar los handlers a todo el sistema
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG) 
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# --- FIN: CONFIGURACIÓN AVANZADA DE LOGGING ---


# Asegúrate de que los directorios 'agents' y 'core' sean paquetes para Python
# Esto es esencial para que la reflexión funcione correctamente
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importar los componentes centrales (que a su vez importan el resto)
from core.agent_manager import AgentManager
from core.message_broker import MessageBroker

# El logger principal usará la configuración definida
logger = logging.getLogger("main")
logger.info("Configuracion de logging estructurado completada. Logs se guardan en ./logs/system.log")

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
        logger.error(f"Error fatal inesperado en el sistema: {e}", exc_info=True)