E = {
"Mot de passe administrateur": "Administrator password",
"Réinitialise le mot de passe d'un compte Open WebUI directement dans sa base (Open WebUI doit être démarré). Sans adresse, le premier administrateur est utilisé. Les connexions déjà ouvertes restent valables jusqu'à leur expiration ; redémarrez Open WebUI pour les couper.":
  "Resets the password of an Open WebUI account directly in its database (Open WebUI must be running). Without an address, the first administrator is used. Sessions already open remain valid until they expire; restart Open WebUI to cut them.",
"Compte (e-mail)": "Account (e-mail)",
"administrateur par défaut": "default administrator",
"Nouveau mot de passe": "New password",
"Réinitialiser le mot de passe": "Reset the password",
"Réinitialisation du mot de passe Open WebUI": "Open WebUI password reset",
"Adresse e-mail invalide.": "Invalid e-mail address.",
"Mot de passe refusé (8 caractères minimum, sans caractère de contrôle).": "Password refused (8 characters minimum, no control characters).",
"Mot de passe trop long (72 octets au maximum pour Open WebUI).": "Password too long (72 bytes maximum for Open WebUI).",
"Open WebUI n'est pas déployé.": "Open WebUI is not deployed.",
"Open WebUI ne répond pas (conteneur arrêté ou base indisponible).": "Open WebUI does not respond (container stopped or database unavailable).",
"Réponse inattendue d'Open WebUI.": "Unexpected response from Open WebUI.",
"Réinitialisation impossible.": "Reset impossible.",
"Aucun compte Open WebUI avec cette adresse.": "No Open WebUI account with this address.",
}
P = [
(r"Mot de passe réinitialisé pour (.+)\.", "Password reset for {1}."),
(r"Open WebUI injoignable : (.+)", "Open WebUI unreachable: {1}"),
(r"Aucun compte Open WebUI avec cette adresse\. Administrateurs : (.+)", "No Open WebUI account with this address. Administrators: {1}"),
]
