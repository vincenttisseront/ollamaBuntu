# Reprise automatique entre serveurs
E = {
"Échecs (24 h)": "Failures (24 h)", "repris": "retried",
}
P = [
(r"Reprise automatique \(24 h\) : (\d+) requête\(s\) sauvée\(s\) par un autre serveur, (\d+) perdue\(s\) faute de serveur disponible\.", "Automatic retry (24 h): {1} request(s) saved by another server, {2} lost for lack of an available server."),
(r"Reprise automatique \(24 h\) : (\d+) requête\(s\) sauvée\(s\) par un autre serveur\.", "Automatic retry (24 h): {1} request(s) saved by another server."),
]
