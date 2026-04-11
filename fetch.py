import socket
import os
from pathlib import Path
import csv
from datetime import datetime
import logging

if "__file__" in globals():
    BASE_DIR = Path(__file__).resolve().parent
else:
    BASE_DIR = Path(os.getcwd())

NUT_HOST = "172.21.0.1"
NUT_PORT = 3493
UPS_NAME = "cyberpower"

# Configuración
LOG_FILE = BASE_DIR / "ups.csv"
MAX_ROWS = 5000  # Máximo de registros de datos (sin contar la cabecera)

def truncate_log_if_needed(file_path, max_rows):
    """
    Si el archivo supera el límite de filas, elimina la fila más antigua
    manteniendo la cabecera intacta.
    """
    if not os.path.exists(file_path):
        return

    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()

        # El total de líneas es max_rows + 1 (la cabecera)
        if len(lines) > (max_rows + 1):
            # lines[0] es la cabecera
            # lines[2:] son todos los datos excepto el primero (el más antiguo)
            # Saltamos lines[1] para borrar el registro viejo
            new_content = [lines[
            0]] + lines[2:]
            
            with open(file_path, 'w') as f:
                f.writelines(new_content)
    except Exception as e:
        print(f"Error al rotar el log: {e}")


def nut_command(cmd):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((NUT_HOST, NUT_PORT))
        s.sendall((cmd + "\n").encode())
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"END LIST" in response or b"ERR" in response:
                break
        return response.decode()

def get_ups_vars():
    raw = nut_command(f"LIST VAR {UPS_NAME}")
    data = {}
    for line in raw.splitlines():
        if line.startswith("VAR"):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                key = parts[2]
                value = parts[3].strip('"')
                data[key] = value
    return data

def fetch_ups_stats():

    truncate_log_if_needed(LOG_FILE, MAX_ROWS)

    # 1. Obtenemos el diccionario con todos los datos
    ups_data = get_ups_vars()

    # 2. Extraemos las variables con un valor por defecto (0) en caso de que no existan
    # Usamos int() para convertir el string que devuelve el comando a un número entero
    try:
        battery_charge = int(ups_data.get('battery.charge', 0))
        ups_load = int(ups_data.get('ups.load', 0))
    except (ValueError, TypeError):
        # En caso de que el dato no sea un número válido
        battery_charge = 0
        ups_load = 0

    ups_watts = round(ups_load * 540 / 100, 1)

    stats_file = LOG_FILE
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    file_exists = stats_file.exists()

    with open(stats_file, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "battery_charge", "ups_watts"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            battery_charge,
            ups_watts
        ])

    msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ups battery: {battery_charge}, instant power: {ups_watts}W"
    logging.info(msg)
    print(msg)

if __name__ == "__main__":
    try:
        fetch_ups_stats()
    except Exception as e:
        logging.error(f"Error: {e}")
        raise