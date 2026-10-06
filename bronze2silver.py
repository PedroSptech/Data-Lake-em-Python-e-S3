import glob
import json
import os

import boto3
import pandas as pd

BUCKET = "itops-04261046"
REGIAO = "us-east-1"
PASTA_BRONZE = "data/bronze"
PASTA_SILVER = "data/silver"
ARQUIVO_SILVER = "silver_consolidado.csv"

os.makedirs(PASTA_BRONZE, exist_ok=True)
os.makedirs(PASTA_SILVER, exist_ok=True)
s3 = boto3.client("s3", region_name=REGIAO)


def baixar_bronze():
    os.system(f"aws s3 sync s3://{BUCKET}/01-bronze {PASTA_BRONZE} --region {REGIAO} --quiet")


def ler_jsons():
    registros = []
    for arquivo in glob.glob(PASTA_BRONZE + "/*.json"):
        with open(arquivo) as f:
            registros.append(json.load(f))

    if not registros:
        return None

    df = pd.DataFrame(registros)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["minuto"] = df["timestamp"].dt.floor("min")
    return df


def calcular_vazao(df, coluna_id):
    df = df.sort_values([coluna_id, "timestamp"]).copy()
    df["bytes_total"] = df["bytes_sent"] + df["bytes_recv"]
    df["segundos"] = df.groupby(coluna_id)["timestamp"].diff().dt.total_seconds()
    df["diferenca_bytes"] = df.groupby(coluna_id)["bytes_total"].diff()
    df["vazao_mbps"] = df["diferenca_bytes"] * 8 / df["segundos"] / 1000000
    df["vazao_mbps"] = df["vazao_mbps"].fillna(0).round(4)
    return df


def definir_status(linha):
    if linha["ram_usage"] > 75:
        return "OOM"
    elif linha["cpu_usage"] > 80:
        return "gargalo de processamento"
    elif linha["active_conn"] > 40:
        return "alta densidade"
    else:
        return "normal"


def main():
    baixar_bronze()
    df = ler_jsons()
    if df is None:
        print("nenhum arquivo no bronze")
        return

    aps = calcular_vazao(df[df["tipo"] == "antena"], "id_antena")
    fw = calcular_vazao(df[df["tipo"] == "firewall"], "id_firewall")

    aps["active_conn"] = aps["active_conn"].astype(int)
    aps["status_carga"] = aps.apply(definir_status, axis=1)

    soma_aps = aps.groupby("minuto")["bytes_sent"].sum().reset_index()
    soma_aps = soma_aps.rename(columns={"bytes_sent": "soma_aps_bytes_sent"})

    fw = fw[[
        "minuto", "bytes_sent", "active_sessions", "dropped_packets",
        "top_blocked_ip", "latency_ms", "cpu_usage", "ram_usage", "vazao_mbps",
    ]]
    fw = fw.drop_duplicates("minuto")
    fw = fw.add_prefix("fw_").rename(columns={"fw_minuto": "minuto"})

    silver = aps.merge(soma_aps, on="minuto").merge(fw, on="minuto", how="left")
    silver["dif_bytes_sent"] = silver["fw_bytes_sent"] - silver["soma_aps_bytes_sent"]
    silver["dif_pct"] = (silver["dif_bytes_sent"] / silver["fw_bytes_sent"] * 100).round(4)
    silver["timestamp"] = silver["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    colunas = [
        "timestamp", "id_antena", "bytes_sent", "bytes_recv", "vazao_mbps",
        "active_conn", "cpu_usage", "ram_usage", "status_carga",
        "soma_aps_bytes_sent", "fw_bytes_sent", "dif_bytes_sent", "dif_pct",
        "fw_active_sessions", "fw_dropped_packets", "fw_top_blocked_ip",
        "fw_latency_ms", "fw_cpu_usage", "fw_ram_usage", "fw_vazao_mbps",
    ]
    silver = silver.sort_values(["timestamp", "id_antena"])[colunas]

    caminho = os.path.join(PASTA_SILVER, ARQUIVO_SILVER)
    silver.to_csv(caminho, index=False)
    s3.upload_file(caminho, BUCKET, "02-silver/" + ARQUIVO_SILVER)
    print("silver gerado com", len(silver), "linhas")


if __name__ == "__main__":
    main()