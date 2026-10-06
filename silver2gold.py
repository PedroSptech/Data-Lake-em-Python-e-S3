import os
from datetime import timedelta

import boto3
import numpy as np
import pandas as pd

BUCKET = "itops-04261046"
REGIAO = "us-east-1"
PASTA_SILVER = "data/silver"
PASTA_GOLD = "data/gold"
ARQUIVO_SILVER = "silver_consolidado.csv"
LIMITE_CONEXOES = 40
TOLERANCIA_PCT = 1
LIMITE_TEMPO_CRITICO_PCT = 10

os.makedirs(PASTA_SILVER, exist_ok=True)
os.makedirs(PASTA_GOLD, exist_ok=True)
s3 = boto3.client("s3", region_name=REGIAO)


def salvar(df, nome):
    caminho = os.path.join(PASTA_GOLD, nome)
    df.to_csv(caminho, index=False)
    s3.upload_file(caminho, BUCKET, "03-gold/" + nome)
    print("gerado:", nome)


def zonas_mortas(df):
    r = df.groupby("id_antena").agg(
        vazao_media_mbps=("vazao_mbps", "mean"),
        conexoes_medias=("active_conn", "mean"),
    ).reset_index()
    media = r["vazao_media_mbps"].mean()
    r["classificacao"] = "normal"
    r.loc[r["vazao_media_mbps"] < media * 0.5, "classificacao"] = "subutilizada"
    return r.sort_values("vazao_media_mbps").round(4)


def eficiencia_hardware(df):
    df = df.copy()
    df["trafego_mb"] = df["vazao_mbps"] * 60 / 8
    r = df.groupby("id_antena").agg(
        trafego_total_mb=("trafego_mb", "sum"),
        cpu_media=("cpu_usage", "mean"),
    ).reset_index()
    r["trafego_por_cpu"] = r["trafego_total_mb"] / r["cpu_media"]
    return r.sort_values("trafego_por_cpu", ascending=False).round(4)


def expurgo_seguranca(fw):
    fw = fw.copy()
    limite = max(fw["fw_dropped_packets"].median() * 5, 100)
    fw["em_ataque"] = fw["fw_dropped_packets"] > limite
    fw["hora"] = fw["minuto"].dt.floor("h")

    r = fw.groupby("hora").agg(
        pacotes_bloqueados=("fw_dropped_packets", "sum"),
        minutos_em_ataque=("em_ataque", "sum"),
        cpu_fw_max=("fw_cpu_usage", "max"),
    ).reset_index()

    r["suspeita_ddos"] = "nao"
    r.loc[r["minutos_em_ataque"] > 0, "suspeita_ddos"] = "sim"

    ataques = fw[fw["em_ataque"]]
    if len(ataques) > 0:
        r["ip_suspeito"] = ataques["fw_top_blocked_ip"].mode()[0]
    else:
        r["ip_suspeito"] = "nenhum"
    r["cpu_fw_max"] = r["cpu_fw_max"].round(2)
    return r


def gargalo_saida(fw):
    correlacao = fw["fw_cpu_usage"].corr(fw["fw_latency_ms"])
    latencia_cpu_baixa = fw[fw["fw_cpu_usage"] <= 50]["fw_latency_ms"].mean()
    latencia_cpu_alta = fw[fw["fw_cpu_usage"] > 50]["fw_latency_ms"].mean()
    return pd.DataFrame([{
        "correlacao_cpu_latencia": round(correlacao, 4),
        "latencia_media_cpu_ate_50": round(latencia_cpu_baixa, 2),
        "latencia_media_cpu_acima_50": round(latencia_cpu_alta, 2),
    }])


def predicao_sobrecarga(df):
    linhas = []
    for antena, g in df.groupby("id_antena"):
        g = g.sort_values("timestamp").tail(30)
        crescimento = np.polyfit(range(len(g)), g["active_conn"], 1)[0]
        atual = g["active_conn"].tail(3).mean()

        minutos = None
        horario = None
        status = "estavel"

        if atual >= LIMITE_CONEXOES:
            minutos = 0
            horario = g["timestamp"].iloc[-1]
            status = "limite atingido"
        elif crescimento > 0.05:
            previsto = (LIMITE_CONEXOES - atual) / crescimento
            if previsto <= 120:
                minutos = round(previsto, 1)
                horario = g["timestamp"].iloc[-1] + timedelta(minutes=previsto)
                status = "risco de sobrecarga"

        if horario is not None:
            horario = horario.strftime("%Y-%m-%d %H:%M:%S")

        linhas.append({
            "id_antena": antena,
            "conexoes_atuais": round(atual, 1),
            "crescimento_por_min": round(crescimento, 3),
            "minutos_ate_limite": minutos,
            "horario_previsto": horario,
            "status": status,
        })
    return pd.DataFrame(linhas)


def auditoria_trafego(df):
    t = df.drop_duplicates("minuto").dropna(subset=["dif_pct"]).copy()
    t["dif_pct_abs"] = t["dif_pct"].abs()
    t["hora"] = t["minuto"].dt.floor("h")

    r = t.groupby("hora").agg(
        minutos_analisados=("minuto", "count"),
        dif_bytes_media=("dif_bytes_sent", "mean"),
        dif_pct_media=("dif_pct_abs", "mean"),
        dif_pct_max=("dif_pct_abs", "max"),
    ).reset_index()

    r["status"] = "consistente"
    r.loc[r["dif_pct_max"] > TOLERANCIA_PCT, "status"] = "investigar"
    r["hora"] = r["hora"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return r.round(4)


def saude_antenas(df):
    estados = ["normal", "alta densidade", "gargalo de processamento", "OOM"]

    r = pd.crosstab(df["id_antena"], df["status_carga"])
    for estado in estados:
        if estado not in r.columns:
            r[estado] = 0
    r = r[estados]
    r.columns.name = None

    r["minutos_total"] = r.sum(axis=1)
    r["minutos_criticos"] = r["minutos_total"] - r["normal"]
    r["pct_tempo_critico"] = (r["minutos_criticos"] / r["minutos_total"] * 100).round(2)

    r["situacao"] = "ok"
    r.loc[r["pct_tempo_critico"] > LIMITE_TEMPO_CRITICO_PCT, "situacao"] = "atencao"
    return r.sort_values("pct_tempo_critico", ascending=False).reset_index()


def janela_manutencao(df):
    d = df.sort_values(["id_antena", "timestamp"]).copy()
    d = d[d.groupby("id_antena").cumcount() > 0]

    total = d.groupby("minuto").agg(
        vazao_total=("vazao_mbps", "sum"),
        conexoes_total=("active_conn", "sum"),
    ).reset_index()
    total["janela"] = total["minuto"].dt.floor("10min")

    r = total.groupby("janela").agg(
        minutos=("minuto", "count"),
        vazao_media_mbps=("vazao_total", "mean"),
        conexoes_medias=("conexoes_total", "mean"),
    ).reset_index()
    r = r[r["minutos"] >= 5].copy()

    r["classificacao"] = "normal"
    if len(r) > 1:
        r.loc[r["vazao_media_mbps"].idxmax(), "classificacao"] = "pico"
        r.loc[r["vazao_media_mbps"].idxmin(), "classificacao"] = "melhor janela para manutencao"

    r["janela"] = r["janela"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return r.round(4)


def main():
    caminho = os.path.join(PASTA_SILVER, ARQUIVO_SILVER)
    s3.download_file(BUCKET, "02-silver/" + ARQUIVO_SILVER, caminho)

    df = pd.read_csv(caminho)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["minuto"] = df["timestamp"].dt.floor("min")

    fw = df.drop_duplicates("minuto")[[
        "minuto", "fw_dropped_packets", "fw_top_blocked_ip",
        "fw_latency_ms", "fw_cpu_usage",
    ]].dropna()

    salvar(zonas_mortas(df), "zonas_mortas.csv")
    salvar(eficiencia_hardware(df), "eficiencia_hardware.csv")
    salvar(predicao_sobrecarga(df), "predicao_sobrecarga.csv")
    salvar(expurgo_seguranca(fw), "expurgo_seguranca.csv")
    salvar(gargalo_saida(fw), "gargalo_saida.csv")
    salvar(auditoria_trafego(df), "auditoria_trafego.csv")
    salvar(saude_antenas(df), "saude_antenas.csv")
    salvar(janela_manutencao(df), "janela_manutencao.csv")


if __name__ == "__main__":
    main()