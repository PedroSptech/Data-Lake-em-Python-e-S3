import json
import os
import random
import time
from datetime import datetime

import boto3
import psutil

BUCKET = "itops-04261046"
REGIAO = "us-east-1"
PASTA_LOCAL = "bronze_local"
ENVIAR_S3 = True

ANTENAS = {
    "ap01": {"parte": 0.10, "conexoes_base": 2, "crescimento": 0.0, "cpu": 5, "ram": 30},
    "ap02": {"parte": 0.50, "conexoes_base": 18, "crescimento": 0.8, "cpu": 10, "ram": 40},
    "ap03": {"parte": 0.40, "conexoes_base": 12, "crescimento": 0.0, "cpu": 45, "ram": 58},
}

os.makedirs(PASTA_LOCAL, exist_ok=True)
s3 = boto3.client("s3", region_name=REGIAO)


def gerar_registro(ap_id, config, ciclo, agora):
    rede = psutil.net_io_counters()

    conexoes = config["conexoes_base"] + config["crescimento"] * ciclo + random.randint(-3, 3)
    conexoes = max(0, int(conexoes))

    cpu = config["cpu"] + conexoes * 0.8 + random.uniform(-3, 3)
    ram = config["ram"] + conexoes * 0.15 + random.uniform(-2, 2)

    if random.random() < 0.05:
        cpu = cpu + 30
    if random.random() < 0.03:
        ram = ram + 20

    return {
        "tipo": "antena",
        "id_antena": ap_id,
        "timestamp": agora.strftime("%Y-%m-%d %H:%M:%S"),
        "bytes_sent": int(rede.bytes_sent * config["parte"]),
        "bytes_recv": int(rede.bytes_recv * config["parte"]),
        "active_conn": conexoes,
        "cpu_usage": round(min(100, max(0, cpu)), 2),
        "ram_usage": round(min(100, max(0, ram)), 2),
    }


def salvar_e_enviar(registro, agora):
    nome = agora.strftime("%Y-%m-%d_%H-%M") + "_" + registro["id_antena"] + ".json"
    caminho = os.path.join(PASTA_LOCAL, nome)

    with open(caminho, "w") as arquivo:
        json.dump(registro, arquivo)

    if ENVIAR_S3:
        try:
            s3.upload_file(caminho, BUCKET, "01-bronze/" + nome)
            print("enviado:", nome)
        except Exception as erro:
            print("falha no envio:", erro)
    else:
        print("salvo:", nome)


def main():
    ciclo = 0
    print("coleta das antenas iniciada, Ctrl+C para parar")
    while True:
        agora = datetime.now()
        for ap_id, config in ANTENAS.items():
            registro = gerar_registro(ap_id, config, ciclo, agora)
            salvar_e_enviar(registro, agora)
        ciclo = ciclo + 1
        time.sleep(60 - time.time() % 60)


if __name__ == "__main__":
    main()