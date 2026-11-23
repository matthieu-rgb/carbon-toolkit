<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# CARBON - Guide complet

Mode d'emploi en français pour installer CARBON, comprendre son fonctionnement
et mener un parcours CAN/UDS de bout en bout, avec ou sans matériel. Pour la
référence d'architecture, voir [DESIGN.md](DESIGN.md) (en anglais).

> **Avertissement.** CARBON est un outil de sécurité offensive automobile. Vous
> ne devez l'utiliser que sur un véhicule, un banc ou un calculateur dont vous
> avez l'autorisation explicite de test. L'injection de trames, l'effacement de
> codes défaut ou l'écriture UDS modifient l'état d'un calculateur et peuvent
> avoir des conséquences réelles sur un véhicule. Tout ce qui suit se fait, par
> défaut, sur un bus virtuel et un calculateur simulé : aucun matériel n'est
> requis pour apprendre.

---

## Table des matières

1. [Ce qu'est CARBON](#1-ce-quest-carbon)
2. [Les grands principes](#2-les-grands-principes)
3. [Installation](#3-installation)
4. [Démarrage rapide, sans aucun matériel](#4-demarrage-rapide-sans-aucun-materiel)
5. [Les outils CAN](#5-les-outils-can)
6. [Le calculateur simulé et le dialogue UDS](#6-le-calculateur-simule-et-le-dialogue-uds)
7. [Le mode Guidé (interface terminal)](#7-le-mode-guide-interface-terminal)
8. [Le mode Web et la carte de surface d'attaque](#8-le-mode-web-et-la-carte-de-surface-dattaque)
9. [Piloter CARBON avec une IA (MCP)](#9-piloter-carbon-avec-une-ia-mcp)
10. [L'approbation des actions destructrices](#10-lapprobation-des-actions-destructrices)
11. [Le journal d'audit](#11-le-journal-daudit)
12. [Brancher du matériel réel](#12-brancher-du-materiel-reel)
13. [Tests de fumée](#13-tests-de-fumee)
14. [Dépannage](#14-depannage)
15. [Licence](#15-licence)

---

## 1. Ce qu'est CARBON

CARBON est une boîte à outils de test d'intrusion automobile, livrée sous forme
d'image Docker reproductible. L'idée tient en une phrase : rassembler les
meilleurs outils CAN et UDS dans un seul environnement, et ajouter par-dessus
une couche qui situe en permanence l'opérateur dans la surface d'attaque du
véhicule.

Il s'adresse à deux publics à la fois :

- le **débutant**, qui découvre le pentest automobile pas à pas grâce au mode
  Guidé et à une interface qui explique chaque étape ;
- l'**expert**, qui travaille en mode Libre, rapide et sans friction, et qui
  peut piloter CARBON au clavier, au clic ou via une IA.

Deux particularités le distinguent d'un simple agrégat d'outils :

- il expose son cœur comme un **serveur MCP**, donc il est pilotable par
  n'importe quelle IA (un modèle local comme Ollama, ou un modèle distant),
  sans embarquer ni imposer aucun modèle ;
- toute action destructrice passe par une **approbation humaine** obligatoire,
  même lorsque la demande vient d'une IA.

---

## 2. Les grands principes

Comprendre ces quatre principes rend tout le reste évident.

**Un seul cœur, des clients fins.** Toute la logique vit dans une bibliothèque
Python unique (le cœur). La ligne de commande, l'interface terminal (TUI), le
client Web et les clients IA (MCP) ne font qu'afficher l'état et envoyer des
actions. Ils partagent la même session vivante.

**Un chemin d'exécution unique.** Quel que soit le point d'entrée, tout outil
s'exécute par le même passage : `Session.run_tool` puis `execute_tool`. Il
n'existe aucun raccourci qui contournerait le garde-fou ou le journal. Le moteur
de méthodologie et la carte de surface d'attaque n'exécutent jamais rien : ils
lisent les résultats et annotent l'état.

**Deux modes.**
- *Guidé* : le moteur tient le fil, impose l'ordre des étapes et refuse (gentiment,
  sans rien casser) un outil hors parcours. C'est le mode d'apprentissage.
- *Libre* : accès direct à tous les outils ; le moteur se contente de tracer la
  position sur la carte et de suggérer sans bloquer. C'est le mode de l'expert.

On bascule de l'un à l'autre sans perdre l'état.

**Le garde-fou destructif.** Les actions qui modifient un calculateur (injection
CAN, effacement de DTC, écriture UDS) ne s'exécutent jamais directement
lorsqu'elles ne viennent pas d'un humain en ligne de commande. Elles attendent
une approbation humaine explicite, donnée sur un canal que l'IA ne peut pas
atteindre. On y revient en détail au chapitre 10.

---

## 3. Installation

### Prérequis

- Le CAN réel nécessite **Linux** (modules noyau `can`, `can_raw`, `vcan`). Sans
  Linux (macOS, par exemple), tout fonctionne quand même grâce aux bus émulés
  de `python-can` (voir plus bas).
- **Docker** (recommandé) ou **Python 3.11 ou plus récent**.

### Depuis les sources (Python >= 3.11)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest            # la suite tourne sans aucun matériel (bus virtuel python-can)
```

La commande `carbon` est alors disponible dans votre environnement virtuel.

### Image Docker (x86_64 et ARM64)

```bash
# multi-architecture (nécessite un registre ou --push)
docker buildx build --platform linux/amd64,linux/arm64 -t carbon:0.5.0 .
# architecture de l'hôte seulement, dans le démon local
docker buildx build --load -t carbon:0.5.0 .
```

L'image embarque `carbon`, `python-can` et `can-utils`. Elle tourne sans
privilège : pas besoin de `--privileged`.

### La structure d'une commande

Les options globales se placent **avant** la sous-commande :

```
carbon [options globales] <sous-commande> [arguments]
```

| Option globale | Rôle | Défaut |
|----------------|------|--------|
| `--channel` | Le canal CAN (par exemple `vcan0`) | `vcan0` |
| `--interface` | Le type d'interface python-can | `socketcan` |
| `--journal` | Le fichier journal de la session | `carbon-session.jsonl` |
| `--yes` | Confirme une action destructrice en ligne de commande | désactivé |

Exemple : `carbon --channel vcan0 --yes can_inject 7DF 0201`.

---

## 4. Démarrage rapide, sans aucun matériel

Le plus simple pour apprendre : un bus CAN virtuel et le calculateur simulé.

### Sous Linux : un bus virtuel vcan0

```bash
sudo scripts/setup_vcan.sh vcan0
```

Puis, avec l'image Docker en réseau hôte pour qu'elle voie `vcan0` :

```bash
docker run --rm --network host -v "$PWD:/work" carbon:0.5.0 can_sniff --count 5
docker run --rm --network host -v "$PWD:/work" carbon:0.5.0 can_dump capture.log --count 100
docker run --rm --network host -v "$PWD:/work" carbon:0.5.0 --yes can_replay capture.log
docker run --rm --network host -v "$PWD:/work" carbon:0.5.0 --yes can_inject 7DF 0201
```

### Sans Linux (macOS, conteneur simple)

Utilisez un bus émulé par python-can, partagé entre les processus :

```bash
carbon --interface udp_multicast --channel 239.74.163.2 can_sniff --count 5
```

Le bus `virtual` en mémoire ne se partage pas entre deux commandes `carbon`
séparées : pour que le calculateur simulé et les outils se parlent, utilisez
`udp_multicast` avec le même canal des deux côtés.

`can_replay` et `can_inject` sont **destructifs** : ils refusent de s'exécuter
en mode non interactif sans `--yes`. Chaque exécution est inscrite au journal.

---

## 5. Les outils CAN

| Outil | Rôle | Destructif |
|-------|------|------------|
| `can_sniff` | Capture passive de trames CAN | non |
| `can_dump` | Capture vers un fichier au format `candump -l` | non |
| `can_replay` | Rejoue une capture sur le bus | **oui** |
| `can_inject` | Injecte une trame unique (données en hexadécimal) | **oui** |

Quelques exemples :

```bash
# Écouter 20 trames puis s'arrêter
carbon --channel vcan0 can_sniff --count 20

# Enregistrer 100 trames dans un fichier
carbon --channel vcan0 can_dump capture.log --count 100

# Rejouer cette capture (destructif : confirmation requise)
carbon --channel vcan0 --yes can_replay capture.log

# Injecter une requête OBD-II (identifiant 0x7DF, données 02 01)
carbon --channel vcan0 --yes can_inject 7DF 0201

# Injecter avec un identifiant étendu (29 bits)
carbon --channel vcan0 --yes can_inject 18DB33F1 0201 --extended
```

---

## 6. Le calculateur simulé et le dialogue UDS

Pour s'entraîner à l'UDS sans véhicule, CARBON embarque un **calculateur simulé**
(une ECU) : un répondeur ISO-TP/UDS léger qui gère les sessions, l'accès de
sécurité, les codes défaut et une routine seed-key documentée.

### Les outils UDS

| Outil | Service UDS | Rôle | Destructif |
|-------|-------------|------|------------|
| `uds_scan` | balayage | Découvre les services pris en charge | non |
| `uds_session` | 0x10 | Change de session de diagnostic | non |
| `uds_security_access` | 0x27 | Déverrouillage seed-key | non |
| `uds_read_did` | 0x22 | Lit un identifiant de données (DID) | non |
| `uds_read_dtc` | 0x19 | Lit les codes défaut (DTC) | non |
| `uds_clear_dtc` | 0x14 | Efface les codes défaut | **oui** |

### Lancer le calculateur, puis lui parler

Terminal 1 (l'ECU écoute sur l'identifiant `0x7E0`, répond sur `0x7E8`) :

```bash
carbon --channel vcan0 emu start
```

Terminal 2, le dialogue type (scan, session, seed-key, DID, DTC) :

```bash
carbon --channel vcan0 uds_scan                 # quels services répondent
carbon --channel vcan0 uds_read_did F190         # le VIN (ouvert)
carbon --channel vcan0 uds_read_did 1234         # protégé : refusé, NRC 0x33 (verrouillé)
carbon --channel vcan0 uds_session               # session de diagnostic étendue
carbon --channel vcan0 uds_security_access       # seed -> clé -> déverrouillé
carbon --channel vcan0 uds_read_did 1234         # réussit maintenant : deadbeef
carbon --channel vcan0 uds_read_dtc              # 2 DTC présents
carbon --channel vcan0 --yes uds_clear_dtc       # destructif : --yes requis
carbon --channel vcan0 uds_read_dtc              # 0 DTC
```

Ce dialogue illustre le point pédagogique central : le DID `1234` et l'effacement
des DTC sont **refusés tant qu'on n'a pas déverrouillé** le calculateur par
seed-key. C'est ce verrouillage qui donne tout son sens à l'étape seed-key.

### Comprendre le seed-key d'exemple

L'accès de sécurité (SecurityAccess) est un défi-réponse : l'outil demande une
graine (`requestSeed`), calcule une clé et la renvoie (`sendKey`). Le calculateur
simulé utilise un algorithme **documenté et pédagogique** (ce n'est pas un
algorithme constructeur réel), que vous pouvez reproduire à la main :

```
clé = rotation_gauche_32bits(graine XOR 0xA5A5A5A5, 3)
```

Autrement dit : XOR de la graine de 4 octets avec `A5A5A5A5`, puis rotation du
résultat 32 bits de 3 bits vers la gauche. Exemple : graine `11223344` donne la
clé `a43cb70d`.

```bash
python3 -c "s=0x11223344^0xA5A5A5A5; print(f'{((s<<3)|(s>>29))&0xFFFFFFFF:08x}')"
```

L'implémentation se trouve dans `carbon/uds/seedkey.py` (`ExampleSeedKey`). Le
cadre accepte d'autres algorithmes implémentant `key_from_seed(seed) -> key`.

### Avec ou sans matériel

- **Linux avec `vcan0`** : utilisez `--channel vcan0` comme ci-dessus ; lancez
  l'ECU et les outils en conteneurs avec `--network host`.
- **Sans Linux** : utilisez un bus émulé partagé, par exemple
  `--interface udp_multicast --channel 239.74.163.3` des deux côtés.
- **Un vrai calculateur** : pointez `--interface` / `--channel` vers votre
  adaptateur (`can0`, slcan, etc.). Ne testez que des véhicules et des
  calculateurs que vous êtes autorisé à tester.

---

## 7. Le mode Guidé (interface terminal)

Le mode Guidé déroule un parcours méthodologique dans une interface terminal
(TUI). Un moteur lit un arbre d'attaque déclaratif en YAML
(`carbon/methodology/trees/carbon_v1.yaml`) et enchaîne les phases CAN/UDS 1 à 6.

```bash
carbon tui --methodology carbon/methodology/trees/carbon_v1.yaml
```

Sans matériel, le parcours tourne sur `vcan0` (ou le bus virtuel) avec le
calculateur simulé. À chaque étape, la TUI affiche l'objectif, l'outil attendu et
le résultat. L'étape suivante ne se débloque que si la condition de l'étape est
remplie. En mode Guidé, un outil hors parcours est refusé ; le mode Libre reste
accessible à tout moment.

Les six phases :

```
1. ACCÈS              -> attacher vcan0 (étape informative)
2. RECONNAISSANCE CAN -> can_sniff / can_dump
3. DIAGNOSTIC UDS     -> uds_scan, uds_session
4. DTC & DONNÉES      -> uds_read_dtc, uds_read_did, uds_clear_dtc (destructif)
5. SEED-KEY           -> uds_security_access
6. REJEU & INJECTION  -> can_replay, can_inject (destructifs)
```

Les étapes destructrices passent toujours par l'approbation : la TUI ouvre une
fenêtre modale que l'opérateur accepte ou refuse. La position dans le parcours
est sauvegardée et reprise au relancement (la reprise restaure votre position de
méthodologie, pas l'état vivant de la cible : si le calculateur simulé a
redémarré, rejouer l'étape rétablit les prérequis).

---

## 8. Le mode Web et la carte de surface d'attaque

`carbon web` sert un client Web local qui apporte ce que le terminal ne sait pas
faire : une **carte de la surface d'attaque** construite en direct, et le mode
Libre pilotable au clic. C'est le même cœur que la TUI et le MCP (même session,
même registre d'outils, même file d'approbation, même journal).

```bash
carbon web                                         # sur 127.0.0.1:8800
carbon --interface virtual --channel carbon-demo web --port 8800
```

La commande affiche un **lien d'amorçage à usage unique**,
`http://127.0.0.1:<port>/?k=<jeton-web>`, ainsi que le chemin du fichier de jeton
MCP (le MCP reste servi sur `/mcp`). Ouvrir le lien dépose le cookie `carbon_web`
(HttpOnly, SameSite=Strict) puis vous redirige vers `/` ; le jeton n'apparaît
plus dans l'URL ensuite.

La carte montre le graphe bus -> calculateur -> services UDS -> niveaux de
sécurité, avec la position courante mise en évidence. Un clic sur un nœud ou un
service lance l'outil correspondant (le Web n'exécute rien lui-même : il envoie
l'action au cœur). Le mode Guidé reste dans la TUI pour l'instant ; le Web est
Libre uniquement.

**Posture de sécurité du mode Web :**

- écoute sur `127.0.0.1` uniquement (toute autre adresse est refusée) ;
- le jeton Web est distinct du jeton MCP : le cookie n'ouvre pas `/mcp`, et le
  jeton MCP n'ouvre pas l'API Web ;
- cookie `HttpOnly` + `SameSite=Strict` ; contrôle des en-têtes `Host` et
  `Origin` (protection contre le CSRF et le DNS-rebinding) ; toutes les routes
  qui modifient l'état sont en POST ;
- les actions destructrices exigent une approbation humaine dans une fenêtre
  modale du Web : un clic sur l'outil ne suffit pas, et tout est journalisé.

---

## 9. Piloter CARBON avec une IA (MCP)

CARBON expose ses outils à un client IA via le Model Context Protocol :
`carbon mcp serve`. Les mêmes garde-fous que la ligne de commande s'appliquent
(registre, autorisation, journal) : le serveur n'ajoute aucun chemin
d'exécution.

### En stdio (Claude Desktop et clients similaires)

```bash
carbon --channel vcan0 --interface socketcan mcp serve --transport stdio
```

Configuration cliente type :

```json
{"mcpServers": {"carbon": {"command": "carbon",
  "args": ["--channel", "vcan0", "mcp", "serve", "--transport", "stdio"]}}}
```

En stdio, la console est le tube du protocole : il n'y a aucun canal
d'approbation, donc **toute action destructrice est refusée**. Ce mode sert les
outils non destructifs (scan, lecture) parfaitement.

### En HTTP avec jeton Bearer

```bash
carbon --channel vcan0 mcp serve --transport http --port 8777
```

Le serveur écoute sur `127.0.0.1` uniquement, endpoint `/mcp`. Un jeton Bearer
aléatoire est généré à chaque lancement et écrit **hors du dépôt**
(`$XDG_RUNTIME_DIR` ou le répertoire temporaire, permissions 0600) ; seul le
**chemin** du fichier est affiché. Chaque requête doit porter l'en-tête
`Authorization: Bearer <jeton>`, sinon elle reçoit un 401.

---

## 10. L'approbation des actions destructrices

C'est la garantie de sécurité centrale de CARBON (critère AC-10). Voici la règle,
une fois pour toutes.

Chaque action porte une **origine** : `CLI` (humain en ligne de commande), `MCP`
(une IA), `TUI` ou `WEB`.

- Pour l'origine `CLI`, le `--yes` confirme l'action : c'est un humain qui tape
  la commande.
- Pour **toute autre origine**, `--yes` (et son équivalent `assume_yes`) est
  **ignoré**. Une action destructrice part en file d'attente (`pending-approval`),
  l'appel **bloque**, et l'action ne s'exécute qu'après une approbation humaine
  explicite donnée sur un canal que l'IA ne peut pas atteindre :
  - en **MCP HTTP** : dans la **console du serveur** (`list`, `approve <id>`,
    `deny <id>`) ;
  - en **TUI** : dans une fenêtre modale ;
  - en **Web** : dans une fenêtre modale du navigateur.

Sans réponse, l'action **expire** et est refusée (comportement « fail-closed »).
Tout est journalisé : l'approbation, le refus comme l'expiration.

La raison de cette règle : une IA qui détient le jeton se l'auto-accorderait si
`--yes` fonctionnait pour elle, ce qui viderait la garantie de tout son sens.
L'approbation passe donc toujours par un humain, hors du canal de l'IA.

---

## 11. Le journal d'audit

Chaque exécution d'outil, qu'elle vienne d'un humain ou d'une IA, est inscrite,
horodatée, dans un journal au format JSONL (par défaut `carbon-session.jsonl`,
modifiable avec `--journal`). Le journal enregistre l'outil, les paramètres,
l'origine de l'appel, le résultat et l'issue des approbations. Il permet de
reconstruire entièrement une session et alimentera le rapport de mission (jalon
v1.0). En MCP, le journal est aussi exposé en lecture seule comme ressource
(`carbon://journal`).

---

## 12. Brancher du matériel réel

CARBON peut se brancher sur un vrai véhicule par passthrough ciblé dans le
conteneur, sans `--privileged` global.

| Besoin | Options Docker |
|--------|----------------|
| `vcan0` / `can0` existant sur l'hôte | `--network host` |
| Créer un vcan dans le conteneur | `--user root --cap-add NET_ADMIN --network host` (puis `scripts/setup_vcan.sh`) |
| Adaptateur USB CAN (slcan, gs_usb...) | `--device /dev/ttyACM0` (ou le nœud adéquat) |
| DoIP (Ethernet vers le calculateur) | `--network host` ou un réseau macvlan, plus `--cap-add NET_RAW` si des sockets bruts sont utilisés |

Autres accès prévus par la couche matérielle : antenne Wi-Fi USB en mode moniteur
(audit infodivertissement), dongle BLE USB (clés, télématique), SDR/RF en
extension. Chacun passe par un `--device` / `--cap-add` ciblé, documenté par
périphérique. Aucun de ces accès n'est nécessaire pour le bus virtuel utilisé par
les tests.

Rappel : ne branchez CARBON que sur un véhicule, un banc ou un calculateur que
vous êtes **autorisé** à tester.

---

## 13. Tests de fumée

Des scripts vérifient chaque brique de bout en bout. Ils choisissent
automatiquement le bus (`vcan0` sous Linux root, sinon un bus émulé en
loopback).

```bash
bash scripts/smoke_can_cycle.sh      # cycle CAN : dump, replay, inject, refus sans --yes
bash scripts/smoke_uds_cycle.sh      # dialogue UDS complet sur le calculateur simulé
bash scripts/smoke_guided.sh         # moteur du mode Guidé (étapes 1 à 6 + reprise)
bash scripts/smoke_web.sh            # client Web : amorçage, cookie, isolation MCP
```

Depuis l'image Docker, les mêmes cibles existent : `smoke`, `smoke-uds`,
`smoke-guided`, `smoke-web`, `smoke-mcp`. Par exemple :

```bash
docker run --rm carbon:0.5.0 smoke-uds
```

---

## 14. Dépannage

**« not a git repository » ou la commande `carbon` est introuvable.** Activez
votre environnement virtuel (`. .venv/bin/activate`) ou passez par l'image
Docker.

**Le calculateur simulé et les outils ne se parlent pas.** Sur un bus `virtual`
en mémoire, deux commandes `carbon` séparées ne partagent pas le bus. Utilisez
`--interface udp_multicast --channel <adresse>` identique des deux côtés, ou
`vcan0` sous Linux.

**Une action destructrice est refusée.** C'est le comportement attendu. En ligne
de commande, ajoutez `--yes` (avant la sous-commande). En MCP, TUI ou Web,
approuvez l'action sur le canal humain prévu (console du serveur, ou fenêtre
modale).

**Pas de `vcan0` disponible.** Créez-le avec `sudo scripts/setup_vcan.sh vcan0`
(Linux, droits root, module `vcan`), ou repliez sur un bus émulé python-can.

**Le port Web est déjà pris.** Changez-le avec `carbon web --port <autre-port>`.

---

## 15. Licence

CARBON est distribué sous licence **GPL-3.0-or-later**. Voir le fichier
[LICENSE](../LICENSE).
