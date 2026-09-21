# Photobooth tactile (Raspberry Pi + caméra + Canon SELPHY CP1500)

## Présentation

Le programme a été testé sur ordinateur avec une caméra simulée (décompte, prise des photos, planche finale,
menu, clavier, envoi de fond depuis un téléphone). Il n'a pas encore été essayé sur un vrai Raspberry Pi avec la
caméra et la SELPHY : voir la section « Ce qu'il reste à valider » plus bas.

### Comment ça marche

* **Accueil** : l'aperçu de la caméra s'affiche avec un cadre qui montre exactement la zone qui sera imprimée.
  Il suffit de toucher l'écran pour lancer le décompte.
* **Décompte** : 3, 2, 1, un flash blanc, puis la photo prise s'affiche en grand.
* **Validation** : après chaque photo, l'invité touche **« Conserver »** pour passer à la suivante ou **« Reprendre »**
  pour la refaire (sans limite). Sans réponse au bout de 30 secondes, la photo est conservée.
* **Résultat et impression** : quand le nombre de photos demandé est atteint, la planche finale s'affiche.
  **Si l'imprimante est connectée**, l'impression démarre automatiquement après **3 secondes** (réglable de 1 à 10 s),
  pendant lesquelles un gros bouton rouge **« Ne pas imprimer »** permet d'annuler. Dans tous les cas la photo est enregistrée.
  Si l'imprimante n'est pas connectée, la planche est seulement enregistrée et l'écran l'indique.

### La galerie et le mode administrateur

* **Galerie (invités)** : le bouton « Galerie » de l'accueil ouvre les planches déjà prises, en commençant par la plus récente.
  On avance (« Suivant »), on recule (« Précédent ») ou on fait glisser le doigt, puis on sort avec « Quitter ».
  Les invités ne peuvent jamais supprimer une photo. Leur droit de réimprimer une planche se règle dans l'onglet *Système*.
* **Administrateur** : après saisie du code (engrenage de l'accueil, ou bouton « Admin » dans la galerie), le mode
  administrateur est actif : les boutons « Imprimer » (réimpression de la planche affichée) et « Supprimer » apparaissent dans la galerie, et le menu de réglages s'ouvre sans redemander le code.
  Le bouton orange **« Déconnecter »** (accueil, galerie et menu) ramène au mode utilisateur.
* **Sauvegarde sur clé USB** : chaque planche et chaque photo individuelle est copiée sur la clé (dossier `Photobooth/`).

### Le menu de configuration

On l'ouvre en maintenant le doigt environ 2 secondes sur l'engrenage en haut à droite de l'écran d'accueil.
**L'accès est protégé par un code à 4 chiffres** (voir « Code d'accès » plus bas). Un aperçu de la planche se met à jour en direct à chaque réglage.

* **Fond** : 7 fonds fournis (or, argent, rose, bleu nuit, noir et or, blanc, émeraude). Vous pouvez en ajouter un
  depuis une clé USB, ou depuis un téléphone sur le même Wi-Fi via une petite page web dont l'adresse s'affiche à l'écran
  (elle demande le code d'accès).
* **Photos** : 1, 2 ou 3 photos, et la durée du décompte. Mises en page : 1 photo (paysage, centrée),
  **2 photos en portrait** (deux photos empilées, texte en dessous : planche 1200×1800), 3 photos (paysage, une grande
  et deux petites comme la planche d'origine).
* **Texte** : 1 ou 2 lignes, un clavier tactile avec les accents, la taille et 14 couleurs au choix pour chaque ligne,
  et le choix de la police.
* **Système** : l'imprimante, le nombre de copies, le comportement après la photo
  (impression automatique annulable, ou sans impression), le délai avant impression et l'autorisation donnée aux invités
  de réimprimer depuis la galerie.

Toutes les planches sont gardées dans `photos/` de l'appareil, avec les photos individuelles dans `photos/raw/`,
et copiées sur la clé USB.

### Ce qu'il reste à valider

* **Réglages de l'imprimante** : la partie qui explique comment brancher la SELPHY via CUPS (section 2) est à valider
  avec l'imprimante réelle. Il faudra peut-être ajuster l'option de format du papier pour éviter des marges.
* **Clé USB** : la détection automatique et l'éjection sécurisée de la clé (section 6) dépendent du système
  et sont à valider avec votre clé sur le Raspberry Pi.
* **Police** : la police par défaut ressemble peu à celle d'une invitation. Déposez la vôtre (un fichier .ttf)
  dans le dossier `fonts/` et elle apparaîtra dans le menu.
* **Couleurs** : si l'aperçu de la caméra a le rouge et le bleu inversés, voir la section 7 pour la ligne à changer.

Écran tactile → aperçu en direct → décompte 3-2-1 → 1, 2 ou 3 photos → planche 10×15 cm → impression.

### Matériel à acheter

Voir `LISTE_ACHATS.md` (liste, budget indicatif et points de compatibilité).

## 1. Installation (Raspberry Pi OS)

```bash
sudo apt update
sudo apt install -y python3-pygame python3-pil python3-numpy python3-flask \
                    python3-picamera2 cups fonts-dejavu-core fonts-liberation
sudo usermod -aG lpadmin $USER        # puis se déconnecter / reconnecter
```

Copiez le dossier `photobooth/` dans `/home/pi/` (adaptez le chemin si votre utilisateur n'est pas « pi »).

## 2. Imprimante (SELPHY CP1500)

1. Connectez l'imprimante au même réseau Wi-Fi 2,4 GHz que le Raspberry Pi (menu de l'imprimante).
2. Ouvrez `http://localhost:631` sur le Pi → *Administration* → *Ajouter une imprimante*.
   Choisissez la SELPHY détectée et le pilote « IPP Everywhere » (sans pilote / AirPrint).
3. Testez : `lp -d NOM_IMPRIMANTE une_image.jpg`
4. Dans le photobooth : maintenez le doigt en haut à droite → *Système* → choisissez l'imprimante.

**Détection de l'imprimante** : le photobooth vérifie toutes les 10 secondes si l'imprimante est joignable
(badge « Imprimante : OK » / « Imprimante non connectée » en haut à gauche de l'accueil). Pour une imprimante réseau,
il teste sa présence sur le réseau. Si l'imprimante a été ajoutée à CUPS avec une adresse de type `dnssd://…`, ce test
ne peut pas la détecter éteinte : indiquez alors son adresse IP dans `config.json` (`"printer_host": "192.168.1.50"`).
Cette détection dépend de votre installation et est à valider avec l'imprimante réelle.

Avec 2 photos, la planche est en portrait (1200×1800) : vérifiez à l'essai qu'elle sort dans le bon sens et sans
rotation inattendue (sinon, ajoutez une option d'orientation dans `"print_options"`, par ex. `"orientation-requested=3"`).

Si le papier ressort avec des marges ou un mauvais recadrage, listez les options avec
`lpoptions -p NOM_IMPRIMANTE -l` et adaptez `"print_options"` dans `config.json`
(ex. `"media=Postcard fit-to-page"`). Cette partie dépend de votre installation : à valider avec l'imprimante réelle.

## 3. Lancer

```bash
cd ~/photobooth
python3 photobooth.py                 # plein écran
python3 photobooth.py --windowed --camera fake   # test sur ordinateur, sans caméra
```

Démarrage automatique : `mkdir -p ~/.config/autostart && cp photobooth.desktop ~/.config/autostart/`

## 4. Menu de configuration

Sur l'écran d'accueil, **maintenez le doigt ~2 secondes sur l'engrenage en haut à droite** (code demandé, sauf si vous êtes déjà connecté en administrateur).

* **Fond** : 7 fonds fournis (or, argent, rose, bleu nuit, noir et or, blanc, émeraude).
  Pour ajouter le vôtre : *Importer depuis une clé USB* (photo au format paysage 3:2 idéalement,
  elle est recadrée au centre), ou depuis un téléphone sur la même Wi-Fi à l'adresse affichée (`http://IP:8080`).
  Les fonds paysage sont pivotés de 90° pour la planche portrait (2 photos) ; une image importée en hauteur
  (idéalement 1200×1800) reste en portrait et est pivotée pour les planches paysage.
* **Photos** : 1, 2 ou 3 photos (2 photos = planche portrait) ; durée du décompte.
* **Texte** : 1 ou 2 lignes, clavier tactile (accents inclus), taille et couleur de chaque ligne, police.
* **Stockage** : copie sur clé USB ou copie interne seulement, état de la clé et espace libre, copie manuelle,
  éjection de la clé en toute sécurité.
* **Système** : imprimante, nombre de copies, changement du code d'accès, mode après la photo
  (impression automatique annulable ou sans impression), délai avant impression et autorisation d'imprimer depuis la galerie.

Tous les réglages sont enregistrés dans `config.json`. Les planches sont conservées dans `photos/`
(et les photos individuelles dans `photos/raw/`) : vous pouvez les réimprimer ou les récupérer après la fête.

## 5. Code d'accès et mode administrateur

* **Au tout premier accès**, le photobooth demande de choisir un code à 4 chiffres (à saisir deux fois).
  Faites-le **avant l'événement** : tant qu'aucun code n'existe, la première personne qui ouvre le menu peut en créer un.
* Ensuite, il faut saisir ce code pour passer en mode administrateur. Après **3 essais ratés**, le clavier est bloqué 30 secondes.
* Le mode administrateur reste actif jusqu'à ce que vous touchiez **« Déconnecter »**, ou automatiquement après
  **10 minutes sans action d'administration** (les photos prises par les invités ne prolongent pas la session).
  Pensez à vous déconnecter avant de laisser le photobooth aux invités.
* Le menu de réglages se referme seul après 2 minutes sans toucher l'écran (l'administrateur reste connecté),
  l'écran de saisie du code après 30 secondes et la galerie après 2 minutes d'inactivité.
* Le code se change dans *Système* → *Changer le code d'accès*.
* La page web d'envoi de fond depuis un téléphone demande aussi ce code (5 erreurs = blocage d'une minute). Tant qu'aucun code n'est défini, elle refuse tout envoi.
* Le code est enregistré dans `config.json` sous forme de hachage, jamais en clair.
* **Code oublié** : éteignez le programme, ouvrez `config.json`, supprimez les lignes `"pin_salt"` et `"pin_hash"`
  (ou mettez leurs valeurs à `""`), puis relancez : le photobooth redemandera de créer un code.

Pour empêcher aussi l'accès au Raspberry Pi lui-même, ne laissez ni clavier ni souris branchés pendant l'événement :
seul l'écran tactile est alors accessible, et il ne montre que le photobooth.

## 6. Sauvegarde sur clé USB

* Branchez une clé USB (FAT32, exFAT ou ext4) sur le Raspberry Pi : elle est détectée automatiquement
  (Raspberry Pi OS la monte dans `/media/…`). Un badge « Clé USB : OK » s'affiche en haut à gauche de l'accueil,
  ou « Pas de clé USB » si elle est absente.
* Les photos sont **toujours enregistrées d'abord sur l'appareil** (dossier `photos/`), puis copiées sur la clé
  dans `Photobooth/` (planches) et `Photobooth/raw/` (photos individuelles). Si la clé est absente ou retirée,
  rien n'est perdu : les photos manquantes sont copiées dès que la clé est de nouveau branchée.
* Pour ne pas abîmer la clé, utilisez **Menu → Stockage → « Éjecter la clé USB en toute sécurité »**
  avant de la débrancher.
* La suppression d'une photo par l'administrateur efface aussi sa copie sur la clé **si elle est branchée à ce moment-là**.
  Une clé absente lors de la suppression conservera sa copie.
* Si la détection automatique ne convient pas, indiquez un dossier précis dans `config.json` : `"usb_path": "/media/pi/MACLE"`.
* L'éjection et la détection dépendent du système : à valider avec votre clé sur le Raspberry Pi.

## 7. Si quelque chose ne va pas

* **Couleurs de l'aperçu inversées (rouge/bleu)** : dans `hardware.py`, remplacez `"BGR888"` par `"RGB888"`.
* **Le toucher tombe à côté** : calibrez l'écran tactile (paramètres de l'écran du fabricant).
* **« Caméra de TEST »** affichée : la caméra n'est pas détectée (vérifiez la nappe et `rpicam-hello`).
* **Le téléphone n'accède pas à la page de fonds** : il doit être sur le même réseau que le Pi.
  Cette page demande le code d'accès, mais évitez tout de même de la laisser sur un réseau public.
