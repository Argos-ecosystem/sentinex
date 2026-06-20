import math
import struct
import wave

# --- CONFIGURACIÓN DE LA ALARMA ---
fs = 44100           # Calidad de audio
frecuencia_1 = 800   # Tono Alto (Hz)
frecuencia_2 = 500   # Tono Bajo (Hz)
velocidad = 0.25     # Cuánto dura cada "ui" (segundos)
repeticiones = 8     # 8 ciclos de 0.5s = sirena de 4 segundos

# --- GENERACIÓN ---
def square_sample(frecuencia, idx):
    return 0.5 if math.sin(2 * math.pi * frecuencia * idx / fs) >= 0 else -0.5

muestras = []
muestras_por_tono = int(fs * velocidad)

for _ in range(repeticiones):
    for i in range(muestras_por_tono):
        muestras.append(square_sample(frecuencia_1, i))
    for i in range(muestras_por_tono):
        muestras.append(square_sample(frecuencia_2, i))

# Fade cortito para evitar clicks al inicio y al final.
fade_muestras = int(fs * 0.02)
for i in range(fade_muestras):
    factor = i / fade_muestras
    muestras[i] *= factor
    muestras[-i - 1] *= factor

# --- GUARDAR ---
# Convertir a 16-bit
nombre_archivo = 'alarma_infernal.wav'
datos_int16 = b''.join(struct.pack('<h', int(muestra * 32767)) for muestra in muestras)

with wave.open(nombre_archivo, 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(fs)
    wav.writeframes(datos_int16)

print(f"¡Listo el pollo! Se creó el archivo: {nombre_archivo}")
print(f"Duración: {len(muestras) / fs:.1f} segundos.")
print("Ábrelo con cuidado que suena juerte.")
