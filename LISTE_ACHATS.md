# Liste d'achats du photobooth (Raspberry Pi + caméra + écran tactile + Canon SELPHY CP1500)

Prix relevés le **21/09/2026** sur des sites marchands, en euros TTC, **à titre indicatif** : les prix du Raspberry Pi
ont fortement monté en 2026 (hausse du coût de la mémoire) et les stocks varient. Les lignes marquées « estimation »
n'ont pas été vérifiées : contrôlez-les avant d'acheter.

## Le matériel

| Élément | Choix conseillé | Prix indicatif |
|---|---|---|
| Ordinateur | Raspberry Pi 5, 4 Go (le programme est léger : 2 Go devraient suffire s'ils sont moins chers) | ≈ 110 à 160 € (109 € à 146 € chez RS, en rupture ; 159 € chez PcComponentes) |
| Alimentation | Alimentation officielle 27 W USB-C (5 V / 5 A) | ≈ 15 € (14,95 € chez LDLC) |
| Refroidissement | Boîtier officiel avec ventilateur, ou refroidisseur actif (le Pi 5 demande un refroidissement actif) | ≈ 15 à 25 € (estimation) |
| Carte mémoire | microSD 32 ou 64 Go, classe A1/A2 | ≈ 10 € (estimation) |
| Caméra | Raspberry Pi Camera Module 3, version standard (75°) : elle est livrée avec le câble 22 broches pour Pi 5 | ≈ 28 à 35 € (24 £ chez The Pi Hut) |
| Écran tactile | Voir « Choisir l'écran » ci-dessous | 46 € (7") à ≈ 60-120 € (10,1") |
| Câble écran | micro-HDMI → HDMI (le Pi 5 a des sorties micro-HDMI), souvent fourni avec l'écran | ≈ 8 € si à part (estimation) |
| Éclairage | Anneau lumineux LED avec trépied, ou 2 petits panneaux LED, placés autour de l'écran et de la caméra | ≈ 25 à 50 € (estimation) |
| Clé USB | 32 ou 64 Go, de marque sûre (elle contient toutes les photos) | ≈ 10 € (estimation) |
| Imprimante | Canon SELPHY CP1500 (déjà en votre possession) | – |
| Consommables | Kit Canon KP-108IN : 3 cartouches d'encre + 108 feuilles 10×15 cm (36 tirages par cartouche) | ≈ 30 € le kit, soit environ 0,28 € par tirage (29,99 € chez Conrad) |
| Support | Trépied ou pied réglable pour l'écran et la caméra, ou caisson en bois | ≈ 20 à 40 € (estimation) |

**Budget total indicatif : environ 320 € avec l'écran 7", et 400 à 450 € avec un écran 10,1"**, consommables compris
(1 kit KP-108IN). Comptez un kit par tranche de 100 tirages : chaque invité qui imprime consomme une feuille et un tiers
de cartouche, et une reprise de photo ne consomme rien (seule la planche finale s'imprime).

## Choisir l'écran

* **7" 1024×600 (ex. CUQI, 46 €)** : le programme s'y adapte (testé). C'est petit pour des invités à un mètre.
* **10,1" 1280×800 tactile capacitif** : recommandé pour l'événement. Exemples : Waveshare (115,80 € chez Kubii, livré avec
  support, alimentation, câble HDMI/micro-HDMI et câble USB), Elecrow (alimentation par micro-USB 5 V, environ 5,3 W à pleine
  luminosité). Il existe des modèles génériques moins chers.
* Vérifiez que le tactile est bien **capacitif** et **USB** (plug and play, sans pilote), et que l'écran est **IPS**.
* Un écran plus petit que la photo (1800×1200) n'est pas un problème : voir la notice.

## Points de compatibilité à vérifier avant de payer

1. **Caméra et Pi 5** : le Pi 5 utilise un connecteur caméra 22 broches. La Camera Module 3 *standard* est livrée avec le bon
   câble ; la version *Wide* (120°) ne l'est pas, il faut ajouter le « Camera Adapter Cable for Raspberry Pi 5 » (quelques euros).
   La Wide couvre un champ plus large mais déforme davantage les visages de près : la version standard convient mieux
   pour des portraits ; prenez la Wide si l'espace devant le photobooth est très réduit.
2. **Alimentation** : prenez l'alimentation officielle 27 W. Avec une alimentation plus faible, le Pi 5 limite la puissance
   disponible sur ses ports USB, ce qui peut gêner l'écran, le tactile et la clé.
3. **Écran** : alimentez-le par son propre adaptateur secteur s'il en est fourni un (ou par le Pi avec l'alimentation 27 W).
4. **Câbles** : micro-HDMI → HDMI pour le Pi 5 (côté Pi : micro-HDMI ; côté écran : HDMI), un câble USB pour le tactile.
5. **Réseau** : le Pi 5 a le Wi-Fi intégré. L'imprimante est en Wi-Fi 2,4 GHz : le Pi et l'imprimante doivent être sur le
   même réseau (box, routeur de voyage ou partage de connexion d'un téléphone).
6. **Lumière** : éclairez le visage de face, pas à contre-jour. C'est ce qui améliore le plus les photos.
7. **Sécurité de l'installation** : pas de clavier ni de souris branchés pendant l'événement, et clé USB hors de portée.

## Sources des prix (consultées le 21/09/2026)

* Raspberry Pi 5 4 Go : RS (fr.rs-online.com, befr.rs-online.com), PcComponentes.fr ; commentaire Kubii sur la hausse des prix.
* Alimentation 27 W : LDLC. Caméra Module 3 : The Pi Hut, TME. Kit KP-108IN : Conrad.fr.
* Écrans : Kubii (Waveshare 10,1"), Elektor (Elecrow 10,1"). Écran 7" : fiche Amazon.fr B0CLLHGX54 (via recherche).
