# Data-Lake-em-Python-e-S3
Data Lake em Python e S3

Projeto que simula dados de 3 antenas Wi-Fi e 1 firewall e os organiza em um Data Lake no Amazon S3, em três camadas. No final, gera relatórios para responder perguntas sobre a rede

Camadas
Bronze: JSONs com os dados brutos, enviados a cada minuto (local2bronze_aps.py e local2bronze_fw.py)
Silver: um CSV único com os dados tratados e cruzados (bronze2silver.py)
Gold: relatórios em CSV com as respostas (silver2gold.py)
