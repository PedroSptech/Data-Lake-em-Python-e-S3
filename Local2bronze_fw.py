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

IP_ATACANTE = "185.220.101.47"
IPS_COMUNS = ["45.33.32.156", "198.51.100.23", "203.0.113.77", "192.0.2.14", "91.121.87.10"]

os.makedirs(PASTA_LOCAL, exist_ok=True)
s3 = boto3.client("s3", region_name=REGIAO)


def gerar_registro(ciclo, agora):
    rede = psutil.net_io_counters()

    posicao = ciclo % 15
    em_ataque = 8 <= posicao < 13

    if em_ataque:
        passo = posicao - 8
        sessoes = 1500 + 300 * passo + random.randint(-100, 100)
        pacotes_descartados = random.randint(8000, 25000)
        cpu = 25 + 16 * passo + random.uniform(-3, 3)
        ip_bloqueado = IP_ATACANTE
    else:
        sessoes = random.randint(150, 600)
        pacotes_descartados = random.randint(0, 120)
        cpu = 8 + sessoes / 150 + random.uniform(-2, 2)
        ip_bloqueado = random.choice(IPS_COMUNS)

    ram = 35 + sessoes / 120 + random.uniform(-2, 2)
    latencia = 10 + cpu * 1.6 + random.uniform(-5, 5)

    return {
        "tipo": "firewall",
        "id_firewall": "fw01",
        "timestamp": agora.strftime("%Y-%m-%d %H:%M:%S"),
        "bytes_sent": rede.bytes_sent,
        "bytes_recv": rede.bytes_recv,
        "active_sessions": sessoes,
        "dropped_packets": pacotes_descartados,
        "top_blocked_ip": ip_bloqueado,
        "latency_ms": round(max(1, latencia), 2),
        "cpu_usage": round(min(100, max(0, cpu)), 2),
        "ram_usage": round(min(100, max(0, ram)), 2),
    }


def salvar_e_enviar(registro, agora):
    nome = agora.strftime("%Y-%m-%d_%H-%M") + "_" + registro["id_firewall"] + ".json"
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
    print("coleta do firewall iniciada, Ctrl+C para parar")
    while True:
        agora = datetime.now()
        registro = gerar_registro(ciclo, agora)
        salvar_e_enviar(registro, agora)
        ciclo = ciclo + 1
        time.sleep(60 - time.time() % 60)


if __name__ == "__main__":
    main()