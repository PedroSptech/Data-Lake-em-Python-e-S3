ARQUIVO <- "silver_consolidado.csv"
LIMITE_CONEXOES <- 40

df <- read.csv(ARQUIVO, stringsAsFactors = FALSE)
df$timestamp <- as.POSIXct(df$timestamp, tz = "UTC")
df$minuto <- as.POSIXct(trunc(df$timestamp, "mins"))

fw <- df[!duplicated(df$minuto), c("minuto", "fw_dropped_packets", "fw_top_blocked_ip", "fw_latency_ms", "fw_cpu_usage")]
fw <- fw[complete.cases(fw), ]

janela_antena <- function(ap) {
  g <- df[df$id_antena == ap, ]
  g <- tail(g[order(g$timestamp), ], 30)
  g$x <- seq_len(nrow(g)) - 1
  g
}

#1 - ZONAS MORTAS OU SUBUTILIZADAS
zonas <- aggregate(cbind(vazao_mbps, active_conn) ~ id_antena, data = df, FUN = mean)
limite_zona <- 0.5 * mean(zonas$vazao_mbps)
zonas$classificacao <- ifelse(zonas$vazao_mbps < limite_zona, "subutilizada", "normal")
print(zonas[order(zonas$vazao_mbps), ], row.names = FALSE)

barplot(zonas$vazao_mbps, names.arg = zonas$id_antena, las = 2,
        col = ifelse(zonas$classificacao == "subutilizada", "red", "steelblue"),
        main = "Zonas mortas - Vazão média por antena",
        xlab = "Antena", ylab = "Vazão média (Mbps)")
abline(h = limite_zona, col = "darkorange", lwd = 2, lty = 2)
legend("topright", legend = c("Normal", "Subutilizada", "Limite de subutilização"),
       fill = c("steelblue", "red", NA), border = NA,
       lty = c(NA, NA, 2), col = c(NA, NA, "darkorange"))

#2 - PREDICAO DE SOBRECARGA (FOCO EM PREVISAO)
predicao <- data.frame()
for (ap in unique(df$id_antena)) {
  g <- janela_antena(ap)
  modelo <- lm(active_conn ~ x, data = g)
  crescimento <- coef(modelo)[["x"]]
  atual <- mean(tail(g$active_conn, 3))
  minutos <- NA
  if (atual >= LIMITE_CONEXOES) {
    minutos <- 0
  } else if (crescimento > 0.05) {
    minutos <- (LIMITE_CONEXOES - atual) / crescimento
  }
  predicao <- rbind(predicao, data.frame(
    id_antena = ap,
    conexoes_atuais = round(atual, 1),
    crescimento_por_min = round(crescimento, 3),
    p_valor = signif(summary(modelo)$coefficients["x", "Pr(>|t|)"], 3),
    minutos_ate_limite = round(minutos, 1)
  ))
}
print(predicao, row.names = FALSE)

grafico_predicao <- function(ap) {
  g <- janela_antena(ap)
  modelo <- lm(active_conn ~ x, data = g)
  plot(g$timestamp, g$active_conn, type = "o", pch = 19, col = "steelblue",
       xlab = "Horário", ylab = "Conexões ativas",
       main = paste(ap, "- Predição de sobrecarga"),
       ylim = c(0, max(LIMITE_CONEXOES, g$active_conn) + 5))
  lines(g$timestamp, fitted(modelo), col = "red", lwd = 2)
  abline(h = LIMITE_CONEXOES, col = "darkorange", lty = 2, lwd = 2)
  legend("topleft", legend = c("Conexões observadas", "Tendência", "Limite de sobrecarga"),
         col = c("steelblue", "red", "darkorange"), lty = c(1, 1, 2), pch = c(19, NA, NA))
}

grafico_predicao("ap02")

g <- janela_antena("ap02")
plot(g$timestamp, g$active_conn, xlab = "Horario", ylab = "Conexoes ativas",
     main = "ap02: conexoes ativas e limite", pch = 19, col = "steelblue",
     ylim = c(0, max(LIMITE_CONEXOES, g$active_conn) + 5))
lines(g$timestamp, fitted(lm(active_conn ~ x, data = g)), col = "red", lwd = 2)
abline(h = LIMITE_CONEXOES, col = "darkorange", lty = 2, lwd = 2)

grafico_predicao("ap03")
grafico_predicao("ap01")

# 3 - EFICIENCIA DE HARDWARE 
df$trafego_mb <- df$vazao_mbps * 60 / 8
trafego <- aggregate(trafego_mb ~ id_antena, data = df, FUN = sum)
cpu <- aggregate(cpu_usage ~ id_antena, data = df, FUN = mean)
efi <- merge(trafego, cpu, by = "id_antena")
efi$trafego_por_cpu <- efi$trafego_mb / efi$cpu_usage
efi <- efi[order(-efi$trafego_por_cpu), ]
print(efi, row.names = FALSE)

barplot(efi$trafego_por_cpu, names.arg = efi$id_antena, las = 2, col = "steelblue",
        main = "Eficiência de hardware por antena",
        xlab = "Antena", ylab = "Tráfego por unidade de CPU")

# 4 - ANALISE DE EXPURGO (EFICIENCIA DE SEGURANCA)
limite <- max(median(fw$fw_dropped_packets) * 5, 100)
fw$em_ataque <- fw$fw_dropped_packets > limite
fw$hora <- as.POSIXct(trunc(fw$minuto, "hours"))
pacotes <- aggregate(fw_dropped_packets ~ hora, data = fw, FUN = sum)
minutos_ataque <- aggregate(em_ataque ~ hora, data = fw, FUN = sum)
cpu_max <- aggregate(fw_cpu_usage ~ hora, data = fw, FUN = max)
expurgo <- Reduce(function(a, b) merge(a, b, by = "hora"), list(pacotes, minutos_ataque, cpu_max))
print(expurgo, row.names = FALSE)
if (any(fw$em_ataque)) {
  ip_suspeito <- names(sort(table(fw$fw_top_blocked_ip[fw$em_ataque]), decreasing = TRUE))[1]
  cat("IP suspeito:", ip_suspeito, "\n")
}

plot(expurgo$hora, expurgo$fw_dropped_packets, type = "o", pch = 19, col = "steelblue",
     xlab = "Horário", ylab = "Pacotes descartados",
     main = "Expurgo de segurança - Pacotes descartados")
abline(h = limite, col = "red", lty = 2, lwd = 2)
pontos_ataque <- expurgo$fw_dropped_packets > limite
points(expurgo$hora[pontos_ataque], expurgo$fw_dropped_packets[pontos_ataque],
       col = "red", pch = 19, cex = 1.3)
legend("topright", legend = c("Pacotes descartados", "Limite de ataque", "Possível ataque"),
       col = c("steelblue", "red", "red"), lty = c(1, 2, NA), pch = c(19, NA, 19))

