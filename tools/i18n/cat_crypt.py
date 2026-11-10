Q = "\u201c{1}\u201d"
E = {
"Disque chiffré": "Encrypted disk", "Phrase de passe du disque": "Disk passphrase", "Obligatoire": "Required", "Phrase trop courte": "Passphrase too short",
"Ce serveur n'a pas de TPM utilisable : le disque est chiffré et sa phrase de passe sera demandée à chaque démarrage.": "This server has no usable TPM: the disk is encrypted and its passphrase will be asked at every boot.",
"Choisissez-la maintenant (12 caractères au moins). La phrase provisoire de l'ISO sera supprimée.": "Choose it now (at least 12 characters). The temporary ISO passphrase will be deleted.",
"Nouvelle phrase de passe (12 caractères au moins) :": "New passphrase (at least 12 characters):", "Saisissez-la à nouveau :": "Enter it again:",
"Cette phrase est nécessaire : sans elle, le disque resterait protégé par la phrase provisoire de l'ISO.": "This passphrase is required: without it, the disk would stay protected by the temporary ISO passphrase.",
"La phrase doit contenir au moins 12 caractères.": "The passphrase must contain at least 12 characters.",
"La phrase n'a pas pu être enregistrée (voir /var/log/ollamabuntu-crypt.log).": "The passphrase could not be saved (see /var/log/ollamabuntu-crypt.log).",
"Clé de récupération du disque": "Disk recovery key", "Nouvelle clé de récupération": "New recovery key",
"Notez cette clé et conservez-la HORS de ce serveur (coffre, gestionnaire de mots de passe).": "Write this key down and keep it OFF this server (safe, password manager).",
"Elle est la seule façon de rouvrir le disque si le TPM ou la phrase de passe sont perdus, et elle ne sera plus jamais affichée.": "It is the only way to reopen the disk if the TPM or the passphrase are lost, and it will never be shown again.",
"Avez-vous enregistré cette clé en dehors de ce serveur ?": "Have you saved this key outside this server?", "Oui, c'est fait": "Yes, done", "Non, la réafficher": "No, show it again",
"Chiffrement du disque": "Disk encryption", "Chiffrement du disque : état et clé de récupération": "Disk encryption: status and recovery key", "Disque chiffré (LUKS2)": "Encrypted disk (LUKS2)",
"automatique, par le TPM de ce serveur": "automatic, by this server's TPM", "phrase de passe saisie à chaque démarrage": "passphrase typed at every boot", "enregistrée": "recorded", "absente": "missing",
"Créer une nouvelle clé de récupération (l'ancienne est révoquée)": "Create a new recovery key (the old one is revoked)",
"L'ancienne clé de récupération sera révoquée. Continuer ?": "The old recovery key will be revoked. Continue?", "Phrase de passe actuelle du disque :": "Current disk passphrase:",
"La clé n'a pas été créée (phrase refusée ?). Rien n'a été modifié.": "The key was not created (passphrase refused?). Nothing was changed.",
"Notez cette clé et conservez-la HORS de ce serveur.": "Write this key down and keep it OFF this server.", "Elle ne sera plus jamais affichée.": "It will never be shown again.",
"aucun système OllamaBuntu trouvé sur les disques de ce serveur ; un volume chiffré (LUKS) a été détecté : démarrez le serveur, puis mettez à jour depuis Système > Mises à jour ou le menu console":
  "no OllamaBuntu system found on this server's disks; an encrypted (LUKS) volume was detected: start the server, then update from System > Updates or the console menu",
"chiffrement du disque : paquets clevis et TPM2 (archive universe) ajoutés": "disk encryption: clevis and TPM2 packages (universe archive) added",
"disque chiffré (LUKS2) : phrase provisoire générée pour cette ISO, supprimée à la fin de l'installation": "encrypted disk (LUKS2): temporary passphrase generated for this ISO, deleted at the end of the installation",
"chiffrement du disque demandé : les paquets clevis et TPM2 n'ont pas pu être téléchargés (voir ci-dessus)": "disk encryption requested: the clevis and TPM2 packages could not be downloaded (see above)",
"chiffrement du disque demandé : paquets clevis et TPM2 non embarqués": "disk encryption requested: clevis and TPM2 packages not bundled",
}
P = [
(r"Déverrouillage au démarrage : (.+)", "Unlock at boot: {1}"), (r"Clé de récupération : (.+)", "Recovery key: {1}"),
(r"DISK_ENCRYPTION doit valoir none ou tpm \(reçu : (.*)\)", "DISK_ENCRYPTION must be none or tpm (received: {1})"),
]
