# Installation du photobooth sur un Raspberry Pi 5 neuf

Mode opératoire pour passer d'un Raspberry Pi 5 sorti de sa boîte à un photobooth fonctionnel (caméra, écran tactile, imprimante Canon SELPHY CP1500, clé USB).

Les points **non validés sur du vrai matériel** sont signalés par la mention « à valider ».

---

## 0. Montage matériel (Pi éteint)

- Fixez le refroidisseur ou le boîtier ventilé, et insérez la carte microSD.
- Branchez la nappe de la Camera Module 3 sur un port caméra du Pi 5, en suivant le sens indiqué dans la doc officielle (loquet levé, nappe insérée, loquet rabaissé).
- Branchez l'écran : micro-HDMI vers HDMI pour l'image, et USB pour le tactile.
- Branchez l'alimentation officielle 27 W en dernier.

## 1. Préparer la carte microSD (depuis un PC)

Avec **Raspberry Pi Imager**, choisissez **Raspberry Pi OS (64-bit) avec bureau** (base Debian Trixie, bureau labwc sous Wayland).

Dans les réglages de personnalisation :

- nom d'hôte : `photobooth`
- nom d'utilisateur : **`pi`** (le fichier de démarrage automatique du projet suppose `/home/pi` ; sinon il faudra l'adapter)
- mot de passe
- Wi-Fi de votre box
- pays : France, clavier : `fr`
- SSH activé

## 2. Premier démarrage et mise à jour

Dans un terminal sur le Pi (ou en SSH) :

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## 3. Vérifier que la caméra est détectée

```bash
rpicam-hello --list-cameras
rpicam-hello -t 5000
```

Si aucune caméra n'apparaît, vérifiez la nappe avant d'aller plus loin.

## 4. Installer les paquets

```bash
sudo apt install -y python3-pygame python3-pil python3-numpy python3-flask \
                    python3-picamera2 cups fonts-dejavu-core fonts-liberation
sudo usermod -aG lpadmin $USER
sudo reboot
```

Installez ces paquets avec `apt`, **sans environnement virtuel** (`.venv`) : `picamera2` doit rester celui du système.
Le paquet `opencv` n'est pas nécessaire (il ne sert que pour une webcam USB).

## 5. Copier le projet sur le Pi

Depuis le PC Windows, dans PowerShell (sans le dossier `.venv` créé par `lancer.bat`) :

```powershell
scp -r C:\test\PhotoBooth-main pi@photobooth.local:~/photobooth
```

Une clé USB fonctionne aussi. Sur le Pi, supprimez ensuite `~/photobooth/.venv` s'il a été copié.

**Important** : vérifiez que c'est la version modifiée de `photobooth.py` (avec le bouton « Touchez pour la photo 2/3 » entre deux photos) qui se trouve dans `~/photobooth`, et non celle de l'archive d'origine.

## 6. Premier test

```bash
cd ~/photobooth
python3 photobooth.py --windowed
```

- La caméra est détectée automatiquement.
- Si « Caméra de TEST » s'affiche : la caméra n'est pas détectée, revenez à l'étape 3.
- Si le rouge et le bleu sont inversés : dans `hardware.py`, remplacez `"BGR888"` par `"RGB888"`.
- Pour le plein écran, lancez sans `--windowed`.

## 7. Imprimante Canon SELPHY CP1500 (à valider)

1. Sur l'imprimante, connectez-la au **même Wi-Fi 2,4 GHz** que le Pi (voir le manuel Canon).
2. Sur le Pi, ouvrez `http://localhost:631` → *Administration* → *Ajouter une imprimante*. Choisissez la SELPHY et le pilote **IPP Everywhere**.
3. Testez : `lp -d NOM_IMPRIMANTE une_image.jpg`
4. Dans le photobooth : maintenez le doigt sur l'icône des réglages (en haut à droite) → *Système* → choisissez l'imprimante.

Points d'attention :

- Le README du projet indique que cette partie est à valider avec l'imprimante réelle.
- Marges ou mauvais recadrage : listez les options avec `lpoptions -p NOM_IMPRIMANTE -l` et adaptez `"print_options"` dans `config.json`, par exemple `"media=Postcard fit-to-page"`.
- Photobooth qui dit « Imprimante non connectée » alors que CUPS la voit : ajoutez son IP dans `config.json` : `"printer_host": "192.168.1.50"`.
- Planche à 2 photos (portrait) qui sort dans le mauvais sens : ajoutez par exemple `"orientation-requested=3"` dans `"print_options"`.
- Si IPP Everywhere échoue, des utilisateurs signalent un repli sur les pilotes Gutenprint. Un témoignage décrit un pilote CP-1300 qui n'imprime qu'un seul tirage avant de bloquer : testez plusieurs impressions de suite.
- Évitez la connexion USB au début : des témoignages indiquent que `ipp-usb` peut empêcher l'ajout de l'imprimante dans CUPS.

## 8. Clé USB (à valider)

- Branchez une clé FAT32, exFAT ou ext4. Le badge « Clé USB : OK » apparaît en haut à gauche de l'accueil.
- Les photos sont d'abord enregistrées sur le Pi (`photos/`), puis copiées sur la clé (`Photobooth/`).
- Avant de la retirer : *Menu → Stockage → Éjecter la clé USB en toute sécurité*.

## 9. Réglages avant l'événement

- **Créez le code à 4 chiffres dès maintenant** : le premier accès au menu vous le demande. Tant qu'il n'existe pas, n'importe qui peut le créer.
- Choisissez le fond, le nombre de photos, la durée du décompte et vos textes.
- Ne laissez ni clavier ni souris branchés pendant l'événement.
- Pensez à toucher « Déconnecter » avant de laisser le photobooth aux invités.

## 10. Démarrage automatique en plein écran (à valider)

```bash
sudo raspi-config        # Système → Connexion automatique → Bureau
mkdir -p ~/.config/autostart
cp ~/photobooth/photobooth.desktop ~/.config/autostart/
```

- Si votre utilisateur n'est pas `pi`, corrigez les deux chemins `/home/pi/...` dans `photobooth.desktop`.
- Redémarrez pour tester.
- Si l'écran s'éteint tout seul, désactivez la mise en veille dans `raspi-config` → *Options d'affichage*.

---

## Récapitulatif de ce qui reste à valider sur votre matériel

- La SELPHY via CUPS
- La détection et l'éjection de la clé USB
- Le démarrage automatique
- Le tactile réel

## En cas de problème

| Symptôme | Piste |
|---|---|
| « Caméra de TEST » affichée | Nappe mal branchée ; vérifier `rpicam-hello --list-cameras` |
| Couleurs rouge/bleu inversées | `"BGR888"` → `"RGB888"` dans `hardware.py` |
| Le toucher tombe à côté | Calibrer l'écran tactile (outils du fabricant) |
| Imprimante « non connectée » | Vérifier le Wi-Fi 2,4 GHz, ajouter `printer_host` dans `config.json` |
| Code d'accès oublié | Arrêter le programme, supprimer `"pin_salt"` et `"pin_hash"` dans `config.json`, relancer |
| Téléphone sans accès à la page des fonds | Il doit être sur le même réseau que le Pi (adresse `http://IP:8080`) |
