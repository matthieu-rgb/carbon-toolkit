---
title: "Conception - CARBON, banc offensif véhicule conteneurisé avec couche IA branchable"
type: design
statut: en revue
auteur: Matthieu Broquard
date: 2026-11-19
source: automotive-pentest-toolkit-requirements.md (exigences v0.1)
tags: [automotive-security, can, automotive-ethernet, uds, docker, mcp, ia, design, projet/carbon]
---

# CARBON — Document de conception

> [!info] Objet
> Ce document transforme les exigences v0.1 (`automotive-pentest-toolkit-requirements.md`) en une
> conception dont un dev compétent du domaine peut partir sans revenir vers l'auteur. Il fige
> l'intention, les frontières, l'architecture retenue, les décisions de « comment », et ce qui
> reste à l'appréciation du constructeur. Il doit être **validé** avant toute ligne de code.

---

## 1. Intention et pourquoi

Les outils de sécurité automobile (`can-utils`, Scapy/ISO-TP, `udsoncan`, CANalyzat0r, vehsec,
CANToolz, outils Wi-Fi/BLE) existent mais sont éparpillés : chacun s'installe à sa façon et
suppose que l'opérateur sait déjà où il en est dans sa démarche. **CARBON** (Car Offensive Bench,
nom provisoire) comble ce vide : un seul environnement Docker reproductible et jetable — « un
Exegol pour la voiture » — qui **intègre** les meilleurs outils (sans les réécrire) et ajoute
par-dessus une **couche de pilotage** qui situe en permanence l'opérateur dans la surface
d'attaque du véhicule.

Nouveauté structurante de cette conception par rapport aux exigences v0.1 : CARBON expose son
cœur comme un **serveur MCP** (Model Context Protocol), ce qui rend la couche de pilotage
**pilotable par n'importe quelle IA** — modèle local (Ollama, llama.cpp) ou frontière (Claude,
GPT) — sans que CARBON embarque ni n'impose aucun modèle. Le périmètre réseau est aussi élargi au
**CAN et à l'Automotive Ethernet** (DoIP, et SOME/IP en extension).

### Pourquoi ce choix d'architecture
La dernière intégration IA d'Exegol valide la direction : Exegol **n'embarque aucun modèle**, il
publie un serveur MCP (`pipx install exegol-mcp`) auquel n'importe quel client IA se connecte, et
expose deux familles d'outils (orchestration de conteneurs + exécution dans le conteneur via
`execute_command_in_container`). CARBON reprend ce découplage « capacités exposées / cerveau
branché par-dessus » — c'est exactement la « règle d'or » des exigences (section 6 : pilotage ≠
outils) — et va un cran plus loin en exposant **aussi la méthodologie**, pas seulement les outils.

---

## 2. Objectifs, non-objectifs, anti-objectifs

### 2.1 Objectifs (repris et mesurables)
| # | Objectif | Indicateur |
|---|---|---|
| O1 | Démarrage sans friction | Environnement opérationnel < 5 min sur machine Docker vierge |
| O2 | Couverture CAN/UDS de référence | Opérations CAN/UDS courantes faisables sans quitter CARBON |
| O3 | Reproductibilité | Deux installations → environnement identique (image versionnée) |
| O4 | Pédagogie | Un débutant sait quoi faire ensuite à chaque étape du mode Guidé |
| O5 | Portabilité terrain | Même image sur portable x86 et Raspberry Pi (ARM) |
| O6 | IA branchable, model-agnostic | Un modèle local **et** un modèle frontière pilotent une session via MCP, sans changement de code CARBON |
| O7 | Deux UI, un seul cœur | TUI et Web offrent les mêmes actions, toute la logique écrite une seule fois (couche partagée) |

### 2.2 Non-objectifs (v1 ; réévalués plus tard)
- Réécriture d'outils existants : **on intègre, on ne refait pas**.
- Analyse de firmware binaire avancée (reverse ECU) — candidat v2.
- Interface mobile native.
- Agent IA embarqué « clé-en-main » (voir §4, extension C) — **pas dans le cœur v1**.

### 2.3 Anti-objectifs (ce qui rendrait le projet un échec même s'il « marche »)
- Un énième agrégat d'outils sans la couche qui situe l'opérateur → on n'apporte rien.
- Une couche de pilotage qui contient de la logique d'outil, ou des outils qui contiennent de la
  méthodologie → le découplage est cassé, on ne peut plus faire évoluer l'un sans l'autre.
- Un produit lié à un seul modèle d'IA → trahit O6.
- Toute capacité pensée pour un usage non autorisé sur un véhicule tiers.

---

## 3. Contraintes

- **Hôte Linux** fournissant SocketCAN (modules `can`, `can_raw`, `vcan`). Le matériel d'interface
  (adaptateur CAN, antenne) est fourni par l'opérateur.
- **Multi-architecture** x86_64 **et** ARM64, même base d'outils (image unique multi-arch).
- **Moindre privilège** : pas de `--privileged` global par défaut ; accès matériel ciblé.
- **Solo-dev** : un seul développeur principal → le phasage strict est une contrainte de survie du
  projet, pas un confort (risque n°3 des exigences).
- **Licences amont** : l'intégration d'outils tiers impose un audit de compatibilité de licences.
- L'opérateur travaille sur un véhicule/banc dont il a **l'autorisation de test**.

---

## 4. Approches considérées

Trois façons de brancher l'IA sur le cœur ont été évaluées (voir conversation de cadrage) :

- **A — Tout-MCP (clone d'Exegol).** Un serveur MCP expose outils + méthodologie (ressources/prompts
  MCP). Léger, mais la méthodo n'est qu'un *conseil* (le modèle peut partir hors-piste même en
  Guidé), pas d'état de progression fiable, et dépend du support inégal des « resources/prompts »
  par les clients. → **Rejeté comme cœur** (reste un sous-ensemble utilisable comme MVP).
- **B — Moteur de méthodologie déterministe + outils, IA par-dessus.** La couche de pilotage est un
  vrai composant (arbre d'attaque YAML, état, progression) séparé des outils ; les deux sont
  exposés en MCP. Méthodo déterministe et testable, survit à un petit modèle médiocre, les deux
  modes (Guidé/Libre) en tombent naturellement. → **Retenu comme cœur v1.**
- **C — Agent IA embarqué + MCP.** CARBON embarque sa propre boucle d'agent (backend configurable)
  pour marcher sans client tiers. Plus lourd (harnais d'agent, prompts, adaptateurs par modèle),
  contre le « on ne refait pas » et le risque solo-dev. → **Retenu comme extension cadrée
  (v1.x/v2), pas dans le cœur v1.**

### Décision : **B comme cœur, C comme extension** — et B rend C quasi gratuit
Parce que B expose tout via MCP, un agent embarqué (C) n'est **rien d'autre qu'un client MCP de
plus** branché sur le même serveur. Aucun dédoublement : l'agent embarqué tape sur la même surface
que Claude Desktop ou Cursor. L'opérateur a donc, sur une base unique, **trois usages au choix** :

1. **Sans IA** — pilotage manuel du moteur en TUI/Web (les modes marchent sans aucun modèle).
2. **Client externe** — Claude/GPT/Ollama branché via MCP.
3. **Agent embarqué** — boucle d'agent CARBON, clé-en-main (extension C).

### Décision interface : **TUI + Web**, deux clients fins sur le même cœur
Choix de l'auteur. Surcoût « deux UI » mitigé par l'architecture : toute la logique vit dans le
cœur, les UI n'affichent et n'envoient que des actions. Phasage : **TUI d'abord, Web juste après**,
les deux lisant le même moteur. Le Web porte la **carte de surface d'attaque** (exigence EF-21) et
reçoit un soin de présentation dédié (skill `frontend-design`).

---

## 5. Architecture cible

```
        CLIENTS (au choix de l'operateur)                 [sans IA : pilotage manuel]
   +------------------+------------------+------------------------+
   | TUI (terminal)   | Web (navigateur) | Client MCP externe     |   AGENT EMBARQUE (ext. C)
   | Textual/Rich     | FastAPI + front  | Claude Desktop, Cursor |   boucle d'agent CARBON
   +--------+---------+--------+---------+-----------+------------+   backend configurable
            |  API interne     |             |  MCP (HTTP+token)      |  (= un client MCP de plus)
            v  (coeur en proc) v             v                        v
   +=================================================================================+
   |                              COEUR CARBON                                       |
   |  +---------------------------+     +--------------------------------------+     |
   |  | MOTEUR DE METHODOLOGIE    |     | REGISTRE D'OUTILS (adaptateurs)      |     |
   |  | arbre d'attaque YAML,     |<--->| can_sniff, can_replay, can_inject,   |     |
   |  | etat de session, position |     | isotp, uds_scan, read_dtc, clear_dtc,|     |
   |  | progression, suggestions  |     | seed_key, dbc_decode, doip_discover  |     |
   |  +---------------------------+     +--------------------------------------+     |
   |  +---------------------------+     +--------------------------------------+     |
   |  | JOURNAL / AUDIT (EF-23,   |     | SERVEUR MCP (HTTP localhost + token) |     |
   |  | ENF-21) + RAPPORT (EF-50) |     | expose outils + methodologie + etat  |     |
   |  +---------------------------+     +--------------------------------------+     |
   +=================================================================================+
                                   |
                       COUCHE ACCES MATERIEL
             SocketCAN (can0 / vcan0), USB passthrough, DoIP/IP
                                   |
   +-------------------------------+-------------------------------+
   | Hote x86 (adaptateur CAN) | Raspberry Pi ARM (sonde) | CAN virtuel (labs) |
   +---------------------------+--------------------------+--------------------+
```

**Règle d'or (inviolable) :** le moteur de méthodologie ne contient aucun outil, le registre
d'outils ne contient aucune méthodologie. On peut remplacer l'un sans casser l'autre.

### 5.1 Le cœur
Bibliothèque Python unique, utilisée en-process par la TUI et le Web, et exposée par le serveur
MCP. Responsabilités : état de session, position dans la surface d'attaque, exécution d'outils via
adaptateurs, journal, génération de rapport.

### 5.2 Moteur de méthodologie (déclaratif)
L'arbre d'attaque est décrit en **YAML** (décision : déclaratif, pour la contribution externe —
question ouverte §11 des exigences tranchée ici). Chaque étape déclare : objectif, outil mobilisé,
résultat attendu, **conditions machine-évaluables** sur le résultat, et étapes suivantes possibles
(une ou plusieurs). Le moteur lit ces données ; il ne code pas la méthodo en dur. Couverture
minimale v1 (EF-13) : accès CAN, découverte UDS, lecture DTC, sessions diagnostiques, seed-key.

**Qui interprète et fait avancer (décision, résout une tension de l'approche B) :** le moteur est
l'autorité de l'avancement, mais en deux temps :
- Il **évalue déterministiquement** les conditions YAML contre la **sortie structurée** de
  l'adaptateur (§5.3). Quand une seule branche est satisfaite, il peut auto-avancer ; l'état de
  progression reste donc fiable et testable **sans IA** (c'est ce qui fait « survivre à un modèle
  médiocre »).
- Quand plusieurs branches sont possibles ou qu'aucune condition n'est tranchée, le moteur
  **propose** les étapes candidates et laisse l'**opérateur ou l'IA choisir** ; le choix est
  journalisé. L'IA interprète et explique, mais ne redéfinit jamais la carte.

Conséquence directe : l'avancement et la **position sur la carte** (EF-21, mode Libre) reposent sur
le **contrat de sortie structurée** des adaptateurs, pas sur du parsing libre. C'est pourquoi ce
contrat (§5.3) est un livrable de premier plan, pas un détail.

### 5.3 Registre d'outils (adaptateurs)
Chaque outil intégré est encapsulé par un **adaptateur** à interface uniforme (entrées validées,
sortie structurée, code de retour, artefacts/captures). Déclaration **déclarative et documentée**
d'un nouvel outil (ENF-30). Les adaptateurs appellent les outils amont (`python-can`, `can-utils`,
`udsoncan`, Scapy, etc.) — ils ne les réécrivent pas.

### 5.4 Serveur MCP
Transport **HTTP sur `127.0.0.1` + token Bearer requis par défaut** (aligné sur Exegol), `stdio`
en option. Expose trois surfaces : **outils** (les adaptateurs), **méthodologie/état** (position,
étape courante, suggestions), et **ressources** (DBC, captures, rapport). Model-agnostic par
construction : le modèle est fourni par le client.

**Processus unique et état partagé (décision) :** le serveur MCP et les clients TUI/Web tournent
dans **le même processus** et partagent la **même instance de session/cœur**. L'« API interne »
de la TUI/Web et la surface MCP sont deux façades sur le même état vivant. C'est ce qui rend
possible le garde-fou destructif ci-dessous : une action demandée par l'IA via MCP peut être mise
en attente et apparaître **immédiatement** pour approbation dans la TUI/Web.

### 5.5 Les deux modes (sur le même cœur)
- **Guidé** : le moteur tient le fil, impose l'ordre des étapes ; l'IA (ou l'opérateur) interprète
  et explique. État de progression persistant et reprise (EF-14).
- **Libre** : accès direct à tous les outils, sans parcours imposé ; le moteur **trace** la
  position sur la carte et suggère de façon non bloquante (EF-21, EF-22).
- Bascule Guidé ↔ Libre sans perte d'état (EF-24).

### 5.6 Environnement simulé sans matériel (décision, résout AC-03 + AC-07)
AC-07 exige que **tout** fonctionne sur `vcan0` sans matériel, et AC-03 exige un **dialogue UDS
complet** (scan → session → DTC → seed-key). Or ICSim simule du trafic CAN mais **n'implémente pas
de serveur de diagnostic UDS/ISO-TP** : il ne répond pas aux requêtes UDS. CARBON embarque donc un
**ECU simulé** (répondeur ISO-TP/UDS léger) comme composant à part entière : il répond aux services
UDS, gère sessions, DTC (lecture/effacement) et une routine **seed-key d'exemple** (§8). C'est le
support de test de la couche UDS et la condition pour tenir AC-03 et AC-07 ensemble. Livré en
**v0.2** (voir roadmap). ICSim reste utilisé pour les labs de trafic CAN (EF-15).

#### 5.6.1 Périmètre v0.2 — « minimal mais réaliste » (Option A, décision auteur 2026-11-20)

Deux niveaux de réalisme ont été envisagés pour l'ECU simulée et la couche UDS : **A** (une ECU,
chemins nominaux **+** codes de réponse négative corrects **+** verrouillage par session/sécurité,
un seed-key d'exemple) et **C** (parc multi-ECU, niveaux de sécurité multiples, DID verrouillés
étendus, timing TesterPresent). **Décision : A pour v0.2** ; **C devient un jalon d'apprentissage
ultérieur** (progression pédagogique : A pour comprendre le dialogue, C pour s'entraîner sur un
parc plus fidèle — voir roadmap). La raison du choix de A : c'est le minimum pour que **sessions et
seed-key aient un sens réel** (un service réellement refusé tant qu'on n'est pas déverrouillé),
sans la sur-ingénierie d'un parc complet.

**Décisions de « comment » (calls auteur, à défaut de contre-indication) :**

- **Transport & client UDS** : côté *client* (adaptateurs CARBON), s'appuyer sur `can-isotp`
  (transport ISO 15765-2) + `udsoncan` (client UDS ISO 14229) — on **n'implémente pas** le protocole
  à la main. Côté *ECU simulée*, un **serveur maison** ISO-TP/UDS léger (udsoncan ne fournit pas de
  serveur), construit au-dessus de `can-isotp`. La règle d'or tient : les adaptateurs *enveloppent*
  la lib, l'ECU simulée est un **outil à part**.
- **Services UDS couverts (client + ECU)** :
  - `0x10` DiagnosticSessionControl — sessions *default* (`0x01`) / *extended* (`0x03`).
  - `0x3E` TesterPresent — maintien de session.
  - `0x27` SecurityAccess — requestSeed / sendKey, **un** niveau de sécurité.
  - `0x22` ReadDataByIdentifier — quelques DID, dont **un verrouillé** derrière la sécurité.
  - `0x19` ReadDTCInformation — lecture des DTC (`reportDTCByStatusMask`, sous-fonction `0x02`).
  - `0x14` ClearDiagnosticInformation — effacement DTC ; **action destructrice** → passe par le
    garde-fou `authorize` (comme inject/replay en v0.1).
  - **Scanner UDS** (`uds_scan`) — balaye les SID, distingue *supporté* / *NRC serviceNotSupported*
    (`0x11`), restitue la surface diagnostic.
- **Verrouillage (ce qui donne du sens au seed-key)** : la session *extended* est requise pour
  SecurityAccess (sinon NRC) ; le **DID protégé** et **ClearDTC** ne répondent qu'une fois le
  seed-key validé, sinon NRC *securityAccessDenied* (`0x33`) / *conditionsNotCorrect* (`0x22`).
  L'ECU renvoie les **NRC corrects** partout (service non supporté, sous-fonction invalide, séquence
  erronée, accès refusé).
- **Seed-key d'exemple (documenté, pas de la vraie crypto)** : l'ECU tire un seed 32 bits ; la clé
  attendue est une transformation **déterministe et documentée** (ex. `key = (seed XOR 0xA5A5A5A5)`
  avec rotation fixe), écrite noir sur blanc dans la doc pour que le débutant la reproduise. Branchée
  dans le framework seed-key enfichable (§8) comme algo de référence.
- **Adressage** : CAN 11-bit, **une** ECU — requête `0x7E0`, réponse `0x7E8` (convention OBD-II).
- **Sans matériel** : tout tourne sur `vcan0`. L'ECU simulée est un processus/thread attaché au même
  bus virtuel que les adaptateurs client (tient AC-07).

### 5.7 Connectivité physique au véhicule et antennes (demande explicite)
CARBON doit pouvoir se **brancher sur un vrai véhicule** et exploiter les **antennes** de
l'opérateur. La couche d'accès matériel couvre donc, par passthrough dans le conteneur :

- **Prise OBD-II → CAN.** Adaptateur OBD-II/CAN USB (type CANable/CANtact/USB-CAN, Wi-Fi
  intégrant SLCAN, ou interfaces natives SocketCAN). CARBON crée/attache `can0` côté hôte et aide à
  **identifier les bus** derrière la prise OBD-II (broches, plusieurs bus CAN possibles). Repli
  `vcan0` quand aucun matériel (ENF-04).
- **Automotive Ethernet / DoIP.** Accès IP vers le véhicule (via câble OBD-II→Ethernet/activation
  DoIP) ; `network=host` seulement si strictement requis et documenté (§6).
- **Antenne Wi-Fi USB** en **mode monitor** (audit infotainment) — passthrough du périphérique.
- **Dongle BLE USB** (clés, télématique) — passthrough.
- **SDR/RF USB** (télécommandes, sans contact) — passthrough, en extension (EF-42).

Décisions : accès par `--device`/`--cap-add` **ciblé par périphérique** (pas de `--privileged`
global, §6) ; les configurations matérielles validées (adaptateurs, antennes) sont **documentées**
(risque n°1 des exigences) ; le mode d'emploi (AC-12) couvre le branchement OBD-II réel **et** le
repli sans matériel. Le détail des modèles d'adaptateurs/antennes supportés et des règles udev est
laissé au constructeur, à partir de cette liste.

---

## 6. Sécurité et conformité (décisions explicites)

Le code sera écrit « proprement avec la sécurité appropriée » (demande de l'auteur). Décisions :

- **Moindre privilège** : jamais de `--privileged` global par défaut. Accès matériel ciblé via
  `--device`/`--cap-add` documenté par périphérique ; `network=host` seulement si strictement
  requis pour DoIP et documenté (ENF-20).
- **Authentification MCP** : token Bearer obligatoire par défaut, bind `127.0.0.1`. Le token est
  généré au lancement et stocké hors du dépôt. OAuth MCP non requis v1.
- **Confirmation des actions destructrices (protocole, corrige une faille du garde-fou)** : toute
  action pouvant modifier l'état d'un calculateur (injection CAN, `clear_dtc`, écriture UDS) passe
  par une **approbation humaine hors-bande**. Le flag `--yes` d'auto-confirmation n'est honoré que
  pour un appel **humain direct en CLI** ; il est **ignoré pour tout appel d'origine MCP** (sinon
  l'IA, qui détient le token, se l'auto-accorderait et viderait la garantie). Concrètement : une
  action destructrice demandée via MCP renvoie un état `pending-approval` et **bloque** jusqu'à ce
  qu'un humain l'approuve dans la TUI ou le Web (possible grâce au processus/état unique, §5.4).
  L'IA ne peut **jamais** déclencher une action destructrice sans cette approbation humaine (comble
  le manque de confirmation constaté chez Exegol MCP).
- **Journalisation/audit** : chaque action (humaine ou IA), horodatée, est journalisée pour
  reconstruire la session (EF-23, ENF-21). Le journal alimente le rapport (EF-50).
- **Avertissement d'usage autorisé** au premier lancement (ENF-22).
- **Validation des entrées** aux frontières (adaptateurs, API MCP, API UI) ; pas d'exécution shell
  non paramétrée à partir d'entrées non validées.
- **Secrets & vie privée** : aucune donnée de mission ni identité de l'opérateur envoyée à un
  service externe par CARBON lui-même. (Le choix d'un modèle frontière côté client sort du
  périmètre de CARBON mais est documenté comme avertissement, cf. Exegol.)
- **Cadre légal** : références ISO 21434 / UN R155 dans la doc (ENF-23).

---

## 7. Surface d'attaque couverte (base du mode Guidé)

```
1. ACCES PHYSIQUE      -> prise OBD-II, identification des bus CAN
2. RECONNAISSANCE CAN  -> sniff, cartographie trafic, identification ECU
3. DIAGNOSTIC UDS      -> scan services, sessions, niveaux de securite
4. DTC & DONNEES       -> lecture/effacement codes defaut, DID
5. SEED-KEY            -> acces sessions protegees (algos documentes)
6. REJEU & INJECTION   -> validation d'impact (avec confirmation)
7. AUTOMOTIVE ETHERNET -> DoIP (SOME/IP en extension)        [NOUVEAU vs v0.1]
8. SANS-FIL (v1.x)     -> Wi-Fi infotainment, BLE cle/telematique
9. RESTITUTION         -> rapport de session
```

---

## 8. Décisions de « comment » (prises ici)

| Sujet | Décision | Statut |
|---|---|---|
| Langage/stack | Python (`python-can`, Scapy, `udsoncan`, SDK MCP Python, Textual) | choix auteur |
| Moteur méthodo | Déclaratif YAML | choix auteur (tranche §11 exigences) |
| Transport MCP | HTTP localhost + token Bearer ; stdio optionnel | choix auteur (aligné Exegol) |
| Interfaces | TUI (Textual) + Web (FastAPI + front soigné `frontend-design`) | choix utilisateur |
| Phasage UI | TUI d'abord, Web juste après, même cœur | choix auteur |
| Agent embarqué (C) | Extension v1.x/v2, = client MCP de plus | choix utilisateur |
| Automotive Ethernet | DoIP remonté dans le périmètre (SOME/IP extension) | choix utilisateur |
| Seed-key v1 | **Framework seed-key enfichable + 1-2 algos d'exemple documentés** (pas de couverture OEM large, souvent propriétaire) ; l'ECU simulé embarque une routine correspondante pour les tests | choix auteur |
| ECU simulé | Répondeur ISO-TP/UDS embarqué (§5.6), livré v0.2 | choix auteur |
| Périmètre UDS v0.2 | **Option A** : 1 ECU, NRC corrects, verrouillage session/sécurité, 1 seed-key d'exemple (§5.6.1). **Option C** (parc multi-ECU) = jalon d'apprentissage ultérieur. | **validé auteur 2026-11-20** |
| Libs UDS v0.2 | Client : `can-isotp` + `udsoncan` (on enveloppe, on ne réécrit pas). ECU simulée : serveur ISO-TP/UDS maison sur `can-isotp`. | choix auteur |
| Distribution | **Image multi-arch préconstruite et signée publiée sur un registre (ex : GHCR)** = chemin d'install supporté, piloté par le wrapper CLI (tient AC-01 < 5 min) ; build local = chemin dev. **Le premier publish public est bloqué par l'audit des licences amont** (redistribution). | choix auteur |
| Licence | **GPLv3** (copyleft, compat. intégration GPL amont) | **validé auteur** (audit licences amont à faire avant 1er publish) |
| Portée offline | Air-gap = **config supportée**, pas une exigence dure v1 ; model-agnostic garantit l'offline via client local (Ollama) | **validé auteur** |
| CAN | Bibliothèque **`python-can`** comme accès CAN de référence | **validé auteur** |

---

## 9. Roadmap par jalons (révisée)

```
v0.1  SOCLE        Dockerfile multi-arch, acces CAN (can0/vcan0),
                   coeur minimal + registre d'outils, CLI, can-utils + Scapy
                   -> Critere : capture et rejeu CAN sur vcan0
v0.2  UDS          ISO-TP, scan UDS, DTC, seed-key documente,
                   + ECU SIMULE (repondeur ISO-TP/UDS, §5.6) -- Option A (§5.6.1)
                   -> Critere : dialogue UDS complet sur ECU simule (sans materiel)
v0.2+ LAB UDS      Option C (apprentissage) : parc multi-ECU, niveaux de securite
                   multiples, DID verrouilles etendus, timing TesterPresent
                   -> Critere : parcours UDS sur plusieurs ECU a adresses distinctes
v0.3  MCP + IA     Serveur MCP (outils + methodo + etat), auth token,
                   confirmation actions destructrices
                   -> Critere : un modele local ET un frontiere pilotent une session (O6)
v0.4  MODE GUIDE   Moteur de methodologie YAML, etapes 1 a 6, etat persistant, TUI
                   -> Critere : un debutant boucle un parcours CAN/UDS
v0.5  MODE LIBRE   Carte surface d'attaque, suggestions, journalisation, Web
                   -> Critere : bascule Guide <-> Libre sans perte d'etat
v1.0  RESTITUTION  Rapport de session exportable, doc + mode d'emploi, licence
                   -> Critere : rapport genere en fin de mission
v1.x  EXT.         Automotive Ethernet (DoIP) consolide, Wi-Fi/BLE, agent embarque (C)
v2+   EXTENSIONS   CAN-FD, SOME/IP, reverse firmware, PwnDoc, sonde Pi avancee
```

> Note : le MCP/IA est volontairement remonté en v0.3 (avant les modes), car c'est la demande
> centrale « coller une IA » et il valide le découplage du cœur tôt.

---

## 10. Critères d'acceptance v1 (GO / NO-GO)

- AC-01 : environnement opérationnel < 5 min sur machine Docker vierge (O1).
- AC-02 : cycle CAN complet (sniff → décodage → rejeu → injection) sans quitter CARBON.
- AC-03 : dialogue UDS complet (scan → session → DTC → seed-key documenté).
- AC-04 : mode Guidé déroule les étapes 1 à 6 avec interprétation des résultats.
- AC-05 : mode Libre affiche la position et journalise les actions.
- AC-06 : image démarre sur x86 et ARM depuis la même source.
- AC-07 : tout fonctionne sur `vcan0` sans aucun matériel.
- AC-08 : rapport de session généré en fin de parcours.
- **AC-09 (nouveau)** : une même session est pilotable par un **modèle local** et par un **modèle
  frontière** via MCP, sans modification du code CARBON (O6).
- **AC-10 (nouveau)** : aucune action destructrice (injection, clear DTC, écriture UDS) n'est
  exécutée — même demandée par l'IA — sans confirmation explicite.
- **AC-11 (nouveau)** : TUI et Web exposent le même jeu d'actions sur le même cœur (O7).
- **AC-12 (nouveau)** : un **mode d'emploi** permet à un nouvel opérateur d'installer et de boucler
  un parcours CAN/UDS sur `vcan0` sans aide extérieure.
- **AC-13 (nouveau)** : le **matériel réel est exploitable** — un adaptateur OBD-II/CAN USB en
  passthrough crée/attache `can0` et capture du trafic ; une antenne Wi-Fi USB passe en mode
  monitor et un dongle BLE est découvert, depuis le conteneur, sans `--privileged` global.

---

## 11. Ce qui reste au constructeur

- Choix fin des bibliothèques (ex : `udsoncan` vs `python-uds`), structure des paquets Python,
  gestionnaire d'environnement (poetry/uv), outil de test.
- Format exact du fichier YAML de méthodologie (schéma versionné) et du format de rapport
  (Markdown/HTML, EF-51 ; hook PwnDoc en v2, EF-52).
- Détail des adaptateurs d'outils et du mécanisme déclaratif d'ajout (ENF-30).
- Choix du framework front Web et direction visuelle (via `frontend-design`).
- Stratégie de tests à la construction d'image (ENF-31) et CI multi-arch.
- Mécanisme de génération/stockage du token MCP.

---

## 12. Questions à trancher avec l'auteur

- [x] Licence : **GPLv3** (validé) — audit des licences amont à réaliser avant le 1er publish public.
- [x] Air-gap : **config supportée** (validé), pas une exigence dure v1.
- [x] Accès CAN : **`python-can`** (validé).
- [ ] Nom de code définitif (CARBON provisoire) — non bloquant.

> **Statut : doc approuvé par l'auteur le 2026-11-19.** Socle v0.1 livré et mergé (PR #1).
> **Périmètre v0.2 (UDS, Option A) approuvé le 2026-11-20** (§5.6.1) ; Option C planifiée comme
> jalon d'apprentissage ultérieur. Étape suivante : plan d'implémentation v0.2.
