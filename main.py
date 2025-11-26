from mcpi.minecraft import Minecraft

def test_connection():
    # Intenta conectarse al servidor (debe estar iniciado en localhost)
    try:
        mc = Minecraft.create()
        mc.postToChat("¡Sistema TAP iniciado y conectado!")
        print("Conexión exitosa. Mensaje enviado al chat.")
    except Exception as e:
        print(f"Error al conectar con Minecraft: {e}")
        print("Asegúrate de que el servidor de Minecraft esté corriendo.")

if __name__ == "__main__":
    test_connection()