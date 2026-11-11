<div align="center">

[![GitHub Release](https://img.shields.io/github/release/Pulpyyyy/ESPSomfy-RTS-companion.svg?style=for-the-badge)](https://github.com/Pulpyyyy/ESPSomfy-RTS-companion/releases) [![License](https://img.shields.io/github/license/Pulpyyyy/ESPSomfy-RTS-companion.svg?style=for-the-badge)](LICENSE) [![Firmware](https://img.shields.io/github/release/Pulpyyyy/ESPSomfy-RTS.svg?style=for-the-badge&label=firmware)](https://github.com/Pulpyyyy/ESPSomfy-RTS/releases)

<img src="images/banner.png" alt="ESPSomfy-RTS Companion : l'intégration Home Assistant du firmware ESPSomfy-RTS v4" width="100%">

<a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=Pulpyyyy&repository=ESPSomfy-RTS-companion&category=integration">
  <img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Ouvrir ce dépôt dans le Marketplace de votre Home Assistant">
</a>

**[English version](README.md)** · [Services](docs/Services.md) · [Automatisations](docs/Automations.md) · [Signaler un problème](https://github.com/Pulpyyyy/ESPSomfy-RTS-companion/issues)

</div>

**ESPSomfy-RTS Companion** fait entrer vos volets, stores, bannes, portails et portes de garage Somfy RTS dans Home Assistant, grâce à une carte ESP32 qui fait tourner le **[firmware ESPSomfy-RTS v4](https://github.com/Pulpyyyy/ESPSomfy-RTS)**. Elle trouve la carte toute seule, suit chaque mouvement, y compris ceux faits avec vos télécommandes, et installe les mises à jour du firmware depuis Home Assistant.

## Commencez par le firmware

L'intégration dialogue avec une ESP32 et un module radio CC1101 équipés d'**ESPSomfy-RTS v4** :

* **[Installez-le depuis votre navigateur](https://pulpyyyy.github.io/ESPSomfy-RTS/)** (Chrome ou Edge, câble USB), ou avec les fichiers de la [dernière version](https://github.com/Pulpyyyy/ESPSomfy-RTS/releases).
* **Chaque ordre passe** : les ordres sont mis en file, partent en un seul train continu comme un appui sur une télécommande, et la carte écoute avant d'émettre.
* **Mises à jour depuis GitHub en un clic**, installées au démarrage, avec retour automatique à la version précédente si la nouvelle ne démarre pas.
* **Une interface moderne** pour téléphone et ordinateur : accueil par pièce, panneau de position, calibrage guidé avec votre télécommande, diagnostic radio.
* **Sécurisé** : code PIN ou mot de passe, pour toute la carte ou pour sa configuration seulement.

Le [wiki du firmware](https://github.com/Pulpyyyy/ESPSomfy-RTS/wiki) détaille le matériel, la mise en route et chaque réglage, en français et en anglais.

## Installation

### Depuis le Marketplace (Home Assistant 2026.11 ou plus récent)

Cliquez sur le bouton ci-dessus, ou allez dans **Paramètres › Marketplace › Ajouter depuis un lien** et saisissez `https://github.com/Pulpyyyy/ESPSomfy-RTS-companion`, puis installez **ESPSomfy-RTS Companion** et redémarrez Home Assistant.

### Avec HACS (versions plus anciennes de Home Assistant)

**HACS › Intégrations › ⋮ › Dépôts personnalisés**, ajoutez `https://github.com/Pulpyyyy/ESPSomfy-RTS-companion` dans la catégorie **Intégration**, installez-la, puis redémarrez Home Assistant.

### À la main

Copiez `custom_components/espsomfy_rts_companion/` dans le dossier `config/custom_components/` de Home Assistant, puis redémarrez-le.

### Premier réglage

Home Assistant trouve la carte tout seul (UPnP ou mDNS) : elle apparaît dans **Paramètres › Appareils et services**, prête à être ajoutée. Saisissez le code PIN ou le mot de passe si la carte en a un. Si Home Assistant est sur un autre segment de réseau, ajoutez l'intégration à la main avec l'adresse de la carte.

## Vous venez d'une intégration ESPSomfy-RTS précédente

ESPSomfy-RTS Companion prend la suite des intégrations ESPSomfy-RTS précédentes pour Home Assistant, sous un nouveau domaine. Quand vous ajoutez une carte déjà installée par une intégration précédente, Companion propose de la reprendre, et ne le fait que si vous confirmez : chaque entité garde son identifiant, chaque appareil garde sa pièce et son nom, et l'historique continue.

1. Installez ESPSomfy-RTS Companion comme ci-dessus et redémarrez Home Assistant.
2. Ajoutez la carte quand Home Assistant la propose, ou à la main avec son adresse, et saisissez son code PIN ou son mot de passe.
3. Si l'intégration précédente est encore installée pour cette carte, l'installation affiche une étape qui indique combien d'entités et d'appareils seront déplacés, et demande s'il faut la reprendre. Confirmez pour les déplacer ici et retirer l'intégration précédente ; leurs identifiants d'entités, leurs pièces, leurs noms et leur historique sont conservés. Refusez pour ajouter la carte comme neuve.
4. Dans vos automatisations et scripts, remplacez les actions de l'intégration précédente par `espsomfy_rts_companion.*`. Quand vous avez repris la carte, les identifiants d'entités et les événements `espsomfy-rts_event` ne changent pas.

Reprise à la main : si vous préférez ne pas utiliser l'étape de reprise, refusez-la ou retirez d'abord l'intégration précédente de Paramètres › Appareils et services, puis ajoutez la carte à neuf. Ses entités reçoivent de nouveaux identifiants, que vous pouvez renommer dans leurs paramètres.

## Fonctionnalités

* **Contrôle complet** : ouvrir, fermer, arrêter et régler une position en pourcentage, inclinaison comprise, pour les volets et les groupes. Un groupe prend la classe de ce qu'il fait bouger : s'il contient un portail ou une porte de garage, Home Assistant et les assistants vocaux le traitent comme tel, et une réparation prévient quand il contient aussi des volets.
* **Toujours synchronisée** : les positions suivent la carte en temps réel, que l'ordre vienne de Home Assistant, d'une télécommande ou de l'interface de la carte.
* **Pièces et groupes alignés** : les pièces de la carte sont des zones de Home Assistant, dans les deux sens. Déplacez un volet dans une autre zone, ou renommez une zone, et la carte suit ; changez une pièce sur la carte et Home Assistant suit. Quand un volet n'est pas dans la même pièce des deux côtés, rien n'est modifié : une réparation demande quel côté garder. Les groupes de la carte apparaissent comme étiquettes sur leurs volets. Désactivable dans les options de l'intégration.
* **La carte en un clic** : la carte, chaque volet et chaque groupe renvoient à la page correspondante de l'interface web de la carte (**Visiter** sur la page de l'appareil).
* **Mises à jour du firmware** : une entité `update` signale chaque nouvelle version d'ESPSomfy-RTS et l'installe depuis Home Assistant.
* **Automatisations** : les volets sont des entités `cover` standard, et l'intégration ajoute des actions pour les pas, les commandes RTS brutes, la correction de position sans mouvement, les drapeaux soleil et vent, le redémarrage et la sauvegarde (voir [Services](docs/Services.md)).
* **État de la carte** : un capteur de diagnostic *Connectivité* par carte est `on` tant que le websocket est connecté et que l'API HTTP répond (vérifié chaque minute).
* **Santé radio** : à partir des mesures de la carte, l'intégration calcule combien de répétitions il faut à chaque volet, comme la page Diagnostic RF de la carte. Un volet qui répète trop peu reçoit une réparation qui règle la valeur conseillée en un clic ; une liaison faible mesurée avec la session guidée reçoit un avertissement avec quoi faire. *Bruit radio*, *Ordres radio perdus* et une *Marge radio* par volet sont des capteurs de diagnostic. Une carte encore en firmware 2.x ou 3.x reçoit une réparation qui mène à l'installation depuis le navigateur.
* **Restauration** : l’action `espsomfy_rts_companion.restore` renvoie un backup enregistré vers la carte et restaure les sections choisies (les volets par défaut). La carte redémarre une fois terminé.
* **Automatisations depuis vos télécommandes** : un déclencheur d’appareil démarre une automatisation quand la carte voit une commande pour un volet, y compris un appui sur une télécommande physique.
* **Diagnostics** : téléchargez les diagnostics de l’entrée pour un rapport de bug, secrets retirés.
* **Télécommandes en entités** : chaque télécommande liée à un volet devient une entité `event` (« Télécommande #1 », « #2 »…), pour démarrer une automatisation sur un appui, la renommer et voir son historique. Un seul déclenchement par appui.
* **Volets et groupes suivent la carte** : un volet ajouté sur la carte apparaît tout seul dans Home Assistant, un volet supprimé sur la carte disparaît avec son appareil, même s'il a été supprimé pendant que Home Assistant était arrêté. Un appareil encore présent sur la carte ne peut pas être supprimé à la main, il reviendrait aussitôt.
* **Sauvegardes** : le bouton *Sauvegarde* (ou l'action `espsomfy_rts_companion.backup`) enregistre la configuration de la carte sur l'hôte Home Assistant. Un échec lève une erreur visible dans les traces d'automatisation, le capteur *Dernière sauvegarde* indique la plus récente, et le nombre de sauvegardes conservées (5 par défaut, de 1 à 50) se règle dans les options de l'intégration. Chaque sauvegarde de Home Assistant prend d'abord une copie fraîche de chaque carte (sauf si la dernière a moins d'une heure) : restaurer Home Assistant ramène aussi la configuration de vos cartes, et une carte qui ne répond pas ne fait jamais échouer la sauvegarde de Home Assistant.

## Événements

Chaque commande vue par la carte (depuis Home Assistant, une télécommande physique ou son interface web) est envoyée sur le bus d'événements de Home Assistant sous la forme d'un événement `espsomfy-rts_event`.

| Clé | Description |
| :--- | :--- |
| `entity_id` | L'entité ciblée dans Home Assistant (par ex. `cover.volet_salon`). |
| `event_key` | Le déclencheur (actuellement toujours `shadeCommand`). |
| `name` | Le nom de l'équipement. |
| `remote_address` | L'adresse radio du moteur dans ESPSomfy-RTS. |
| `source_address` | L'adresse de la source (canal de télécommande ou groupe). |
| `remote_type` | `remote` (télécommande dédiée), `group` ou `internal`. |
| `remote_slot` | Le slot 1-based de la télécommande dédiée sur ce volet, sinon vide. |
| `remote_linked` | La télécommande source est-elle appairée à ce volet. |
| `remote_name` | Un nom lisible : `Télécommande <volet> #<slot>` pour une dédiée, le nom du groupe pour un groupe, vide pour `internal`. |
| `device_id` | L'appareil Home Assistant du volet. |
| `area` | La pièce du volet, le cas échéant. |

`source` indique l'origine : `remote` (télécommande physique), `internal` (interface de la carte) ou `group` (commande de groupe). `command` est l'action : `Up`, `Down`, `My`, `StepUp`, `StepDown`, `Prog`, ou une combinaison de touches (`My+Up`, `My+Down`, `Up+Down`, `My+Up+Down`).

## Déclencheurs d'appareil

Pour lancer une automatisation sans écouter l'événement brut, utilisez le déclencheur d'appareil **Un volet a reçu une commande** (Paramètres > Automatisations > Nouvelle automatisation > Ajouter un déclencheur > Appareil). Il se déclenche quand la carte voit une commande pour ce volet, depuis Home Assistant ou une télécommande physique. La commande et sa source sont dans `trigger.event.data`.

```yaml
triggers:
  - trigger: device
    domain: espsomfy_rts_companion
    device_id: <votre appareil volet>
    entity_id: <votre entité cover>
    type: command_received
actions:
  - action: notify.notify
    data:
      message: >-
        {{ trigger.event.data.name }} : {{ trigger.event.data.command }}
        (depuis {{ trigger.event.data.source }})
```

Un filtre facultatif **source** (télécommande physique, groupe ou carte) ou **adresse de télécommande** restreint le déclencheur.

## Tous les volets d'un coup

Pour démarrer sur une commande de n'importe quel volet, présent ou futur, utilisez le déclencheur **Un volet a reçu une commande** de l'intégration (Nouvelle automatisation > Ajouter un déclencheur > ESPSomfy-RTS Companion). Laissez la cible vide pour tous les volets, ou choisissez des volets, des pièces ou des étiquettes, avec un filtre de source facultatif.

```yaml
triggers:
  - trigger: espsomfy_rts_companion.command_received
    options:
      source: remote
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.remote_name }} sur {{ trigger.event.data.name }}"
```

Plus d'exemples : [Automatisations](docs/Automations.md).

## Crédits

Cette intégration est partie d'[ESPSomfy-RTS Enhanced](https://github.com/xkain/ESPSomfy-RTS-enhanced) de xkain, elle-même issue d'[ESPSomfy-RTS-HA](https://github.com/rstrouse/ESPSomfy-RTS-HA) de rstrouse.
